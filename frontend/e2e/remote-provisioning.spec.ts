import { expect, test, type Page } from '@playwright/test'

async function remoteFixture(page: Page, mode = 'LINUX_REMOTE') {
  const employee = {
    id: 'remote-test', name: '远程测试员工', role: '开发', description: '', default_work_area: 'development',
    status: 'IDLE', task_types: ['ISSUE', 'REQUIREMENT'], category_ids: [], enabled: true,
    auto_claim: false, auto_execute: false, current_task_count: 0, last_heartbeat: null,
    runtime_state: 'IDLE', runtime_status_label: '空闲', runtime_detail: '', failure: null,
    today_usage: {}, today_completed: 0,
    execution_environment: { id: 101, employee_id: 'remote-test', mode, name: '远程环境', description: '',
      host: '192.0.2.1', port: 22, username: 'root', has_ssh_password: true,
      workspace_root: '/opt/project', opencode_path: '/usr/local/bin/opencode', opencode_server_port: 17302,
      model_name: null as string | null, status: 'UNKNOWN', status_detail: {}, labels: [] },
  }
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) return route.continue()
    if (path === '/api/employees') return route.fulfill({ json: [employee] })
    if (path === '/api/system/metrics') return route.fulfill({ json: {} })
    return route.fulfill({ json: [] })
  })
  return employee
}

test('远程部署及重启阶段可见，成功刷新配置，未保存配置禁止维护', async ({ page }) => {
  const employee = await remoteFixture(page)
  const actions: string[] = []
  await page.route('**/api/employees/remote-test/environment/*', route => {
    const action = route.request().url().split('/').pop()!
    actions.push(action)
    employee.execution_environment.model_name = 'astra-gateway/deepseek-flash'
    employee.execution_environment.status = 'AVAILABLE'
    return route.fulfill({ contentType: 'application/x-ndjson', body: [
      { type: 'step', name: '全局 OpenCode 配置', state: 'running' },
      { type: 'step', name: '全局 OpenCode 配置', state: 'passed', passed: true, detail: '已备份合并' },
      { type: 'result', success: true },
    ].map(x => JSON.stringify(x)).join('\n') + '\n' })
  })
  await page.goto('/employees?edit=remote-test')
  const drawer = page.getByTestId('employee-config-modal')
  await expect(drawer).toBeVisible()
  const deploy = page.getByTestId('deploy-environment')
  await deploy.click()
  await expect(drawer.getByText('部署完成，远程员工环境可用。', { exact: true })).toBeVisible()
  await expect(drawer.getByText('已备份合并')).toBeVisible()
  await expect(drawer.locator('input[placeholder="opencode/glm-5.1"]')).toHaveValue('astra-gateway/deepseek-flash')
  await page.getByTestId('restart-environment').click()
  await expect(drawer.getByText('OpenCode Serve 已重启，健康检查通过。')).toBeVisible()
  expect(actions).toEqual(['deploy', 'restart'])
  await drawer.locator('input[placeholder="10.0.0.12"]').fill('192.0.2.2')
  await expect(deploy).toBeDisabled()
  await expect(page.getByTestId('restart-environment')).toBeDisabled()
  await page.screenshot({ path: '../artifacts/remote-provisioning/controls.png', fullPage: true })
})

test('失败阶段保留可重试，本地员工不显示远程部署', async ({ page }) => {
  await remoteFixture(page)
  await page.route('**/api/employees/remote-test/environment/deploy', route => route.fulfill({
    contentType: 'application/x-ndjson', body: JSON.stringify({ type: 'step', name: '系统依赖', state: 'failed', detail: '请管理员安装系统依赖' }) + '\n' + JSON.stringify({ type: 'result', success: false, message: '请管理员安装系统依赖' }) + '\n',
  }))
  await page.goto('/employees?edit=remote-test')
  await page.getByTestId('deploy-environment').click()
  await expect(page.getByText('请管理员安装系统依赖').first()).toBeVisible()
  await expect(page.getByTestId('deploy-environment')).toBeEnabled()
  await remoteFixture(page, 'LOCAL')
  await page.reload()
  await expect(page.getByTestId('employee-config-modal')).toBeVisible()
  await expect(page.getByTestId('deploy-environment')).toHaveCount(0)
})

test('流式维护中锁定表单，取消后恢复操作', async ({ page }) => {
  await remoteFixture(page)
  await page.addInitScript(() => {
    const original = window.fetch
    window.fetch = (input, init) => {
      if (!String(input).endsWith('/environment/deploy')) return original(input, init)
      return Promise.resolve(new Response(new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode(JSON.stringify({ type: 'step', name: 'OpenCode 安装', state: 'running' }) + '\n'))
          init?.signal?.addEventListener('abort', () => controller.error(new DOMException('Aborted', 'AbortError')))
        },
      }), { headers: { 'Content-Type': 'application/x-ndjson' } }))
    }
  })
  await page.goto('/employees?edit=remote-test')
  await page.getByTestId('deploy-environment').click()
  await expect(page.getByTestId('environment-checks')).toContainText('正在执行')
  await expect(page.locator('input[placeholder="10.0.0.12"]')).toBeDisabled()
  await page.getByTestId('cancel-environment-operation').click()
  await expect(page.getByText('操作已取消，请核对远端状态后重试。', { exact: true })).toBeVisible()
  await expect(page.getByTestId('deploy-environment')).toBeEnabled()
  await expect(page.locator('input[placeholder="10.0.0.12"]')).toBeEnabled()
})
