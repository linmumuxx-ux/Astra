import { expect, test, type Locator, type Page } from '@playwright/test'

// 「节点详情」重构回归：/api/gateway/** 全部本地 mock（带内存 store，可被操作改写），
// 覆盖深链刷新、左侧竖向二级导航、关键详情字段、探测 / 启停 / 安全下线 / 恢复调度、
// 编辑抽屉、加载失败重试、只读权限与 401 会话失效。
const CONTROL_TOKEN = 'e2e-gateway-node-detail-token'
const NODE_ID = 'node-alpha'
const NODE_PATH = `/gateway/nodes/${NODE_ID}`
const BETA_ID = 'node-beta'
const BETA_PATH = `/gateway/nodes/${BETA_ID}`

type Json = Record<string, unknown>

interface MockOptions {
  roles?: string[]
  failFirstNode?: boolean
  unauthorized?: boolean
  failLogRefresh?: boolean
  // 按端点只让非整页请求返回 401，验证统计 / 日志 / 节点操作与整页一致地退回接入表单。
  unauthorizedOn?: 'stats' | 'requests' | 'action'
  // 显式延迟，用来控制响应顺序，复现统计窗口与节点切换的竞态。
  statsDelayMs?: Record<string, number>
  nodeDelayMs?: Record<string, number>
  // 这些节点 id 的详情直接 500，用来验证新节点加载失败后不再残留旧节点的可操作内容。
  failingNodeIds?: string[]
}

interface MockState {
  nodes: Json[]
  patched: Json[]
  probes: { id: string; body: Json }[]
  drains: string[]
  activates: string[]
  statsWindows: string[]
  requestPages: string[]
  nodeAttempts: number
  // 日志总数，可被用例改写以验证刷新后总页数变少时回退末页。
  logTotal: number
}

function nodeFixture(): Json {
  return {
    id: NODE_ID,
    name: 'Alpha 节点',
    pool_id: 'pool-1',
    base_url: 'https://alpha.example.test',
    auth_type: 'BEARER',
    auth_header: 'Authorization',
    connect_timeout_seconds: 5,
    request_timeout_seconds: 60,
    health_path: '/health',
    probe_interval_seconds: 300,
    models: ['gpt-test', 'gpt-pro'],
    weight: 100,
    max_concurrency: 8,
    hourly_token_limit: null,
    daily_token_limit: 5000,
    quota_policy: 'STOP',
    config_state: 'ENABLED',
    scheduling_state: 'ACTIVE',
    health_state: 'HEALTHY',
    success_streak: 3,
    failure_streak: 0,
    health_detail: { model_call: 'ok' },
    has_api_key: true,
    sort_order: 0,
    last_checked_at: '2026-01-02T03:04:05Z',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-02T00:00:00Z',
  }
}

function betaFixture(): Json {
  return {
    ...nodeFixture(),
    id: BETA_ID,
    name: 'Beta 节点',
    base_url: 'https://beta.example.test',
    models: ['gpt-beta'],
  }
}

function checkFixture(id: number, probeType: string, extra: Json = {}, nodeId = NODE_ID): Json {
  return {
    id,
    node_id: nodeId,
    probe_type: probeType,
    success: true,
    latency_ms: 10 + id,
    status_code: 200,
    error: null,
    detail: {},
    created_at: '2026-01-02T00:00:00Z',
    ...extra,
  }
}

function healthCheckFixtures(nodeId = NODE_ID): Json[] {
  return [
    checkFixture(1, 'NETWORK', {}, nodeId),
    checkFixture(2, 'SERVICE', {}, nodeId),
    checkFixture(3, 'MODEL', {}, nodeId),
    checkFixture(4, 'STREAM', {}, nodeId),
    checkFixture(5, 'MODEL', { success: false, status_code: 502, error: '上游返回 502' }, nodeId),
  ]
}

const statsWindows: Record<string, number> = { hour: 6, today: 42, '7d': 310, '30d': 2400 }

function statsFixture(window: string, scopeId = NODE_ID): Json {
  return {
    scope: 'node',
    scope_id: scopeId,
    window,
    window_start: '2026-01-02T00:00:00Z',
    window_end: '2026-01-02T23:59:59Z',
    requests: statsWindows[window] ?? 0,
    success: statsWindows[window] ?? 0,
    errors: 0,
    success_rate: 1,
    input_tokens: 1_200,
    output_tokens: 2_400,
    total_tokens: 3_600,
    unknown_usage_requests: 0,
    qps: 0.42,
    active: 1,
    peak_concurrency: 2,
    connect_ms: { avg: 12, p50: 11, p95: 20 },
    ttfb_ms: { avg: 50, p50: 40, p95: 90 },
    ttft_ms: { avg: 80, p50: 70, p95: 120 },
    duration_ms: { avg: 900, p50: 800, p95: 1500 },
    output_tps: { avg: 20, p50: 18, p95: 30 },
    trend: [
      { bucket_start: '2026-01-02T00:00:00Z', requests: 3, success: 3, errors: 0, input_tokens: 30, output_tokens: 60, total_tokens: 90, unknown_usage_requests: 0 },
      { bucket_start: '2026-01-02T01:00:00Z', requests: 5, success: 5, errors: 0, input_tokens: 50, output_tokens: 80, total_tokens: 130, unknown_usage_requests: 0 },
    ],
  }
}

function logFixture(index: number, page: number, nodeId = NODE_ID): Json {
  return {
    id: `req-${nodeId}-${page}-${index}`,
    key_id: 'key-e2e-0001',
    owner_id: 'user-e2e',
    model: page === 1 ? 'gpt-test' : 'gpt-pro',
    pool_id: 'pool-1',
    node_id: nodeId,
    streaming: index % 2 === 0,
    retry_count: index % 3,
    status_code: index === 3 ? 502 : 200,
    error_code: index === 3 ? 'UPSTREAM_ERROR' : null,
    stream_interrupted: false,
    connect_ms: 12,
    ttfb_ms: 50,
    ttft_ms: 80,
    duration_ms: 900,
    input_tokens: 30,
    output_tokens: 60,
    total_tokens: 90,
    output_tps: 20,
    usage_known: true,
    started_at: '2026-01-02T00:00:00Z',
    finished_at: '2026-01-02T00:00:01Z',
  }
}

async function mockGateway(page: Page, options: MockOptions = {}): Promise<MockState> {
  const state: MockState = {
    nodes: [nodeFixture(), betaFixture()],
    patched: [],
    probes: [],
    drains: [],
    activates: [],
    statsWindows: [],
    requestPages: [],
    nodeAttempts: 0,
    logTotal: 120,
  }
  await page.addInitScript((token) => {
    window.sessionStorage.setItem('astra.gateway.control.token', token)
  }, CONTROL_TOKEN)
  await page.route('**/api/gateway/**', async (route) => {
    const request = route.request()
    const method = request.method()
    const url = new URL(request.url())
    const pathname = url.pathname
    const json = (data: unknown, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
    const body = (): Json => (request.postData() ? JSON.parse(request.postData() as string) : {})
    const sleep = (ms: number) => (ms > 0 ? new Promise((resolve) => setTimeout(resolve, ms)) : Promise.resolve())

    if (pathname === '/api/gateway/permissions') {
      return json({ actor: 'e2e-admin', roles: options.roles ?? ['node'] })
    }
    if (pathname === '/api/gateway/pools') {
      return json([
        { id: 'pool-1', name: '默认资源池', description: '', weight: 100, enabled: true, sort_order: 0, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
      ])
    }
    if (pathname === '/api/gateway/nodes') return json(state.nodes)
    if (pathname === '/api/gateway/requests') {
      // 首屏之后的日志请求才模拟凭据失效，验证日志自身的 401 也退回接入表单。
      if (options.unauthorizedOn === 'requests' && state.requestPages.length > 0) {
        return json({ detail: '控制面凭据已失效' }, 401)
      }
      state.requestPages.push(`${url.searchParams.get('node_id')}#${url.searchParams.get('page')}`)
      // 只让首屏之后的日志刷新失败，用来验证「日志失败不牵连其它区块」。
      if (options.failLogRefresh && state.requestPages.length > 1) {
        return json({ detail: '调用日志服务不可用' }, 503)
      }
      const target = Number(url.searchParams.get('page') ?? '1')
      return json({
        items: Array.from({ length: 3 }, (_, index) => logFixture(index + 1, target, url.searchParams.get('node_id') ?? NODE_ID)),
        total: state.logTotal,
        page: target,
        page_size: Number(url.searchParams.get('page_size') ?? '50'),
      })
    }
    if (pathname === '/api/gateway/stats') {
      const window = url.searchParams.get('window') ?? 'today'
      // 整页固定拉取的 hour / today 放行，只有交互切换的窗口才模拟凭据失效。
      if (options.unauthorizedOn === 'stats' && window !== 'hour' && window !== 'today') {
        return json({ detail: '控制面凭据已失效' }, 401)
      }
      state.statsWindows.push(window)
      await sleep(options.statsDelayMs?.[window] ?? 0)
      return json(statsFixture(window, url.searchParams.get('scope_id') ?? NODE_ID))
    }
    if (/^\/api\/gateway\/nodes\/[^/]+\/health-checks$/.test(pathname)) {
      return json(healthCheckFixtures(decodeURIComponent(/^\/api\/gateway\/nodes\/([^/]+)\/health-checks$/.exec(pathname)?.[1] ?? NODE_ID)))
    }
    const action = /^\/api\/gateway\/nodes\/([^/]+)\/(probe|drain|activate)$/.exec(pathname)
    if (action && method === 'POST') {
      if (options.unauthorizedOn === 'action') return json({ detail: '控制面凭据已失效' }, 401)
      const id = decodeURIComponent(action[1])
      const kind = action[2]
      const current = state.nodes.find((item) => item.id === id) ?? (state.nodes[0] as Json)
      if (kind === 'probe') {
        const payload = body()
        state.probes.push({ id, body: payload })
        const types = (payload.probe_types ?? []) as string[]
        return json({
          node: current,
          checks: types.map((type, index) => checkFixture(index + 1, type, { created_at: '2026-01-03T00:00:00Z' }, id)),
        })
      }
      const scheduling = kind === 'drain' ? 'DRAINING' : 'ACTIVE'
      state[kind === 'drain' ? 'drains' : 'activates'].push(id)
      state.nodes = state.nodes.map((item) => (item.id === id ? { ...item, scheduling_state: scheduling } : item))
      return json(state.nodes.find((item) => item.id === id) ?? current)
    }
    const single = /^\/api\/gateway\/nodes\/([^/]+)$/.exec(pathname)
    if (single) {
      if (options.unauthorized) return json({ detail: '控制面凭据已失效' }, 401)
      const id = decodeURIComponent(single[1])
      if (method === 'GET') {
        state.nodeAttempts += 1
        await sleep(options.nodeDelayMs?.[id] ?? 0)
        if (options.failFirstNode && state.nodeAttempts === 1) {
          return json({ detail: '节点详情服务暂不可用' }, 500)
        }
        if (options.failingNodeIds?.includes(id)) {
          return json({ detail: '节点详情服务暂不可用' }, 500)
        }
        return json(state.nodes.find((item) => item.id === id) ?? { ...(state.nodes[0] as Json), id })
      }
      if (method === 'PATCH') {
        const payload = body()
        state.patched.push(payload)
        state.nodes = [{ ...(state.nodes[0] as Json), ...payload }]
        return json(state.nodes[0])
      }
    }
    return json({ detail: `未 mock 的网关请求：${method} ${pathname}` })
  })
  return state
}

function section(page: Page, id: string) {
  return page.getByTestId(`gateway-node-section-${id}`)
}

function content(page: Page) {
  return page.getByTestId('gateway-node-content')
}

function navItem(page: Page, id: string) {
  return page.getByTestId(`gateway-node-nav-${id}`)
}

function metricValue(page: Page, id: string) {
  return page.getByTestId(`gateway-node-metric-${id}`).locator('.el-statistic__content')
}

function descriptions(content: Locator) {
  return content.locator('.el-descriptions__cell')
}

async function openDetail(page: Page) {
  await page.goto(NODE_PATH)
  await expect(page.getByRole('heading', { level: 2, name: 'Alpha 节点' })).toBeVisible()
}

// 同一条路由记录内换节点 id，组件实例被复用，走的正是 watch(nodeId) 而不是整页刷新。
async function switchNodeRoute(page: Page, path: string) {
  await page.evaluate((target) => {
    window.history.pushState({}, '', target)
    window.dispatchEvent(new PopStateEvent('popstate', { state: {} }))
  }, path)
  await expect(page).toHaveURL(new RegExp(`${path}$`))
}

test.describe('API 中转 · 节点详情', () => {
  test('深链直接进入，刷新后仍是同一页', async ({ page }) => {
    await mockGateway(page)
    await page.goto(NODE_PATH)
    await expect(page).toHaveURL(new RegExp(`${NODE_PATH}$`))
    await expect(page.getByTestId('gateway-node-detail')).toBeVisible()
    await expect(page.getByRole('heading', { level: 2, name: 'Alpha 节点' })).toBeVisible()

    // 七个区块一次性渲染，二级导航不依赖 URL 参数。
    for (const id of ['overview', 'tokens', 'performance', 'limits', 'health', 'logs', 'config']) {
      await expect(section(page, id)).toHaveCount(1)
    }

    await page.reload()
    await expect(page).toHaveURL(new RegExp(`${NODE_PATH}$`))
    await expect(page.getByTestId('gateway-node-info')).toContainText('https://alpha.example.test')
    await expect(navItem(page, 'overview')).toHaveClass(/is-active/)
  })

  test('左侧竖向导航点击后滚动到对应区块并同步选中态', async ({ page }) => {
    await mockGateway(page)
    await openDetail(page)

    await expect(navItem(page, 'overview')).toHaveClass(/is-active/)
    await expect(page.getByTestId('gateway-node-nav')).toBeVisible()

    for (const id of ['health', 'logs', 'config', 'tokens']) {
      await navItem(page, id).click()
      await expect(navItem(page, id)).toHaveClass(/is-active/)
      await expect(section(page, id)).toBeInViewport()
      await expect(page).toHaveURL(new RegExp(`${NODE_PATH}$`))
      for (const other of ['overview', 'tokens', 'performance', 'limits', 'health', 'logs', 'config'].filter((item) => item !== id)) {
        await expect(navItem(page, other)).not.toHaveClass(/is-active/)
      }
    }

    // 手动滚到底部：最后一个区块拿不到顶部位置，仍要成为当前区块。
    await content(page).evaluate((element) => element.scrollTo(0, element.scrollHeight))
    await expect(navItem(page, 'config')).toHaveClass(/is-active/)

    // 滚回顶部时选中态回到首个区块。
    await content(page).evaluate((element) => element.scrollTo(0, 0))
    await expect(navItem(page, 'overview')).toHaveClass(/is-active/)
  })

  test('节点基本信息、状态、指标、额度与配置字段完整', async ({ page }) => {
    await mockGateway(page)
    await openDetail(page)

    // 头部：名称、ID、下游地址与三态标签
    await expect(page.getByText(NODE_ID, { exact: true })).toBeVisible()
    const tags = page.locator('[aria-label="节点状态"] .el-tag')
    await expect(tags).toHaveText(['健康', '调度中', '启用', '默认资源池'])

    // 概览指标（今日窗口）
    await expect(metricValue(page, 'requests')).toHaveText('42')
    await expect(metricValue(page, 'success-rate')).toHaveText('100%')
    await expect(metricValue(page, 'active')).toHaveText('1')
    await expect(metricValue(page, 'qps')).toHaveText('0.42')
    await expect(metricValue(page, 'tokens')).toHaveText('3.6K')
    await expect(metricValue(page, 'streak')).toHaveText('3 / 0')

    // 节点信息：凭据只显示配置状态，绝不回显
    const info = page.getByTestId('gateway-node-info')
    await expect(descriptions(info).filter({ hasText: '已配置（不回显）' })).toHaveCount(1)
    await expect(info).toContainText('Bearer Token · Authorization')
    await expect(info).toContainText('gpt-test、gpt-pro')
    await expect(info).toContainText('默认资源池')

    // 认证结论由真实模型调用推断，最近探测表保留类型 / 结果 / 延迟 / 时间
    const probeCard = page.getByTestId('gateway-node-probe-latest')
    await expect(probeCard.locator('.el-card__header .el-tag')).toHaveText('认证 PASS')
    await expect(probeCard.locator('.el-table__row')).toHaveCount(5)

    // 健康区块：状态 + 服务端快照 + 探测历史
    const health = page.getByTestId('gateway-node-health-state')
    await expect(health).toContainText('健康')
    await expect(page.getByTestId('gateway-node-health-detail')).toContainText('model_call')
    const history = page.getByTestId('gateway-node-health-table')
    await expect(history.locator('.el-table__row')).toHaveCount(5)
    await expect(history).toContainText('上游返回 502')
    await expect(history).toContainText('失败')

    // 额度与限制
    const quota = page.getByTestId('gateway-node-quota')
    await expect(quota).toContainText('停止新请求')
    await expect(quota).toContainText('不限')
    await expect(quota).toContainText('3.6K')
    await expect(page.getByTestId('gateway-node-scheduling-limits')).toContainText('8')
    await expect(page.getByTestId('gateway-node-scheduling-limits')).toContainText('100')

    // 配置区块
    const config = page.getByTestId('gateway-node-config')
    await expect(config).toContainText('5000')
    await expect(config).toContainText('300 秒')
    await expect(config).toContainText('5 / 60 秒')
  })

  test('统计窗口切换会重新拉取节点统计并刷新指标', async ({ page }) => {
    const state = await mockGateway(page)
    await openDetail(page)
    await expect(metricValue(page, 'requests')).toHaveText('42')

    await page.getByTestId('gateway-node-window').getByText('近 7 天', { exact: true }).click()
    await expect(metricValue(page, 'requests')).toHaveText('310')
    await expect(metricValue(page, 'success-rate')).toHaveText('100%')
    expect(state.statsWindows).toEqual(expect.arrayContaining(['hour', 'today', '7d']))
  })

  test('调用日志展示字段并支持服务端分页', async ({ page }) => {
    const state = await mockGateway(page)
    await openDetail(page)

    const logs = page.getByTestId('gateway-node-logs-table')
    await expect(logs.locator('.el-table__row')).toHaveCount(3)
    await expect(logs).toContainText('key-e2e-000')
    await expect(logs).toContainText('gpt-test')
    await expect(logs).toContainText('SSE')
    await expect(logs).toContainText('30 / 60 / 90')
    await expect(logs).toContainText('80 ms')
    await expect(logs).toContainText('UPSTREAM_ERROR')
    await expect(page.getByTestId('gateway-node-logs-total')).toContainText('共 120 条 · 第 1 页')

    await page.getByTestId('gateway-node-logs-pagination').locator('.el-pager li', { hasText: '2' }).click()
    await expect(page.getByTestId('gateway-node-logs-total')).toContainText('第 2 页')
    await expect(logs).toContainText('gpt-pro')
    expect(state.requestPages).toEqual([`${NODE_ID}#1`, `${NODE_ID}#2`])
  })

  test('探测、启停、安全下线与恢复调度', async ({ page }) => {
    const state = await mockGateway(page)
    await openDetail(page)

    await page.getByTestId('gateway-node-probe').click()
    await expect(page.locator('.el-notification').filter({ hasText: '探测完成：4/4 项通过' })).toBeVisible()
    expect(state.probes.at(-1)?.body).toEqual({ probe_types: ['NETWORK', 'SERVICE', 'MODEL', 'STREAM'] })

    await page.getByTestId('gateway-node-toggle').click()
    await expect(page.locator('.el-notification').filter({ hasText: '节点已禁用' })).toBeVisible()
    expect(state.patched.at(-1)).toEqual({ config_state: 'DISABLED' })
    await expect(page.getByTestId('gateway-node-toggle')).toHaveText('启用')
    await page.getByTestId('gateway-node-toggle').click()
    expect(state.patched.at(-1)).toEqual({ config_state: 'ENABLED' })

    await page.getByTestId('gateway-node-drain').click()
    const confirm = page.getByTestId('astra-confirm-dialog')
    await expect(confirm).toContainText('活跃请求会继续完成')
    await confirm.getByRole('button', { name: '安全下线' }).click()
    await expect(page.locator('.el-notification').filter({ hasText: '节点已进入安全下线' })).toBeVisible()
    expect(state.drains).toEqual([NODE_ID])
    await expect(page.getByTestId('gateway-node-drain')).toHaveCount(0)
    await expect(page.getByTestId('gateway-node-restore')).toBeVisible()
    await expect(page.locator('[aria-label="节点状态"] .el-tag').first()).toHaveText('健康')

    await page.getByTestId('gateway-node-restore').click()
    await expect(page.locator('.el-notification').filter({ hasText: '节点已恢复调度' })).toBeVisible()
    expect(state.activates).toEqual([NODE_ID])
    await expect(page.getByTestId('gateway-node-drain')).toBeVisible()
  })

  test('编辑抽屉保存后回填节点配置', async ({ page }) => {
    const state = await mockGateway(page)
    await openDetail(page)

    await page.getByTestId('gateway-node-edit').click()
    const drawer = page.getByTestId('gateway-node-drawer')
    await expect(drawer).toBeVisible()
    await expect(drawer.locator('.el-drawer__title')).toHaveText('编辑节点')
    await expect(drawer.getByTestId('gateway-node-api-key')).toHaveValue('')
    await drawer.getByLabel('节点名称').fill('Alpha 节点 改')
    await drawer.getByTestId('gateway-node-save').click()
    await expect(drawer).toHaveCount(0)
    expect(state.patched.some((payload) => payload.name === 'Alpha 节点 改')).toBe(true)
    await expect(page.getByRole('heading', { level: 2, name: 'Alpha 节点 改' })).toBeVisible()

    // 配置区块的「编辑配置」入口复用同一个抽屉。
    await section(page, 'config').getByTestId('gateway-node-config-edit').click()
    await expect(page.getByTestId('gateway-node-drawer')).toBeVisible()
  })

  test('加载失败展示错误并可重试成功', async ({ page }) => {
    await mockGateway(page, { failFirstNode: true })
    await page.goto(NODE_PATH)

    const alert = page.getByTestId('gateway-node-error')
    await expect(alert).toContainText('节点详情服务暂不可用')
    await expect(alert.getByTestId('gateway-node-retry')).toBeVisible()
    await expect(page.getByTestId('gateway-node-state')).toBeVisible()

    await alert.getByTestId('gateway-node-retry').click()
    await expect(alert).toHaveCount(0)
    await expect(page.getByTestId('gateway-node-info')).toContainText('https://alpha.example.test')
  })

  test('只读权限保留观测与操作入口，隐藏启用与编辑', async ({ page }) => {
    await mockGateway(page, { roles: [] })
    await openDetail(page)

    await expect(page.getByTestId('gateway-node-probe')).toBeVisible()
    await expect(page.getByTestId('gateway-node-drain')).toBeVisible()
    await expect(page.getByTestId('gateway-node-toggle')).toHaveCount(0)
    await expect(page.getByTestId('gateway-node-edit')).toHaveCount(0)
    await expect(page.getByTestId('gateway-node-config-edit')).toHaveCount(0)
    await expect(page.getByTestId('gateway-node-info')).toContainText('gpt-test、gpt-pro')
    await expect(page.getByTestId('gateway-node-config')).toContainText('https://alpha.example.test')
  })

  test('控制面凭据失效（401）退回接入表单', async ({ page }) => {
    await mockGateway(page, { unauthorized: true })
    await page.goto(NODE_PATH)

    await expect(page.getByTestId('gateway-connect')).toBeVisible()
    await expect(page.getByTestId('gateway-node-detail')).toHaveCount(0)
    expect(await page.evaluate(() => window.sessionStorage.getItem('astra.gateway.control.token'))).toBeNull()
  })

  test('日志刷新失败只提示错误，不清空其它区块', async ({ page }) => {
    await mockGateway(page, { failLogRefresh: true })
    await openDetail(page)

    await page.getByTestId('gateway-node-logs-refresh').click()
    await expect(page.locator('.el-notification').filter({ hasText: '调用日志服务不可用' })).toBeVisible()
    await expect(page.getByTestId('gateway-node-error')).toHaveCount(0)
    await expect(page.getByTestId('gateway-node-logs-total')).toContainText('共 120 条 · 第 1 页')
    await expect(page.getByTestId('gateway-node-info')).toContainText('https://alpha.example.test')
  })

  test('统计窗口快速切换只采纳最后一次响应', async ({ page }) => {
    const state = await mockGateway(page, { statsDelayMs: { '7d': 900 } })
    await openDetail(page)
    await expect(metricValue(page, 'requests')).toHaveText('42')

    // 近 7 天故意慢：先切过去再立刻切回今日，慢的旧响应必须被丢弃。
    await page.getByTestId('gateway-node-window').getByText('近 7 天', { exact: true }).click()
    await page.getByTestId('gateway-node-window').getByText('今日', { exact: true }).click()
    await expect.poll(() => state.statsWindows.filter((item) => item === '7d').length).toBeGreaterThan(0)

    await expect(metricValue(page, 'requests')).toHaveText('42')
    await expect(page.getByTestId('gateway-node-window')).toContainText('今日')
    // 旧的近 7 天响应此刻才返回，落地就会把指标改成 310。
    await page.waitForTimeout(1200)
    await expect(metricValue(page, 'requests')).toHaveText('42')
  })

  test('切换节点立即清空旧数据，切换后不残留上一个节点', async ({ page }) => {
    await mockGateway(page, { nodeDelayMs: { [BETA_ID]: 900 } })
    await openDetail(page)
    await expect(page.getByTestId('gateway-node-info')).toContainText('https://alpha.example.test')

    await switchNodeRoute(page, BETA_PATH)

    // Beta 还在加载：Alpha 的名称、探测表和操作按钮都不能留在新路由下。
    await expect(page.getByTestId('gateway-node-state')).toBeVisible()
    await expect(page.getByText('Alpha 节点', { exact: true })).toHaveCount(0)
    await expect(page.getByTestId('gateway-node-probe')).toHaveCount(0)
    await expect(page.getByTestId('gateway-node-probe-table')).toHaveCount(0)
    await expect(page.getByTestId('gateway-node-logs-total')).toHaveCount(0)

    await expect(page.getByRole('heading', { level: 2, name: 'Beta 节点' })).toBeVisible()
    await expect(page.getByTestId('gateway-node-info')).toContainText('https://beta.example.test')
    await expect(page.getByTestId('gateway-node-info')).toContainText('gpt-beta')
  })

  test('切换节点时旧节点的慢响应不覆盖新节点', async ({ page }) => {
    await mockGateway(page, { nodeDelayMs: { [NODE_ID]: 1200 } })
    await page.goto(NODE_PATH)
    // Alpha 尚未返回，趁它在途切到 Beta。
    await expect(page.getByTestId('gateway-node-state')).toBeVisible()
    await switchNodeRoute(page, BETA_PATH)

    await expect(page.getByRole('heading', { level: 2, name: 'Beta 节点' })).toBeVisible()
    await page.waitForTimeout(1500)
    await expect(page.getByRole('heading', { level: 2, name: 'Beta 节点' })).toBeVisible()
    await expect(page.getByTestId('gateway-node-info')).toContainText('https://beta.example.test')
    await expect(page.getByTestId('gateway-node-error')).toHaveCount(0)
  })

  test('切换到加载失败的节点时不残留上一个节点的可操作内容', async ({ page }) => {
    await mockGateway(page, { failingNodeIds: [BETA_ID] })
    await openDetail(page)

    await switchNodeRoute(page, BETA_PATH)

    await expect(page.getByTestId('gateway-node-error')).toContainText('节点详情服务暂不可用')
    await expect(page.getByTestId('gateway-node-probe')).toHaveCount(0)
    await expect(page.getByTestId('gateway-node-drain')).toHaveCount(0)
    await expect(page.getByTestId('gateway-node-edit')).toHaveCount(0)
    await expect(page.getByText('Alpha 节点', { exact: true })).toHaveCount(0)
  })

  test('整页刷新与节点操作保留日志当前页，总量变少时回退末页', async ({ page }) => {
    const state = await mockGateway(page)
    await openDetail(page)

    await page.getByTestId('gateway-node-logs-pagination').locator('.el-pager li', { hasText: '2' }).click()
    await expect(page.getByTestId('gateway-node-logs-total')).toContainText('第 2 页')

    await page.getByTestId('gateway-node-refresh').click()
    await expect(page.getByTestId('gateway-node-logs-total')).toContainText('共 120 条 · 第 2 页')
    expect(state.requestPages.at(-1)).toBe(`${NODE_ID}#2`)

    // 探测等节点操作会整页重载，日志页码同样保留。
    await page.getByTestId('gateway-node-probe').click()
    await expect(page.locator('.el-notification').filter({ hasText: '探测完成：4/4 项通过' })).toBeVisible()
    await expect(page.getByTestId('gateway-node-logs-total')).toContainText('共 120 条 · 第 2 页')
    expect(state.requestPages.at(-1)).toBe(`${NODE_ID}#2`)

    // 总量缩到不足第 2 页时回退到末页，而不是停在空白页。
    state.logTotal = 5
    await page.getByTestId('gateway-node-refresh').click()
    await expect(page.getByTestId('gateway-node-logs-total')).toContainText('共 5 条 · 第 1 页')
    expect(state.requestPages.at(-1)).toBe(`${NODE_ID}#1`)
    await expect(page.getByTestId('gateway-node-logs-table').locator('.el-table__row')).toHaveCount(3)
  })

  for (const part of ['stats', 'requests', 'action'] as const) {
    test(`${part} 端点 401 与整页一致退回接入表单`, async ({ page }) => {
      await mockGateway(page, { unauthorizedOn: part })
      await openDetail(page)

      if (part === 'stats') {
        await page.getByTestId('gateway-node-window').getByText('近 7 天', { exact: true }).click()
      } else if (part === 'requests') {
        await page.getByTestId('gateway-node-logs-refresh').click()
      } else {
        await page.getByTestId('gateway-node-probe').click()
      }

      await expect(page.getByTestId('gateway-connect')).toBeVisible()
      await expect(page.getByTestId('gateway-node-detail')).toHaveCount(0)
      expect(await page.evaluate(() => window.sessionStorage.getItem('astra.gateway.control.token'))).toBeNull()
    })
  }
})

