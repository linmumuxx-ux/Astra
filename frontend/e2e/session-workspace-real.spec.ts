import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, realpathSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { execFileSync, spawn, type ChildProcess } from 'node:child_process'
import { createServer } from 'node:net'

// Opt-in integration: real Astra, real OpenCode and a configured real model; no route mocks.
test.describe('真实 Task / Session Workspace', () => {
  test.use({ actionTimeout: 15_000 })
  test.describe.configure({ mode: 'serial', timeout: 120_000 })
  test.skip(process.env.ASTRA_WORKSPACE_E2E_REAL !== '1', '需要真实 OpenCode 可用模型')
  let server: ChildProcess
  let port: number
  let root: string
  let repo: string
  let employee: string
  let a: any
  let b: any
  let native: string
  const model = process.env.ASTRA_REAL_E2E_MODEL!
  const frame = (page: Page) => page.frameLocator('iframe[title="OpenCode Task Workspace"]')
  const anomalies = new Map<Page, string[]>()
  let expectedFailure = false

  async function get(request: APIRequestContext, id: string) {
    const response = await request.get(`/api/tasks/${id}`)
    expect(response.ok()).toBeTruthy()
    return response.json()
  }
  async function outcome(request: APIRequestContext, id: string, state: string) {
    await expect.poll(async () => (await get(request, id)).status, { timeout: 100_000, intervals: [300, 600, 1000] }).toBe(state)
    return get(request, id)
  }
  async function open(page: Page, task: any) {
    await page.goto(`/tasks/${task.id}`)
    await expect(page.locator('.task-header h1')).toHaveText(task.title)
    await expect(frame(page).locator('[data-component="prompt-input"]')).toBeVisible({ timeout: 25_000 })
    await expect(page.getByLabel('选择 Session')).toHaveValue(task.current_session_id)
  }
  async function runServer(request: APIRequestContext) {
    server = spawn(process.env.ASTRA_REAL_E2E_BINARY || 'opencode', ['serve', '--hostname', '127.0.0.1', '--port', String(port)], { cwd: repo, stdio: 'ignore' })
    await expect.poll(async () => {
      try { return (await request.get(`${native}/global/health`)).ok() } catch { return false }
    }, { timeout: 30_000 }).toBe(true)
  }
  async function stopServer() {
    if (!server || server.exitCode !== null) return
    const stopped = new Promise<void>(resolve => server.once('exit', () => resolve()))
    server.kill('SIGTERM')
    await stopped
  }
  async function createTask(request: APIRequestContext, suffix: string, description: string) {
    const response = await request.post('/api/tasks', { data: {
      task_type: 'ISSUE', category_id: 'testing-platform', title: `${employee} ${suffix}`, description,
      acceptance_criteria: [{ content: '按要求修改指定文件并完成回复' }], priority: 'LOW', employee_id: employee,
    } })
    expect(response.status()).toBe(201)
    return response.json()
  }

  test.beforeAll(async ({ request }) => {
    expect(model, '必须显式配置 ASTRA_REAL_E2E_MODEL，不能跳过真实执行').toBeTruthy()
    root = realpathSync(mkdtempSync(join(tmpdir(), 'astra-native-acceptance-')))
    repo = join(root, 'repository'); mkdirSync(repo)
    writeFileSync(join(repo, 'hello.ts'), 'export const hello = "before"\n')
    writeFileSync(join(repo, 'README.md'), '# Acceptance repository\n')
    execFileSync('git', ['init', '-b', 'acceptance'], { cwd: repo })
    execFileSync('git', ['add', '.'], { cwd: repo })
    execFileSync('git', ['-c', 'user.name=Astra E2E', '-c', 'user.email=e2e@localhost', 'commit', '-m', 'fixture'], { cwd: repo })
    const socket = createServer()
    await new Promise<void>(resolve => socket.listen(0, '127.0.0.1', resolve))
    port = (socket.address() as { port: number }).port
    await new Promise<void>(resolve => socket.close(() => resolve()))
    native = `http://127.0.0.1:${port}`
    await runServer(request)
    employee = `native-${Date.now()}`
    const response = await request.post('/api/employees', { data: {
      id: employee, name: employee, role: '验收员工', auto_claim: false, auto_execute: false,
      task_types: ['ISSUE'], category_ids: ['testing-platform'], execution_environment: {
        mode: 'LOCAL', workspace_root: repo, opencode_server_port: port,
        opencode_path: process.env.ASTRA_REAL_E2E_BINARY || 'opencode', model_name: model,
      },
    } })
    expect(response.status()).toBe(201)
    a = await createTask(request, 'Task A', 'Use the question tool to ask "Approve workspace edit?" with option "Approve". Wait for the answer. Then change hello.ts from "before" to "after", append "A changed" to README.md, and reply "A_COMPLETE". Do not commit.')
    b = await createTask(request, 'Task B', 'Append "B isolated" to README.md. Do not change hello.ts. Do not commit. Reply "B_COMPLETE".')
  })
  test.beforeEach(async ({ page }) => {
    expectedFailure = false
    const issues: string[] = []; anomalies.set(page, issues)
    page.on('pageerror', e => issues.push(`JS: ${e.message}`))
    page.on('console', m => { if (!expectedFailure && (m.type() === 'error' || m.text().includes('[Vue warn]'))) issues.push(m.text()) })
    page.on('response', r => { if (!expectedFailure && r.status() >= 400) issues.push(`HTTP ${r.status()} ${r.url()}`) })
    page.on('requestfailed', r => { if (!expectedFailure && !/ERR_ABORTED|NS_BINDING_ABORTED/.test(r.failure()?.errorText || '')) issues.push(`NETWORK ${r.url()} ${r.failure()?.errorText}`) })
  })
  test.afterEach(async ({ page }, info) => {
    await page.screenshot({ path: info.outputPath('workspace.png'), fullPage: true })
    await info.attach('browser-diagnostics', { body: JSON.stringify(anomalies.get(page), null, 2), contentType: 'application/json' })
    expect(anomalies.get(page)).toEqual([])
  })
  test.afterAll(async ({ request }) => {
    for (const task of [a, b]) {
      if (task && server?.exitCode === null) {
        const current = await get(request, task.id)
        if (['RUNNING', 'WAITING'].includes(current.status) || current.pending_message_id) await request.post(`/api/tasks/${task.id}/stop`)
      }
    }
    await stopServer()
  })

  test('1 列表进入 Workspace，真实问题使任务 WAITING，回答后执行成功', async ({ page, request }) => {
    await page.goto('/tasks')
    await page.getByText(a.title, { exact: true }).click()
    await page.getByRole('button', { name: '启动任务', exact: true }).click()
    a = await outcome(request, a.id, 'WAITING')
    await expect(page.locator('.task-header .runtime-status-badge')).toHaveAttribute('data-state', 'WAITING')
    await expect(frame(page).getByText('Approve workspace edit?', { exact: true })).toBeVisible({ timeout: 25_000 })
    await frame(page).getByText('Approve', { exact: true }).click()
    const submit = frame(page).getByRole('button', { name: /Submit|Confirm|提交|确认/ }).last()
    if (await submit.isVisible()) await submit.click()
    a = await outcome(request, a.id, 'SUCCEEDED')
    await expect(page.locator('.task-header .runtime-status-badge')).toHaveAttribute('data-state', 'SUCCEEDED', { timeout: 10_000 })
    await expect(frame(page).locator('[data-component="text-part"]').filter({ hasText: 'A_COMPLETE' }).last()).toBeVisible()
    expect(readFileSync(join(a.workspace, 'hello.ts'), 'utf8')).toContain('"after"')
  })

  test('2 同一 Session 续聊，SSE 驱动 RUNNING 到 SUCCEEDED，无刷新更新', async ({ page, request }) => {
    await open(page, a)
    const binding = await (await request.get(`/api/tasks/${a.id}/workspace`)).json()
    const writes: string[] = []
    page.on('request', r => {
      if (r.method() === 'POST') writes.push(new URL(r.url()).pathname)
      if (r.url().endsWith('/prompt_async')) {
        const selected = r.postDataJSON().model
        expect(`${selected.providerID}/${selected.modelID}`).toBe(model)
      }
    })
    const prompt = frame(page).locator('[data-component="prompt-input"]')
    await prompt.fill('Read hello.ts, then reply exactly CONTINUE_COMPLETE. Do not change any files.')
    await prompt.press('Enter')
    await expect(page.locator('.task-header .runtime-status-badge')).toHaveAttribute('data-state', 'RUNNING', { timeout: 10_000 })
    a = await outcome(request, a.id, 'SUCCEEDED')
    await expect(page.locator('.task-header .runtime-status-badge')).toHaveAttribute('data-state', 'SUCCEEDED', { timeout: 10_000 })
    await expect(frame(page).locator('[data-component="text-part"]').filter({ hasText: 'CONTINUE_COMPLETE' }).last()).toBeVisible()
    // ASTRA 主题在原生 Workspace 内生效：用户消息右对齐，OpenCode 消息带明确身份标识。
    await expect(frame(page).locator('#astra-workspace-theme')).toHaveCount(1)
    const assistantIdentity = await frame(page).locator('[data-slot="session-turn-assistant-content"]').first().evaluate(el => getComputedStyle(el, '::before').content)
    const userMarginLeft = await frame(page).locator('[data-component="user-message"]').first().evaluate(el => getComputedStyle(el).marginLeft)
    expect(assistantIdentity).toContain('OpenCode')
    expect(userMarginLeft).not.toBe('0px')
    expect(writes).toContain(`/api/tasks/${a.id}/opencode/${a.current_session_id}/session/${a.current_session_id}/prompt_async`)
    expect(writes.some(path => /\/(start|restart)$/.test(path))).toBe(false)
    // Continuing must reuse the same Session; status/finished_at legitimately change.
    const after = (await (await request.get(`/api/tasks/${a.id}/workspace`)).json()).sessions
    expect(after.map((item: any) => item.id)).toEqual(binding.sessions.map((item: any) => item.id))
  })

  test('2.5 打开原生 Settings 读取只读 shells 不再 403，且不重建 Session、不丢失对话', async ({ page, request }) => {
    await open(page, a)
    const before = a.current_session_id
    const writes: string[] = []
    const shells: number[] = []
    page.on('request', r => { if (r.method() === 'POST') writes.push(new URL(r.url()).pathname) })
    page.on('response', r => { if (r.url().endsWith('/pty/shells')) shells.push(r.status()) })

    await frame(page).locator('[data-component="prompt-input"]').click()
    await page.keyboard.press(process.platform === 'darwin' ? 'Meta+Comma' : 'Control+Comma')

    await expect(frame(page).locator('[role="dialog"]')).toBeVisible({ timeout: 10_000 })
    await expect.poll(() => shells.length, { timeout: 10_000 }).toBeGreaterThan(0)
    expect(shells.every(status => status === 200)).toBeTruthy()
    // 单个非核心设置读取失败也不能显示整页错误或原始堆栈。
    await expect(frame(page).locator('body')).not.toContainText('Something went wrong')
    await expect(frame(page).locator('body')).not.toContainText('Forbidden')
    // Session 绑定不变，对话与 Diff 状态保留。
    expect((await get(request, a.id)).current_session_id).toBe(before)
    expect(writes.some(path => /\/(start|restart)$/.test(path))).toBe(false)
    await expect(frame(page).locator('[data-component="text-part"]').filter({ hasText: 'CONTINUE_COMPLETE' }).last()).toBeVisible()
  })

  test('3 真实文件切换、Changes 与实际 Diff 行内容', async ({ page }) => {
    await open(page, a)
    if (await frame(page).getByRole('button', { name: 'Toggle review', exact: true }).getAttribute('aria-expanded') !== 'true') await frame(page).getByRole('button', { name: 'Toggle review', exact: true }).click()
    await frame(page).getByRole('button', { name: 'Open file', exact: true }).click()
    const tree = frame(page).locator('[data-component="file-tree-v2"]').last()
    await tree.getByText('hello.ts', { exact: true }).click()
    await expect(frame(page).locator('[data-component="file"][data-mode="text"]').last()).toContainText('export const hello = "after"')
    await tree.getByText('README.md', { exact: true }).click()
    await expect(frame(page).locator('[data-component="file"][data-mode="text"]').last()).toContainText('A changed')
    await frame(page).getByRole('tab', { name: /files changed/i }).click()
    const review = frame(page).locator('#review-panel')
    await review.locator('[data-component="file-tree-v2"]').getByText('hello.ts', { exact: true }).click()
    const diff = review.locator('[data-component="file"][data-mode="diff"]')
    await expect(diff.first()).toContainText('"before"')
    await expect(diff.first()).toContainText('"after"')
  })

  test('4 附件入口收敛到原生输入框；刷新保留对话、绑定与路径', async ({ page, request }) => {
    await open(page, a)
    // 文件上传统一由原生输入框的附件入口承担，Astra 外壳不再提供单独上传入口。
    await expect(page.locator('.file-transfer')).toHaveCount(0)
    await expect(page.locator('input[type="file"]')).toHaveCount(0)
    await expect(frame(page).locator('[data-component="prompt-input"]')).toBeVisible()
    await page.reload()
    await expect(frame(page).locator('[data-component="text-part"]').filter({ hasText: 'CONTINUE_COMPLETE' }).last()).toBeVisible({ timeout: 25_000 })
    await expect(page.getByLabel('选择 Session')).toHaveValue(a.current_session_id)
    await page.getByRole('button', { name: '任务信息', exact: true }).click()
    await expect(page.locator('.task-info')).toContainText(a.workspace)
    const repoInfo = await (await request.get(`/api/tasks/${a.id}/repo`)).json()
    expect(repoInfo.name).toBe('repository')
    await expect(page.locator('.repo')).toContainText('repository / detached')
    expect(repoInfo.commit).toBe(execFileSync('git', ['rev-parse', 'HEAD'], { cwd: a.workspace, encoding: 'utf8' }).trim())
    expect(repoInfo.branch).toBe(execFileSync('git', ['branch', '--show-current'], { cwd: a.workspace, encoding: 'utf8' }).trim())
    await expect(page.locator('.repo')).toContainText(repoInfo.commit.slice(0, 8))
    await expect(page.locator('.task-header .runtime-status-badge')).toHaveAttribute('data-state', 'SUCCEEDED')
    if (await frame(page).getByRole('button', { name: 'Toggle review', exact: true }).getAttribute('aria-expanded') !== 'true') await frame(page).getByRole('button', { name: 'Toggle review', exact: true }).click()
    await frame(page).getByRole('button', { name: 'Open file', exact: true }).click()
    await expect(frame(page).locator('[data-component="file-tree-v2"]').last()).toBeVisible()
  })

  test('5 Task A → B → A，Session、文件、Diff 与状态隔离', async ({ page, request }) => {
    expect((await request.post(`/api/tasks/${b.id}/start`)).ok()).toBeTruthy()
    b = await outcome(request, b.id, 'SUCCEEDED')
    expect(a.current_session_id).not.toBe(b.current_session_id)
    expect(a.workspace).not.toBe(b.workspace)
    await open(page, a)
    await page.getByRole('link', { name: '返回任务列表', exact: true }).click()
    await page.getByText(b.title, { exact: true }).click()
    await expect(page.getByLabel('选择 Session')).toHaveValue(b.current_session_id)
    await expect(frame(page).locator('[data-component="text-part"]').filter({ hasText: 'B_COMPLETE' }).last()).toBeVisible()
    await expect(frame(page).getByText('CONTINUE_COMPLETE', { exact: true })).toHaveCount(0)
    expect(readFileSync(join(b.workspace, 'hello.ts'), 'utf8')).toContain('"before"')
    const diffs = await (await request.get(`/api/tasks/${b.id}/opencode/${b.current_session_id}/vcs/diff?mode=git`)).json()
    expect(diffs.map((f: any) => f.file)).toEqual(['README.md'])
    expect((await request.get(`/api/tasks/${a.id}/opencode/${b.current_session_id}/session`)).status()).toBe(404)
    await page.getByRole('link', { name: '返回任务列表', exact: true }).click()
    await page.getByText(a.title, { exact: true }).click()
    await expect(page.getByLabel('选择 Session')).toHaveValue(a.current_session_id)
    await expect(frame(page).locator('[data-component="text-part"]').filter({ hasText: 'CONTINUE_COMPLETE' }).last()).toBeVisible()
    await expect(frame(page).getByText('B_COMPLETE', { exact: true })).toHaveCount(0)
  })

  test('6 原生模型错误投影 FAILED；同一 Session 恢复后清除异常', async ({ page, request }) => {
    expectedFailure = true
    await open(page, a)
    const response = await request.post(`/api/tasks/${a.id}/opencode/${a.current_session_id}/session/${a.current_session_id}/prompt_async`, { data: {
      model: { providerID: 'missing-e2e-provider', modelID: 'missing-model' }, parts: [{ type: 'text', text: 'Failure acceptance' }],
    } })
    expect(response.status()).toBe(204)
    a = await outcome(request, a.id, 'FAILED')
    await expect(page.locator('.task-header .runtime-status-badge')).toHaveAttribute('data-state', 'FAILED', { timeout: 10_000 })
    // The provider error text is OpenCode-owned copy; Astra must still surface the
    // failure fact and keep the failed native turn visible in the conversation.
    expect(a.failure_reason).toBeTruthy()
    await expect(frame(page).locator('body')).toContainText('Failure acceptance')
    const [providerID, ...rest] = model.split('/')
    expect((await request.post(`/api/tasks/${a.id}/opencode/${a.current_session_id}/session/${a.current_session_id}/prompt_async`, { data: {
      model: { providerID, modelID: rest.join('/') }, parts: [{ type: 'text', text: 'Reply RECOVERED_COMPLETE. No tools.' }],
    } })).status()).toBe(204)
    a = await outcome(request, a.id, 'SUCCEEDED')
    await expect(page.locator('.task-header .runtime-status-badge')).toHaveAttribute('data-state', 'SUCCEEDED', { timeout: 10_000 })
    await expect(page.locator('.workspace-alert')).toHaveCount(0)
    await expect(frame(page).locator('[data-component="text-part"]').filter({ hasText: 'RECOVERED_COMPLETE' }).last()).toBeVisible()
  })

  test('7 真实 Server 断开和重启：明确提示、保留业务状态、恢复原 Session', async ({ page, request }) => {
    expectedFailure = true
    await stopServer()
    await page.goto(`/tasks/${a.id}`)
    await page.getByRole('button', { name: '任务信息', exact: true }).click()
    expect((await request.post(`/api/tasks/${a.id}/reconnect`)).status()).toBe(503)
    await page.reload()
    await expect(page.locator('.workspace-alert')).toContainText('最后已知状态')
    expect((await get(request, a.id)).status).toBe('SUCCEEDED')
    await runServer(request)
    await page.locator('.workspace-alert').getByRole('button', { name: '重连', exact: true }).click()
    await expect(page.locator('.workspace-alert')).toHaveCount(0)
    await expect(frame(page).locator('[data-component="text-part"]').filter({ hasText: 'RECOVERED_COMPLETE' }).last()).toBeVisible({ timeout: 25_000 })
    expect((await get(request, a.id)).current_session_id).toBe(a.current_session_id)
  })

  test('8 真实 Session 删除后明确反馈，不自动新建、不无限加载', async ({ page, request }) => {
    expectedFailure = true
    expect((await request.delete(`${native}/session/${b.current_session_id}`, { params: { directory: b.workspace } })).ok()).toBeTruthy()
    await page.goto(`/tasks/${b.id}`)
    expect((await request.post(`/api/tasks/${b.id}/reconnect`)).status()).toBe(404)
    await page.reload()
    await expect(page.locator('.task-header h1')).toHaveText(b.title)
    await expect(page.locator('.workspace-alert')).toContainText('Session')
    expect((await get(request, b.id)).current_session_id).toBe(b.current_session_id)
    expect((await (await request.get(`/api/tasks/${b.id}/workspace`)).json()).sessions).toHaveLength(1)
  })
})
