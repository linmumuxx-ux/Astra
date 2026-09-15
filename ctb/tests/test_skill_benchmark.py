import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "skill_benchmark.py"
spec = importlib.util.spec_from_file_location("skill_benchmark", str(MODULE_PATH))
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


class SkillBenchmarkTest(unittest.TestCase):
    def test_parse_opencode_usage(self):
        events = [
            {"info": {"usage": {"input": 100, "output": 20, "cache": {"read": 5}}}, "model": "m1"},
            {"part": {"type": "tool", "tool": "read", "callID": "c1"}},
            {"usage": {"input_tokens": 40, "output_tokens": 10}},
        ]
        usage = bench.parse_opencode_usage(events)
        self.assertEqual(usage["input_tokens"], 140)
        self.assertEqual(usage["output_tokens"], 30)
        self.assertEqual(usage["cache_read_tokens"], 5)
        self.assertEqual(usage["total_tokens"], 175)
        self.assertEqual(usage["llm_calls"], 2)
        self.assertEqual(usage["tool_calls"], 1)
        self.assertEqual(usage["model"], "m1")

    def test_summarize_tracks_p95_and_accuracy_variance(self):
        trials = []
        for i, (rate, sec, tokens) in enumerate([(100, 10, 1000), (100, 12, 900), (95, 11, 1100)], 1):
            trials.append({"trial": i, "generation_success": True, "correct_env_pass": True, "kill_rate": rate, "duration_seconds": sec, "usage": {"total_tokens": tokens, "input_tokens": tokens-100, "output_tokens": 100, "llm_calls": 2, "tool_calls": 4}, "submission": {"sha256": "h%d" % i}})
        out = bench.summarize_trials(trials)
        self.assertEqual(out["trial_count"], 3)
        self.assertEqual(out["accuracy"]["min"], 95.0)
        self.assertGreater(out["accuracy"]["stdev"], 0)
        self.assertGreaterEqual(out["duration_seconds"]["p95"], 11.0)

    def test_accuracy_regression_is_rejected_even_if_cheaper(self):
        baseline = {"generation_success_rate": 1.0, "correct_env_pass_rate": 1.0, "accuracy": {"min": 100, "p50": 100, "stdev": 0}, "duration_seconds": {"p50": 100, "p95": 110}, "total_tokens": {"p50": 10000, "p95": 11000}}
        candidate = {"generation_success_rate": 1.0, "correct_env_pass_rate": 1.0, "accuracy": {"min": 95, "p50": 100, "stdev": 2}, "duration_seconds": {"p50": 50, "p95": 60}, "total_tokens": {"p50": 5000, "p95": 6000}}
        policy = {"accuracy": {"min_correct_env_pass_rate": 1.0, "max_kill_rate_regression_pp": 0}, "stability": {"max_success_rate_regression": 0, "max_accuracy_stdev_increase_pp": 0.5}, "efficiency": {"promotion_min_improvement_pct": 5, "max_single_metric_regression_pct": 10}}
        self.assertEqual(bench.compare_summaries(baseline, candidate, policy)["decision"], "REJECT")

    def test_equal_accuracy_cheaper_candidate_is_promoted(self):
        baseline = {"generation_success_rate": 1.0, "correct_env_pass_rate": 1.0, "accuracy": {"min": 100, "p50": 100, "stdev": 0}, "duration_seconds": {"p50": 100, "p95": 120}, "total_tokens": {"p50": 10000, "p95": 12000}}
        candidate = {"generation_success_rate": 1.0, "correct_env_pass_rate": 1.0, "accuracy": {"min": 100, "p50": 100, "stdev": 0}, "duration_seconds": {"p50": 80, "p95": 90}, "total_tokens": {"p50": 8000, "p95": 9000}}
        policy = {"accuracy": {"min_correct_env_pass_rate": 1.0, "max_kill_rate_regression_pp": 0}, "stability": {"max_success_rate_regression": 0, "max_accuracy_stdev_increase_pp": 0.5}, "efficiency": {"promotion_min_improvement_pct": 5, "max_single_metric_regression_pct": 10}}
        out = bench.compare_summaries(baseline, candidate, policy)
        self.assertEqual(out["decision"], "PROMOTE")
        self.assertLess(out["normalized_cost_index"], 1.0)

    def test_starter_overrides_evolved_submission(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            question = root / "question"
            workspace = root / "workspace"
            question.mkdir()
            workspace.mkdir()
            (question / "starter_test_submission.py").write_text("starter\n", encoding="utf-8")
            (workspace / "test_submission.py").write_text("solved\n", encoding="utf-8")
            used = bench._apply_starter(question, workspace)
            self.assertEqual(used, "starter_test_submission.py")
            self.assertEqual((workspace / "test_submission.py").read_text(encoding="utf-8"), "starter\n")

    def test_footprint_is_explicitly_static_estimate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / "SKILL.md").write_text("abcd" * 10, encoding="utf-8")
            out = bench.skill_footprint(root)
            self.assertEqual(out["estimated_context_tokens"], 10)
            self.assertIn("Static", out["note"])


if __name__ == "__main__":
    unittest.main()
