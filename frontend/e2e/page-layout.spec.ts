import { expect, test, type Locator, type Page } from '@playwright/test'

// 管理页统一布局回归：标题区、筛选面板、搜索区位置与「无更多筛选」四条硬约束。
// 全部接口本地 mock，不依赖后端与真实数据。

const NOW = '2026-01-01T00:00:00Z'
const CONTROL_TOKEN = 'e2e-page-layout-token'

const nodeFixture = {
  id: 'node-alpha', name: 'Alpha 节点', pool_id: 'pool-1', base_url: 'https://alpha.example.test',
  auth_type: 'BEARER', auth_header: '', connect_timeout_seconds: 5, request_timeout_seconds: 60,
  health_path: '/health', probe_interval_seconds: 300, models: ['gpt-test'], weight: 100,
  max_concurrency: 8, hourly_token_limit: null, daily_token_limit: null, quota_policy: 'STOP',
  config_state: 'ENABLED', scheduling_state: 'ACTIVE', health_state: 'HEALTHY', success_streak: 3,
  failure_streak: 0, health_detail: {}, has_api_key: true, sort_order: 0, last_checked_at: NOW,
  created_at: NOW, updated_at: NOW,
}
const statsFixture = {
  scope: 'overview', scope_id: null, window: 'hour', window_start: NOW, window_end: NOW,
  requests: 5, success: 5, errors: 0, success_rate: 1, input_tokens: 100, output_tokens: 200,
  total_tokens: 300, unknown_usage_requests: 0, qps: 0.1, active: 0, peak_concurrency: 2,
  connect_ms: { avg: 10, p50: 9, p95: 20 }, ttfb_ms: { avg: 50, p50: 40, p95: 90 },
  ttft_ms: { avg: 80, p50: 70, p95: 120 }, duration_ms: { avg: 900, p50: 800, p95: 1500 },
  output_tps: { avg: 20, p50: 18, p95: 30 }, trend: [],
}

async function mockApi(page: Page) {
  await page.addInitScript((token) => window.sessionStorage.setItem('astra.gateway.control.token', token), CONTROL_TOKEN)
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => {
    const { pathname, searchParams } = new URL(route.request().url())
    const json = (data: unknown) => route.fulfill({ json: data })
    if (pathname === '/api/events/stream') {
      return route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: '' })
    }
    if (pathname === '/api/employees') {
      return json([{ id: 'astra-01', name: '员工-01', role: '质量防线', enabled: true, description: '质量门禁', execution_environment: { model_name: 'gpt-5' }, created_at: NOW, updated_at: NOW }])
    }
    if (pathname === '/api/tasks') {
      return json([
        { id: 'T-20260930-001', title: '复核发布门禁', task_type: 'ISSUE', status: 'RUNNING', priority: 'HIGH', category_id: null, employee_id: 'astra-01', current_progress: '正在复核', runtime_state: { terminal: false }, created_at: NOW, updated_at: NOW },
        { id: 'T-20260930-002', title: '等待人工确认的回调改动', task_type: 'ISSUE', status: 'WAITING', priority: 'HIGH', category_id: null, employee_id: 'astra-01', current_progress: '等待人工确认', runtime_state: { terminal: false }, created_at: NOW, updated_at: NOW },
      ])
    }
    if (pathname === '/api/task-categories') {
      return json([{ id: 'cat-1', name: '质量防线', description: '质量相关', sort_order: 10, enabled: true, task_prompt: 'a', question_prompt: '' }])
    }
    if (pathname === '/api/workspaces') return json([])
    if (pathname.startsWith('/api/assistant')) return json({ items: [] })
    if (pathname === '/api/library/permissions') return json({ user_id: 'e2e', role: 'admin', can_manage: true, can_review: true })
    if (pathname === '/api/library/stats') {
      return json({ knowledge_pages: 2, visible_knowledge_total: 39, knowledge_spaces: 1, weekly_references: 0, published_experiences: 1, candidate_experiences: 4 })
    }
    if (pathname === '/api/library/spaces') {
      return json([{ id: 'space-root', name: '公共知识库', description: '', parent_id: null, sort_order: 0, status: 'active', access_scope: 'public', knowledge_count: 8, subtree_knowledge_count: 12, children: [], created_at: NOW, updated_at: NOW }])
    }
    if (pathname === '/api/library/usage/summary') {
      return json({ days: 7, total_references: 12, used_resources: 5, feedback_count: 2, top_knowledge: [], trend: [] })
    }
    if (pathname === '/api/library/service/status') {
      return json({ enabled: true, healthy: true, message: '', last_synced_at: '2026-09-08T12:00:00Z', pending_count: 0, failed_count: 0 })
    }
    if (pathname === '/api/library/knowledge') {
      return json({ items: [], total: searchParams.get('space_id') ? 3 : 39, page: 1, page_size: 20, pages: 2 })
    }
    if (pathname === '/api/gateway/permissions') return json({ actor: 'e2e-admin', roles: ['system', 'node', 'route', 'key', 'publish'] })
    if (pathname === '/api/gateway/nodes') return json([nodeFixture])
    if (pathname === '/api/gateway/pools') return json([{ id: 'pool-1', name: '默认资源池', description: '', weight: 100, enabled: true, sort_order: 0, created_at: NOW, updated_at: NOW }])
    if (pathname === '/api/gateway/routes') return json([{ id: 'route-1', model: 'gpt-test', pool_id: 'pool-1', description: '', enabled: true, weight: 100, created_at: NOW, updated_at: NOW }])
    if (pathname === '/api/gateway/keys') return json([])
    if (pathname === '/api/gateway/stats') return json(statsFixture)
    if (pathname === '/api/gateway/requests') return json({ items: [], total: 0, page: 1, page_size: 50 })
    if (pathname === '/api/gateway/instances') return json([])
    if (pathname === '/api/gateway/config/draft') return json({ valid: true, errors: [], warnings: [], counts: { nodes: 1, pools: 1, routes: 1, keys: 0 } })
    if (pathname === '/api/gateway/config/versions') return json([])
    return json({})
  })
}

// 有筛选面板的页面。gateway 的子页筛选面板在父级标题区之下的内容区里。
const filterPages = [
  { name: '数字员工', path: '/employees', testid: 'employee-filter' },
  { name: '任务管理', path: '/tasks', testid: 'task-filter' },
  { name: '配置中心', path: '/settings', testid: 'category-filter' },
  { name: '数字图书馆', path: '/library', testid: 'knowledge-filter' },
  { name: 'API 中转 · 下游节点', path: '/gateway/nodes', testid: 'gateway-nodes-filter' },
  { name: 'API 中转 · API Key 管理', path: '/gateway/keys', testid: 'gateway-keys-filter' },
]

// 有统一标题区且右侧带刷新 + 主操作的页面。
const headerPages = [
  { name: '数字员工', path: '/employees', refresh: 'employee-refresh', primary: 'employee-create' },
  { name: '任务管理', path: '/tasks', refresh: 'task-refresh', primary: 'task-create' },
  { name: '数字图书馆', path: '/library', refresh: 'library-refresh', primary: 'library-create' },
  { name: '配置中心', path: '/settings', refresh: 'category-refresh', primary: 'category-create' },
  { name: 'API 中转 · 下游节点', path: '/gateway/nodes', refresh: 'gateway-nodes-refresh', primary: 'gateway-node-create' },
  { name: 'API 中转 · API Key 管理', path: '/gateway/keys', refresh: 'gateway-keys-refresh', primary: 'gateway-keys-create' },
]

async function box(locator: Locator) {
  const value = await locator.boundingBox()
  expect(value, '元素应可见并有布局盒').toBeTruthy()
  return value!
}

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await mockApi(page)
})

test('所有管理页的标题字号一致，标题区只有一个 h2', async ({ page }) => {
  for (const target of [...headerPages, { name: '待处理', path: '/interventions' }]) {
    await page.goto(target.path)
    const header = page.locator('.astra-page-header').first()
    await expect(header, target.name).toBeVisible()
    const title = header.locator('.astra-page-header__title')
    // 统一取 --astra-font-section (18px)，与数字图书馆首行一致。
    await expect(title).toHaveCSS('font-size', '18px')
    await expect(title).toHaveCSS('font-weight', '700')
    await expect(header.locator('.astra-page-header__desc')).toBeVisible()
  }
})

test('刷新与主操作按钮在各页处于同一视觉位置', async ({ page }) => {
  const refreshTops: number[] = []
  const primaryRights: number[] = []
  const controlHeights: number[] = []

  for (const target of headerPages) {
    await page.goto(target.path)
    const refresh = page.getByTestId(target.refresh)
    const primary = page.getByTestId(target.primary)
    await expect(refresh, `${target.name} 刷新`).toBeVisible()
    await expect(primary, `${target.name} 主操作`).toBeVisible()
    refreshTops.push((await box(refresh)).y)
    primaryRights.push((await box(primary)).x + (await box(primary)).width)
    // 标题区按钮与筛选控件同属全局 small 档，高度一致。
    controlHeights.push((await box(refresh)).height, (await box(primary)).height)
  }

  const spread = (values: number[]) => Math.max(...values) - Math.min(...values)
  // 各页标题区上下留白相同，按钮顶端对齐；主操作右缘也应对齐。
  expect(spread(refreshTops), '刷新按钮顶端应一致').toBeLessThanOrEqual(1)
  expect(spread(primaryRights), '主操作按钮右缘应一致').toBeLessThanOrEqual(1)
  expect(new Set(controlHeights).size, '标题区按钮高度应唯一').toBe(1)
})

test('筛选面板统一为浅灰边框白底圆角，且不再零散排在页面背景上', async ({ page }) => {
  for (const target of filterPages) {
    await page.goto(target.path)
    const panel = page.getByTestId(target.testid)
    await expect(panel, `${target.name} 筛选面板`).toBeVisible()
    const style = await panel.evaluate((el) => {
      const css = getComputedStyle(el)
      return { border: css.borderTopWidth, radius: css.borderTopLeftRadius, background: css.backgroundColor, padding: css.paddingTop }
    })
    expect(style.border, `${target.name} 边框宽度`).toBe('1px')
    expect(parseFloat(style.radius), `${target.name} 圆角`).toBeGreaterThan(0)
    // 面板是白底而不是页面底色，说明控件不再直接摆在页面背景上。
    expect(style.background, `${target.name} 面板底色`).toBe('rgb(255, 255, 255)')
    expect(parseFloat(style.padding), `${target.name} 内边距`).toBeGreaterThan(0)
  }
})

test('筛选面板内控件同高，业务筛选在左、关键词搜索整体靠右', async ({ page }) => {
  for (const target of filterPages) {
    await page.goto(target.path)
    const panel = page.getByTestId(target.testid)
    const fields = panel.locator('.astra-filter__fields')
    const searchGroup = panel.locator('.astra-filter__search')
    await expect(fields, `${target.name} 左侧筛选区`).toBeVisible()
    await expect(searchGroup, `${target.name} 右侧搜索区`).toBeVisible()

    // 面板内所有控件共用全局 small 档高度，且垂直居中对齐。
    const controls = panel.locator('.el-input, .el-select, .el-button')
    const heights = await controls.evaluateAll((els) => els.map((el) => Math.round(el.getBoundingClientRect().height)))
    expect(new Set(heights).size, `${target.name} 控件高度应统一，实际 ${heights}`).toBe(1)

    // 右侧搜索区在左侧全部业务筛选之后（margin-left: auto 生效）。
    const selects = fields.locator('.el-select')
    const count = await selects.count()
    let lastSelectRight = 0
    for (let index = 0; index < count; index += 1) {
      lastSelectRight = Math.max(lastSelectRight, (await box(selects.nth(index))).x + (await box(selects.nth(index))).width)
    }
    const searchBox = await box(searchGroup)
    expect(searchBox.x, `${target.name} 搜索区应在左侧筛选之后`).toBeGreaterThanOrEqual(lastSelectRight)
    // 搜索区贴着面板的内容右边缘（面板自身有 1px 边框 + 12px 内边距）。
    const panelBox = await box(panel)
    const gap = panelBox.x + panelBox.width - (searchBox.x + searchBox.width)
    expect(gap, `${target.name} 搜索区右缘`).toBeGreaterThan(0)
    expect(gap, `${target.name} 搜索区右缘`).toBeLessThanOrEqual(14)
  }
})

test('全站不再有「更多筛选」「高级筛选」入口', async ({ page }) => {
  for (const target of [...headerPages, { name: '待处理', path: '/interventions' }]) {
    await page.goto(target.path)
    await expect(page.getByRole('button', { name: /更多筛选|高级筛选/ }), target.name).toHaveCount(0)
  }
})

test('数字图书馆不再单独占一整行展示知识服务状态', async ({ page }) => {
  await page.goto('/library')
  // 旧的一整行服务状态卡已删除。
  await expect(page.locator('.library-service-bar')).toHaveCount(0)
  // 服务状态并入标题信息区，与标题合成一个整体。
  const meta = page.locator('.astra-page-header__meta')
  await expect(meta).toHaveCount(1)
  await expect(meta.getByTestId('library-service-state')).toHaveText('知识服务：正常')
  await expect(meta.getByTestId('library-service-synced')).toContainText('最近同步')
  await expect(meta.getByTestId('library-review-queue')).toContainText('待审核经验')
  // 待同步 / 同步失败为 0 时不展示，不占标题信息区的位置。
  await expect(meta.getByTestId('library-service-queue')).toHaveCount(0)
})

test('数据总数只在分页左侧出现一次', async ({ page }) => {
  await page.goto('/employees')
  const list = page.getByTestId('employee-list-page')
  await expect(list.getByTestId('employee-total')).toHaveText('共 1 条')
  await expect(list.locator('.astra-page-header').getByText('共')).toHaveCount(0)
  await expect(list.locator('.astra-filter').getByText('共')).toHaveCount(0)
})

test('API 中转左侧竖向子菜单保持正常并高亮当前分区', async ({ page }) => {
  await page.goto('/gateway/nodes')
  const menu = page.getByTestId('gateway-page').getByRole('complementary')
  await expect(menu).toBeVisible()
  for (const id of ['overview', 'nodes', 'routes', 'keys', 'logs', 'versions', 'self']) {
    await expect(page.getByTestId(`gateway-menu-${id}`)).toBeVisible()
  }
  await expect(page.getByTestId('gateway-menu-nodes')).toHaveClass(/is-active/)
  await page.getByTestId('gateway-menu-keys').click()
  await expect(page.getByTestId('gateway-menu-keys')).toHaveClass(/is-active/)
  await expect(page.getByTestId('gateway-menu-nodes')).not.toHaveClass(/is-active/)
})

test('待处理页同样走统一标题区与筛选面板，队列只提供进入任务的入口', async ({ page }) => {
  await page.goto('/interventions')
  const page_ = page.getByTestId('intervention-page')
  await expect(page_.locator('.astra-page-header')).toHaveCount(1)
  await expect(page_.getByTestId('intervention-filter')).toBeVisible()
  await expect(page_.getByRole('button', { name: /等待人工或外部条件 · 1/ })).toBeVisible()
  await expect(page_.getByRole('button', { name: /执行失败 · 0/ })).toBeVisible()

  // 人工介入已收敛进任务 Workspace：队列行只提供进入该任务的入口。
  const row = page_.getByRole('row').filter({ hasText: '等待人工确认的回调改动' })
  await expect(row).toBeVisible()
  await expect(row.getByRole('button', { name: '进入 T-20260930-002 任务详情' })).toBeVisible()
  await row.getByRole('button', { name: '进入 T-20260930-002 任务详情' }).click()
  await expect(page).toHaveURL(/\/tasks\/T-20260930-002$/)
})

test('数字助手入口收在顶部栏，不遮挡表格操作与分页', async ({ page }) => {
  await page.goto('/employees')
  const launcher = page.getByTestId('assistant-launcher')
  await expect(launcher).toBeVisible()
  // 不再是 fixed 悬浮球：位置由顶栏决定，不会压住内容。
  await expect(launcher).not.toHaveCSS('position', 'fixed')

  const panel = page.locator('.astra-table-panel')
  const panelBox = await box(panel)
  const launcherBox = await box(launcher)
  const overlapsTable = launcherBox.x < panelBox.x + panelBox.width
    && launcherBox.x + launcherBox.width > panelBox.x
    && launcherBox.y < panelBox.y + panelBox.height
    && launcherBox.y + launcherBox.height > panelBox.y
  expect(overlapsTable, '助手入口不应与表格面板重叠').toBeFalsy()

  const pagination = page.getByTestId('employee-pagination')
  const paginationBox = await box(pagination)
  const overlapsPagination = launcherBox.x < paginationBox.x + paginationBox.width
    && launcherBox.x + launcherBox.width > paginationBox.x
    && launcherBox.y < paginationBox.y + paginationBox.height
    && launcherBox.y + launcherBox.height > paginationBox.y
  expect(overlapsPagination, '助手入口不应与分页重叠').toBeFalsy()
})
