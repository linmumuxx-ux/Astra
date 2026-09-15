#!/usr/bin/env python3
"""CTB skill efficiency/stability benchmark.

Accuracy is a hard gate. Efficiency is only compared when correctness is tied.
The runner executes OpenCode, parses JSONL token/tool usage, evaluates the
reference implementation, then runs hidden evaluation outside the public agent
workspace.
"""
from __future__ import print_function

import argparse
import ast
import hashlib
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_PROMPT = (
    "Use the ctb-test-design skill to solve this CTB test-design task. "
    "Read only the public workspace. Create or improve test_submission.py, "
    "maintain .ctb/design.json, and keep ctb_design_summary.md concise. "
    "Do not access or infer hidden evaluator content."
)
FORBIDDEN_PARTS = {"hidden", "implementation", "candidate", "results", "history"}


def _percentile(values, p):
    values = sorted(float(x) for x in values if x is not None)
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    rank = (len(values) - 1) * p
    lo, hi = int(math.floor(rank)), int(math.ceil(rank))
    if lo == hi:
        return values[lo]
    return values[lo] + (values[hi] - values[lo]) * (rank - lo)


def _summary(values):
    values = [float(x) for x in values if x is not None]
    if not values:
        return {"count": 0, "min": None, "p50": None, "p95": None, "max": None, "mean": None, "stdev": None, "cv": None}
    mean = statistics.mean(values)
    stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
    return {"count": len(values), "min": min(values), "p50": _percentile(values, .50), "p95": _percentile(values, .95), "max": max(values), "mean": mean, "stdev": stdev, "cv": stdev / mean if mean else 0.0}


def _integer(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return max(0, int(value))
    return None


def _token_values(payload):
    cache = payload.get("cache") if isinstance(payload.get("cache"), dict) else {}
    return (
        _integer(payload.get("input_tokens", payload.get("input"))),
        _integer(payload.get("output_tokens", payload.get("output"))),
        _integer(payload.get("cache_read_tokens", payload.get("cacheRead", cache.get("read")))),
        _integer(payload.get("cache_write_tokens", payload.get("cacheWrite", cache.get("write")))),
    )


def _find_tokens(event):
    candidates = []
    info = event.get("info")
    if isinstance(info, dict):
        for key in ("tokens", "usage"):
            if isinstance(info.get(key), dict):
                candidates.append(info[key])
    part = event.get("part")
    if isinstance(part, dict):
        for key in ("tokens", "usage"):
            if isinstance(part.get(key), dict):
                candidates.append(part[key])
        candidates.append(part)
    for key in ("tokens", "usage"):
        if isinstance(event.get(key), dict):
            candidates.append(event[key])
    candidates.append(event)
    for candidate in candidates:
        values = _token_values(candidate)
        if any(value is not None for value in values):
            return values
    return (None, None, None, None)


def _deep_value(value, keys):
    if isinstance(value, dict):
        for key in keys:
            if value.get(key) not in (None, ""):
                return str(value[key])
        for child in value.values():
            found = _deep_value(child, keys)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _deep_value(child, keys)
            if found:
                return found
    return None


def parse_opencode_usage(events):
    totals = [None, None, None, None]
    llm_calls = 0
    model = None
    tool_calls = {}
    for index, event in enumerate(events):
        values = _find_tokens(event)
        if any(value is not None for value in values):
            llm_calls += 1
            for pos, value in enumerate(values):
                if value is not None:
                    totals[pos] = (totals[pos] or 0) + value
        model = model or _deep_value(event, ("modelID", "model_id", "modelName", "model_name", "model"))
        part = event.get("part") if isinstance(event.get("part"), dict) else event
        event_type = str(event.get("type", "")).lower()
        part_type = str(part.get("type", "")).lower() if isinstance(part, dict) else ""
        if "tool" not in event_type and part_type not in {"tool", "tool_use", "tool-call"}:
            continue
        name = _deep_value(part, ("tool", "toolName", "tool_name", "name")) or "other"
        call_id = _deep_value(part, ("callID", "call_id", "toolCallID", "tool_call_id", "id"))
        tool_calls[call_id or "event-%d" % index] = name
    total_tokens = sum(x or 0 for x in totals) if any(x is not None for x in totals) else None
    by_tool = {}
    for name in tool_calls.values():
        by_tool[name] = by_tool.get(name, 0) + 1
    return {"input_tokens": totals[0], "output_tokens": totals[1], "cache_read_tokens": totals[2], "cache_write_tokens": totals[3], "total_tokens": total_tokens, "llm_calls": llm_calls if llm_calls else None, "tool_calls": len(tool_calls), "tool_calls_by_name": dict(sorted(by_tool.items())), "model": model}


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _prepare_public_workspace(question_dir, workspace_dir):
    question_dir, workspace_dir = Path(question_dir).resolve(), Path(workspace_dir).resolve()
    files = _read_json(question_dir / "public_files.json").get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("public_files.json must contain a non-empty files list")
    if workspace_dir.exists():
        shutil.rmtree(str(workspace_dir))
    workspace_dir.mkdir(parents=True)
    for rel in files:
        rel_path = Path(rel)
        if rel_path.is_absolute() or ".." in rel_path.parts or any(part.lower() in FORBIDDEN_PARTS for part in rel_path.parts):
            raise RuntimeError("invalid/forbidden public path: %s" % rel)
        src = question_dir / rel_path
        if not src.is_file():
            raise RuntimeError("missing public file: %s" % src)
        dst = workspace_dir / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))


def _apply_starter(question_dir, workspace_dir):
    """Reset an evolved testcase file to the frozen Skill A/B starter."""
    starter = Path(question_dir).resolve() / "starter_test_submission.py"
    if not starter.is_file():
        return None
    target = Path(workspace_dir).resolve() / "test_submission.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(starter), str(target))
    return starter.name


def _install_skill(skill_dir, workspace_dir):
    skill_dir = Path(skill_dir).resolve()
    target = Path(workspace_dir) / ".opencode" / "skills" / skill_dir.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(str(skill_dir), str(target))


def _parse_jsonl(text):
    events = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def _submission_stats(path):
    path = Path(path)
    if not path.is_file():
        return {"exists": False, "sha256": None, "testcase_count": 0, "bytes": 0}
    data = path.read_bytes()
    testcase_count = 0
    try:
        tree = ast.parse(data.decode("utf-8"))
        testcase_count = sum(1 for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"))
    except Exception:
        pass
    return {"exists": True, "sha256": hashlib.sha256(data).hexdigest(), "testcase_count": testcase_count, "bytes": len(data)}


def _validate_correct(question_dir, submission_path, timeout):
    question_dir, submission_path = Path(question_dir).resolve(), Path(submission_path).resolve()
    with tempfile.TemporaryDirectory(prefix="ctb-correct-") as td:
        td = Path(td)
        impl = question_dir / "implementation"
        if impl.is_dir():
            shutil.copytree(str(impl), str(td / "implementation"))
        shutil.copy2(str(question_dir / "test_aw.py"), str(td / "test_aw.py"))
        shutil.copy2(str(submission_path), str(td / "test_submission.py"))
        proc = subprocess.run([sys.executable, "-m", "unittest", "-q", "test_submission.py"], cwd=str(td), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return proc.returncode == 0, proc.stdout[-4000:]


def _evaluate_hidden(question_dir, submission_path, timeout):
    evaluator = Path(question_dir).resolve() / "hidden" / "evaluate.py"
    proc = subprocess.run([sys.executable, str(evaluator), str(Path(submission_path).resolve())], cwd=str(evaluator.parent), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if proc.returncode:
        raise RuntimeError("hidden evaluator failed: %s" % (proc.stderr or proc.stdout)[-2000:])
    return json.loads(proc.stdout)


def run_trial(args, index, output_dir):
    trial_dir = Path(output_dir) / ("trial-%02d" % index)
    trial_dir.mkdir(parents=True, exist_ok=True)
    prompt = args.prompt
    if args.profile:
        prompt += "\n\nCTB runtime profile: %s. Accuracy is a hard gate; use the profile only to reduce redundant work, and escalate when correctness evidence is insufficient." % args.profile.upper()

    # Never place the agent workspace below the benchmark repository: simple
    # parent-directory traversal must not expose hidden evaluation artifacts.
    with tempfile.TemporaryDirectory(prefix="ctb-public-agent-") as public_td:
        workspace = Path(public_td) / "workspace"
        _prepare_public_workspace(args.question, workspace)
        starter_template = _apply_starter(args.question, workspace)
        _install_skill(args.skill, workspace)
        cmd = [args.opencode, "run", "--format", "json", "--dir", str(workspace)]
        if args.model:
            cmd.extend(["--model", args.model])
        cmd.append(prompt)
        started = time.perf_counter()
        try:
            proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=args.timeout)
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            duration = time.perf_counter() - started
            stdout, stderr = exc.stdout or "", exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            proc, timed_out = None, True
        else:
            duration = time.perf_counter() - started
            stdout, stderr = proc.stdout, proc.stderr
        usage = parse_opencode_usage(_parse_jsonl(stdout))
        (trial_dir / "opencode.jsonl").write_text(stdout, encoding="utf-8")
        if stderr:
            (trial_dir / "stderr.log").write_text(stderr, encoding="utf-8")
        workspace_submission = workspace / "test_submission.py"
        stats = _submission_stats(workspace_submission)
        generated = (not timed_out) and proc is not None and proc.returncode == 0 and stats["exists"]
        submission = trial_dir / "test_submission.py"
        if stats["exists"]:
            shutil.copy2(str(workspace_submission), str(submission))
        for rel in (Path(".ctb/design.json"), Path("ctb_design_summary.md")):
            src = workspace / rel
            if src.is_file():
                dst = trial_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))

    correct_pass, correct_output, hidden, eval_error = False, "", None, None
    if generated:
        try:
            correct_pass, correct_output = _validate_correct(args.question, submission, args.eval_timeout)
            if correct_pass:
                hidden = _evaluate_hidden(args.question, submission, args.eval_timeout)
        except Exception as exc:
            eval_error = str(exc)
    killed = hidden.get("killed_count") if isinstance(hidden, dict) else None
    total = hidden.get("total") if isinstance(hidden, dict) else None
    kill_rate = 100.0 * killed / total if isinstance(killed, int) and isinstance(total, int) and total else None
    result = {"trial": index, "profile": args.profile or "auto", "starter_template": starter_template, "generation_success": generated, "timeout": timed_out, "exit_code": None if proc is None else proc.returncode, "duration_seconds": round(duration, 4), "usage": usage, "submission": stats, "correct_env_pass": bool(correct_pass), "kill_rate": kill_rate, "killed_bugs": killed, "total_bugs": total, "hidden_errors": hidden.get("errors", {}) if isinstance(hidden, dict) else {}, "evaluation_error": eval_error}
    _write_json(trial_dir / "result.json", result)
    if correct_output:
        (trial_dir / "correct.log").write_text(correct_output, encoding="utf-8")
    if hidden is not None:
        _write_json(trial_dir / "hidden.json", hidden)
    return result


def summarize_trials(trials):
    n = len(trials)
    generated = [t for t in trials if t.get("generation_success")]
    correct = [t for t in trials if t.get("correct_env_pass")]
    hashes = [((t.get("submission") or {}).get("sha256")) for t in correct]
    hashes = [x for x in hashes if x]
    def field(name):
        return [t.get(name) for t in trials]
    def usage(name):
        return [(t.get("usage") or {}).get(name) for t in trials]
    return {
        "schema_version": 1,
        "trial_count": n,
        "generation_success_rate": len(generated) / n if n else 0.0,
        "correct_env_pass_rate": len(correct) / n if n else 0.0,
        "accuracy": _summary(field("kill_rate")),
        "duration_seconds": _summary(field("duration_seconds")),
        "total_tokens": _summary(usage("total_tokens")),
        "input_tokens": _summary(usage("input_tokens")),
        "output_tokens": _summary(usage("output_tokens")),
        "llm_calls": _summary(usage("llm_calls")),
        "tool_calls": _summary(usage("tool_calls")),
        "submission_consistency": {"unique_hashes": len(set(hashes)), "identical_rate": max(hashes.count(x) for x in set(hashes)) / len(hashes) if hashes else None},
    }


def _metric(summary, name, stat="p50"):
    value = (summary.get(name) or {}).get(stat)
    return float(value) if isinstance(value, (int, float)) else None


def compare_summaries(baseline, candidate, policy):
    acc, stab, eff = policy.get("accuracy", {}), policy.get("stability", {}), policy.get("efficiency", {})
    reasons = []
    required_correct = float(acc.get("min_correct_env_pass_rate", 1.0))
    if candidate.get("correct_env_pass_rate", 0.0) < required_correct:
        reasons.append("candidate correct-env pass rate below %.3f" % required_correct)
    max_acc_reg = float(acc.get("max_kill_rate_regression_pp", 0.0))
    for stat in ("min", "p50"):
        b, c = _metric(baseline, "accuracy", stat), _metric(candidate, "accuracy", stat)
        if b is not None and (c is None or c + max_acc_reg < b):
            reasons.append("accuracy %s regressed: baseline=%s candidate=%s" % (stat, b, c))
    max_success_reg = float(stab.get("max_success_rate_regression", 0.0))
    if float(candidate.get("generation_success_rate", 0.0)) + max_success_reg < float(baseline.get("generation_success_rate", 0.0)):
        reasons.append("generation success rate regressed")
    b_std, c_std = _metric(baseline, "accuracy", "stdev"), _metric(candidate, "accuracy", "stdev")
    if b_std is not None and c_std is not None and c_std > b_std + float(stab.get("max_accuracy_stdev_increase_pp", 0.5)):
        reasons.append("accuracy variability increased")
    gates_pass = not reasons

    details, components = {}, []
    weights = eff.get("weights", {"duration_seconds.p50": .25, "duration_seconds.p95": .25, "total_tokens.p50": .25, "total_tokens.p95": .25})
    for key, weight in weights.items():
        metric_name, stat = key.split(".", 1)
        b, c = _metric(baseline, metric_name, stat), _metric(candidate, metric_name, stat)
        ratio = c / b if c is not None and b is not None and b > 0 else None
        details[key] = {"baseline": b, "candidate": c, "ratio": ratio, "weight": weight}
        if ratio is not None and float(weight) > 0:
            components.append((ratio, float(weight)))
    if components:
        total_w = sum(w for _, w in components)
        cost_index = math.exp(sum(w * math.log(max(r, 1e-9)) for r, w in components) / total_w)
    else:
        cost_index = None
    max_reg = float(eff.get("max_single_metric_regression_pct", 10.0)) / 100.0
    if gates_pass:
        for key, detail in details.items():
            if detail["ratio"] is not None and detail["ratio"] > 1.0 + max_reg:
                reasons.append("efficiency metric %s regressed %.1f%%" % (key, (detail["ratio"] - 1.0) * 100.0))
                gates_pass = False
    min_improve = float(eff.get("promotion_min_improvement_pct", 5.0)) / 100.0
    if not gates_pass:
        decision = "REJECT"
    elif cost_index is None:
        decision = "HOLD"; reasons.append("no comparable duration/token metrics")
    elif cost_index <= 1.0 - min_improve:
        decision = "PROMOTE"; reasons.append("accuracy/stability gates passed and efficiency improved %.1f%%" % ((1.0 - cost_index) * 100.0))
    else:
        decision = "HOLD"; reasons.append("accuracy/stability gates passed but efficiency improvement < %.1f%%" % (min_improve * 100.0))
    return {"schema_version": 1, "decision": decision, "accuracy_stability_gate": gates_pass, "normalized_cost_index": cost_index, "components": details, "reasons": reasons}


def skill_footprint(skill_dir):
    skill_dir = Path(skill_dir)
    files, total_bytes, total_chars = [], 0, 0
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        rel = str(path.relative_to(skill_dir)).replace(os.sep, "/")
        files.append({"path": rel, "bytes": len(data), "chars": len(text), "estimated_tokens": int(math.ceil(len(text) / 4.0))})
        total_bytes += len(data); total_chars += len(text)
    return {"skill": skill_dir.name, "files": files, "total_bytes": total_bytes, "total_chars": total_chars, "estimated_context_tokens": int(math.ceil(total_chars / 4.0)), "note": "Static chars/4 estimate only; use run mode for actual model token usage."}


def command_run(args):
    out = Path(args.output).resolve(); out.mkdir(parents=True, exist_ok=True)
    trials = []
    for i in range(1, args.runs + 1):
        print("[CTB] trial %d/%d" % (i, args.runs), file=sys.stderr)
        trials.append(run_trial(args, i, out))
    summary = summarize_trials(trials)
    summary.update({"question": str(Path(args.question).resolve()), "skill": str(Path(args.skill).resolve()), "profile": args.profile or "auto", "model": args.model})
    _write_json(out / "trials.json", trials); _write_json(out / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2)); return 0


def command_summarize(args):
    data = _read_json(args.input); trials = data.get("trials") if isinstance(data, dict) else data
    if not isinstance(trials, list):
        raise SystemExit("input must be a trial list or {'trials': [...]}")
    result = summarize_trials(trials)
    if args.output: _write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 0


def command_compare(args):
    result = compare_summaries(_read_json(args.baseline), _read_json(args.candidate), _read_json(args.policy))
    if args.output: _write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 2 if args.gate and result["decision"] == "REJECT" else 0


def command_footprint(args):
    result = skill_footprint(args.skill)
    if args.output: _write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 0


def build_parser():
    parser = argparse.ArgumentParser(description="CTB skill accuracy-first efficiency benchmark")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run"); run.add_argument("--question", required=True); run.add_argument("--skill", required=True); run.add_argument("--model"); run.add_argument("--opencode", default="opencode"); run.add_argument("--runs", type=int, default=5); run.add_argument("--profile", choices=("fast", "balanced", "thorough")); run.add_argument("--prompt", default=DEFAULT_PROMPT); run.add_argument("--timeout", type=int, default=900); run.add_argument("--eval-timeout", type=int, default=120); run.add_argument("--output", required=True); run.set_defaults(func=command_run)
    summarize = sub.add_parser("summarize"); summarize.add_argument("--input", required=True); summarize.add_argument("--output"); summarize.set_defaults(func=command_summarize)
    compare = sub.add_parser("compare"); compare.add_argument("--baseline", required=True); compare.add_argument("--candidate", required=True); compare.add_argument("--policy", required=True); compare.add_argument("--output"); compare.add_argument("--gate", action="store_true"); compare.set_defaults(func=command_compare)
    footprint = sub.add_parser("footprint"); footprint.add_argument("--skill", required=True); footprint.add_argument("--output"); footprint.set_defaults(func=command_footprint)
    return parser


def main():
    args = build_parser().parse_args(); return args.func(args)

if __name__ == "__main__":
    raise SystemExit(main())
