# 任务分类配置修复（2026-09-07）

## 根因

- CategoryConfig 只暴露 load，父组件未调用，子组件未在挂载时加载；初始快照空字符串与空数组序列化值不同，进入即 dirty。
- 提示词只有状态标签，没有编辑入口；接口回填强制置空，保存 payload、后端 schema/model 均无对应字段。
- SettingsView 初始化无条件选择员工并覆盖 query，刷新分类页会丢失 tab 参数。

## 修复

- 挂载加载分类（含停用项）；规范化回填和基线同步更新，加载完成前不判断 dirty。仅比较持久化字段，展开/收起不参与 dirty。
- 统一 FormField 的任务/问题提示词编辑控件，完整提交并按服务端返回值更新快照；保留提示词换行和前后空格。
- 添加两个 nullable Text 字段及 Alembic 0016_category_prompts。PATCH 未传字段不覆盖，允许清空。
- 仅保存变化行，保存成功立即保留真实 ID 和基线，后续行失败可安全重试。增加离开分类页的未保存保护。
- 分类页刷新保留 tab；员工默认选择状态独立初始化。

## 验证

- 前端生产构建、类型检查通过。
- 后端 test_category_prompts.py + test_api.py：9 passed。覆盖创建、双字段更新、仅改描述不丢提示词、新客户端读取持久化数据、清空。
- Chromium category-config.spec.ts：3 passed。覆盖延迟加载无误报、展开无误报、修改还原、可编辑、双字段保存、刷新保留页签及内容、清空持久化、加载失败重试、部分保存失败重试不重复创建。
- Ruff 检查通过。
- SQLite 迁移链升级至 0015 再升级 0016 成功。本机 backend/data/astra.db 从 0015 升级到 0016；迁移前备份 /tmp/astra-before-category-prompts-20260907.db；原分类所有既有列逐值比对一致。
- 浏览器验证使用隔离数据库 /tmp/astra-category-qa.db，未向用户业务数据库写入测试分类。截图 artifacts/category-config/saved-prompts.png（运行目录为仓库根时输出至相邻 artifacts 目录）。

其他环境更新代码时需在 backend 目录运行 `.venv/bin/alembic upgrade head` 并重启后端。本次未部署远端；未改变 Runtime 提示词组装逻辑。
