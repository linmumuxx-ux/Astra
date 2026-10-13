"""历史内容只认受控归档根和内容哈希；不接受业务请求指定文件路径。"""

import hashlib
import json
import os
import re
from pathlib import Path

from domains.core import DomainError


def read_artifact(root: str | None, content_ref: str, expected_sha256: str):
    if not root or not Path(root).is_absolute():
        raise DomainError(503, "历史归档根目录尚未配置")
    match = re.fullmatch(r"artifact://([a-f0-9]{64})\.json", content_ref)
    if not match or match.group(1) != expected_sha256:
        raise DomainError(409, "历史索引的内容引用与哈希不一致")
    try:
        directory = Path(root).resolve(strict=True)
    except OSError as exc:
        raise DomainError(503, "历史归档根目录不可用") from exc
    path = directory / f"{expected_sha256}.json"
    if path.is_symlink():
        raise DomainError(409, "历史内容不能通过符号链接指向外部文件")
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as source:
            content = source.read(8 * 1024 * 1024 + 1)
    except FileNotFoundError as exc:
        raise DomainError(404, "历史归档内容不存在，需核验迁移报告") from exc
    except OSError as exc:
        raise DomainError(503, "历史归档内容当前不可读取") from exc
    if len(content) > 8 * 1024 * 1024:
        raise DomainError(413, "历史内容超过在线读取限制，请使用受控审计导出")
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise DomainError(409, "历史归档内容哈希不匹配，拒绝使用被修改的证据")
    try:
        return json.loads(content)
    except (UnicodeDecodeError, ValueError) as exc:
        raise DomainError(409, "历史归档不是有效 UTF-8 JSON") from exc
