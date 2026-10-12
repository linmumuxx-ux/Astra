import { expect, test, type Locator, type Page } from '@playwright/test'
import type { DashboardActivity, DashboardAttention, DashboardEmployee, DashboardEmployees, DashboardOverview } from '../src/api/types'

type Section = 'overview' | 'employees' | 'attention' | 'activity'
type Snapshot = { overview: DashboardOverview; employees: DashboardEmployees; attention: DashboardAttention; activity: DashboardActivity }
type StreamControl = {
  urls: string[]
  emit: (type: 'connected' | 'update' | 'error', data?: Record<string, unknown>) => void
  setVisible: (visible: boolean) => void
}
type OfficeWindow = Window & { __officeSSE: StreamControl }

function employee(id: string, overrides: Partial<DashboardEmployee> = {}): DashboardEmployee {
  return {
    id, name: `员工${id}`, role: '自动化工程师', character_id: 0, status: 'IDLE', enabled: true,
    state: 'idle', state_label: '空闲', runtime_state: 'IDLE', runtime_status_label: '空闲',
    runtime_detail: '', failure: null, current_task: null, ...overrides,
  }
}

function task(id: string, overrides: Partial<NonNullable<DashboardEmployee['current_task']>> = {}): NonNullable<DashboardEmployee['current_task']> {
  return {
    id, title: `处理任务${id}`, status: 'RUNNING', current_session_id: `session-${id}`,
    session_status: 'RUNNING', runtime_status_label: '执行中', runtime_detail: '',
    human_required_reason: null, runtime_connection: 'CONNECTED', ...overrides,
  }
}

function snapshot(): Snapshot {
  return {
    overview: { employee_total: 6, team_count: 2, working_employees: 1, running_tasks: 2, completed_today: 8, attention_total: 3, waiting_tasks: 1, failed_tasks: 1, online_employees: 6 },
    employees: { teams: [
      { id: 'engineering', name: '研发团队', order: 10, employee_count: 3, employees: [
        employee('working', { name: '小绿', status: 'WORKING', state: 'working', state_label: '执行中', current_task: task('T-WORK', { title: '修复登录回调' }) }),
        employee('attention', { name: '小圆', status: 'WAIT_HUMAN', state: 'waiting', state_label: '等待人工', current_task: task('T-WAIT', { title: '确认发布权限', status: 'WAITING', session_status: 'PAUSED', human_required_reason: '请确认是否允许发布到测试环境' }) }),
        employee('idle', { name: '小蓝', role: '研发文档整理' }),
      ] },
      { id: 'operations', name: '运营团队', order: 20, employee_count: 3, employees: [
        // Task 的业务闭环尚未结束，Session 已结束时工位仍应静止。
        employee('ended', { name: '小松', status: 'WORKING', state_label: '本轮已结束', current_task: task('T-ENDED', { title: '汇总客服反馈', session_status: 'SUCCEEDED', runtime_status_label: '本轮已结束' }) }),
        employee('paused', { name: '小白', status: 'PAUSED', state: 'waiting', state_label: '已暂停', current_task: task('T-PAUSE', { title: '等待外部资料', session_status: 'PAUSED', runtime_status_label: '已暂停' }) }),
        employee('error', { name: '小橙', status: 'ERROR', state: 'error', state_label: '执行异常', current_task: task('T-ERROR', { title: '同步运营报表', status: 'FAILED', session_status: 'FAILED', runtime_status_label: '执行异常' }) }),
      ] },
    ] },
    attention: { items: [
      { task_id: 'T-WAIT', task_title: '确认发布权限', employee_id: 'attention', employee_name: '小圆', status: 'WAITING', status_label: '等待人工', current_session_id: 'session-T-WAIT', session_status: 'PAUSED', runtime_detail: '', human_required_reason: '请确认是否允许发布到测试环境', runtime_connection: 'CONNECTED', occurred_at: '2026-10-01T01:00:00Z' },
      { task_id: 'T-ERROR', task_title: '同步运营报表', employee_id: 'error', employee_name: '小橙', status: 'FAILED', status_label: '执行异常', current_session_id: 'session-T-ERROR', session_status: 'FAILED', runtime_detail: '报表来源不可用', human_required_reason: null, runtime_connection: 'CONNECTED', occurred_at: '2026-10-01T00:59:00Z' },
      { task_id: 'T-INACTIVE', task_title: '检查长时间无进展的任务', employee_id: null, employee_name: '数字员工', status: 'RUNNING', status_label: '长时间无进展', current_session_id: 'session-T-INACTIVE', session_status: 'RUNNING', runtime_detail: '长时间无进展，需要检查当前会话', human_required_reason: null, runtime_connection: 'CONNECTED', occurred_at: '2026-10-01T00:58:00Z' },
    ] },
    activity: { items: [
      { id: 10, employee_id: 'working', employee_name: '小绿', kind: 'task_started', description: '开始处理「修复登录回调」', created_at: '2026-10-01T00:55:00Z', target_type: 'task', target_id: 'T-WORK' },
      { id: 9, employee_id: 'ended', employee_name: '小松', kind: 'task_completed', description: '完成「上一项运营任务」', created_at: '2026-10-01T00:50:00Z', target_type: 'task', target_id: 'T-PREVIOUS' },
    ] },
  }
}

async function installStream(page: Page) {
  // 用例控制连接与业务事件；生产代码不含假状态或测试专用分支。
  await page.addInitScript(() => {
    const sources: FakeEventSource[] = []
    let hidden = false
    class FakeEventSource extends EventTarget {
      static CONNECTING = 0
      static OPEN = 1
      static CLOSED = 2
      readonly url: string
      readonly withCredentials = false
      readyState = 0
      onerror: ((event: Event) => void) | null = null
      constructor(url: string | URL) { super(); this.url = String(url); sources.push(this) }
      close() { this.readyState = 2 }
    }
    Object.defineProperty(window, 'EventSource', { value: FakeEventSource, configurable: true })
    Object.defineProperty(document, 'hidden', { get: () => hidden, configurable: true })
    ;(window as unknown as OfficeWindow).__officeSSE = {
      get urls() { return sources.map(source => source.url) },
      emit(type, data = {}) {
        for (const source of sources.filter(source => source.readyState !== 2)) {
          if (type === 'error') { source.readyState = 0; source.onerror?.(new Event('error')) }
          else {
            if (type === 'connected') source.readyState = 1
            source.dispatchEvent(new MessageEvent(type, { data: JSON.stringify(data) }))
          }
        }
      },
      setVisible(visible) { hidden = !visible; document.dispatchEvent(new Event('visibilitychange')) },
    }
  })
}

async function emit(page: Page, type: 'connected' | 'update' | 'error', data: Record<string, unknown> = {}) {
  await page.evaluate(({ type, data }) => (window as unknown as OfficeWindow).__officeSSE.emit(type, data), { type, data })
}

async function mockOffice(page: Page, initial = snapshot()) {
  const harness = {
    snapshot: initial,
    failures: new Set<Section>(),
    requests: [] as string[],
    calls: { overview: 0, employees: 0, attention: 0, activity: 0 },
    beforeReply: undefined as ((section: Section, call: number) => Promise<void>) | undefined,
  }
  await installStream(page)
  // 包括跳转后的请求也全部隔离，测试不会访问或写入真实业务接口。
  await page.route(/^https?:\/\/[^/]+\/api(?:\/|$)/, async (route) => {
    const path = new URL(route.request().url()).pathname
    harness.requests.push(path)
    const section = path.slice('/api/dashboard/'.length) as Section
    if (path.startsWith('/api/dashboard/') && Object.hasOwn(harness.calls, section)) {
      const call = ++harness.calls[section]
      const payload = structuredClone(harness.snapshot[section])
      const failed = harness.failures.has(section)
      await harness.beforeReply?.(section, call)
      await route.fulfill(failed ? { status: 503, json: { detail: `${section} 暂时不可用` } } : { json: payload })
      return
    }
    await route.fulfill({ status: 404, json: { detail: '未配置的测试接口' } })
  })
  return harness
}

function desk(page: Page, id: string): Locator {
  return page.locator(`[data-testid="office-workstation"][data-employee-id="${id}"]`)
}

async function openOffice(page: Page, count = 6) {
  const initialResponses = ['overview', 'employees', 'attention', 'activity'].map(section =>
    page.waitForResponse(response => new URL(response.url()).pathname === `/api/dashboard/${section}`),
  )
  await page.goto('/')
  await Promise.all(initialResponses)
  await expect(page.getByTestId('digital-office-scene')).toBeVisible()
  await expect(page.getByTestId('office-workstation')).toHaveCount(count)
  await expect(page.getByText('自动刷新已关闭', { exact: true })).toBeVisible()
}

async function keyboardAnimation(workstation: Locator) {
  return workstation.locator('.office-workstation__keyboard').evaluate(element => getComputedStyle(element).animationName)
}

async function officeIds(page: Page) {
  return page.getByTestId('office-workstation').evaluateAll(elements => elements.map(element => element.getAttribute('data-employee-id')))
}

test('工位由当前 Session 事实驱动，已结束与暂停轮次静止', async ({ page }) => {
  const harness = await mockOffice(page)
  await openOffice(page)
  await expect(desk(page, 'working')).toHaveAttribute('data-state', 'working')
  await expect(desk(page, 'working')).not.toHaveClass(/office-workstation--working/)
  expect(await keyboardAnimation(desk(page, 'working'))).toBe('none')
  await expect(desk(page, 'ended')).toHaveAttribute('data-state', 'idle')
  await expect(desk(page, 'ended')).toContainText('本轮已结束')
  await expect(desk(page, 'paused')).toHaveAttribute('data-state', 'waiting')
  await expect(desk(page, 'attention')).toHaveAttribute('data-state', 'attention')
  await expect(desk(page, 'error')).toHaveAttribute('data-state', 'error')
  for (const id of ['ended', 'paused', 'attention', 'error', 'idle']) expect(await keyboardAnimation(desk(page, id))).toBe('none')
  // 历史完成事件不被当作当前刚完成的动画。
  await expect(page.locator('.office-workstation__completed')).toHaveCount(0)
  expect(await page.evaluate(() => (window as unknown as OfficeWindow).__officeSSE.urls)).toEqual([])
  expect(harness.requests).not.toContain('/api/tasks')
  expect(harness.requests).not.toContain('/api/dashboard/tasks')
  expect(harness.requests).not.toContain('/api/dashboard/knowledge')
  await expect(page.locator('.office-summary')).toContainText('今日完成8')
  await expect(page.locator('.office-summary')).toContainText('在线员工6/6')
})

test('人工等待、失败与无进展事项明确呈现并直达现有任务', async ({ page }) => {
  await mockOffice(page)
  await openOffice(page)
  await expect(desk(page, 'attention')).toContainText('等待你的确认')
  const waiting = page.locator('.attention-item[data-status="WAITING"]')
  await expect(waiting).toContainText('请确认是否允许发布到测试环境')
  await expect(waiting).toHaveAttribute('href', '/tasks/T-WAIT')
  await expect(page.locator('.attention-item[data-status="FAILED"]')).toContainText('执行异常')
  await expect(page.locator('.attention-item[data-status="RUNNING"]')).toContainText('长时间无进展')
  await expect(desk(page, 'idle').locator('.office-workstation__main')).toHaveAttribute('href', '/employees/idle')
  await expect(desk(page, 'working').locator('.office-workstation__main')).toHaveAttribute('href', '/tasks/T-WORK')
  await expect(page.getByTestId('office-activity-feed').locator('a').first()).toHaveAttribute('href', '/tasks/T-WORK')
  await waiting.click()
  await expect(page).toHaveURL(/\/tasks\/T-WAIT$/)
  expect(await page.evaluate(() => (window as unknown as OfficeWindow).__officeSSE.urls)).toEqual([])
})

test('首页读取保存的形象，状态、排序和同形象员工不改变人物', async ({ page }) => {
  const harness = await mockOffice(page)
  const first = harness.snapshot.employees.teams[0]!.employees[0]!
  const other = harness.snapshot.employees.teams[0]!.employees[2]!
  first.character_id = 8
  other.character_id = 8
  await openOffice(page)
  await expect(desk(page, first.id).locator('.office-workstation__character')).toHaveAttribute('src', '/assets/office/characters/character-8-back.png')
  await expect(desk(page, other.id).locator('.office-workstation__character')).toHaveAttribute('src', '/assets/office/characters/character-8-back.png')
  first.state = 'error'
  harness.snapshot.employees.teams[0]!.employees.reverse()
  await page.getByRole('button', { name: '刷新首页数据' }).click()
  await expect(desk(page, first.id).locator('.office-workstation__character')).toHaveAttribute('src', '/assets/office/characters/character-8-front.png')
  await expect(desk(page, other.id).locator('.office-workstation__character')).toHaveAttribute('src', '/assets/office/characters/character-8-back.png')
})

test('无员工、无任务和无事件时提供正常空态与原创建入口', async ({ page }) => {
  const empty = snapshot()
  empty.employees.teams = []
  empty.attention.items = []
  empty.activity.items = []
  empty.overview = { employee_total: 0, team_count: 0, working_employees: 0, running_tasks: 0, completed_today: 0, attention_total: 0, waiting_tasks: 0, failed_tasks: 0, online_employees: 0 }
  await mockOffice(page, empty)
  await openOffice(page, 0)
  await expect(page.getByRole('heading', { name: '办公室还没有数字员工' })).toBeVisible()
  await expect(page.getByRole('link', { name: '创建数字员工' })).toHaveAttribute('href', '/employees?create=1')
  await expect(page.getByText('当前无需处理')).toBeVisible()
  await expect(page.getByText('暂无最近动态')).toBeVisible()
  await expect(page.locator('.office-summary')).toContainText('在线员工0/0')
})

test('首次接口失败不伪报空闲或零事项，重试后恢复真实快照', async ({ page }) => {
  const harness = await mockOffice(page)
  for (const section of ['overview', 'employees', 'attention', 'activity'] as Section[]) harness.failures.add(section)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '数字员工暂时无法获取' })).toBeVisible()
  await expect(page.getByText('运行概况暂时无法获取')).toBeVisible()
  await expect(page.getByText('待处理事项暂时无法更新')).toBeVisible()
  await expect(page.getByText('最近动态暂时无法更新')).toBeVisible()
  await expect(page.getByText('当前无需处理')).toHaveCount(0)
  await expect(page.getByText('暂无最近动态')).toHaveCount(0)
  await expect(page.getByTestId('office-workstation')).toHaveCount(0)
  await expect(page.locator('.office-summary')).toContainText('在线员工—')
  harness.failures.clear()
  await page.getByRole('button', { name: '刷新首页数据' }).click()
  await expect(page.getByTestId('office-workstation')).toHaveCount(6)
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(desk(page, 'working')).not.toHaveClass(/office-workstation--working/)
  await expect(page.locator('.office-summary')).toContainText('在线员工6/6')
})

test('手动刷新期间合并重复点击，业务事件与连接恢复不追加刷新', async ({ page }) => {
  await page.clock.install()
  const harness = await mockOffice(page)
  await openOffice(page)
  const ids = await officeIds(page)
  const baseline = harness.calls.employees
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  harness.beforeReply = async (section, call) => { if (section === 'employees' && call === baseline + 1) await gate }
  const refresh = page.getByRole('button', { name: '刷新首页数据' })
  await refresh.click()
  await expect.poll(() => harness.calls.employees).toBe(baseline + 1)
  // 原生 DOM 点击也不能绕过刷新中的防重入。
  await refresh.evaluate(button => { button.click(); button.click() })
  await emit(page, 'connected')
  await emit(page, 'update', { id: 21, type: 'task.waiting_human', task_id: 'T-WORK' })
  release()
  await expect(refresh).toBeEnabled()
  await page.clock.runFor(1000)
  expect(harness.calls.employees).toBe(baseline + 1)
  expect(await officeIds(page)).toEqual(ids)
  expect(await page.evaluate(() => (window as unknown as OfficeWindow).__officeSSE.urls)).toEqual([])
  expect(harness.requests).not.toContain('/api/tasks')
})

test('手动刷新部分失败时保留快照和提示，重试后恢复', async ({ page }) => {
  const harness = await mockOffice(page)
  await openOffice(page)
  const refresh = page.getByRole('button', { name: '刷新首页数据' })
  harness.failures.add('attention')
  await refresh.click()
  await expect(page.getByText('待处理事项暂时无法更新')).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('上次快照')
  await expect(page.locator('.attention-item[href="/tasks/T-WAIT"]')).toContainText('请确认是否允许发布到测试环境')
  await expect(page.getByText('当前无需处理')).toHaveCount(0)
  await expect(desk(page, 'working')).not.toHaveClass(/office-workstation--working/)
  harness.failures.clear()
  await refresh.click()
  await expect(page.getByText('待处理事项暂时无法更新')).toHaveCount(0)
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByText('自动刷新已关闭')).toBeVisible()
  expect(harness.requests).not.toContain('/api/tasks')
})

test('顶栏通知徽标与首页待处理数量共用 overview 快照', async ({ page }) => {
  const harness = await mockOffice(page)
  await openOffice(page)
  const badge = page.getByRole('link', { name: '消息通知' }).locator('.el-badge__content')
  const attentionCount = page.locator('#attention-title > span')
  await expect(badge).toHaveText('3')
  await expect(attentionCount).toHaveText('3')
  await expect(desk(page, 'working')).not.toHaveClass(/office-workstation--working/)
  harness.snapshot.overview.attention_total = 7
  await page.getByRole('button', { name: '刷新首页数据' }).click()
  await expect(badge).toHaveText('7')
  await expect(attentionCount).toHaveText('7')
  // 列表可以只提供最近事项，徽标不能由列表长度或另一次全量查询推导。
  await expect(page.locator('.attention-item')).toHaveCount(3)
  harness.failures.add('overview')
  await page.getByRole('button', { name: '刷新首页数据' }).click()
  await expect(page.getByRole('alert')).toContainText('上次快照')
  await expect(badge).toHaveText('7')
  await expect(attentionCount).toHaveText('7')
  expect(harness.requests).not.toContain('/api/tasks')
})

test('手动刷新完成前保留旧工位且不播放工作动画', async ({ page }) => {
  const harness = await mockOffice(page)
  await openOffice(page)
  const baseline = harness.calls.employees
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  harness.beforeReply = async (section, call) => { if (section === 'employees' && call === baseline + 1) await gate }
  const current = harness.snapshot.employees.teams[0]!.employees[0]!
  current.state = 'idle'; current.state_label = '本轮已结束'; current.current_task!.session_status = 'SUCCEEDED'
  await page.getByRole('button', { name: '刷新首页数据' }).click()
  await expect.poll(() => harness.calls.employees).toBe(baseline + 1)
  await expect(desk(page, 'working')).toHaveAttribute('data-state', 'working')
  expect(await keyboardAnimation(desk(page, 'working'))).toBe('none')
  release()
  await expect(desk(page, 'working')).toHaveAttribute('data-state', 'idle')
  await expect(desk(page, 'working')).toContainText('本轮已结束')
  expect(await keyboardAnimation(desk(page, 'working'))).toBe('none')
})

test('初始动态为空后第一次真实完成事件仍显示短暂完成反馈', async ({ page }) => {
  const initial = snapshot()
  initial.activity.items = []
  const harness = await mockOffice(page, initial)
  await openOffice(page)
  await expect(desk(page, 'working')).not.toHaveClass(/office-workstation--working/)
  await expect(page.getByText('暂无最近动态')).toBeVisible()
  await expect(page.locator('.office-workstation__completed')).toHaveCount(0)
  harness.snapshot.activity.items = [{ id: 33, employee_id: 'ended', employee_name: '小松', kind: 'task_completed', description: '完成「汇总客服反馈」', created_at: '2026-10-01T01:03:00Z', target_type: 'task', target_id: 'T-ENDED' }]
  await page.getByRole('button', { name: '刷新首页数据' }).click()
  await expect(page.getByTestId('office-activity-feed')).toContainText('完成「汇总客服反馈」')
  await expect(desk(page, 'ended').locator('.office-workstation__completed')).toBeVisible()
  await expect(page.locator('.office-workstation__completed')).toHaveCount(1)
  expect(await keyboardAnimation(desk(page, 'ended'))).toBe('none')
  await expect(desk(page, 'ended').locator('.office-workstation__completed')).toHaveCount(0, { timeout: 5000 })
})

test('完成动态先于工位快照返回，员工变为空闲后仍显示完成反馈', async ({ page }) => {
  const harness = await mockOffice(page)
  await openOffice(page)
  await expect(page.getByRole('button', { name: '刷新首页数据' })).toBeEnabled()
  const baseline = harness.calls.employees
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  harness.beforeReply = async (section, call) => { if (section === 'employees' && call === baseline + 1) await gate }
  const current = harness.snapshot.employees.teams[0]!.employees[0]!
  current.state = 'idle'; current.state_label = '本轮已结束'; current.current_task!.session_status = 'SUCCEEDED'
  harness.snapshot.activity.items.unshift({ id: 34, employee_id: 'working', employee_name: '小绿', kind: 'task_completed', description: '完成「修复登录回调」', created_at: '2026-10-01T01:04:00Z', target_type: 'task', target_id: 'T-WORK' })
  await page.getByRole('button', { name: '刷新首页数据' }).click()
  await expect(page.getByTestId('office-activity-feed')).toContainText('完成「修复登录回调」')
  await expect(desk(page, 'working')).toHaveAttribute('data-state', 'working')
  await expect(desk(page, 'working').locator('.office-workstation__completed')).toHaveCount(0)
  release()
  await expect(desk(page, 'working')).toHaveAttribute('data-state', 'idle')
  await expect(desk(page, 'working').locator('.office-workstation__completed')).toBeVisible()
  await expect(desk(page, 'working').locator('.office-workstation__completed')).toHaveCount(0, { timeout: 5000 })
})

test('闲置一分钟与业务事件不自动更新，手动刷新后呈现 Session 结束', async ({ page }) => {
  await page.clock.install()
  const harness = await mockOffice(page)
  await openOffice(page)
  const baseline = { ...harness.calls }
  const current = harness.snapshot.employees.teams[0]!.employees[0]!
  current.state = 'idle'; current.state_label = '本轮已结束'; current.current_task!.session_status = 'SUCCEEDED'
  harness.snapshot.overview.working_employees = 0
  await emit(page, 'update', { id: 40, type: 'task.completed', task_id: 'T-WORK' })
  await emit(page, 'error')
  await emit(page, 'connected')
  await page.clock.runFor(60_000)
  expect(harness.calls).toEqual(baseline)
  await expect(desk(page, 'working')).toHaveAttribute('data-state', 'working')
  await page.getByRole('button', { name: '刷新首页数据' }).click()
  await expect(desk(page, 'working')).toHaveAttribute('data-state', 'idle')
  await expect(desk(page, 'working')).toContainText('本轮已结束')
  expect(harness.calls.employees).toBe(baseline.employees + 1)
})

test('团队与状态筛选、姓名职责任务搜索保留原工位顺序', async ({ page }) => {
  await mockOffice(page)
  await openOffice(page)
  const ids = await officeIds(page)
  await page.getByRole('combobox', { name: '团队筛选' }).press('Enter')
  await page.getByRole('option', { name: '运营团队 · 3' }).click()
  expect(await officeIds(page)).toEqual(['ended', 'paused', 'error'])
  await page.getByRole('radio', { name: /^待处理/ }).press('Space')
  await expect(page.getByRole('radio', { name: /^待处理/ })).toBeChecked()
  expect(await officeIds(page)).toEqual(['error'])
  await page.getByRole('radio', { name: '全部员工', exact: true }).press('Space')
  await expect(page.getByRole('radio', { name: '全部员工', exact: true })).toBeChecked()
  await page.getByRole('combobox', { name: '团队筛选' }).press('Enter')
  await page.getByRole('option', { name: '全部团队', exact: true }).click()
  expect(await officeIds(page)).toEqual(ids)

  const search = page.getByLabel('全局搜索')
  await search.fill('小绿')
  await search.press('Enter')
  await expect(page.getByTestId('office-workstation')).toHaveCount(1)
  expect(await officeIds(page)).toEqual(['working'])
  await search.fill('研发文档')
  await search.press('Enter')
  await expect(page.getByTestId('office-workstation')).toHaveCount(1)
  expect(await officeIds(page)).toEqual(['idle'])
  await search.fill('运营报表')
  await search.press('Enter')
  await expect(page.getByTestId('office-workstation')).toHaveCount(1)
  expect(await officeIds(page)).toEqual(['error'])
  await search.fill('不存在的员工')
  await search.press('Enter')
  await expect(page.getByRole('heading', { name: '没有找到“不存在的员工”' })).toBeVisible()
  await search.fill('')
  await search.press('Enter')
  await expect(page.getByTestId('office-workstation')).toHaveCount(6)
  expect(await officeIds(page)).toEqual(ids)
})

test('60 位员工在桌面均可访问，长文案不引起横向溢出', async ({ page }) => {
  const many = snapshot()
  many.employees.teams = [0, 1, 2].map(teamIndex => ({
    id: `team-${teamIndex}`, name: `团队${teamIndex}`, order: teamIndex, employee_count: 20,
    employees: Array.from({ length: 20 }, (_, index) => employee(`${teamIndex}-${index}`, {
      name: `员工${teamIndex}-${index} 的完整长姓名`, role: '负责非常长的研发与运营自动化任务说明'.repeat(4),
      current_task: index === 0 ? task(`T-${teamIndex}`, { title: '需要保留完整提示的当前任务'.repeat(8), session_status: 'SUCCEEDED' }) : null,
    })),
  }))
  many.overview.employee_total = 60
  many.overview.online_employees = 60
  many.overview.working_employees = 0
  many.overview.team_count = 3
  await mockOffice(page, many)
  await openOffice(page, 60)
  const ids = await officeIds(page)
  for (const width of [1440, 1920]) {
    await page.setViewportSize({ width, height: 1000 })
    await expect(page.getByTestId('office-workstation')).toHaveCount(60)
    expect(await officeIds(page)).toEqual(ids)
    const dimensions = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }))
    expect(dimensions.scroll).toBeLessThanOrEqual(dimensions.client)
    await page.getByTestId('office-workstation').last().scrollIntoViewIfNeeded()
    await expect(page.getByTestId('office-workstation').last()).toBeVisible()
  }
  await expect(page.getByTestId('office-workstation').first().locator('.office-workstation__identity strong')).toHaveText('员工0-0 的完整长姓名')
  await page.getByTestId('office-workstation').first().locator('.office-workstation__identity').hover()
  const tooltip = page.getByRole('tooltip')
  await expect(tooltip).toContainText('需要保留完整提示的当前任务'.repeat(8))
  await expect(tooltip).toContainText('在线 · 空闲')
  const tooltipBounds = await tooltip.boundingBox()
  const viewportBounds = await page.getByTestId('office-room-viewport').boundingBox()
  expect(tooltipBounds!.width).toBeLessThanOrEqual(320)
  expect(tooltipBounds!.y).toBeGreaterThanOrEqual(viewportBounds!.y)
  expect(tooltipBounds!.y + tooltipBounds!.height).toBeLessThanOrEqual(viewportBounds!.y + viewportBounds!.height)
  // 姓名/动作完全滚出可见区域时，桌椅还可见也不能把提示留在筛选栏上。
  await page.getByTestId('office-room-viewport').evaluate(element => { element.scrollTop = 100 })
  await expect(tooltip).not.toBeVisible()
})

test('减少动态效果保留真实工作状态与入口并关闭持续动画', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await mockOffice(page)
  await openOffice(page)
  await expect(desk(page, 'working')).toHaveAttribute('data-state', 'working')
  await expect(desk(page, 'working')).toContainText('修复登录回调')
  const animations = await desk(page, 'working').locator('*').evaluateAll(elements => elements.map(element => getComputedStyle(element).animationName))
  expect(animations.every(name => name === 'none')).toBe(true)
  await expect(desk(page, 'working').locator('.office-workstation__main')).toHaveAttribute('href', '/tasks/T-WORK')
})

test('切回前台仍保留快照，不自动补刷', async ({ page }) => {
  await page.clock.install()
  const harness = await mockOffice(page)
  await openOffice(page)
  const baseline = { ...harness.calls }
  await page.evaluate(() => (window as unknown as OfficeWindow).__officeSSE.setVisible(false))
  await page.clock.runFor(30_000)
  const current = harness.snapshot.employees.teams[0]!.employees[0]!
  current.state = 'idle'; current.state_label = '本轮已结束'; current.current_task!.session_status = 'SUCCEEDED'
  await page.evaluate(() => (window as unknown as OfficeWindow).__officeSSE.setVisible(true))
  await page.clock.runFor(30_000)
  expect(harness.calls).toEqual(baseline)
  await expect(desk(page, 'working')).toHaveAttribute('data-state', 'working')
  expect(await keyboardAnimation(desk(page, 'working'))).toBe('none')
})

test('离线、停用与任务状态独立展示，员工详情和会话入口可直接访问', async ({ page }) => {
  const initial = snapshot()
  initial.employees.teams[0]!.employees.push(
    employee('offline', { name: '离线员工', status: 'OFFLINE', state_label: '离线', current_task: task('T-OFFLINE') }),
    employee('disabled', { name: '停用员工', enabled: false, state_label: '已停用', current_task: task('T-DISABLED') }),
  )
  await mockOffice(page, initial)
  await openOffice(page, 8)
  await expect(desk(page, 'offline')).toHaveAttribute('data-state', 'offline')
  await expect(desk(page, 'disabled')).toHaveAttribute('data-state', 'disabled')
  await expect(desk(page, 'working').locator('.office-workstation__status')).toHaveText('在线执行中')
  await expect(desk(page, 'working').getByRole('link', { name: '查看小绿的员工详情' })).toHaveAttribute('href', '/employees/working')
  await expect(desk(page, 'working').getByRole('link', { name: '进入会话：修复登录回调' })).toHaveAttribute('href', '/tasks/T-WORK')
  await page.getByRole('radio', { name: '离线 / 停用' }).press('Space')
  expect(await officeIds(page)).toEqual(['offline', 'disabled'])
})

test('相邻重复动态合并，执行结果与被其他事件隔开的进展保持独立', async ({ page }) => {
  const initial = snapshot()
  const started = initial.activity.items[0]!
  initial.activity.items = [
    { ...started, id: 20 }, { ...started, id: 19 },
    { ...started, id: 18, kind: 'task_completed', description: '完成「修复登录回调」' },
    { ...started, id: 17 },
  ]
  await mockOffice(page, initial)
  await openOffice(page)
  const feed = page.getByTestId('office-activity-feed')
  await expect(feed.locator('.activity-feed__item')).toHaveCount(3)
  await expect(feed.locator('.activity-feed__item').first()).toContainText('同类事件 2 次')
  await expect(feed.locator('.activity-feed__item').nth(1)).toContainText('完成「修复登录回调」')
  await expect(feed.locator('time').first()).toHaveAttribute('datetime', started.created_at)
  await expect(feed.locator('a').first()).toHaveAttribute('href', '/tasks/T-WORK')
})

test('首页请求超时释放刷新按钮，保留工位快照并可手动恢复', async ({ page }) => {
  await page.clock.install()
  const harness = await mockOffice(page)
  await openOffice(page)
  const baseline = harness.calls.employees
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  harness.beforeReply = async (section, call) => { if (section === 'employees' && call === baseline + 1) await gate }
  const refresh = page.getByRole('button', { name: '刷新首页数据' })
  await refresh.click()
  await expect.poll(() => harness.calls.employees).toBe(baseline + 1)
  await page.clock.runFor(15_100)
  await expect(refresh).toBeEnabled()
  await expect(page.getByRole('alert')).toContainText('上次快照')
  await expect(desk(page, 'working')).toHaveAttribute('data-state', 'working')
  release()
  harness.beforeReply = undefined
  const current = harness.snapshot.employees.teams[0]!.employees[0]!
  current.state = 'idle'; current.state_label = '本轮已结束'; current.current_task!.session_status = 'SUCCEEDED'
  await refresh.click()
  await expect(desk(page, 'working')).toHaveAttribute('data-state', 'idle')
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('首页创建任务一次点击打开现有抽屉', async ({ page }) => {
  await mockOffice(page)
  await openOffice(page)
  await page.getByRole('link', { name: '创建任务', exact: true }).click()
  await expect(page).toHaveURL(/\/tasks\?create=1$/)
  await expect(page.getByTestId('task-create-modal')).toBeVisible()
  await expect(page.getByPlaceholder('例如：修复用户登录接口偶发 500 问题')).toBeVisible()
})

test('桌面首屏集中统计且空待办紧凑，办公区无横向溢出', async ({ page }) => {
  const initial = snapshot()
  initial.attention.items = []
  initial.overview.attention_total = 0
  await mockOffice(page, initial)
  await openOffice(page)
  for (const width of [1280, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(page.locator('.office-summary')).toContainText('正在工作1')
    await expect(page.locator('.office-summary')).toContainText('今日完成8')
    const dimensions = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }))
    expect(dimensions.scroll).toBeLessThanOrEqual(dimensions.client)
    const attentionBounds = await page.locator('.attention-panel').boundingBox()
    expect(attentionBounds!.height).toBeLessThan(100)
    await expect(page.getByRole('link', { name: '创建任务', exact: true })).toBeInViewport()
  }
})
