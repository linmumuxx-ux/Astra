from pathlib import PurePath

from app.models import Task


def build_task_prompt(
    task: Task,
    workspace: PurePath,
    *,
    retry: bool = False,
    native_question: bool = False,
) -> str:
    criteria = "\n".join(
        f"{item.get('id', f'AC-{index + 1:02d}')}. {item.get('content', '')}"
        for index, item in enumerate(task.acceptance_criteria or [])
    )
    human_input = (task.human_intervention or {}).get("response")
    suspension = task.suspension or {}
    review = (task.review_history or [])[-1] if task.review_history else {}
    retry_text = ""
    if retry:
        retry_text = "\n这是同一任务继续处理，请使用当前执行会话中的已有上下文。"
        if human_input:
            retry_text += f"\n人工补充信息：\n{human_input}"
    context_text = ""
    if task.current_progress:
        context_text += f"\n已保留的当前进展：\n{task.current_progress}"
    if suspension.get("scene_context"):
        context_text += f"\n挂起时现场上下文：\n{suspension['scene_context']}"
    if review.get("feedback"):
        context_text += f"\n上次结果被退回的意见：\n{review['feedback']}"
    if human_input and not retry:
        context_text += f"\n人工补充信息：\n{human_input}"

    if native_question:
        intervention_instructions = """
当任务必须询问使用者或等待业务答案时，必须使用 OpenCode 原生 question Tool
提出可直接回答的具体问题。收到回答后继续当前 Session，不要另建任务。
不要用文本标记或自定义 JSON 伪装成 OpenCode 原生 Question。
"""
    else:
        intervention_instructions = """
当任务必须询问使用者、等待业务答案、权限或其他人工输入时，不要猜测或自行跳过。
当前执行环境完全非交互，不能直接联系使用者。需要人工输入时返回下述标记：
ASTRA_INTERVENTION_JSON: {"blocking_reason":"为什么需要人工输入",
"completed_work":"已完成的工作","current_state":"当前保留状态",
"requested_input":"需要请使用者回答的具体问题"}
不要同时返回完成结果。
"""

    return f"""当前任务：
{task.id}

任务来源：
{task.source}

任务目标：
{task.title}

任务描述：
{task.description}

员工工作空间：
{workspace}

验收标准：
{criteria}

请在该工作空间内自主决定完成方式。Astra 不规定你使用的 Agent、Skill、Tool、命令、
检查方式或内部步骤。请在完成后如实说明处理结果，并逐项说明验收标准是否满足及相关证据。
{intervention_instructions}
最终回复末尾必须追加以下 JSON；ASTRA_RESULT_JSON 标记与 JSON 开头
保持在同一行，且每个验收项都必须选择一个确切结论：
ASTRA_RESULT_JSON: {{"summary":"面向使用者的结果摘要","changes":[],"files":[],"commits":[],
"logs":[],"attachments":[],"other":{{}},"acceptance_results":[{{"criterion_id":"AC-01",
"status":"SATISFIED 或 UNSATISFIED 或 UNCONFIRMED","description":"结论说明","evidence":[]}}]}}
不要省略或改写 ASTRA_RESULT_JSON 标记。{context_text}{retry_text}
"""
