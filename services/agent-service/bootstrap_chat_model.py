"""向已运行的 Agent Service 登记聊天模型，并打印 Session 要用的配置。

Nexus 页面不收集模型或密钥。本脚本只调用官方 `/credential/`。
打印的 JSON 赋给 NEXUS_AGENTSCOPE_CHAT_MODEL_CONFIG。
"""

from __future__ import annotations

import json
import os
import sys

import httpx


def openai_api_key() -> str:
    """读取 OpenAI 兼容密钥。OPENAI_API_KEY 为空时才用 DEEPSEEK_API_KEY。不打印取值。"""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if api_key:
        return api_key
    return os.environ.get("DEEPSEEK_API_KEY", "").strip()


def credential_payload() -> tuple[dict, str]:
    provider = os.environ.get("NEXUS_CHAT_PROVIDER", "ollama")
    if provider == "ollama":
        host = os.environ.get("NEXUS_OLLAMA_HOST", "http://127.0.0.1:11434")
        model = os.environ.get("NEXUS_OLLAMA_MODEL", "qwen2.5:3b")
        return {"type": "ollama_credential", "host": host}, model
    if provider == "openai":
        api_key = openai_api_key()
        model = os.environ.get("OPENAI_MODEL", "").strip()
        if not api_key or not model:
            raise SystemExit("openai 需要 OPENAI_MODEL，以及 OPENAI_API_KEY 或 DEEPSEEK_API_KEY")
        data = {"type": "openai_credential", "api_key": api_key}
        base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
        if base_url:
            data["base_url"] = base_url
        return data, model
    raise SystemExit(f"不支持的 NEXUS_CHAT_PROVIDER：{provider}")


def same_endpoint(stored: dict, data: dict) -> bool:
    if stored.get("type") != data.get("type"):
        return False
    if data.get("type") == "openai_credential":
        return (stored.get("base_url") or "") == (data.get("base_url") or "")
    if data.get("type") == "ollama_credential":
        return (stored.get("host") or "") == (data.get("host") or "")
    return True


def existing_id(client: httpx.Client, data: dict) -> str | None:
    response = client.get("/credential/")
    response.raise_for_status()
    for item in response.json().get("credentials", []):
        stored = item.get("data") or {}
        if item.get("id") and same_endpoint(stored, data):
            return str(item["id"])
    return None


def public_chat_config(credential_type: str, credential_id: str, model: str) -> dict:
    return {
        "type": credential_type,
        "credential_id": credential_id,
        "model": model,
        "parameters": {},
    }


def main() -> None:
    base = os.environ.get("NEXUS_AGENTSCOPE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    user_id = os.environ.get("NEXUS_AGENTSCOPE_USER_ID", "nexus")
    data, model = credential_payload()
    headers = {"X-User-ID": user_id}
    with httpx.Client(base_url=base, headers=headers, timeout=30) as client:
        credential_id = existing_id(client, data)
        if credential_id is None:
            created = client.post("/credential/", json={"data": data})
            created.raise_for_status()
            credential_id = str(created.json()["credential_id"])
    config = public_chat_config(data["type"], credential_id, model)
    json.dump(config, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
