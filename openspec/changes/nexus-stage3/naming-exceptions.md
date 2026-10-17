# 命名例外清单

按 D4，只改用户能看到的产品文案。下面这些名字留下，隔离不靠改它们。

| 留下的名字 | 原因 |
|---|---|
| 环境变量前缀 `ASTRA_` | 改名会碰到大量设置。变量名不改，默认产品名是 Nexus |
| `ASTRA_GATEWAY_MASTER_KEY` | 不改 Gateway 密钥名，也不轮换主密钥 |
| 请求头 `X-Astra-User-Id`、`X-Astra-Role`、`X-Astra-Worker-Epoch`、`X-Astra-Worker-Gateway-Key`、`X-Astra-Sha256` | 通道身份，不是页面文案 |
| 前端组件、store、CSS 变量（`AstraPageHeader`、`useAstraStore`、`--astra-*`） | 不是用户读到的产品名 |
| Celery 历史注释、`openspec/specs/` 和已归档 OpenSpec | 不是运行入口。历史契约不改 |
| 测试夹具里为了断言旧字符串而保留的样本 | 只存在于测试，例如路径、`user.name`、员工名 |
| 演示种子 `Astra-01` 一类名称 | 库存名。页面展示已换成 Worker 编号 |
| 已卸下的助手模块里的「平台助手」字样 | 产品路径 `/api/assistant` 已不挂载，这些字符串不再是入口 |
