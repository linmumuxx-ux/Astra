import { expect, test, type Page } from '@playwright/test'

// 「Key 自助用量」重构回归：/api/gateway/** 全部本地 mock，不使用真实密钥。
// 聚焦普通 Gateway Key 的独立自助鉴权边界：Key 存在 sessionStorage，
// 只以 Bearer 头发往 /api/gateway/self/**，不回显到页面、统计或调用记录。
const CONTROL_TOKEN = 'e2e-gateway-self-control-token'
const SELF_KEY = 'agw_e2e_self_usage_key_placeholder'

type Json = Record<string, unknown>

interface MockOptions {
  failFirstStats?: boolean
  unauthorized?: boolean
  empty?: boolean
}

interface MockState {
  selfStatsWindows: string[]
  selfRequests: Record<string, string>[]
  selfAuthorizations: Array<string | undefined>
  statsAttempts: number
}

function statsFixture(window: string): Json {
  const perWindow: Record<string, Json> = {
    hour: { requests: 6, success: 6, errors: 0, success_rate: 1, total_tokens: 640, active: 1, unknown_usage_requests: 0 },
    today: { requests: 42, success: 40, errors: 2, success_rate: 0.952, total_tokens: 5_120, active: 3, unknown_usage_requests: 2 },
    '7d': { requests: 310, success: 305, errors: 5, success_rate: 0.984, total_tokens: 41_000, active: 1, unknown_usage_requests: 6 },
    '30d': { requests: 2_400, success: 2_360, errors: 40, success_rate: 0.983, total_tokens: 310_000, active: 0, unknown_usage_requests: 30 },
  }
  return {
    scope: 'key',
    scope_id: 'key-self',
    window,
    window_start: '2026-01-01T00:00:00Z',
    window_end: '2026-01-02T00:00:00Z',
    input_tokens: 1_520,
    output_tokens: 3_600,
    qps: 0.4,
    peak_concurrency: 4,
    connect_ms: { avg: 10, p50: 9, p95: 20 },
    ttfb_ms: { avg: 50, p50: 40, p95: 90 },
    ttft_ms: { avg: 80, p50: 70, p95: 120 },
    duration_ms: { avg: 900, p50: 800, p95: 1500 },
    output_tps: { avg: 20, p50: 18, p95: 30 },
    trend: [
      { bucket_start: '2026-01-01T00:00:00Z', requests: 3, success: 3, errors: 0, input_tokens: 30, output_tokens: 60, total_tokens: 90, unknown_usage_requests: 0 },
      { bucket_start: '2026-01-01T01:00:00Z', requests: 5, success: 4, errors: 1, input_tokens: 50, output_tokens: 80, total_tokens: 130, unknown_usage_requests: 1 },
      { bucket_start: '2026-01-01T02:00:00Z', requests: 4, success: 4, errors: 0, input_tokens: 40, output_tokens: 70, total_tokens: 110, unknown_usage_requests: 0 },
    ],
    ...(perWindow[window] ?? perWindow.today),
  }
}

function logFixture(id: string, extra: Json = {}): Json {
  return {
    id,
    key_id: 'key-self',
    owner_id: 'user-self',
    model: 'gpt-self',
    pool_id: 'pool-1',
    node_id: 'node-self',
    streaming: true,
    retry_count: 0,
    status_code: 200,
    error_code: null,
    stream_interrupted: false,
    connect_ms: 10,
    ttfb_ms: 50,
    ttft_ms: 80,
    duration_ms: 900,
    input_tokens: 100,
    output_tokens: 200,
    total_tokens: 300,
    output_tps: 21.3,
    usage_known: true,
    started_at: '2026-01-06T08:30:00Z',
    finished_at: '2026-01-06T08:30:01Z',
    ...extra,
  }
}

function buildLogs(): Json[] {
  return [
    logFixture('req-self-202601060800001'),
    logFixture('req-self-202601060915002', {
      model: null,
      node_id: null,
      streaming: false,
      retry_count: 1,
      status_code: 502,
      error_code: 'UPSTREAM_CONNECT_TIMEOUT',
      stream_interrupted: true,
      ttfb_ms: null,
      ttft_ms: null,
      duration_ms: null,
      input_tokens: null,
      output_tokens: null,
      total_tokens: null,
      output_tps: null,
      usage_known: false,
      started_at: '2026-01-06T09:15:00Z',
      finished_at: null,
    }),
  ]
}

async function mockGateway(page: Page, options: MockOptions = {}): Promise<MockState> {
  const state: MockState = { selfStatsWindows: [], selfRequests: [], selfAuthorizations: [], statsAttempts: 0 }
  await page.addInitScript((token) => {
    window.sessionStorage.setItem('astra.gateway.control.token', token)
  }, CONTROL_TOKEN)
  await page.route('**/api/gateway/**', (route) => {
    const url = new URL(route.request().url())
    const pathname = url.pathname
    const json = (data: unknown, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })

    if (pathname === '/api/gateway/permissions') {
      return json({ actor: 'e2e-admin', roles: ['system'] })
    }
    if (pathname === '/api/gateway/self/stats') {
      state.statsAttempts += 1
      state.selfAuthorizations.push(route.request().headers().authorization)
      const window = url.searchParams.get('window') ?? 'today'
      state.selfStatsWindows.push(window)
      if (options.unauthorized) return json({ detail: 'Gateway Key 无效' }, 401)
      if (options.failFirstStats && state.statsAttempts === 1) {
        return json({ detail: '用量服务暂不可用' }, 503)
      }
      return json(statsFixture(window))
    }
    if (pathname === '/api/gateway/self/requests') {
      state.selfAuthorizations.push(route.request().headers().authorization)
      state.selfRequests.push(Object.fromEntries(url.searchParams.entries()))
      if (options.unauthorized) return json({ detail: 'Gateway Key 无效' }, 401)
      const target = Number(url.searchParams.get('page') ?? '1')
      const size = Number(url.searchParams.get('page_size') ?? '50')
      if (options.empty) return json({ items: [], total: 0, page: target, page_size: size })
      return json({ items: buildLogs(), total: 120, page: target, page_size: size })
    }
    return json({ detail: `未 mock 的网关请求：${pathname}` })
  })
  return state
}

function metricValue(page: Page, id: string) {
  return page.getByTestId(`gateway-self-metric-${id}`).locator('.el-statistic__content')
}

function logRows(page: Page) {
  return page.getByTestId('gateway-self-table').locator('.el-table__row')
}

async function selectPageSize(page: Page, label: string) {
  await page.locator('.gateway-self__size .el-select__wrapper').click()
  await page.locator('.el-select-dropdown:visible .el-select-dropdown__item', { hasText: label }).first().click()
}

test.describe('API 中转 · Key 自助用量', () => {
  test('无 Key 时只呈现接入表单，输入后用当前 Key 拉取自身用量', async ({ page }) => {
    const state = await mockGateway(page)
    await page.goto('/gateway/self')

    await expect(page.getByRole('heading', { level: 3, name: 'Key 自助用量' })).toBeVisible()
    await expect(page.getByTestId('gateway-self-connect')).toBeVisible()
    await expect(page.getByTestId('gateway-self-key-input')).toHaveAttribute('type', 'password')
    // 空态不发任何自助请求，也不渲染统计与调用记录。
    await expect(page.getByTestId('gateway-self-table')).toHaveCount(0)
    expect(state.selfStatsWindows).toEqual([])
    expect(state.selfRequests).toEqual([])

    await page.getByTestId('gateway-self-key-input').fill(SELF_KEY)
    await page.getByTestId('gateway-self-submit').click()

    await expect(page.getByTestId('gateway-self-connect')).toHaveCount(0)
    await expect(page.getByTestId('gateway-self-table')).toBeVisible()
    expect(state.selfStatsWindows).toEqual(['today'])
    expect(state.selfRequests[0]).toEqual({ page: '1', page_size: '50' })
    // 自助请求只带 Gateway Key 自身，不带控制面凭据。
    expect(state.selfAuthorizations.every((value) => value === `Bearer ${SELF_KEY}`)).toBe(true)
    await expect(page.getByTestId('gateway-self-key-input')).toHaveCount(0)

    // Key 原文不得回显到页面任何位置：输入框清空、统计与调用记录都不含原文。
    const body = await page.getByTestId('gateway-self').innerText()
    expect(body).not.toContain(SELF_KEY)
    await expect(page.getByTestId('gateway-self-metric-requests')).not.toContainText(SELF_KEY)
  })

  test('指标、趋势与调用记录字段均按后端契约展示', async ({ page }) => {
    await mockGateway(page)
    await page.goto('/gateway/self')
    await page.getByTestId('gateway-self-key-input').fill(SELF_KEY)
    await page.getByTestId('gateway-self-submit').click()

    await expect(metricValue(page, 'requests')).toHaveText('42')
    await expect(metricValue(page, 'success-rate')).toHaveText('95.2%')
    await expect(metricValue(page, 'tokens')).toHaveText('5.1K')
    await expect(metricValue(page, 'unknown')).toHaveText('2')
    await expect(metricValue(page, 'active')).toHaveText('3')
    await expect(metricValue(page, 'window')).toHaveText('今日')

    const trend = page.getByTestId('gateway-self-trend')
    await expect(trend.getByRole('img', { name: 'API 中转 Token 使用趋势图' })).toBeVisible()
    await expect(trend.locator('canvas')).toBeVisible()
    await expect(trend).toContainText('今日')

    const expectedTime = await page.evaluate(() =>
      new Date('2026-01-06T08:30:00Z').toLocaleString('zh-CN', {
        month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
      }))
    const okRow = logRows(page).filter({ hasText: 'gpt-self' })
    await expect(okRow.locator('td').nth(0)).toHaveText(expectedTime)
    await expect(okRow.locator('.el-tag', { hasText: '200' })).toBeVisible()
    await expect(okRow).toContainText('SSE')
    await expect(okRow).toContainText('100 / 200 / 300')
    await expect(okRow).toContainText('80 ms')
    await expect(okRow).toContainText('900 ms')

    // 错误行：error_code 优先、用量未知与空值占位语义保持不变。
    const badRow = logRows(page).filter({ hasText: 'UPSTREAM_CONNECT_TIMEOUT' })
    await expect(badRow.locator('.el-tag', { hasText: 'UPSTREAM_CONNECT_TIMEOUT' })).toBeVisible()
    await expect(badRow).toContainText('普通')
    await expect(badRow).toContainText('unknown')
    await expect(badRow.locator('td').nth(6)).toHaveText('—')
    await expect(badRow.locator('td').nth(7)).toHaveText('—')

    await expect(page.getByTestId('gateway-self-total')).toContainText('共 120 条 · 第 1 页')
  })

  test('时间窗口切换重新请求后端，调用记录翻页保留窗口', async ({ page }) => {
    const state = await mockGateway(page)
    await page.goto('/gateway/self')
    await page.getByTestId('gateway-self-key-input').fill(SELF_KEY)
    await page.getByTestId('gateway-self-submit').click()
    await expect(logRows(page)).toHaveCount(2)

    const switcher = page.getByTestId('gateway-self-window')
    await switcher.locator('label.el-radio-button', { hasText: '本小时' }).click()
    await expect(switcher.getByRole('radio', { name: '本小时' })).toBeChecked()
    await expect(metricValue(page, 'requests')).toHaveText('6')
    await expect(metricValue(page, 'window')).toHaveText('本小时')
    expect(state.selfStatsWindows).toEqual(['today', 'hour'])

    await switcher.locator('label.el-radio-button', { hasText: '近 30 天' }).click()
    await expect(metricValue(page, 'requests')).toHaveText('2,400')
    await expect(metricValue(page, 'tokens')).toHaveText('310.0K')
    expect(state.selfStatsWindows).toEqual(['today', 'hour', '30d'])

    await page.getByTestId('gateway-self-pagination').locator('.btn-next').click()
    await expect(page.getByTestId('gateway-self-total')).toContainText('第 2 页')
    expect(state.selfRequests[state.selfRequests.length - 1]).toEqual({ page: '2', page_size: '50' })

    await selectPageSize(page, '每页 20')
    expect(state.selfRequests[state.selfRequests.length - 1]).toEqual({ page: '1', page_size: '20' })
  })

  test('调用记录为空时展示空态文案', async ({ page }) => {
    await mockGateway(page, { empty: true })
    await page.goto('/gateway/self')
    await page.getByTestId('gateway-self-key-input').fill(SELF_KEY)
    await page.getByTestId('gateway-self-submit').click()

    await expect(page.locator('.el-empty__description')).toHaveText('暂无调用记录。')
    await expect(page.getByTestId('gateway-self-total')).toContainText('共 0 条')
    await expect(metricValue(page, 'requests')).toHaveText('42')
  })

  test('加载失败展示错误并可重试成功', async ({ page }) => {
    await mockGateway(page, { failFirstStats: true })
    await page.goto('/gateway/self')
    await page.getByTestId('gateway-self-key-input').fill(SELF_KEY)
    await page.getByTestId('gateway-self-submit').click()

    const alert = page.getByTestId('gateway-self-error')
    await expect(alert).toBeVisible()
    await expect(alert).toContainText('用量服务暂不可用')
    await expect(logRows(page)).toHaveCount(0)
    await expect(metricValue(page, 'requests')).toHaveText('—')

    await page.getByTestId('gateway-self-retry').click()
    await expect(alert).toHaveCount(0)
    await expect(logRows(page)).toHaveCount(2)
    await expect(metricValue(page, 'requests')).toHaveText('42')
  })

  test('Key 失效（401）清除会话凭据并退回接入表单', async ({ page }) => {
    await mockGateway(page, { unauthorized: true })
    await page.goto('/gateway/self')
    await page.getByTestId('gateway-self-key-input').fill(SELF_KEY)
    await page.getByTestId('gateway-self-submit').click()

    await expect(page.getByTestId('gateway-self-auth-error')).toContainText('Gateway Key 无效或已失效')
    await expect(page.getByTestId('gateway-self-connect')).toBeVisible()
    await expect(page.getByTestId('gateway-self-table')).toHaveCount(0)
    await expect(page.getByTestId('gateway-self-window')).toHaveCount(0)
    // 控制面会话不受自助 Key 失效影响，页面仍留在接入表单而不是被踢回控制面。
    await expect(page.getByTestId('gateway-page')).toBeVisible()
    expect(await page.evaluate(() => window.sessionStorage.getItem('astra.gateway.self.key'))).toBeNull()
  })

  test('退出去用量清除 Key，刷新页面保持同一会话状态', async ({ page }) => {
    await mockGateway(page)
    await page.goto('/gateway/self')
    await page.getByTestId('gateway-self-key-input').fill(SELF_KEY)
    await page.getByTestId('gateway-self-submit').click()
    await expect(logRows(page)).toHaveCount(2)

    // 会话内刷新：用量的 Key 仍在，恢复为已连接视图。
    await page.reload()
    await expect(page.getByTestId('gateway-self-connect')).toHaveCount(0)
    await expect(logRows(page)).toHaveCount(2)
    await expect(metricValue(page, 'requests')).toHaveText('42')

    await page.getByTestId('gateway-self-clear').click()
    await expect(page.getByTestId('gateway-self-connect')).toBeVisible()
    await expect(page.getByTestId('gateway-self-table')).toHaveCount(0)
    expect(await page.evaluate(() => window.sessionStorage.getItem('astra.gateway.self.key'))).toBeNull()

    // 退出去用量后刷新仍是接入表单，不会再发出自助请求。
    await page.reload()
    await expect(page.getByTestId('gateway-self-connect')).toBeVisible()
  })
})
