# Astra 1.0 Web

独立 Vue 3 / Element Plus 应用，仅调用新 `/api/v1`。不导入旧 `frontend` 的业务模块、路由、Store 或 Workspace UI。品牌 Token 与组件主题从已验证的旧主题复制到 `src/styles`，之后在新应用维护。

## 开发与构建

在 `apps/web` 执行：

```sh
npm ci
ASTRA_API_URL=http://127.0.0.1:8200 npm run dev
npm run build
```

默认页面地址 `http://127.0.0.1:5273`。`ASTRA_API_URL` 只控制开发代理；生产反向代理需将 `/api/v1` 转给新 API。需使用不同 API 前缀时，在构建时显式提供 `VITE_API_BASE`。前端不提供默认身份，凭据必须由后台签发。

构建产物 `dist/` 包含全部 JavaScript、Three.js、图标及 CSS，无 CDN、外部字体、远程材质或在线资产依赖。静态服务器需对页面路由提供 `index.html` 回退；API 错误不可回退成 HTML。SSE 代理需关闭响应缓冲并保持流式连接。所有正式写入含 `Idempotency-Key`，传输失败重试保留该操作键。

## 真实 API 浏览器验收

```sh
npx playwright install chromium
npm run test:e2e:real
```

`test:e2e:real` 自动创建一次性 SQLite 新库、私有临时凭据、随机端口新 API 与 Vite，使用真实 REST / SSE 与真实浏览器，不使用网络 Mock。凭据不会打印到日志；测试完成清理临时凭据、数据库和由该脚本启动的进程。可用 `ASTRA_PYTHON` 显式选择安装了新 API 依赖的 Python，默认使用仓库 `backend/.venv/bin/python`。

可使用已安装的浏览器：

```sh
ASTRA_E2E_BROWSER='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' npm run test:e2e:real
```

连接已有**隔离验收环境**时，使用 `ASTRA_E2E_TOKEN_FILE`、`ASTRA_E2E_API_URL` 和 `ASTRA_WEB_URL` 后执行 `npm run test:e2e`。套件会创建团队、岗位、员工、目标、Task、审批和资料，请勿指向生产库。

截图写入 `docs/astra-1.0/evidence/`，测试结果在忽略目录 `test-results/`。测试关闭 Trace、视频及失败自动截图，避免把登录凭据写进测试记录。

## 页面当前边界

页面读取后端权威状态，未完成的后端能力不会伪装成可执行功能。API 网关尚无管理接口时明确呈现未接入；个人 Git Memory 未配置时明确呈现未配置；任务没有原生工作区 URL 时不展示不可用嵌入；Skill 验证发布链只按真实记录展示。页面存在和构建成功不等于完整 Astra 1.0 已验收，详见 `docs/astra-1.0/pages.md`。
