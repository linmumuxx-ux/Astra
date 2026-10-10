import { expect, test, type Page } from '@playwright/test'

// 「调用日志」重构回归：/api/gateway/** 全部本地 mock，聚焦服务端能力：
// 筛选/翻页参数原样透传（page、page_size、request_id、model、node_id、key_id、status_code、error_code）、
// Token/延迟/吞吐/错误细节展示、空态文案、加载失败重试与无需登录的日志查询。

type Json = Record<string, unknown>

interface MockOptions {
  empty?: boolean
  failFirst?: boolean
  unauthorized?: boolean
}

interface MockState {
  queries: Record<string, string>[]
  attempts: number
}

function logFixture(id: string, extra: Json = {}): Json {
  return {
    id, key_id: 'key-1', owner_id: 'user-001', model: 'gpt-test', pool_id: 'pool-1',
    node_id: 'node-alpha', streaming: true, retry_count: 0, status_code: 200,
    error_code: null, stream_interrupted: false, connect_ms: 10, ttfb_ms: 50, ttft_ms: 80,
    duration_ms: 900, input_tokens: 100, output_tokens: 200, total_tokens: 300,
    output_tps: 21.3, usage_known: true,
    started_at: '2026-01-06T08:30:00Z', finished_at: '2026-01-06T08:30:01Z', ...extra,
  }
}

function buildLogs(): Json[] {
  return [
    logFixture('req-2026010608-abcdef0123456'),
    logFixture('req-2026010609-error-987654321098', {
      key_id: null, model: null, node_id: 'node-unknown', streaming: false, retry_count: 2,
      status_code: 502, error_code: 'UPSTREAM_CONNECT_TIMEOUT', stream_interrupted: true,
      ttfb_ms: null, ttft_ms: null, duration_ms: null,
      input_tokens: null, output_tokens: null, total_tokens: null,
      output_tps: null, usage_known: false, started_at: '2026-01-06T09:15:00Z', finished_at: null,
    }),
  ]
}

async function mockGateway(page: Page, options: MockOptions = {}): Promise<MockState> {
  const state: MockState = { queries: [], attempts: 0 }
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
    const url = new URL(request.url())
    const pathname = url.pathname
    expect(pathname).not.toBe('/api/gateway/permissions')
    expect(pathname).not.toMatch(/^\/api\/gateway\/(config|self)(\/|$)/)
    expect(route.request().headers().authorization).toBeUndefined()
    const json = (data: unknown, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })

    if (pathname === '/api/gateway/nodes') {
      return json([{ id: 'node-alpha', name: 'Alpha 节点' }])
    }
    if (pathname === '/api/gateway/keys') {
      return json([{ id: 'key-1', name: '测试 Key' }])
    }
    if (pathname === '/api/gateway/routes') {
      return json([{ id: 'route-1', model: 'gpt-test', pool_id: 'pool-1', description: '', enabled: true, weight: 100, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }])
    }
    if (pathname === '/api/gateway/requests' && method === 'GET') {
      state.attempts += 1
      state.queries.push(Object.fromEntries(url.searchParams.entries()))
      if (options.unauthorized) return json({ detail: '访问被拒绝' }, 401)
      if (options.failFirst && state.attempts === 1) {
        return json({ detail: '网关控制面暂时不可用' }, 500)
      }
      const pageValue = Number(url.searchParams.get('page') ?? '1')
      const sizeValue = Number(url.searchParams.get('page_size') ?? '50')
      if (options.empty) return json({ items: [], total: 0, page: pageValue, page_size: sizeValue })
      return json({ items: buildLogs(), total: 120, page: pageValue, page_size: sizeValue })
    }
    return json({ detail: `未 mock 的网关请求：${method} ${pathname}` })
  })
  return state
}

function logRows(page: Page) {
  return page.getByTestId('gateway-requests-table').locator('.el-table__row')
}

// 统一样式层后不再有页面自定 class，筛选控件一律用 data-testid 定位。
async function selectOption(page: Page, testId: string, label: string) {
  await page.getByTestId(testId).locator('.el-select__wrapper').click()
  await page.locator('.el-select-dropdown:visible .el-select-dropdown__item', { hasText: label }).first().click()
}

function lastQuery(state: MockState): Record<string, string> {
  return state.queries[state.queries.length - 1]
}

test.describe('API 中转 · 调用日志', () => {
  test('服务端筛选与翻页参数原样透传', async ({ page }) => {
    const state = await mockGateway(page)
    await page.goto('/gateway/logs')
    await expect(logRows(page)).toHaveCount(2)
    expect(state.queries[0]).toEqual({ page: '1', page_size: '50' })

    await page.getByTestId('log-filter-request').fill('req-2026010608-abcdef0123456')
    await selectOption(page, 'log-filter-model', 'gpt-test')
    await selectOption(page, 'log-filter-node', 'Alpha 节点')
    await selectOption(page, 'log-filter-key', '测试 Key')
    await page.getByTestId('log-filter-status-code').fill('502')
    await page.getByTestId('log-filter-error-code').fill('UPSTREAM_CONNECT_TIMEOUT')
    await selectOption(page, 'log-filter-size', '每页 100')
    await page.getByTestId('gateway-requests-apply').click()

    expect(lastQuery(state)).toEqual({
      page: '1',
      page_size: '100',
      request_id: 'req-2026010608-abcdef0123456',
      model: 'gpt-test',
      node_id: 'node-alpha',
      key_id: 'key-1',
      status_code: '502',
      error_code: 'UPSTREAM_CONNECT_TIMEOUT',
    })

    // 翻页保留全部筛选条件，只推进 page。
    await page.getByTestId('gateway-requests-pagination').locator('.btn-next').click()
    expect(lastQuery(state)).toMatchObject({ page: '2', page_size: '100', model: 'gpt-test', status_code: '502' })

    // 重置清空筛选并回到第 1 页。
    await page.getByTestId('gateway-requests-reset').click()
    expect(lastQuery(state)).toEqual({ page: '1', page_size: '100' })
    await expect(page.getByLabel('Request ID 筛选')).toHaveValue('')
  })

  test('Token、延迟、吞吐与错误细节完整展示', async ({ page }) => {
    await mockGateway(page)
    await page.goto('/gateway/logs')

    const expectedTime = await page.evaluate(() =>
      new Date('2026-01-06T08:30:00Z').toLocaleString('zh-CN', {
        month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
      }))
    const okRow = logRows(page).filter({ hasText: '测试 Key' })
    await expect(okRow.locator('td').nth(0)).toHaveText(expectedTime)
    const idCell = okRow.locator('.log-mono')
    await expect(idCell).toHaveText('req-202601…123456')
    await expect(idCell).toHaveAttribute('title', 'req-2026010608-abcdef0123456')
    await expect(okRow).toContainText('gpt-test')
    await expect(okRow).toContainText('Alpha 节点')
    await expect(okRow.locator('.el-tag', { hasText: '200' })).toBeVisible()
    await expect(okRow).toContainText('SSE')
    await expect(okRow.locator('td').nth(6)).toHaveText('0')
    await expect(okRow).toContainText('100 / 200 / 300')
    await expect(okRow).toContainText('50 ms / 80 ms')
    await expect(okRow).toContainText('900 ms')
    await expect(okRow).toContainText('21.3')

    // 错误行：error_code 优先于状态码、流式中断、用量未知与空值占位。
    const badRow = logRows(page).filter({ hasText: 'UPSTREAM_CONNECT_TIMEOUT' })
    await expect(badRow.locator('.el-tag', { hasText: 'UPSTREAM_CONNECT_TIMEOUT' })).toBeVisible()
    await expect(badRow).toContainText('普通')
    await expect(badRow.locator('.log-interrupted')).toContainText('中断')
    await expect(badRow.locator('td').nth(6)).toHaveText('2')
    await expect(badRow).toContainText('unknown')
    await expect(badRow).toContainText('— / —')
    await expect(badRow.locator('td').nth(9)).toHaveText('—')
    await expect(badRow.locator('td').nth(10)).toHaveText('—')

    await expect(page.getByTestId('gateway-requests-total')).toContainText('共 120 条 · 第 1 页')
  })

  test('空态：无数据与筛选无结果两种文案', async ({ page }) => {
    const state = await mockGateway(page, { empty: true })
    await page.goto('/gateway/logs')

    await expect(page.locator('.el-empty__description')).toHaveText('暂无调用记录。')
    await expect(page.getByTestId('gateway-requests-total')).toContainText('共 0 条')

    await page.getByTestId('log-filter-error-code').fill('NOT_FOUND')
    await page.getByTestId('gateway-requests-apply').click()
    expect(lastQuery(state)).toMatchObject({ page: '1', error_code: 'NOT_FOUND' })
    await expect(page.locator('.el-empty__description')).toHaveText('没有匹配的调用记录，调整筛选条件后重试。')
  })

  test('加载失败展示错误并可重试成功', async ({ page }) => {
    await mockGateway(page, { failFirst: true })
    await page.goto('/gateway/logs')

    const alert = page.getByTestId('gateway-requests-error')
    await expect(alert).toContainText('网关控制面暂时不可用')
    await expect(logRows(page)).toHaveCount(0)
    await alert.getByTestId('gateway-requests-retry').click()
    await expect(alert).toHaveCount(0)
    await expect(logRows(page)).toHaveCount(2)
  })

  test('无需登录即可查询日志，日志页面只提供查询操作', async ({ page }) => {
    const state = await mockGateway(page)
    await page.goto('/gateway/logs')

    await expect(page.getByTestId('gateway-header').getByRole('heading', { level: 2, name: 'API 中转' })).toBeVisible()
    await expect(logRows(page)).toHaveCount(2)
    await expect(page.getByRole('button', { name: /新增|编辑|删除|吊销|发布|回滚/ })).toHaveCount(0)

    await page.getByTestId('gateway-requests-refresh').click()
    expect(lastQuery(state)).toMatchObject({ page: '1' })
  })

  test('控制面返回 401 时显示请求错误并保留日志页面', async ({ page }) => {
    await mockGateway(page, { unauthorized: true })
    await page.goto('/gateway/logs')
    await expect(page.getByTestId('gateway-requests-error')).toContainText('访问被拒绝')
    await expect(page.getByTestId('gateway-requests')).toBeVisible()
  })
})
