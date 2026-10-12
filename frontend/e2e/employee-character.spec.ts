import { expect, test, type Page } from '@playwright/test'

async function characterFixture(page: Page) {
  const employee = {
    id: 'character-test', name: '形象测试员工', role: '开发', description: '', character_id: 2,
    default_work_area: 'development', status: 'IDLE', enabled: true, auto_claim: false, auto_execute: false,
    task_types: ['ISSUE'], category_ids: ['testing-platform'], current_task_count: 0,
    runtime_state: 'IDLE', runtime_status_label: '空闲', runtime_detail: '', failure: null,
    today_usage: {}, today_completed: 0, last_heartbeat: null, online_since: null,
    created_at: '2026-10-10T00:00:00Z', updated_at: '2026-10-10T00:00:00Z',
    execution_environment: {
      id: 1, employee_id: 'character-test', mode: 'LOCAL', name: '本地环境', description: '',
      host: null, port: 22, username: null, has_ssh_password: false, opencode_server_port: 4096,
      opencode_path: 'opencode', model_name: null, workspace_root: '/tmp/character-test', labels: [],
      status: 'AVAILABLE', status_detail: {}, last_checked_at: null,
    },
  }
  const harness = { employee, failSave: false, writes: [] as Record<string, unknown>[], requests: [] as string[] }
  await page.route('**/api/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (!path.startsWith('/api/')) return route.continue()
    harness.requests.push(`${request.method()} ${path}`)
    if (request.method() === 'PATCH' || (path === '/api/employees' && request.method() === 'POST')) {
      harness.writes.push(request.postDataJSON())
      if (harness.failSave) return route.fulfill({ status: 503, json: { detail: '保存暂时失败' } })
      Object.assign(employee, request.postDataJSON())
      return route.fulfill({ json: employee, status: request.method() === 'POST' ? 201 : 200 })
    }
    if (path === '/api/employees') return route.fulfill({ json: [employee] })
    if (path.endsWith('/environment/test')) return route.fulfill({ json: { status: 'AVAILABLE', checks: [] } })
    if (path.endsWith('/usage')) return route.fulfill({ json: { summary: {}, tools: [], trend: [] } })
    if (path === '/api/task-categories') return route.fulfill({ json: [
      { id: 'testing-platform', name: '测试平台', description: '', enabled: true },
    ] })
    if (path === '/api/system/metrics') return route.fulfill({ json: {} })
    if (path === '/api/dashboard/employees') return route.fulfill({ json: { teams: [
      { id: 'development', name: '研发团队', order: 0, employee_count: 1, employees: [
        { ...employee, state: 'idle', state_label: '空闲', current_task: null },
      ] },
    ] } })
    if (path === '/api/dashboard/overview') return route.fulfill({ json: { employee_total: 1, online_employees: 1, completed_today: 0 } })
    if (path.startsWith('/api/dashboard/')) return route.fulfill({ json: { items: [] } })
    return route.fulfill({ json: [] })
  })
  return harness
}

test('九种首页形象可预览，新建保存后列表、详情、首页和编辑一致', async ({ page }) => {
  const harness = await characterFixture(page)
  await page.goto('/employees?create=1')
  const drawer = page.getByTestId('employee-config-modal')
  const picker = page.getByTestId('employee-character-picker')
  await expect(picker.getByRole('radio')).toHaveCount(9)
  await expect(picker.getByRole('radio', { name: '形象 1', exact: true })).toBeChecked()
  await expect.poll(() => picker.locator('img').evaluateAll(images => images.every(image => (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0))).toBe(true)
  await picker.getByText('形象 9', { exact: true }).click()
  await expect(picker.getByRole('radio', { name: '形象 9', exact: true })).toBeChecked()
  await page.screenshot({ path: '../artifacts/employee-character-picker.png', animations: 'disabled' })
  await drawer.getByLabel('员工 ID', { exact: true }).fill('character-test')
  await drawer.getByLabel('员工名称', { exact: true }).fill('形象测试员工')
  await drawer.getByLabel('岗位', { exact: true }).fill('开发')
  await drawer.getByLabel('工作空间', { exact: true }).fill('/tmp/character-test')
  await drawer.getByRole('button', { name: '创建员工', exact: true }).click()
  await expect(drawer).toBeHidden()
  expect(harness.writes[0]?.character_id).toBe(8)
  await expect(page.locator('.employee-avatar-image img')).toHaveAttribute('src', '/assets/office/characters/character-8-front.png')
  await page.reload()
  await expect(page.locator('.employee-avatar-image img')).toHaveAttribute('src', '/assets/office/characters/character-8-front.png')
  await page.goto('/employees/character-test')
  await expect(page.locator('.employee-detail__hero .employee-avatar-image img')).toHaveAttribute('src', '/assets/office/characters/character-8-front.png')
  await page.getByRole('button', { name: '编辑', exact: true }).click()
  await expect(picker.getByRole('radio', { name: '形象 9', exact: true })).toBeChecked()
  await picker.getByText('形象 1', { exact: true }).click()
  await drawer.getByRole('button', { name: '保存', exact: true }).click()
  await expect(drawer).toBeHidden()
  expect(harness.employee.character_id).toBe(0)
  await page.goto('/')
  await expect(page.locator('.office-workstation__character')).toHaveAttribute('src', '/assets/office/characters/character-0-back.png')
})

test('形象选择支持放弃修改和保存失败后重试，单独更换不检测环境', async ({ page }) => {
  const harness = await characterFixture(page)
  await page.goto('/employees?edit=character-test')
  const drawer = page.getByTestId('employee-config-modal')
  const picker = page.getByTestId('employee-character-picker')
  await expect(picker.getByRole('radio', { name: '形象 3', exact: true })).toBeChecked()
  await picker.getByText('形象 4', { exact: true }).click()
  await drawer.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByTestId('astra-confirm-dialog').getByRole('button', { name: '放弃并关闭' }).click()
  await expect(drawer).toBeHidden()
  expect(harness.writes).toHaveLength(0)
  await page.getByRole('button', { name: '编辑 形象测试员工', exact: true }).click()
  await expect(picker.getByRole('radio', { name: '形象 3', exact: true })).toBeChecked()
  await picker.getByText('形象 7', { exact: true }).click()
  harness.failSave = true
  await drawer.getByRole('button', { name: '保存', exact: true }).click()
  await expect(drawer.getByText('保存暂时失败')).toBeVisible()
  await expect(picker.getByRole('radio', { name: '形象 7', exact: true })).toBeChecked()
  expect(harness.employee.character_id).toBe(2)
  harness.failSave = false
  await drawer.getByRole('button', { name: '保存', exact: true }).click()
  await expect(drawer).toBeHidden()
  expect(harness.employee.character_id).toBe(6)
  expect(harness.requests.filter(path => path.includes('/environment'))).toEqual([])
  await page.goto('/employees?edit=character-test')
  await expect(picker.getByRole('radio', { name: '形象 7', exact: true })).toBeChecked()
})

test('窄屏仍可浏览和选择全部九种形象', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await characterFixture(page)
  await page.goto('/employees?edit=character-test')
  const picker = page.getByTestId('employee-character-picker')
  await expect(picker.getByRole('radio')).toHaveCount(9)
  await picker.getByText('形象 9', { exact: true }).click()
  await expect(picker.getByRole('radio', { name: '形象 9', exact: true })).toBeChecked()
  const bounds = await picker.boundingBox()
  expect(bounds!.x).toBeGreaterThanOrEqual(0)
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390)
  await page.screenshot({ path: '../artifacts/employee-character-mobile.png', animations: 'disabled' })
})
