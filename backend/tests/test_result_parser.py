from app.domain import AcceptanceStatus
from app.runtime.result_parser import (
    build_work_result,
    human_readable_result,
    parse_human_intervention,
)

CRITERIA = [{"id": "AC-01", "content": "打印 helloword"}]


def test_markdown_acceptance_table_is_recognized():
    raw = """任务完成。

| 验收项 | 状态 | 证据 |
| --- | --- | --- |
| AC-01. 打印 helloword | ✅ 满足 | 控制台输出 helloword |
"""

    result = build_work_result(raw, CRITERIA, "/records/run.json")

    acceptance = result["acceptance_results"][0]
    assert acceptance["status"] == AcceptanceStatus.SATISFIED
    assert acceptance["description"] == "控制台输出 helloword"
    assert acceptance["evidence"] == ["控制台输出 helloword", "/records/run.json"]


def test_unsatisfied_takes_precedence_over_satisfied_substring():
    raw = "| AC-01 | 未满足 | 实际输出不正确 |"

    result = build_work_result(raw, CRITERIA, "/records/run.json")

    assert result["acceptance_results"][0]["status"] == AcceptanceStatus.UNSATISFIED


def test_structured_result_is_preferred_and_hidden_from_human_summary():
    raw = (
        "已完成处理。\n"
        'ASTRA_RESULT_JSON: {"summary":"处理成功","files":["result.txt"],'
        '"acceptance_results":[{"criterion_id":"AC-01","status":"SATISFIED",'
        '"description":"文件内容正确","evidence":["result.txt"]}]}'
    )

    result = build_work_result(raw, CRITERIA, "/records/run.json")

    assert human_readable_result(raw) == "已完成处理。"
    assert result["summary"] == "处理成功"
    assert result["files"] == ["result.txt"]
    assert result["acceptance_results"][0]["status"] == AcceptanceStatus.SATISFIED


def test_structured_human_intervention_preserves_question_and_hides_payload():
    raw = (
        "需要你补充一个信息后才能继续。\n"
        'ASTRA_INTERVENTION_JSON: {"blocking_reason":"缺少业务答案",'
        '"completed_work":"已准备输出脚本","current_state":"等待回答",'
        '"requested_input":"请告诉我需要打印的具体内容是什么？"}'
    )

    intervention = parse_human_intervention(raw)

    assert intervention == {
        "blocking_reason": "缺少业务答案",
        "completed_work": "已准备输出脚本",
        "current_state": "等待回答",
        "requested_input": "请告诉我需要打印的具体内容是什么？",
        "options": [],
    }
    assert human_readable_result(raw) == "需要你补充一个信息后才能继续。"


def test_missing_per_criterion_conclusion_remains_unconfirmed():
    result = build_work_result("工作已经结束。", CRITERIA, "/records/run.json")

    acceptance = result["acceptance_results"][0]
    assert acceptance["status"] == AcceptanceStatus.UNCONFIRMED
    assert "请人工核对" in acceptance["description"]
