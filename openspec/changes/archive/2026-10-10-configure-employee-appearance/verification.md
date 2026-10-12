# 形象配置验证

## 完整性、正确性与一致性

新增的“数字员工形象配置” Requirement 的五个 Scenario 均有对应实现和针对性验证。员工 `character_id` 为持久化事实源，前端共用首页九种素材，已删除运行时 ID 选形象和动态避重逻辑。迁移仅一次性计算旧首页人物，不改变其他员工字段；不涉及 Runtime 生命周期或 workspace-ui 构建。

| Scenario | 验证证据 |
| --- | --- |
| 新建员工并选择形象 | `backend/tests/test_employee_character.py` 验证默认值及持久化；`frontend/e2e/employee-character.spec.ts` 验证九种图片可加载、选择、创建、重载、列表、详情、首页与重开配置；`frontend/e2e/astra.spec.ts` 使用隔离后端创建员工并确认形象保存与回显 |
| 编辑已有员工形象 | API 用例遍历 0–8，GET/列表/首页均返回所选编号，状态不变；浏览器用例验证详情页编辑及首页展示；同形象员工不相互影响 |
| 放弃或保存失败 | 浏览器验证放弃不写入，重开恢复原选择，503 保留草稿，再次保存成功；只改形象不调用环境检测 |
| 非法形象输入与局部更新 | 创建和 PATCH 拒绝 -1、9、null、小数、字符串及布尔值；创建省略默认 0，PATCH 省略保留已有选择 |
| 升级保留原首页形象 | 隔离 SQLite 迁移覆盖英文、中文和 emoji ID，期望值以旧首页 JS 表达式核对；验证非空默认值、其他字段保留与 downgrade；首页浏览器用例验证状态、排序及同形象员工不改变人物 |

## 已运行检查

- 针对性后端：`pytest tests/test_employee_character.py tests/test_dashboard_office.py tests/test_api.py`，40 passed。
- 浏览器针对性：数字办公室及远程配置回归 19 passed；新增形象配置用例修正测试路由范围与原生单选标签操作后 2 passed。
- 窄屏验证发现既有 600px 固定抽屉会截断人物选择区，已限制抽屉宽度并改为两列人物；修改后的形象配置（含 390px 窄屏）及远程配置回归 6 passed，重新运行管理台类型检查和生产构建通过。
- 静态检查：后端 `ruff check app tests` 通过；新增迁移 Ruff 通过；管理台 `vue-tsc -b` 通过；`git diff --check` 通过。
- 管理台生产构建：直接运行 `vite build` 通过，复用已有 workspace-ui 静态产物；存在现有包体大小提示。
- OpenSpec change 校验、主规范校验、配置检查及 OpenCode bootstrap 回归通过。
- 全量后端：467 passed、4 skipped、1 failed。失败为 `test_preflight_database_isolation.py::test_gateway_tables_are_registered_as_astra_tables` 仍要求已删除的 `gateway_config_versions` 表，与本次员工形象实现无关。
- 完整隔离 Chromium E2E：195 passed、15 skipped、1 failed。员工创建形象持久化、新增形象用例、首页形象用例及原有配置表单回归均通过。失败为 `astra.spec.ts:31` 仍要求旧标题“实时动态”，当前首页标题为“最近动态”，属于既有手动刷新变更留下的旧断言。

## 验证边界与风险

未对真实 MySQL、生产服务或真实 OpenCode 员工执行验证。数据库迁移在临时 SQLite 数据库完成，完整 E2E 使用隔离服务和执行器；未修改现有业务数据库。部署前需在 `backend/` 执行 `alembic upgrade head`，回滚删除形象列会丢失用户选择，应预先备份。

已同步 `digital-office-home` 主规范及使用指南，保留同工作区其他变更的规范内容。全量回归失败必须单独记录，不将它们报告为通过。

## OpenSpec 验证结论

完整性：6 项任务均已执行，1 项新增 Requirement 的 5 个 Scenario 均有验证证据。正确性：创建、编辑、保存失败、局部更新和升级保留形象与契约一致。一致性：员工记录为单一事实源，统一复用首页素材，无 Runtime 改动或长期历史兼容逻辑。本变更无未实现需求；全量验证有上述 2 项与本变更无关的失败，作为验证限制保留。
