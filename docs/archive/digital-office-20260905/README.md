# NEXUS 数字办公室首页归档（2026-09-05）

本目录保存被数据看板首页替换前的数字办公室实现，供后续重新评估或恢复。

## 归档内容

- `digital-office-source.tar.gz`：首页入口、办公室场景组件、员工状态适配、角色资源与设计说明的完整快照。
- 归档基于当时工作树，而不是仅基于 Git HEAD，因此包含尚未提交的数字办公室改动。
- SHA-256：`f67e90d92a2ddcc78366c19a52108982d602534d09f5f722e5f3078b179d564d`

## 查看与恢复

先查看文件列表：

```bash
tar -tzf docs/archive/digital-office-20260905/digital-office-source.tar.gz
```

建议恢复到临时目录进行对比，不要直接覆盖当前首页：

```bash
mkdir -p /tmp/astra-digital-office-20260905
tar -xzf docs/archive/digital-office-20260905/digital-office-source.tar.gz \
  -C /tmp/astra-digital-office-20260905
```

若未来重启该方向，优先复用其中的员工头像、团队分组和事件状态适配；办公室场景应作为独立专业页面或实验入口，不再直接替换数据总览首页。
