"""用本机 all-MiniLM-L6-v2 编码几句话，打印维度和余弦。

不启用 AgentScope 知识库，也不读取 API 密钥。
AgentScope 2.0.10 只从 OpenAI、Ollama、Gemini、DashScope 凭证构造嵌入模型。
DeepSeek 没有嵌入模型。Milvus Lite 需要未安装的 pymilvus。
"""

from __future__ import annotations

import json
import math
import sys

TEXTS = (
    "自动化测试失败",
    "测试脚本没有通过",
    "今天的天气很好",
)


def cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        raise SystemExit("嵌入向量长度为 0")
    return dot / (left_norm * right_norm)


def main() -> None:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise SystemExit(
            "缺少 sentence-transformers。请用 nexus/deploy/requirements-embedding.txt 单独安装。"
        ) from exc

    model = SentenceTransformer("all-MiniLM-L6-v2")
    vectors = model.encode(list(TEXTS), normalize_embeddings=False)
    rows = [vector.tolist() for vector in vectors]
    dims = {len(row) for row in rows}
    if len(dims) != 1:
        raise SystemExit(f"维度不一致：{sorted(dims)}")
    similar = cosine(rows[0], rows[1])
    dissimilar = cosine(rows[0], rows[2])
    if similar <= dissimilar:
        raise SystemExit(f"余弦不合理：相近 {similar}，不相近 {dissimilar}")
    json.dump(
        {
            "model": "all-MiniLM-L6-v2",
            "dims": dims.pop(),
            "similar": round(similar, 4),
            "dissimilar": round(dissimilar, 4),
        },
        sys.stdout,
        ensure_ascii=False,
    )
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
