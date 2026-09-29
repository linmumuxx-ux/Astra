import { expect, test, type Page } from '@playwright/test'

// 「下游节点」重构回归：/api/gateway/** 全部本地 mock（带内存 store，可被操作改写），
// 覆盖筛选/分页、只读权限、创建/编辑校验与 payload、密钥安全、探测、下线/恢复、
// 启停、删除保护与失败反馈。
const CONTROL_TOKEN = 'e2e-gateway-nodes-token'

type Json = Record<string, unknown>

interface MockOptions {
  roles?: string[]
  failFirstNodes?: boolean
  deleteError?: string
}

interface MockState {
  nodes: Json[]
  created: Json[]
  patched: Json[]
  probes: { id: string; body: Json }[]
  drains: string[]
  activates: string[]
  deletes: string[]
  nodesAttempts: number
}

function buildNodes(): Json[] {
  const alpha = (index: number): Json => ({
    id: `node-${index}`,
    name: `Alpha ${index}`,
    pool_id: null,
    base_url: `https://alpha${index}.example.test`,
    auth_type: 'BEARER',
    auth_header: 'Authorization',
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
  })
  const list: Json[] = Array.from({ length: 8 }, (_, i) => alpha(i + 1))
  list.push(
    { ...alpha(9), name: 'Beta 慢速', pool_id: 'pool-1', health_state: 'UNHEALTHY', has_api_key: false },
    { ...alpha(10), name: 'Beta 备用', pool_id: 'pool-1', health_state: 'DEGRADED', scheduling_state: 'DRAINING' },
    { ...alpha(11), name: 'Gamma 桥接', health_state: 'UNKNOWN', scheduling_state: 'BLOCKED' },
    { ...alpha(12), name: 'Delta 新装', health_state: 'CHECKING', config_state: 'DISABLED' },
  )
  return list
}

const statsFixture = {
  scope: 'node', scope_id: null, window: 'hour',
  window_start: '2026-01-01T00:00:00Z', window_end: '2026-01-01T01:00:00Z',
  requests: 0, success: 0, errors: 0, success_rate: null,
  input_tokens: 0, output_tokens: 0, total_tokens: 0, unknown_usage_requests: 0,
  qps: 0, active: 0, peak_concurrency: 0,
  connect_ms: { avg: null, p50: null, p95: null },
  ttfb_ms: { avg: null, p50: null, p95: null },
  ttft_ms: { avg: null, p50: null, p95: null },
  duration_ms: { avg: null, p50: null, p95: null },
  output_tps: { avg: null, p50: null, p95: null },
  trend: [],
}

async function mockGateway(page: Page, options: MockOptions = {}): Promise<MockState> {
  const state: MockState = {
    nodes: buildNodes(),
    created: [],
    patched: [],
    probes: [],
    drains: [],
    activates: [],
    deletes: [],
    nodesAttempts: 0,
  }
  await page.addInitScript((token) => {
    window.sessionStorage.setItem('astra.gateway.control.token', token)
  }, CONTROL_TOKEN)
  await page.route('**/api/gateway/**', (route) => {
    const request = route.request()
    const method = request.method()
    const pathname = new URL(request.url()).pathname
    const json = (data: unknown, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
    const body = (): Json => (request.postData() ? JSON.parse(request.postData() as string) : {})

    if (pathname === '/api/gateway/permissions') {
      return json({ actor: 'e2e-admin', roles: options.roles ?? ['system'] })
    }
    if (pathname === '/api/gateway/pools') {
      return json([
        { id: 'pool-1', name: '默认资源池', description: '', weight: 100, enabled: true, sort_order: 0, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
      ])
    }
    if (pathname === '/api/gateway/nodes' && method === 'GET') {
      state.nodesAttempts += 1
      if (options.failFirstNodes && state.nodesAttempts === 1) {
        return json({ detail: '网关控制面暂时不可用' }, 500)
      }
      return json(state.nodes)
    }
    if (pathname === '/api/gateway/nodes' && method === 'POST') {
      const payload = body()
      state.created.push(payload)
      const created: Json = {
        ...(state.nodes[0] as Json),
        id: 'node-new',
        name: payload.name,
        base_url: payload.base_url,
        models: payload.models,
        pool_id: payload.pool_id ?? null,
        health_state: 'UNKNOWN',
        scheduling_state: payload.scheduling_state ?? 'DRAINING',
        config_state: payload.config_state ?? 'DISABLED',
        has_api_key: Boolean(payload.api_key),
        last_checked_at: null,
      }
      state.nodes.push(created)
      return json(created, 201)
    }
    const action = /^\/api\/gateway\/nodes\/([^/]+)\/(probe|drain|activate)$/.exec(pathname)
    if (action && method === 'POST') {
      const [, rawId, kind] = action
      const id = decodeURIComponent(rawId)
      const node = state.nodes.find((item) => item.id === id) ?? state.nodes[0]
      if (kind === 'probe') {
        state.probes.push({ id, body: body() })
        const probeTypes = (body().probe_types ?? ['NETWORK', 'SERVICE', 'MODEL', 'STREAM']) as string[]
        const updated = { ...node, health_state: 'HEALTHY', last_checked_at: '2026-01-02T00:00:00Z' }
        state.nodes = state.nodes.map((item) => (item.id === id ? updated : item))
        return json({
          node: updated,
          checks: probeTypes.map((type, index) => ({
            id: index + 1, node_id: id, probe_type: type, success: true,
            latency_ms: 10 + index, status_code: 200, error: null, detail: {},
            created_at: '2026-01-02T00:00:00Z',
          })),
        })
      }
      const scheduling = kind === 'drain' ? 'DRAINING' : 'ACTIVE'
      state[kind === 'drain' ? 'drains' : 'activates'].push(id)
      const updated = { ...node, scheduling_state: scheduling }
      state.nodes = state.nodes.map((item) => (item.id === id ? updated : item))
      return json(updated)
    }
    const single = /^\/api\/gateway\/nodes\/([^/]+)$/.exec(pathname)
    if (single) {
      const id = decodeURIComponent(single[1])
      const index = state.nodes.findIndex((item) => item.id === id)
      const node = index >= 0 ? state.nodes[index] : { ...(state.nodes[0] as Json), id }
      if (method === 'GET') return json(node)
      if (method === 'PATCH') {
        const payload = body()
        state.patched.push(payload)
        const updated = { ...node, ...payload }
        delete updated.api_key
        if (index >= 0) state.nodes[index] = updated
        return json(updated)
      }
      if (method === 'DELETE') {
        state.deletes.push(id)
        if (options.deleteError) return json({ detail: options.deleteError }, 409)
        state.nodes = state.nodes.filter((item) => item.id !== id)
        return route.fulfill({ status: 204 })
      }
    }
    if (/^\/api\/gateway\/nodes\/[^/]+\/health-checks$/.test(pathname)) return json([])
    if (pathname === '/api/gateway/stats' || pathname === '/api/gateway/instances') {
      return json(pathname === '/api/gateway/stats' ? statsFixture : [])
    }
    if (pathname === '/api/gateway/requests') return json({ items: [], total: 0, page: 1, page_size: 50 })
    return json({ detail: `未 mock 的网关请求：${method} ${pathname}` })
  })
  return state
}

function nodesSection(page: Page) {
  return page.getByTestId('gateway-nodes')
}

function totalText(page: Page) {
  return nodesSection(page).locator('.gateway-nodes__footer')
}

function visibleRows(page: Page) {
  return nodesSection(page).locator('.el-table__row')
}

async function openFilterSelect(page: Page, className: string) {
  await page.locator(`.${className} .el-select__wrapper`).click()
}

test.describe('API 中转 · 下游节点', () => {
  test('列表分页与筛选（只读账号无操作列与新增入口）', async ({ page }) => {
    await mockGateway(page, { roles: [] })
    await page.goto('/gateway/nodes')

    await expect(page.getByRole('heading', { level: 3, name: '下游节点' })).toBeVisible()
    await expect(page.getByTestId('gateway-node-create')).toHaveCount(0)
    const headers = await nodesSection(page).locator('.el-table__header-wrapper th').allInnerTexts()
    expect(headers).not.toContain('操作')

    await expect(visibleRows(page)).toHaveCount(10)
    await expect(totalText(page)).toContainText('共 12 条')

    await page.getByTestId('gateway-nodes-pagination').locator('.el-pager li', { hasText: '2' }).click()
    await expect(visibleRows(page)).toHaveCount(2)
    await expect(page.getByText('Gamma 桥接')).toBeVisible()

    await page.getByLabel('搜索节点').fill('Beta')
    await expect(visibleRows(page)).toHaveCount(2)
    await expect(totalText(page)).toContainText('共 2 条')
    await expect(page.getByText('Alpha 1')).toHaveCount(0)
    await page.getByLabel('搜索节点').fill('')

    await openFilterSelect(page, 'node-filter__health')
    await page.locator('.el-select-dropdown:visible .el-select-dropdown__item', { hasText: '健康' }).first().click()
    await expect(totalText(page)).toContainText('共 8 条')
    await expect(page.getByText('Beta 慢速')).toHaveCount(0)

    await page.getByRole('button', { name: '清除筛选' }).click()
    await openFilterSelect(page, 'node-filter__scheduling')
    await page.locator('.el-select-dropdown:visible .el-select-dropdown__item', { hasText: '安全下线' }).first().click()
    await expect(totalText(page)).toContainText('共 1 条')
    await expect(page.getByText('Beta 备用')).toBeVisible()

    await page.getByRole('button', { name: '清除筛选' }).click()
    await expect(totalText(page)).toContainText('共 12 条')

    // 详情跳转仍可从节点名链接进入。
    await page.getByTestId('gateway-nodes-pagination').locator('.el-pager li', { hasText: '2' }).click()
    await page.getByRole('link', { name: /Gamma 桥接/ }).click()
    await expect(page).toHaveURL(/\/gateway\/nodes\/node-11$/)
    await expect(page.getByTestId('gateway-node-detail')).toBeVisible()
  })

  test('node 角色展示新增与操作列', async ({ page }) => {
    await mockGateway(page, { roles: ['node'] })
    await page.goto('/gateway/nodes')
    await expect(page.getByTestId('gateway-node-create')).toBeVisible()
    const headers = await nodesSection(page).locator('.el-table__header-wrapper th').allInnerTexts()
    expect(headers).toContain('操作')
  })

  test('创建：必填校验、/v1 拦截、健康就绪门禁与两阶段 payload', async ({ page }) => {
    const state = await mockGateway(page)
    await page.goto('/gateway/nodes')

    await page.getByTestId('gateway-node-create').click()
    const drawer = page.getByTestId('gateway-node-drawer')
    await expect(drawer).toBeVisible()

    await drawer.getByTestId('gateway-node-save').click()
    await expect(drawer.locator('.el-form-item__error').filter({ hasText: '请填写节点名称' })).toBeVisible()
    await expect(drawer.locator('.el-form-item__error').filter({ hasText: '请填写节点 Base URL' })).toBeVisible()

    await drawer.getByLabel('节点名称').fill('E2E 新节点')
    await drawer.getByLabel(/Base URL/).fill('https://new.example.test/v1')
    await drawer.getByLabel('节点名称').click()
    await expect(drawer.locator('.el-form-item__error', { hasText: '不要包含 /v1' })).toBeVisible()

    await drawer.getByLabel(/Base URL/).fill('https://new.example.test')
    await drawer.getByLabel('下游凭据').fill('sk-e2e-secret')
    await drawer.getByLabel('支持模型（逗号或换行分隔）').fill('gpt-new')

    // 未探测时「调度中」保存被门禁拒绝，且不落库。
    await drawer.getByTestId('gateway-node-save').click()
    await expect(drawer.getByTestId('gateway-node-error')).toContainText('节点需完成')
    expect(state.created).toHaveLength(0)

    await drawer.getByTestId('gateway-node-probe-run').click()
    await expect(drawer.getByTestId('gateway-node-probe-checks').locator('li')).toHaveCount(4)

    await drawer.getByTestId('gateway-node-save').click()
    await expect(drawer).toHaveCount(0)

    expect(state.created).toHaveLength(1)
    const createPayload = state.created[0]
    expect(createPayload).toMatchObject({
      name: 'E2E 新节点',
      base_url: 'https://new.example.test',
      models: ['gpt-new'],
      api_key: 'sk-e2e-secret',
      config_state: 'DISABLED',
      scheduling_state: 'DRAINING',
    })
    expect(state.patched.length).toBeGreaterThanOrEqual(2)
    expect(state.patched.some((payload) => 'api_key' in payload)).toBe(false)
    expect(state.patched.at(-1)).toMatchObject({
      config_state: 'ENABLED',
      scheduling_state: 'ACTIVE',
      pool_id: null,
    })
    // 密钥不回显：任何 DOM 文本都不包含明文。
    await expect(page.getByText('sk-e2e-secret')).toHaveCount(0)
    await expect(totalText(page)).toContainText('共 13 条')
  })

  test('编辑：不回显既有密钥，保存 payload 不含 api_key', async ({ page }) => {
    const state = await mockGateway(page)
    await page.goto('/gateway/nodes')

    await page.getByRole('button', { name: '编辑 Alpha 1' }).click()
    const drawer = page.getByTestId('gateway-node-drawer')
    await expect(drawer.locator('.el-drawer__title')).toHaveText('编辑节点')
    const secretInput = drawer.getByTestId('gateway-node-api-key')
    await expect(secretInput).toHaveValue('')
    await expect(secretInput).toHaveAttribute('placeholder', /留空保持不变/)
    await expect(drawer.getByLabel('节点名称')).toHaveValue('Alpha 1')

    await drawer.getByTestId('gateway-node-save').click()
    await expect(drawer).toHaveCount(0)
    expect(state.created).toHaveLength(0)
    expect(state.patched.length).toBeGreaterThanOrEqual(2)
    expect(state.patched.every((payload) => !('api_key' in payload))).toBe(true)
  })

  test('未保存修改提醒：继续编辑保留表单，确认后关闭且不提交', async ({ page }) => {
    const state = await mockGateway(page)
    await page.goto('/gateway/nodes')

    await page.getByRole('button', { name: '编辑 Alpha 2' }).click()
    const drawer = page.getByTestId('gateway-node-drawer')
    await drawer.getByLabel('节点名称').fill('Alpha 2 改')
    await expect(drawer.getByTestId('gateway-node-dirty')).toBeVisible()

    await drawer.getByRole('button', { name: '取消' }).click()
    const confirm = page.getByTestId('astra-confirm-dialog')
    await expect(confirm).toContainText('放弃未保存修改')
    await confirm.getByRole('button', { name: '继续编辑' }).click()
    await expect(drawer).toBeVisible()
    await expect(drawer.getByLabel('节点名称')).toHaveValue('Alpha 2 改')

    await drawer.getByRole('button', { name: '取消' }).click()
    await confirm.getByRole('button', { name: '放弃并关闭' }).click()
    await expect(drawer).toHaveCount(0)
    expect(state.patched).toHaveLength(0)
  })

  test('行内探测、启停、安全下线与恢复调度', async ({ page }) => {
    const state = await mockGateway(page)
    await page.goto('/gateway/nodes')

    await page.getByRole('button', { name: '探测 Alpha 1' }).click()
    await expect(page.locator('.el-notification').filter({ hasText: 'Alpha 1 探测完成：4/4 项通过' })).toBeVisible()
    expect(state.probes.at(-1)?.body).toEqual({ probe_types: ['NETWORK', 'SERVICE', 'MODEL', 'STREAM'] })

    await page.getByRole('button', { name: '禁用 Alpha 1' }).click()
    await expect(page.locator('.el-notification').filter({ hasText: '节点已禁用' })).toBeVisible()
    expect(state.patched.at(-1)).toEqual({ config_state: 'DISABLED' })
    await page.getByRole('button', { name: '启用 Alpha 1' }).click()
    expect(state.patched.at(-1)).toEqual({ config_state: 'ENABLED' })

    await page.getByRole('button', { name: '安全下线 Alpha 1' }).click()
    const confirm = page.getByTestId('astra-confirm-dialog')
    await expect(confirm).toContainText('进入 DRAINING')
    await confirm.getByRole('button', { name: '安全下线' }).click()
    await expect(page.locator('.el-notification').filter({ hasText: '节点已进入安全下线' })).toBeVisible()
    expect(state.drains).toContain('node-1')
    await expect(visibleRows(page).filter({ hasText: 'Alpha 1' }).getByText('安全下线')).toBeVisible()

    await page.getByRole('button', { name: '恢复调度 Alpha 1' }).click()
    await expect(page.locator('.el-notification').filter({ hasText: '节点已恢复调度' })).toBeVisible()
    expect(state.activates).toContain('node-1')
  })

  test('删除保护：409 反馈失败信息，成功后列表移除', async ({ page }) => {
    const failing = await mockGateway(page, { deleteError: '节点仍有活跃并发，无法删除' })
    await page.goto('/gateway/nodes')

    await page.getByRole('button', { name: '删除 Alpha 1' }).click()
    const confirm = page.getByTestId('astra-confirm-dialog')
    await expect(confirm).toContainText('仅当节点已 DRAINING 且活跃并发为 0')
    await confirm.getByRole('button', { name: '删除节点' }).click()
    await expect(page.locator('.el-notification').filter({ hasText: '节点仍有活跃并发，无法删除' })).toBeVisible()
    expect(failing.deletes).toEqual(['node-1'])
    await expect(totalText(page)).toContainText('共 12 条')

    const store = await mockGateway(page)
    await page.goto('/gateway/nodes')
    await page.getByRole('button', { name: '删除 Beta 慢速' }).click()
    await page.getByTestId('astra-confirm-dialog').getByRole('button', { name: '删除节点' }).click()
    await expect(page.locator('.el-notification').filter({ hasText: '节点已删除' })).toBeVisible()
    expect(store.deletes).toEqual(['node-9'])
    await expect(totalText(page)).toContainText('共 11 条')
    await expect(page.getByText('Beta 慢速')).toHaveCount(0)
  })

  test('加载失败展示错误并可重试成功', async ({ page }) => {
    await mockGateway(page, { failFirstNodes: true })
    await page.goto('/gateway/nodes')

    const alert = page.getByTestId('gateway-nodes-error')
    await expect(alert).toContainText('网关控制面暂时不可用')
    await expect(alert.getByTestId('gateway-nodes-retry')).toBeVisible()

    await alert.getByTestId('gateway-nodes-retry').click()
    await expect(alert).toHaveCount(0)
    await expect(visibleRows(page)).toHaveCount(10)
  })
})
