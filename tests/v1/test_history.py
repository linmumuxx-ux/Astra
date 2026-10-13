import hashlib
import json

import pytest

from domains.core import DomainError
from domains.governance.history import read_artifact
from domains.governance.models import HistoricalArtifact

from . import test_domains
from .test_domains import another_human, setup_team

api = test_domains.api


def archive(root):
    content = (
        json.dumps({"source": {"table": "tasks", "id": 42}, "data": {"title": "原始历史"}}) + "\n"
    ).encode()
    sha = hashlib.sha256(content).hexdigest()
    (root / f"{sha}.json").write_bytes(content)
    return sha


async def test_history_api_checks_private_visibility_and_actual_content_hash(api, tmp_path, monkeypatch):
    app, client, _ = api
    team, _, _ = await setup_team(client)
    owner_id, owner_token = await another_human(app, team["id"])
    sha = archive(tmp_path)
    monkeypatch.setenv("ASTRA_V1_HISTORY_ARTIFACT_ROOT", str(tmp_path))
    async with app.state.db.sessions.begin() as session:
        artifact = HistoricalArtifact(
            team_id=team["id"],
            kind="task-history",
            visibility="PRIVATE",
            owner_actor_id=owner_id,
            content_ref=f"artifact://{sha}.json",
            sha256=sha,
        )
        session.add(artifact)
        await session.flush()
        artifact_id = artifact.id
    path = f"/api/v1/historical-artifacts/{artifact_id}/content"
    assert (await client.get(path)).status_code == 403  # 管理员也不旁路私人历史授权。
    headers = {"Authorization": f"Bearer {owner_token}"}
    result = await client.get(path, headers=headers)
    assert result.status_code == 200 and result.json()["content"]["data"]["title"] == "原始历史"
    (tmp_path / f"{sha}.json").write_text('{"data":"被改写"}')
    assert (await client.get(path, headers=headers)).status_code == 409


def test_history_resolver_rejects_paths_missing_hash_and_symlink(tmp_path):
    sha = archive(tmp_path)
    for ref, expected in [("file:///etc/passwd", sha), (f"artifact://{sha}.json", "0" * 64)]:
        with pytest.raises(DomainError) as caught:
            read_artifact(str(tmp_path), ref, expected)
        assert caught.value.status == 409
    path = tmp_path / f"{sha}.json"
    original = tmp_path / "original.json"
    path.rename(original)
    path.symlink_to(original)
    with pytest.raises(DomainError) as caught:
        read_artifact(str(tmp_path), f"artifact://{sha}.json", sha)
    assert caught.value.status == 409
