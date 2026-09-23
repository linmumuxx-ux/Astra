import { expect, test } from '@playwright/test'

// Isolated protocol fixture; live acceptance is in session-workspace-real.spec.ts.
test('协议契约：原生 Workspace 显示对话、工具、文件与 Diff，续聊保持 Session', async ({ page }) => {
  const requests: Array<{path: string; body: any}> = []
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const directory = '/test/workspace'
  const sid = 'ses_workspace'
  const now = Date.now()
  const info = {id: sid, slug: 'task-workspace', projectID: 'project_test', directory, version: '1.18.31', title: 'Workspace acceptance', time: {created: now - 3000, updated: now}, summary: {additions: 1, deletions: 1, files: 1}}
  const task = {id: 'T-WORKSPACE', title: 'Workspace acceptance', description: 'Use native OpenCode', status: 'FAILED', runtime_state: 'FAILED', runtime_status_label: '执行失败', runtime_detail: '', runtime_connection: 'CONNECTED', current_session_id: sid, workspace: directory, employee_id: 'E1', acceptance_criteria: [], started_at: new Date(now - 3000).toISOString(), created_at: new Date(now).toISOString(), updated_at: new Date(now).toISOString()}
  const diff = [{file: 'hello.ts', before: 'export const hello = "before"\n', after: 'export const hello = "after"\n', additions: 1, deletions: 1, status: 'modified'}]
  const model = {id: 'test-model', providerID: 'test', name: 'Test model', api: {id: 'test-model', url: '', npm: ''}, capabilities: {temperature: true, reasoning: false, attachment: true, toolcall: true, input: {text: true, image: true}, output: {text: true}}, cost: {input: 0, output: 0, cache: {read: 0, write: 0}}, limit: {context: 128000, output: 4096}, status: 'active', options: {}, headers: {}, release_date: '2026-01-01'}
  const providers = {all: [{id: 'test', name: 'Test', env: [], models: {'test-model': model}}], connected: ['test'], default: {test: 'test-model'}}
  const messages = [
    {info: {id: 'msg_00000001', role: 'user', sessionID: sid, time: {created: now - 2000}, agent: 'build', model: {providerID: 'test', modelID: 'test-model'}}, parts: [{id: 'prt_user0001', sessionID: sid, messageID: 'msg_00000001', type: 'text', text: 'Please update hello.ts'}]},
    {info: {id: 'msg_00000002', role: 'assistant', sessionID: sid, parentID: 'msg_00000001', time: {created: now - 1000, completed: now}, modelID: 'test-model', providerID: 'test', mode: 'build', agent: 'build', path: {cwd: directory, root: directory}, cost: 0, tokens: {input: 10, output: 10, reasoning: 0, cache: {read: 0, write: 0}}, finish: 'stop'}, parts: [
      {id: 'prt_00000002', sessionID: sid, messageID: 'msg_00000002', type: 'tool', callID: 'call_001', tool: 'read', state: {status: 'completed', input: {filePath: `${directory}/hello.ts`}, output: 'export const hello = "after"', title: `${directory}/hello.ts`, metadata: {}, time: {start: now - 1000, end: now - 500}}},
      {id: 'prt_00000003', sessionID: sid, messageID: 'msg_00000002', type: 'text', text: 'Updated the greeting in hello.ts.'},
    ]},
  ]
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (!path.startsWith('/api/')) return route.continue()
    if (path.includes('/opencode/')) {
      const native = path.split(`/opencode/${sid}`)[1]!
      if (route.request().method() !== 'GET') {
        requests.push({path: native, body: route.request().postDataJSON()})
        return route.fulfill({status: 204})
      }
      if (native === '/global/event') return route.fulfill({contentType: 'text/event-stream', body: `data: ${JSON.stringify({directory, payload: {type: 'server.connected', properties: {}}})}\n\n`})
      const data: Record<string, unknown> = {
        '/global/health': {healthy: true, version: '1.18.31'}, '/global/config': {}, '/config': {model: 'test/test-model', snapshot: true},
        '/path': {directory, worktree: directory, home: directory, config: directory, state: directory},
        '/project': [{id: 'project_test', worktree: directory, vcs: 'git', time: {created: now}, sandboxes: []}],
        '/project/current': {id: 'project_test', worktree: directory, vcs: 'git', time: {created: now}, sandboxes: []},
        '/provider': providers, '/config/providers': {providers: providers.all, default: providers.default}, '/provider/auth': {},
        '/agent': [{name: 'build', mode: 'primary', native: true, permission: []}], '/command': [], '/skill': [], '/mcp': {}, '/lsp': [], '/formatter': [], '/pty': [],
        '/vcs': {branch: 'main'}, '/permission': [], '/question': [], '/session/status': {}, '/session': [info],
        [`/session/${sid}`]: info, [`/session/${sid}/message`]: messages, [`/session/${sid}/children`]: [], [`/session/${sid}/todo`]: [], [`/session/${sid}/diff`]: diff,
        '/file': [{name: 'hello.ts', path: 'hello.ts', absolute: `${directory}/hello.ts`, type: 'file', ignored: false}],
        '/file/content': {type: 'text', content: diff[0]!.after}, '/file/status': [{path: 'hello.ts', added: 1, removed: 1, status: 'modified'}], '/find/file': ['hello.ts'],
        '/experimental/worktree': [], '/experimental/resource': {}, '/api/reference': {location: {directory, project: {id: 'project_test', directory}}, data: []},
        '/vcs/diff': [{file: 'hello.ts', additions: 1, deletions: 1, status: 'modified', patch: 'diff --git a/hello.ts b/hello.ts\n--- a/hello.ts\n+++ b/hello.ts\n@@ -1 +1 @@\n-export const hello = "before"\n+export const hello = "after"\n'}],
      }
      if (!(native in data)) { errors.push(`Unhandled native GET: ${native}`); return route.fulfill({status: 404, json: {message: native}}) }
      return route.fulfill({json: data[native]})
    }
    if (path.endsWith('/workspace')) return route.fulfill({json: {task_id: task.id, task_status: task.status, runtime: {server: `/api/tasks/${task.id}/opencode`, session_id: sid, workspace: directory, connection: 'CONNECTED', error: null, opencode_version: '1.18.31', workspace_ui: '/opencode-workspace/1.18.31/index.html'}, sessions: [{id: sid, workspace: directory, current: true, created_at: task.created_at, status: 'RUNNING', superseded_by: null, finished_at: null, opencode_version: '1.18.31', workspace_ui: '/opencode-workspace/1.18.31/index.html'}], history: []}})
    if (path.endsWith('/repo')) return route.fulfill({json: {name: 'sample', branch: 'main', commit: '0123456789abcdef', dirty: true, changes: 1}})
    if (path === '/api/tasks/T-WORKSPACE') return route.fulfill({json: task})
    if (path === '/api/tasks') return route.fulfill({json: [task]})
    if (path === '/api/employees') return route.fulfill({json: [{id: 'E1', name: 'Engineer'}]})
    if (path.endsWith('/stream')) return route.fulfill({contentType: 'text/event-stream', body: 'event: connected\ndata: {}\n\n'})
    return route.fulfill({json: path === '/api/system/metrics' ? {} : []})
  })
  await page.goto('/tasks/T-WORKSPACE')
  await expect(page.getByTestId('task-workspace')).toBeVisible()
  const frame = page.frameLocator('iframe[title="OpenCode Task Workspace"]')
  await expect(frame.locator('[data-component="prompt-input"]')).toBeVisible({timeout: 20000})
  await expect(frame.getByText('Please update hello.ts', {exact: true})).toBeVisible()
  await expect(frame.getByText('Updated the greeting in hello.ts.', {exact: true})).toBeVisible()
  const countSummary = frame.locator('[data-component="tool-count-summary"]')
  await expect(countSummary).toBeVisible()
  await expect(
    countSummary.locator('[data-slot="tool-count-summary-item"][data-active="true"]'),
  ).toContainText('read')
  await frame.getByRole('button', {name: 'Toggle review', exact: true}).click()
  const review = frame.locator('#review-panel')
  const diffView = review.locator('[data-component="file"][data-mode="diff"]')
  await expect(diffView).toContainText('"before"')
  await expect(diffView).toContainText('"after"')
  await frame.getByRole('button', {name: 'Open file', exact: true}).click()
  await frame.locator('[data-component="file-tree-v2"]').getByText('hello.ts', {exact: true}).click()
  await expect(frame.locator('[data-component="file"][data-mode="text"]')).toContainText('"after"')
  await frame.locator('[data-component="prompt-input"]').fill('Continue in the same session')
  await frame.locator('[data-component="prompt-input"]').press('Enter')
  await expect.poll(() => requests.filter(item => item.path.endsWith('/prompt_async')).length).toBe(1)
  expect(requests.find(item => item.path.endsWith('/prompt_async'))?.path).toBe(`/session/${sid}/prompt_async`)
  expect(requests.some(item => item.path === '/session')).toBeFalsy()
  expect(errors).toEqual([])
  await page.screenshot({path: '../artifacts/session-workspace.png', fullPage: true})
})
