import { expect, test, type Page } from '@playwright/test'

// 布局回归不依赖真实网关控制面：/api/gateway/** 全部本地 mock，
// 控制面 Bearer 仅写入 sessionStorage，与真实凭据体系保持一致。
const CONTROL_TOKEN = 'e2e-gateway-control-token'

const nodeFixture = {
  id: 'node-alpha',
  name: 'Alpha 节点',
  pool_id: 'pool-1',
  base_url: 'https://alpha.example.test',
  auth_type: 'BEARER',
  auth_header: '',
  connect_timeout_seconds: 5,
  request_timeout_seconds: 60,
  health_path: '/health',
  probe_interval_seconds: 300,
  models: ['gpt-test'],
  weight: 100,
  max_concurrency: 8,
  hourly_token_limit: null,
  daily_token_limit: null,
  quota_policy: 'STOP',
  config_state: 'ENABLED',
  scheduling_state: 'ACTIVE',
  health_state: 'HEALTHY',
  success_streak: 3,
  failure_streak: 0,
  health_detail: {},
  has_api_key: true,
  sort_order: 0,
  last_checked_at: '2026-01-01T00:00:00Z',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const statsFixture = {
  scope: 'overview',
  scope_id: null,
  window: 'hour',
  window_start: '2026-01-01T00:00:00Z',
  window_end: '2026-01-01T01:00:00Z',
  requests: 5,
  success: 5,
  errors: 0,
  success_rate: 1,
  input_tokens: 100,
  output_tokens: 200,
  total_tokens: 300,
  unknown_usage_requests: 0,
  qps: 0.1,
  active: 0,
  peak_concurrency: 2,
  connect_ms: { avg: 10, p50: 9, p95: 20 },
  ttfb_ms: { avg: 50, p50: 40, p95: 90 },
  ttft_ms: { avg: 80, p50: 70, p95: 120 },
  duration_ms: { avg: 900, p50: 800, p95: 1500 },
  output_tps: { avg: 20, p50: 18, p95: 30 },
  trend: [],
}

async function mockGatewayApi(page: Page) {
  await page.addInitScript((token) => {
    window.sessionStorage.setItem('astra.gateway.control.token', token)
  }, CONTROL_TOKEN)
  await page.route('**/api/gateway/**', (route) => {
    const pathname = new URL(route.request().url()).pathname
    const json = (data: unknown) =>
      route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) })
    if (pathname === '/api/gateway/permissions') return json({ actor: 'e2e-admin', roles: ['system'] })
    if (pathname === '/api/gateway/nodes') return json([nodeFixture])
    if (pathname === '/api/gateway/pools') return json([
      { id: 'pool-1', name: '默认资源池', description: '', weight: 100, enabled: true, sort_order: 0, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
    ])
    if (pathname === '/api/gateway/routes') return json([
      { id: 'route-1', model: 'gpt-test', pool_id: 'pool-1', description: '', enabled: true, weight: 100, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
    ])
    if (pathname === '/api/gateway/keys') return json([
      { id: 'key-1', name: '测试 Key', key_prefix: 'agw_e2e', owner_id: null, allowed_models: [], max_concurrency: 4, hourly_token_limit: null, daily_token_limit: null, enabled: true, expires_at: null, last_used_at: null, revoked_at: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
    ])
    if (pathname === '/api/gateway/requests' || pathname.startsWith('/api/gateway/self/requests')) {
      return json({ items: [], total: 0, page: 1, page_size: 50 })
    }
    if (pathname === '/api/gateway/stats' || pathname.startsWith('/api/gateway/self/stats')) {
      return json({ ...statsFixture, scope: 'overview' })
    }
    if (pathname === '/api/gateway/instances') return json([])
    if (pathname === '/api/gateway/audits') return json([])
    if (pathname === '/api/gateway/config/draft') {
      return json({ valid: true, errors: [], warnings: [], counts: { nodes: 1, pools: 1, routes: 1, keys: 1 } })
    }
    if (pathname === '/api/gateway/config/versions') {
      return json([
        { id: 1, version: 1, status: 'CURRENT', source_version: null, note: '初始发布', published_by: 'e2e-admin', published_at: '2026-01-01T00:00:00Z', created_at: '2026-01-01T00:00:00Z' },
      ])
    }
    if (/^\/api\/gateway\/nodes\/[^/]+\/health-checks$/.test(pathname)) return json([])
    const match = /^\/api\/gateway\/nodes\/([^/]+)$/.exec(pathname)
    if (match) return json({ ...nodeFixture, id: decodeURIComponent(match[1]) })
    return json({ detail: `未 mock 的网关请求：${pathname}` })
  })
}

const sections = [
  { id: 'overview', label: '运行总览', path: '/gateway/overview', heading: 'API 中转总览' },
  { id: 'nodes', label: '下游节点', path: '/gateway/nodes', heading: '节点' },
  { id: 'routes', label: '资源池与路由', path: '/gateway/routes', heading: '资源池与模型路由' },
  { id: 'keys', label: 'API Key 管理', path: '/gateway/keys', heading: 'Gateway Key' },
  { id: 'logs', label: '调用日志', path: '/gateway/logs', heading: '调用日志' },
  { id: 'versions', label: '配置版本', path: '/gateway/versions', heading: '配置草稿与版本' },
  { id: 'self', label: '自助用量', path: '/gateway/self', heading: 'Key 自助用量' },
]

test.describe('API 中转布局与路由', () => {
  test.beforeEach(async ({ page }) => {
    await mockGatewayApi(page)
  })

  test('七个菜单可切换且状态同步', async ({ page }) => {
    await page.goto('/gateway')
    await expect(page).toHaveURL(/\/gateway\/overview$/)
    await expect(page.getByTestId('gateway-page')).toBeVisible()
    await expect(page.getByTestId('gateway-menu-overview')).toHaveClass(/is-active/)

    for (const section of sections) {
      await page.getByTestId(`gateway-menu-${section.id}`).click()
      await expect(page).toHaveURL(new RegExp(`${section.path}$`))
      await expect(page.getByTestId(`gateway-menu-${section.id}`)).toHaveClass(/is-active/)
      await expect(page.getByRole('heading', { level: 3, name: section.heading })).toBeVisible()
      for (const other of sections.filter((item) => item.id !== section.id)) {
        await expect(page.getByTestId(`gateway-menu-${other.id}`)).not.toHaveClass(/is-active/)
      }
    }

    // 顶层 Astra 导航仍然保留并高亮「API 中转」。
    await expect(page.getByRole('menuitem', { name: 'API 中转' })).toHaveClass(/is-active/)
  })

  test('直接访问与刷新保持对应页面', async ({ page }) => {
    await page.goto('/gateway/versions')
    await expect(page.getByRole('heading', { level: 3, name: '配置草稿与版本' })).toBeVisible()
    await expect(page.getByTestId('gateway-menu-versions')).toHaveClass(/is-active/)

    await page.reload()
    await expect(page).toHaveURL(/\/gateway\/versions$/)
    await expect(page.getByRole('heading', { level: 3, name: '配置草稿与版本' })).toBeVisible()
    await expect(page.getByTestId('gateway-menu-versions')).toHaveClass(/is-active/)
  })

  test('旧 ?tab= 链接无损转向新路径', async ({ page }) => {
    await page.goto('/gateway?tab=logs')
    await expect(page).toHaveURL(/\/gateway\/logs$/)
    await expect(page.getByRole('heading', { level: 3, name: '调用日志' })).toBeVisible()

    await page.goto('/gateway?tab=nodes')
    await expect(page).toHaveURL(/\/gateway\/nodes$/)
    await expect(page.getByRole('heading', { level: 3, name: '节点' })).toBeVisible()

    await page.goto('/gateway?tab=%E4%B8%8D%E5%AD%98%E5%9C%A8')
    await expect(page).toHaveURL(/\/gateway\/overview$/)
  })

  test('节点详情可从列表进入、深链刷新且旧返回链接可用', async ({ page }) => {
    await page.goto('/gateway/nodes')
    await page.getByRole('link', { name: /Alpha 节点/ }).click()
    await expect(page).toHaveURL(/\/gateway\/nodes\/node-alpha$/)
    await expect(page.getByTestId('gateway-node-detail')).toBeVisible()
    await expect(page.getByRole('heading', { level: 2, name: 'Alpha 节点' })).toBeVisible()

    await page.reload()
    await expect(page.getByTestId('gateway-node-detail')).toBeVisible()

    await page.getByRole('link', { name: '节点列表' }).click()
    await expect(page).toHaveURL(/\/gateway\/nodes$/)
    await expect(page.getByRole('heading', { level: 3, name: '节点' })).toBeVisible()
  })
})
