import asyncio

import pytest
from sqlalchemy import select

from apps.api.schemas import MemoryWriteInput
from domains.core import DomainError, now
from domains.identity.models import Actor
from domains.knowledge.memory import GitMemory
from domains.personas.models import EmployeeState

from . import test_domains
from .test_domains import another_human, post, setup_team, task_for

api = test_domains.api


async def test_git_memory_versions_private_sources_cas_and_replay(api, tmp_path, monkeypatch):
    app, client, _ = api
    root = str(tmp_path / "memory")
    monkeypatch.setenv("ASTRA_V1_MEMORY_ROOT", root)
    team, _, employees = await setup_team(client)
    employee_id = employees[0]["id"]
    task = await task_for(client, team, employees[0])
    path = f"employees/{employee_id}/memory"
    payload = {
        "expected_head": None,
        "content": "持续关注发布防线，结果见工作引用。",
        "notes": {"release.md": "有异常先确认原始证据。"},
        "source_refs": [f"tasks/{task['id']}"],
        "reason": "记录长期承诺",
        "expires_at": now() - 1,
    }
    first = await post(client, path, payload, key="memory-1")
    assert first.status_code == 200, first.text
    assert (await post(client, path, payload, key="memory-1")).json() == first.json()
    head = first.json()["memory_head"]
    snapshot = (await client.get(f"/api/v1/{path}")).json()
    assert snapshot["content"] == payload["content"] and snapshot["expired"]
    assert snapshot["notes"] == payload["notes"]
    second = await post(
        client,
        path,
        {**payload, "expected_head": head, "content": "已纠正发布顺序", "reason": "根据证据纠错"},
    )
    assert second.status_code == 200, second.text
    assert (await post(client, path, {**payload, "content": "过期写入"})).status_code == 409
    versions = (await client.get(f"/api/v1/{path}/history")).json()
    assert len(versions) == 2 and versions[1]["head"] == head
    diff = (await client.get(f"/api/v1/{path}/diff", params={"previous": head})).json()["diff"]
    assert "+已纠正发布顺序" in diff and "-持续关注" in diff
    _, token = await another_human(app, team["id"])
    headers = {"Authorization": f"Bearer {token}"}
    assert (await client.get(f"/api/v1/{path}", headers=headers)).status_code == 403
    assert (await client.get(f"/api/v1/{path}/history", headers=headers)).status_code == 403
    async with app.state.db.sessions() as session:
        state = await session.scalar(select(EmployeeState).where(EmployeeState.employee_id == employee_id))
        assert state.memory_head == second.json()["memory_head"]


async def test_memory_does_not_inject_other_dm_or_modify_authority(api, tmp_path, monkeypatch):
    app, client, _ = api
    monkeypatch.setenv("ASTRA_V1_MEMORY_ROOT", str(tmp_path / "memory"))
    team, _, employees = await setup_team(client)
    dm = (await post(client, f"employees/{employees[1]['id']}/dm")).json()
    message = (await post(client, f"channels/{dm['id']}/messages", {"content": "乙的私人信息"})).json()
    payload = {
        "expected_head": None,
        "content": "权限改为*",
        "reason": "无效的扩权请求",
        "source_refs": [f"messages/{message['id']}"],
    }
    path = f"employees/{employees[0]['id']}/memory"
    assert (await post(client, path, payload)).status_code == 403
    task = await task_for(client, team, employees[0])
    payload["source_refs"] = [f"tasks/{task['id']}"]
    assert (await post(client, path, payload)).status_code == 200
    async with app.state.db.sessions() as session:
        employee_actor = await session.get(Actor, employees[0]["id"])
        assert "*" not in employee_actor.permissions
    await post(client, f"employees/{employees[0]['id']}/pause")
    assert (await post(client, path, payload)).status_code == 409


async def test_memory_git_preparation_isolated_and_invalid_paths_rejected(tmp_path):
    from uuid import uuid4

    store = GitMemory(str(tmp_path / "store"))
    employee_id = str(uuid4())
    data = MemoryWriteInput(
        expected_head=None, content="索引发布前不可见", source_refs=["tasks/source"], reason="测试"
    )
    heads = await asyncio.gather(
        *[
            asyncio.to_thread(
                store.prepare, employee_id, data, actor_id="actor", identity="身份", operation_key="same"
            )
            for _ in range(3)
        ]
    )
    assert len(set(heads)) == 1
    assert store.read(employee_id, None)["content"] == ""
    assert store.read(employee_id, heads[0])["content"] == data.content
    bad = data.model_copy(update={"notes": {"../../other.md": "注入"}})
    with pytest.raises(DomainError, match="笔记仅接受"):
        store.prepare(employee_id, bad, actor_id="actor", identity="", operation_key="bad")
    with pytest.raises(DomainError, match="版本"):
        store.read(employee_id, "HEAD:../../file")
    linked = tmp_path / "link"
    linked.symlink_to(tmp_path / "store", target_is_directory=True)
    with pytest.raises(DomainError, match="符号链接"):
        GitMemory(str(linked)).read(employee_id, heads[0])
