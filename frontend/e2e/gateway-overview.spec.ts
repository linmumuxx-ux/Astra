import { expect, test, type Page } from '@playwright/test'

// 「运行总览」重构回归：/api/gateway/** 全部本地 mock，指标按窗口返回不同数值，
// 用以证明页面展示直接来自后端观测契约，而不是前端拼装。
const CONTROL_TOKEN = 'e2e-gateway-overview-token'

const nodeFixtures = [
  { id: 'node-healthy-1', name: 'Healthy One', health_state: 'HEALTHY', scheduling_state: 'ACTIVE', models: ['gpt-a'] },
  { id: 'node-healthy-2', name: 'Healthy Two', health_state: 'HEALTHY', scheduling_state: 'ACTIVE', models: ['gpt-a', 'gpt-b'] },
  { id: 'node-degraded', name: 'Degraded', health_state: 'DEGRADED', scheduling_state: 'DRAINING', models: ['gpt-b'] },
  { id: 'node-unhealthy', name: 'Unhealthy', health_state: 'UNHEALTHY', scheduling_state: 'BLOCKED', models: [] },
  { id: 'node-unknown', name: 'Unknown', health_state: 'UNKNOWN', scheduling_state: 'ACTIVE', models: ['gpt-c'] },
].map((node) => ({
  pool_id: 'pool-1',
  base_url: 'https://node.example.test',
  auth_type: 'BEARER',
  auth_header: '',
  connect_timeout_seconds: 5,
  request_timeout_seconds: 60,
  health_path: '/health',
  probe_interval_seconds: 300,
  weight: 100,
  max_concurrency: 8,
  hourly_token_limit: null,
  daily_token_limit: null,
  quota_policy: 'STOP',
  config_state: 'ENABLED',
  success_streak: 1,
  failure_streak: 0,
  health_detail: {},
  has_api_key: true,
  sort_order: 0,
  last_checked_at: '2026-01-01T00:00:00Z',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  ...node,
}))

const windowStats: Record<string, Record<string, unknown>> = {
  today: { requests: 120, errors: 3, success_rate: 0.975, total_tokens: 3_456, qps: 1.5, active: 4, peak_concurrency: 9, unknown_usage_requests: 1 },
  '7d': { requests: 888, errors: 12, success_rate: 0.986, total_tokens: 43_210, qps: 2.34, active: 2, peak_concurrency: 15, unknown_usage_requests: 0 },
  '30d': { requests: 12_345, errors: 90, success_rate: 0.99, total_tokens: 1_234_567, qps: 0.46, active: 1, peak_concurrency: 20, unknown_usage_requests: 5 },
}

function statsFixture(window: string) {
  const overrides = windowStats[window] ?? windowStats.today
  return {
    scope: 'overview',
    scope_id: null,
    window,
    window_start: '2026-01-01T00:00:00Z',
    window_end: '2026-01-02T00:00:00Z',
    success: 0,
    input_tokens: 1,
    output_tokens: 2,
    connect_ms: { avg: 10, p50: 9, p95: 20 },
    ttfb_ms: { avg: 50, p50: 40, p95: 90 },
    ttft_ms: { avg: 80, p50: 70, p95: 120 },
    duration_ms: { avg: 900, p50: 800, p95: 1500 },
    output_tps: { avg: 20, p50: 18, p95: 30 },
    trend: [
      { bucket_start: '2026-01-01T00:00:00Z', requests: 4, success: 4, errors: 0, input_tokens: 40, output_tokens: 60, total_tokens: 100, unknown_usage_requests: 0 },
      { bucket_start: '2026-01-01T00:05:00Z', requests: 6, success: 5, errors: 1, input_tokens: 55, output_tokens: 90, total_tokens: 145, unknown_usage_requests: 1 },
      { bucket_start: '2026-01-01T00:10:00Z', requests: 8, success: 8, errors: 0, input_tokens: 70, output_tokens: 110, total_tokens: 180, unknown_usage_requests: 0 },
    ],
    ...overrides,
  }
}

const instanceFixture = {
  instance_id: 'gw-node-01:4242',
  status: 'ACTIVE',
  app_version: '1.8.2',
  config_version: 7,
  pid: 4242,
  started_at: '2026-01-01T00:00:00Z',
  updated_at: new Date().toISOString(),
  uptime_seconds: 3_661,
  age_seconds: 30,
  requests: 99,
  errors: 2,
  active: 3,
  cpu_percent: 12.5,
  memory_bytes: 300 * 1024 * 1024,
}

async function mockGatewayApi(page: Page, options: { failFirstStats?: boolean } = {}) {
  await page.addInitScript((token) => {
    window.sessionStorage.setItem('astra.gateway.control.token', token)
  }, CONTROL_TOKEN)
  let statsAttempts = 0
  await page.route('**/api/gateway/**', (route) => {
    const url = new URL(route.request().url())
    const pathname = url.pathname
    const json = (data: unknown) =>
      route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) })
    if (pathname === '/api/gateway/permissions') return json({ actor: 'e2e-admin', roles: ['system'] })
    if (pathname === '/api/gateway/stats') {
      statsAttempts += 1
      if (options.failFirstStats && statsAttempts === 1) {
        return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '观测服务暂不可用' }) })
      }
      return json(statsFixture(url.searchParams.get('window') ?? 'today'))
    }
    if (pathname === '/api/gateway/nodes') return json(nodeFixtures)
    if (pathname === '/api/gateway/instances') return json([instanceFixture])
    if (pathname === '/api/gateway/pools') return json([])
    return json({ detail: `未 mock 的网关请求：${pathname}` })
  })
}

function metricValue(page: Page, id: string) {
  return page.getByTestId(`gateway-metric-${id}`).locator('.el-statistic__content')
}

test.describe('API 中转 · 运行总览', () => {
  test('时间窗口切换后关键指标、节点健康与实例状态来自后端契约', async ({ page }) => {
    await mockGatewayApi(page)
    const todayRequest = page.waitForRequest((request) =>
      request.url().includes('/api/gateway/stats') && request.url().includes('window=today'))
    await page.goto('/gateway/overview')

    await expect(page.getByRole('heading', { level: 3, name: 'API 中转总览' })).toBeVisible()
    await todayRequest
    await expect(metricValue(page, 'requests')).toHaveText('120')
    await expect(metricValue(page, 'qps')).toHaveText('1.50')
    await expect(metricValue(page, 'tokens')).toHaveText('3.5K')
    await expect(metricValue(page, 'success-rate')).toHaveText('97.5%')

    // 切换到「近 7 天」：应重新请求后端且数值随之变化。
    const switcher = page.getByTestId('gateway-window-switch')
    await switcher.locator('label.el-radio-button', { hasText: '近 7 天' }).click()
    await expect(switcher.getByRole('radio', { name: '近 7 天' })).toBeChecked()
    await expect(page).toHaveURL(/\/gateway\/overview$/)
    await expect(metricValue(page, 'requests')).toHaveText('888')
    await expect(metricValue(page, 'qps')).toHaveText('2.34')
    await expect(metricValue(page, 'tokens')).toHaveText('43.2K')

    await switcher.locator('label.el-radio-button', { hasText: '近 30 天' }).click()
    await expect(metricValue(page, 'requests')).toHaveText('12,345')
    await expect(metricValue(page, 'tokens')).toHaveText('1.23M')

    // 节点健康分布与调度摘要来自 nodes 接口。
    const health = page.getByTestId('gateway-overview-health')
    await expect(health.getByText('调度中 3 · 安全下线 1 · 已阻止 1')).toBeVisible()
    await expect(health.locator('li').filter({ hasText: '健康' })).toContainText('2')
    await expect(health.locator('li').filter({ hasText: '异常' })).toContainText('1')

    // 实例状态来自 instances 接口。
    const instances = page.getByTestId('gateway-overview-instances')
    await expect(instances.getByText('gw-node-01:4242')).toBeVisible()
    await expect(instances.getByText('在线')).toBeVisible()
    await expect(instances.getByText('1.8.2')).toBeVisible()
    await expect(instances.getByText('99 / 2')).toBeVisible()
  })

  test('加载失败展示错误并可重试成功', async ({ page }) => {
    await mockGatewayApi(page, { failFirstStats: true })
    await page.goto('/gateway/overview')

    const alert = page.getByTestId('gateway-overview-error')
    await expect(alert).toBeVisible()
    await expect(alert).toContainText('观测服务暂不可用')
    await expect(metricValue(page, 'requests')).toHaveText('—')

    await page.getByTestId('gateway-overview-retry').click()
    await expect(alert).toHaveCount(0)
    await expect(metricValue(page, 'requests')).toHaveText('120')
  })

  test('趋势图渲染并可进入节点列表', async ({ page }) => {
    await mockGatewayApi(page)
    await page.goto('/gateway/overview')

    await expect(page.getByTestId('gateway-overview-trend').getByRole('img', { name: 'API 中转 Token 使用趋势图' })).toBeVisible()
    await expect(page.getByTestId('gateway-overview-trend').locator('canvas')).toBeVisible()

    await page.getByTestId('gateway-nodes-entry').click()
    await expect(page).toHaveURL(/\/gateway\/nodes$/)
    await expect(page.getByRole('heading', { level: 3, name: '下游节点' })).toBeVisible()
  })
})
