import { expect, test, type Page } from '@playwright/test'

// 「资源池与模型路由」重构回归：/api/gateway/pools|routes 全部本地 mock（内存 store 可被写操作改写），
// 覆盖分页/筛选、无需登录的写操作、池与路由的创建/编辑/删除 payload、模型名唯一预校验、
// 服务端唯一性与引用冲突（409 失败保留表单）、未保存提醒与加载失败重试 / 401 断开。

type Json = Record<string, unknown>

interface MockOptions {
  failFirstPools?: boolean
  poolsUnauthorized?: boolean
}

interface MockState {
  pools: Json[]
  routes: Json[]
  poolCreated: Json[]
  poolPatched: Json[]
  poolDeletes: string[]
  routeCreated: Json[]
  routePatched: Json[]
  routeDeletes: string[]
  poolsAttempts: number
}

function poolFixture(id: string, name: string, extra: Json = {}): Json {
  return {
    id, name, description: '', weight: 100, enabled: true, sort_order: 0,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', ...extra,
  }
}

function routeFixture(id: string, model: string, poolId: string, extra: Json = {}): Json {
  return {
    id, model, pool_id: poolId, description: '', enabled: true, weight: 1,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', ...extra,
  }
}

function buildPools(): Json[] {
  return [
    poolFixture('p1', 'Alpha 1', { sort_order: 1 }),
    poolFixture('p2', 'Alpha 2', { sort_order: 2 }),
    poolFixture('p3', 'Alpha 3', { sort_order: 3 }),
    poolFixture('p4', 'Alpha 4', { sort_order: 4 }),
    poolFixture('p5', 'Alpha 5', { sort_order: 5 }),
    poolFixture('p6', 'Alpha 6', { sort_order: 6 }),
    poolFixture('p7', 'Alpha 7', { sort_order: 7 }),
    poolFixture('p8', 'Alpha 8', { sort_order: 8 }),
    poolFixture('p9', 'Alpha 9', { sort_order: 9 }),
    poolFixture('p10', 'Beta 1', { description: '备用池', sort_order: 10 }),
    poolFixture('p11', 'Beta 2', { enabled: false, sort_order: 11 }),
    poolFixture('p12', 'Gamma 引用', { sort_order: 12 }),
  ]
}

function buildRoutes(): Json[] {
  return [
    routeFixture('r1', 'gpt-4o', 'p1', { weight: 100 }),
    routeFixture('r2', 'gpt-4o-mini', 'p1'),
    routeFixture('r3', 'o1', 'p1'),
    routeFixture('r4', 'o3', 'p2'),
    routeFixture('r5', 'qwen-max', 'p2'),
    routeFixture('r6', 'qwen-plus', 'p3'),
    routeFixture('r7', 'deepseek-v3', 'p3'),
    routeFixture('r8', 'kimi-k2', 'p4'),
    routeFixture('r9', 'doubao-pro', 'p4'),
    routeFixture('r10', 'claude-x', 'p10'),
    routeFixture('r11', 'claude-y', 'p11', { enabled: false }),
    routeFixture('r12', 'glm-4', 'p12'),
  ]
}

async function mockGateway(page: Page, options: MockOptions = {}): Promise<MockState> {
  const state: MockState = {
    pools: buildPools(),
    routes: buildRoutes(),
    poolCreated: [],
    poolPatched: [],
    poolDeletes: [],
    routeCreated: [],
    routePatched: [],
    routeDeletes: [],
    poolsAttempts: 0,
  }
  // 隔离 Astra 全局数据与事件流，避免未连接后端影响页面导航。
  await page.route((url) => url.pathname.startsWith('/api/') && !url.pathname.startsWith('/api/gateway/'), (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname === '/api/events/stream') {
      return route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: '' })
    }
    const data = ['/api/employees', '/api/tasks', '/api/task-categories', '/api/events'].includes(pathname) ? [] : {}
    return route.fulfill({ json: data })
  })
  await page.route('**/api/gateway/**', (route) => {
    const request = route.request()
    const method = request.method()
    const pathname = new URL(request.url()).pathname
    expect(pathname).not.toBe('/api/gateway/permissions')
    expect(pathname).not.toMatch(/^\/api\/gateway\/(config|self)(\/|$)/)
    expect(route.request().headers().authorization).toBeUndefined()
    const json = (data: unknown, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
    const body = (): Json => (request.postData() ? JSON.parse(request.postData() as string) : {})

    if (pathname === '/api/gateway/pools' && method === 'GET') {
      state.poolsAttempts += 1
      if (options.poolsUnauthorized) return json({ detail: '访问被拒绝' }, 401)
      if (options.failFirstPools && state.poolsAttempts === 1) {
        return json({ detail: '网关控制面暂时不可用' }, 500)
      }
      return json(state.pools)
    }
    if (pathname === '/api/gateway/pools' && method === 'POST') {
      const payload = body()
      if (state.pools.some((item) => item.name === payload.name)) {
        return json({ detail: '唯一约束冲突，请检查名称或模型是否重复' }, 409)
      }
      state.poolCreated.push(payload)
      const created = {
        ...poolFixture(`p${state.pools.length + 1}`, String(payload.name ?? '')),
        ...payload,
        id: `p${state.pools.length + 1}`,
        created_at: '2026-01-02T00:00:00Z',
        updated_at: '2026-01-02T00:00:00Z',
      }
      state.pools.push(created)
      return json(created, 201)
    }
    const poolSingle = /^\/api\/gateway\/pools\/([^/]+)$/.exec(pathname)
    if (poolSingle) {
      const id = decodeURIComponent(poolSingle[1])
      const index = state.pools.findIndex((item) => item.id === id)
      const pool = index >= 0 ? state.pools[index] : null
      if (!pool) return json({ detail: '资源池不存在' }, 404)
      if (method === 'PATCH') {
        const payload = body()
        if (typeof payload.name === 'string'
          && state.pools.some((item) => item.id !== id && item.name === payload.name)) {
          return json({ detail: '唯一约束冲突，请检查名称或模型是否重复' }, 409)
        }
        state.poolPatched.push(payload)
        const updated = { ...pool, ...payload, updated_at: '2026-01-02T00:00:00Z' }
        state.pools[index] = updated
        return json(updated)
      }
      if (method === 'DELETE') {
        state.poolDeletes.push(id)
        if (state.routes.some((item) => item.pool_id === id)) {
          return json({ detail: '资源池仍被节点或路由引用，无法删除' }, 409)
        }
        state.pools = state.pools.filter((item) => item.id !== id)
        return route.fulfill({ status: 204 })
      }
    }
    if (pathname === '/api/gateway/routes' && method === 'GET') return json(state.routes)
    if (pathname === '/api/gateway/routes' && method === 'POST') {
      const payload = body()
      if (state.routes.some((item) => item.model === payload.model)) {
        return json({ detail: '唯一约束冲突，请检查名称或模型是否重复' }, 409)
      }
      if (!state.pools.some((item) => item.id === payload.pool_id)) {
        return json({ detail: '资源池不存在' }, 404)
      }
      state.routeCreated.push(payload)
      const created = {
        ...routeFixture(`r${state.routes.length + 1}`, String(payload.model ?? ''), String(payload.pool_id ?? '')),
        ...payload,
        id: `r${state.routes.length + 1}`,
        created_at: '2026-01-02T00:00:00Z',
        updated_at: '2026-01-02T00:00:00Z',
      }
      state.routes.push(created)
      return json(created, 201)
    }
    const routeSingle = /^\/api\/gateway\/routes\/([^/]+)$/.exec(pathname)
    if (routeSingle) {
      const id = decodeURIComponent(routeSingle[1])
      const index = state.routes.findIndex((item) => item.id === id)
      const routeItem = index >= 0 ? state.routes[index] : null
      if (!routeItem) return json({ detail: '路由不存在' }, 404)
      if (method === 'PATCH') {
        const payload = body()
        if (typeof payload.model === 'string'
          && state.routes.some((item) => item.id !== id && item.model === payload.model)) {
          return json({ detail: '唯一约束冲突，请检查名称或模型是否重复' }, 409)
        }
        state.routePatched.push(payload)
        const updated = { ...routeItem, ...payload, updated_at: '2026-01-02T00:00:00Z' }
        state.routes[index] = updated
        return json(updated)
      }
      if (method === 'DELETE') {
        state.routeDeletes.push(id)
        state.routes = state.routes.filter((item) => item.id !== id)
        return route.fulfill({ status: 204 })
      }
    }
    return json({ detail: `未 mock 的网关请求：${method} ${pathname}` })
  })
  return state
}

function poolRows(page: Page) {
  return page.getByTestId('gateway-pool-table').locator('.el-table__row')
}

function routeRows(page: Page) {
  return page.getByTestId('gateway-route-table').locator('.el-table__row')
}

function poolTotal(page: Page) {
  return page.getByTestId('gateway-pool-card').locator('.gateway-pools-routes__footer')
}

function routeTotal(page: Page) {
  return page.getByTestId('gateway-route-card').locator('.gateway-pools-routes__footer')
}

// 统一样式层后不再有页面自定 class，筛选控件一律用 data-testid 定位。
async function openFilterSelect(page: Page, testId: string) {
  await page.getByTestId(testId).locator('.el-select__wrapper').click()
}

async function selectDrawerOption(page: Page, testId: string, optionText: string) {
  await page.getByTestId(testId).locator('.el-select__wrapper').click()
  await page.locator('.el-select-dropdown:visible .el-select-dropdown__item', { hasText: optionText }).first().click()
}

test.describe('API 中转 · 资源池与模型路由', () => {
  test('无需登录即可分页与筛选，资源池和路由均显示写操作入口', async ({ page }) => {
    await mockGateway(page)
    await page.goto('/gateway/routes')

    await expect(page.getByTestId('gateway-header').getByRole('heading', { level: 2, name: 'API 中转' })).toBeVisible()
    await expect(page.getByTestId('gateway-pool-create')).toBeVisible()
    await expect(page.getByTestId('gateway-route-create')).toBeVisible()
    const poolHeaders = await page.getByTestId('gateway-pool-table').locator('.el-table__header-wrapper th').allInnerTexts()
    expect(poolHeaders).toContain('操作')
    const routeHeaders = await page.getByTestId('gateway-route-table').locator('.el-table__header-wrapper th').allInnerTexts()
    expect(routeHeaders).toContain('操作')

    // 资源池：12 个 → 首页 10 行 + 分页；第二页 2 行。
    await expect(poolRows(page)).toHaveCount(10)
    await expect(poolTotal(page)).toContainText('共 12 个')
    await page.getByTestId('gateway-pool-pagination').locator('.el-pager li', { hasText: '2' }).click()
    await expect(poolRows(page)).toHaveCount(2)
    await expect(poolRows(page).filter({ hasText: 'Gamma 引用' })).toBeVisible()

    // 关键字与状态筛选。
    await page.getByLabel('搜索资源池').fill('Alpha')
    await expect(poolTotal(page)).toContainText('共 9 个')
    await expect(poolRows(page).filter({ hasText: 'Beta 1' })).toHaveCount(0)
    await page.getByLabel('搜索资源池').fill('Beta')
    await expect(poolRows(page)).toHaveCount(2)
    await page.getByLabel('搜索资源池').fill('')
    await openFilterSelect(page, 'pool-filter-enabled')
    await page.locator('.el-select-dropdown:visible .el-select-dropdown__item', { hasText: '禁用' }).first().click()
    await expect(poolTotal(page)).toContainText('共 1 个')
    await expect(poolRows(page).filter({ hasText: 'Beta 2' })).toBeVisible()
    await page.getByRole('button', { name: '清除筛选' }).first().click()
    await expect(poolTotal(page)).toContainText('共 12 个')

    // 路由：12 条 → 首页 10 行 + 分页；关键字 / 资源池 / 状态筛选。
    await expect(routeRows(page)).toHaveCount(10)
    await expect(routeTotal(page)).toContainText('共 12 条')
    await page.getByTestId('gateway-route-pagination').locator('.el-pager li', { hasText: '2' }).click()
    await expect(routeRows(page)).toHaveCount(2)
    await expect(routeRows(page).filter({ hasText: 'glm-4' })).toBeVisible()

    await page.getByLabel('搜索路由').fill('claude')
    await expect(routeTotal(page)).toContainText('共 2 条')
    await page.getByLabel('搜索路由').fill('')
    await openFilterSelect(page, 'route-filter-pool')
    await page.locator('.el-select-dropdown:visible .el-select-dropdown__item', { hasText: 'Alpha 1' }).first().click()
    await expect(routeTotal(page)).toContainText('共 3 条')
    await expect(routeRows(page).filter({ hasText: 'gpt-4o-mini' })).toBeVisible()
    await page.getByRole('button', { name: '清除筛选' }).first().click()
    await openFilterSelect(page, 'route-filter-enabled')
    await page.locator('.el-select-dropdown:visible .el-select-dropdown__item', { hasText: '禁用' }).first().click()
    await expect(routeTotal(page)).toContainText('共 1 条')
    await expect(routeRows(page).filter({ hasText: 'claude-y' })).toBeVisible()
    await page.getByRole('button', { name: '清除筛选' }).first().click()
    await expect(routeTotal(page)).toContainText('共 12 条')
  })

  test('资源池：创建必填校验、payload、编辑保存直接更新与删除', async ({ page }) => {
    const state = await mockGateway(page)
    await page.goto('/gateway/routes')

    await page.getByTestId('gateway-pool-create').click()
    const drawer = page.getByTestId('gateway-pool-drawer')
    await expect(drawer).toBeVisible()

    await drawer.getByTestId('gateway-pool-save').click()
    await expect(drawer.locator('.el-form-item__error').filter({ hasText: '请填写资源池名称' })).toBeVisible()
    expect(state.poolCreated).toHaveLength(0)

    await drawer.getByLabel('名称').fill('E2E 资源池')
    await drawer.getByLabel('描述').fill('e2e 测试池')
    await drawer.getByLabel('权重').fill('50')
    await drawer.getByLabel('排序').fill('7')
    await drawer.getByTestId('gateway-pool-save').click()
    await expect(drawer).toHaveCount(0)
    await expect(page.locator('.el-notification').filter({ hasText: '资源池已保存' })).toBeVisible()
    expect(state.poolCreated).toHaveLength(1)
    expect(state.poolCreated[0]).toEqual({
      name: 'E2E 资源池', description: 'e2e 测试池', weight: 50, sort_order: 7, enabled: true,
    })
    await expect(poolTotal(page)).toContainText('共 13 个')

    // 编辑回填全部字段，保存走 PATCH。
    await page.getByRole('button', { name: '编辑 Alpha 1' }).click()
    await expect(drawer.locator('.el-drawer__title')).toHaveText('编辑资源池')
    await expect(drawer.getByLabel('名称')).toHaveValue('Alpha 1')
    await expect(drawer.getByLabel('权重')).toHaveValue('100')
    await drawer.getByLabel('权重').fill('80')
    await drawer.getByTestId('gateway-pool-save').click()
    await expect(drawer).toHaveCount(0)
    expect(state.poolPatched.at(-1)).toMatchObject({ name: 'Alpha 1', weight: 80 })
    await expect(poolRows(page).filter({ hasText: 'Alpha 1' })).toBeVisible()
    await expect(poolRows(page).filter({ hasText: 'Alpha 1' })).toContainText('80')
    await page.reload()
    await expect(poolRows(page).filter({ hasText: 'Alpha 1' })).toContainText('80')

    // 删除未被任何路由引用的资源池（p5）。
    await page.getByRole('button', { name: '删除 Alpha 5' }).click()
    const confirm = page.getByTestId('astra-confirm-dialog')
    await expect(confirm).toContainText('确认删除「Alpha 5」')
    await confirm.getByRole('button', { name: '删除' }).click()
    await expect(page.locator('.el-notification').filter({ hasText: '资源池已删除' })).toBeVisible()
    expect(state.poolDeletes).toEqual(['p5'])
    await expect(poolTotal(page)).toContainText('共 12 个')
    await expect(poolRows(page).filter({ hasText: 'Alpha 5' })).toHaveCount(0)
  })

  test('路由：必填、模型名唯一预校验、保存后直接更新与删除', async ({ page }) => {
    const state = await mockGateway(page)
    await page.goto('/gateway/routes')

    await page.getByTestId('gateway-route-create').click()
    const drawer = page.getByTestId('gateway-route-drawer')
    await drawer.getByTestId('gateway-route-save').click()
    await expect(drawer.locator('.el-form-item__error').filter({ hasText: '请填写模型名' })).toBeVisible()
    await expect(drawer.locator('.el-form-item__error').filter({ hasText: '请选择资源池' })).toBeVisible()
    expect(state.routeCreated).toHaveLength(0)

    // 客户端唯一性预校验：重复模型名被拦截，不发请求。
    await drawer.getByLabel('模型名').fill('gpt-4o')
    await drawer.getByLabel('描述').click()
    await expect(drawer.locator('.el-form-item__error', { hasText: '已有路由，模型名必须唯一' })).toBeVisible()
    await selectDrawerOption(page, 'gateway-route-pool', 'Alpha 1')
    await drawer.getByTestId('gateway-route-save').click()
    expect(state.routeCreated).toHaveLength(0)
    await expect(drawer).toBeVisible()

    // 换唯一模型名后创建成功，payload 与既有 API 契约一致。
    await drawer.getByLabel('模型名').fill('e2e-model')
    await drawer.getByLabel('描述').click()
    await drawer.getByTestId('gateway-route-save').click()
    await expect(drawer).toHaveCount(0)
    await expect(page.locator('.el-notification').filter({ hasText: '路由已保存' })).toBeVisible()
    expect(state.routeCreated).toHaveLength(1)
    expect(state.routeCreated[0]).toEqual({
      model: 'e2e-model', pool_id: 'p1', description: '', weight: 1, enabled: true,
    })
    await expect(routeTotal(page)).toContainText('共 13 条')

    // 编辑不改模型名不会误报唯一性冲突。
    await page.getByRole('button', { name: '编辑 gpt-4o', exact: true }).click()
    await expect(drawer.getByLabel('模型名')).toHaveValue('gpt-4o')
    await drawer.getByLabel('权重').fill('60')
    await drawer.getByTestId('gateway-route-save').click()
    await expect(drawer).toHaveCount(0)
    expect(state.routePatched.at(-1)).toMatchObject({ model: 'gpt-4o', weight: 60 })
    const updatedRow = routeRows(page).filter({ has: page.getByRole('button', { name: '编辑 gpt-4o', exact: true }) })
    await expect(updatedRow).toContainText('60')
    await page.reload()
    await expect(updatedRow).toContainText('60')

    // 删除路由走原生确认。
    await page.getByRole('button', { name: '删除 claude-x' }).click()
    const confirm = page.getByTestId('astra-confirm-dialog')
    await expect(confirm).toContainText('确认删除模型「claude-x」的路由？')
    await confirm.getByRole('button', { name: '删除' }).click()
    await expect(page.locator('.el-notification').filter({ hasText: '路由已删除' })).toBeVisible()
    expect(state.routeDeletes).toEqual(['r10'])
    await expect(routeTotal(page)).toContainText('共 12 条')
  })

  test('服务端冲突：引用删除保护与唯一性 409，失败保留表单', async ({ page }) => {
    const state = await mockGateway(page)
    await page.goto('/gateway/routes')

    // Gamma 引用 是第 12 个池，位于分页第二页。
    await page.getByTestId('gateway-pool-pagination').locator('.el-pager li', { hasText: '2' }).click()
    await page.getByRole('button', { name: '删除 Gamma 引用' }).click()
    const confirm = page.getByTestId('astra-confirm-dialog')
    await confirm.getByRole('button', { name: '删除' }).click()
    await expect(page.locator('.el-notification').filter({ hasText: '资源池仍被节点或路由引用，无法删除' })).toBeVisible()
    expect(state.poolDeletes).toEqual(['p12'])
    await expect(poolTotal(page)).toContainText('共 12 个')
    await expect(poolRows(page).filter({ hasText: 'Gamma 引用' })).toBeVisible()

    // 同名资源池：服务端 409，抽屉保留输入。
    await page.getByTestId('gateway-pool-create').click()
    const drawer = page.getByTestId('gateway-pool-drawer')
    await drawer.getByLabel('名称').fill('Alpha 1')
    await drawer.getByTestId('gateway-pool-save').click()
    await expect(drawer.getByTestId('gateway-pool-error')).toContainText('唯一约束冲突，请检查名称或模型是否重复')
    await expect(drawer.getByLabel('名称')).toHaveValue('Alpha 1')
    expect(state.poolCreated).toHaveLength(0)
    await expect(poolTotal(page)).toContainText('共 12 个')
  })

  test('未保存修改提醒：继续编辑保留表单，放弃关闭不发请求', async ({ page }) => {
    const state = await mockGateway(page)
    await page.goto('/gateway/routes')

    await page.getByRole('button', { name: '编辑 Alpha 5' }).click()
    const drawer = page.getByTestId('gateway-pool-drawer')
    await drawer.getByLabel('名称').fill('Alpha 5 改')
    await expect(drawer.getByTestId('gateway-pool-dirty')).toBeVisible()

    await drawer.getByRole('button', { name: '取消' }).click()
    const confirm = page.getByTestId('astra-confirm-dialog')
    await expect(confirm).toContainText('放弃未保存修改')
    await confirm.getByRole('button', { name: '继续编辑' }).click()
    await expect(drawer).toBeVisible()
    await expect(drawer.getByLabel('名称')).toHaveValue('Alpha 5 改')

    await drawer.getByRole('button', { name: '取消' }).click()
    await confirm.getByRole('button', { name: '放弃并关闭' }).click()
    await expect(drawer).toHaveCount(0)
    expect(state.poolPatched).toHaveLength(0)
    await expect(poolRows(page).filter({ hasText: 'Alpha 5' })).toBeVisible()
  })

  test('加载失败展示错误并可重试成功', async ({ page }) => {
    await mockGateway(page, { failFirstPools: true })
    await page.goto('/gateway/routes')

    const alert = page.getByTestId('gateway-pools-routes-error')
    await expect(alert).toContainText('网关控制面暂时不可用')
    await expect(alert.getByTestId('gateway-pools-routes-retry')).toBeVisible()

    await alert.getByTestId('gateway-pools-routes-retry').click()
    await expect(alert).toHaveCount(0)
    await expect(poolRows(page)).toHaveCount(10)
    await expect(routeRows(page)).toHaveCount(10)
  })

  test('控制面返回 401 时显示请求错误并保留管理页面', async ({ page }) => {
    await mockGateway(page, { poolsUnauthorized: true })
    await page.goto('/gateway/routes')
    await expect(page.getByTestId('gateway-pools-routes-error')).toContainText('访问被拒绝')
    await expect(page.getByTestId('gateway-page')).toBeVisible()
    await expect(page.getByTestId('gateway-pool-create')).toBeVisible()
  })
})
