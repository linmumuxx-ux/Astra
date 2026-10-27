---
description: Superpowers verification-before-completion - run real verification before claiming completion
---

使用原生 `skill` 工具加载并执行 `verification-before-completion` skill，然后处理下面的输入。

要求：

- 在声称"完成/通过/已修复"之前，必须运行对应验证命令并读取完整输出与退出码。
- 报告实际状态与证据；没有证据就明确说未验证。
- 涉及 Astra 核心 Runtime 或主要流程时，按 `AGENTS.md` 运行对应 E2E / `scripts/verify.py`。

输入：$ARGUMENTS