import { expect, test, type Page } from '@playwright/test'

// 「API Key 管理」重构回归：/api/gateway/keys 全部本地 mock（内存 store 可被写操作改写），
// 覆盖分页/筛选、只读权限、创建/编辑 payload、额度展示、Key 原文一次性与复制、
// 吊销（确认 + 已吊销禁操作）、服务端 409/500 保留表单、未保存提醒与加载失败重试 / 401 断开。
const CONTROL_TOKEN = 'e2e-gateway-keys-token'

type Json = Record<string, unknown>

interface MockOptions {
  roles?: string[]
  failFirstKeys?: boolean
  keysUnauthorized?: boolean
  duplicateName409?: boolean
}

interface MockState {
  keys: Json[]
  created: Json[]
  patched: Json[]
  revokes: string[]
  keysAttempts: number
}

function keyFixture(id: string, name: string, extra: Json = {}): Json {
  return {
    id, name, key_prefix: `agw_${id}`, owner_id: 'user-001', allowed_models: ['gpt-4o'],
    max_concurrency: 4, hourly_token_limit: 1000, daily_token_limit: 50_000,
    enabled: true, expires_at: null, last_used_at: null, revoked_at: null,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', ...extra,
  }
}

function buildKeys(): Json[] {
  const list: Json[] = Array.from({ length: 9 }, (_, i) =>
    keyFixture(`k${i + 1}`, `Alpha ${i + 1}`, { owner_id: i === 0 ? null : `user-00${i + 1}` }))
  list.push(
    keyFixture('k10', 'Beta 停用', { enabled: false, allowed_models: [] }),
    keyFixture('k11', 'Gamma 吊销', { revoked_at: '2026-01-05T00:00:00Z' }),
    keyFixture('k12', 'Delta 限额', {
      owner_id: null, allowed_models: [], max_concurrency: 0,
      hourly_token_limit: 3_600_000, daily_token_limit: 12_000,
      expires_at: '2026-12-31T10:30:00Z', last_used_at: '2026-01-06T00:00:00Z',
    }),
  )
  return list
}

async function mockGateway(page: Page, options: MockOptions = {}): Promise<MockState> {
  const state: MockState = {
    keys: buildKeys(),
    created: [],
    patched: [],
    revokes: [],
    keysAttempts: 0,
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
      return json({ actor: 'e2e-admin', roles: options.roles ?? ['key'] })
    }
    if (pathname === '/api/gateway/keys' && method === 'GET') {
      state.keysAttempts += 1
      if (options.keysUnauthorized) return json({ detail: '凭据无效' }, 401)
      if (options.failFirstKeys && state.keysAttempts === 1) {
        return json({ detail: '网关控制面暂时不可用' }, 500)
      }
      return json(state.keys)
    }
    if (pathname === '/api/gateway/keys' && method === 'POST') {
      const payload = body()
      if (options.duplicateName409
        && state.keys.some((item) => item.name === payload.name)) {
        return json({ detail: 'Gateway Key 名称已存在，无法重复创建' }, 409)
      }
      state.created.push(payload)
      const id = `k${state.keys.length + 1}`
      const created = {
        ...keyFixture(id, String(payload.name ?? '')),
        ...payload,
        id,
        key_prefix: 'agw_new1',
        enabled: true,
        created_at: '2026-01-02T00:00:00Z',
        updated_at: '2026-01-02T00:00:00Z',
      }
      state.keys.push(created)
      // 原文只在 201 响应里出现一次，store 内不再保留。
      return json({ ...created, key: 'agw_new1_5c0a4b8e2d7f41a0_secret' }, 201)
    }
    const keySingle = /^\/api\/gateway\/keys\/([^/]+)$/.exec(pathname)
    if (keySingle) {
      const id = decodeURIComponent(keySingle[1])
      const index = state.keys.findIndex((item) => item.id === id)
      const key = index >= 0 ? state.keys[index] : null
      if (!key) return json({ detail: 'Key 不存在' }, 404)
      if (method === 'PATCH') {
        const payload = body()
        state.patched.push(payload)
        const updated = { ...key, ...payload, updated_at: '2026-01-02T00:00:00Z' }
        state.keys[index] = updated
        return json(updated)
      }
      if (method === 'DELETE') {
        state.revokes.push(id)
        const revoked = { ...key, revoked_at: '2026-01-07T00:00:00Z' }
        state.keys[index] = revoked
        return json(revoked)
      }
    }
    return json({ detail: `未 mock 的网关请求：${method} ${pathname}` })
  })
  return state
}

function keyRows(page: Page) {
  return page.getByTestId('gateway-keys-table').locator('.el-table__row')
}

async function stopFailPatch(page: Page) {
  await page.unroute('**/api/gateway/keys/k1')
}

function keyTotal(page: Page) {
  return page.locator('.gateway-keys__footer')
}

async function openStatusFilter(page: Page) {
  await page.locator('.key-filter__status .el-select__wrapper').click()
}

async function selectStatusOption(page: Page, label: string) {
  await openStatusFilter(page)
  await page.locator('.el-select-dropdown:visible .el-select-dropdown__item', { hasText: label }).first().click()
}

test.describe('API 中转 · API Key 管理', () => {
  test('列表分页与筛选（只读账号无操作列与新增入口）', async ({ page }) => {
    await mockGateway(page, { roles: ['view'] })
    await page.goto('/gateway/keys')

    await expect(page.getByRole('heading', { level: 3, name: 'API Key 管理' })).toBeVisible()
    await expect(page.getByTestId('gateway-keys-create')).toHaveCount(0)
    const headers = await page.getByTestId('gateway-keys-table').locator('.el-table__header-wrapper th').allInnerTexts()
    expect(headers).not.toContain('操作')

    // 12 个 Key → 首页 10 行 + 分页；第二页 2 行，含额度展示（3.6M / 12K）。
    await expect(keyRows(page)).toHaveCount(10)
    await expect(keyTotal(page)).toContainText('共 12 条')
    await page.getByTestId('gateway-keys-pagination').locator('.el-pager li', { hasText: '2' }).click()
    await expect(keyRows(page)).toHaveCount(2)
    const deltaRow = keyRows(page).filter({ hasText: 'Delta 限额' })
    await expect(deltaRow).toContainText('3.6M / 12K')
    await expect(deltaRow).toContainText('不限')
    await expect(deltaRow).toContainText('全部')

    // 关键字：名称 / 前缀 / 归属。
    await page.getByLabel('搜索 Key').fill('Beta')
    await expect(keyTotal(page)).toContainText('共 1 条')
    await expect(keyRows(page).filter({ hasText: 'Beta 停用' })).toBeVisible()
    await page.getByLabel('搜索 Key').fill('agw_k3')
    await expect(keyTotal(page)).toContainText('共 1 条')
    await expect(keyRows(page).filter({ hasText: 'Alpha 3' })).toBeVisible()
    await page.getByLabel('搜索 Key').fill('user-002')
    await expect(keyTotal(page)).toContainText('共 1 条')
    await page.getByLabel('搜索 Key').fill('')

    // 状态筛选：启用 10 / 停用 1 / 已吊销 1。
    await selectStatusOption(page, '启用')
    await expect(keyTotal(page)).toContainText('共 10 条')
    await selectStatusOption(page, '停用')
    await expect(keyTotal(page)).toContainText('共 1 条')
    await expect(keyRows(page).filter({ hasText: 'Beta 停用' })).toBeVisible()
    await selectStatusOption(page, '已吊销')
    await expect(keyTotal(page)).toContainText('共 1 条')
    await expect(keyRows(page).filter({ hasText: 'Gamma 吊销' })).toContainText('已吊销')
    await page.getByRole('button', { name: '清除筛选' }).click()
    await expect(keyTotal(page)).toContainText('共 12 条')
  })

  test('创建：必填校验、payload、Key 原文一次性展示与复制', async ({ page }) => {
    const state = await mockGateway(page)
    await page.goto('/gateway/keys')
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write'], { origin: new URL(page.url()).origin })

    await page.getByTestId('gateway-keys-create').click()
    const drawer = page.getByTestId('gateway-key-drawer')
    await expect(drawer).toBeVisible()
    // 新建表单没有启用开关（启停仅在编辑时出现）。
    await expect(drawer.getByTestId('gateway-key-enabled')).toHaveCount(0)

    await drawer.getByTestId('gateway-key-save').click()
    await expect(drawer.locator('.el-form-item__error').filter({ hasText: '请填写 Key 名称' })).toBeVisible()
    expect(state.created).toHaveLength(0)
    await expect(page.getByTestId('gateway-key-plaintext')).toHaveCount(0)

    await drawer.getByLabel('名称').fill('E2E Key')
    await drawer.getByLabel('归属 ID').fill('user-e2e')
    await drawer.getByLabel('允许模型（留空为全部，逗号或换行分隔）').fill('gpt-4o, claude-x\no3')
    await drawer.getByLabel('最大并发（0 为不限）').fill('6')
    await drawer.getByLabel('每小时 Token 限额').fill('100000')
    await drawer.getByPlaceholder('长期有效').fill('2026-12-31 23:59')
    await drawer.getByPlaceholder('长期有效').press('Enter')
    await drawer.getByTestId('gateway-key-save').click()
    await expect(drawer).toHaveCount(0)

    // 原文仅在创建成功后展示一次，可复制。
    const plaintext = page.getByTestId('gateway-key-plaintext')
    await expect(plaintext).toBeVisible()
    const secret = 'agw_new1_5c0a4b8e2d7f41a0_secret'
    await expect(plaintext.getByTestId('gateway-key-plaintext-value')).toHaveValue(secret)
    await plaintext.getByTestId('gateway-key-copy').click()
    await expect(page.locator('.el-notification').filter({ hasText: 'Key 已复制到剪贴板' })).toBeVisible()
    await expect(page.evaluate(() => navigator.clipboard.readText())).resolves.toBe(secret)

    expect(state.created).toHaveLength(1)
    expect(state.created[0]).toEqual({
      name: 'E2E Key',
      owner_id: 'user-e2e',
      allowed_models: ['gpt-4o', 'claude-x', 'o3'],
      max_concurrency: 6,
      hourly_token_limit: 100000,
      daily_token_limit: null,
      expires_at: new Date('2026-12-31T23:59').toISOString(),
    })

    // 关闭后原文不再出现：列表只含前缀，页面上找不到 Key 明文。
    await plaintext.getByTestId('gateway-key-plaintext-done').click()
    await expect(plaintext).toHaveCount(0)
    await expect(page.locator(`text=${secret}`)).toHaveCount(0)
    await expect(keyTotal(page)).toContainText('共 13 条')
    await page.reload()
    await expect(page.locator(`text=${secret}`)).toHaveCount(0)
  })

  test('编辑：字段回填、启停与额度 PATCH payload、服务端 500 保留表单', async ({ page }) => {
    const state = await mockGateway(page)
    await page.goto('/gateway/keys')

    await page.getByRole('button', { name: '编辑 Alpha 1' }).click()
    const drawer = page.getByTestId('gateway-key-drawer')
    await expect(drawer.locator('.el-drawer__title')).toHaveText('编辑 Key')
    await expect(drawer.getByLabel('名称')).toHaveValue('Alpha 1')
    await expect(drawer.getByLabel('允许模型（留空为全部，逗号或换行分隔）')).toHaveValue('gpt-4o')
    await expect(drawer.getByLabel('最大并发（0 为不限）')).toHaveValue('4')
    await expect(drawer.getByLabel('每小时 Token 限额')).toHaveValue('1000')
    await expect(drawer.getByLabel('每日 Token 限额')).toHaveValue('50000')
    await expect(drawer.getByTestId('gateway-key-enabled')).toBeVisible()

    // 服务端 500：抽屉保留输入并展示原文错误。
    await drawer.getByLabel('每小时 Token 限额').fill('2000')
    await page.route('**/api/gateway/keys/k1', async (route) => {
      if (route.request().method() === 'PATCH') {
        await route.fulfill({
          status: 500, contentType: 'application/json',
          body: JSON.stringify({ detail: '网关控制面暂时不可用' }),
        })
        return
      }
      await route.continue()
    })
    await drawer.getByTestId('gateway-key-save').click()
    await expect(drawer.getByTestId('gateway-key-error')).toContainText('网关控制面暂时不可用')
    await expect(drawer.getByLabel('每小时 Token 限额')).toHaveValue('2000')
    expect(state.patched).toHaveLength(0)
    await stopFailPatch(page)
    await drawer.getByTestId('gateway-key-save').click()
    await expect(drawer).toHaveCount(0)
    await expect(page.locator('.el-notification').filter({ hasText: 'Key 已更新' })).toBeVisible()
    expect(state.patched[0]).toEqual({
      name: 'Alpha 1',
      owner_id: null,
      allowed_models: ['gpt-4o'],
      max_concurrency: 4,
      hourly_token_limit: 2000,
      daily_token_limit: 50000,
      expires_at: null,
      enabled: true,
    })
    await expect(keyRows(page).filter({ hasText: 'Alpha 1' })).toContainText('2K / 50K')

    // 停用走编辑开关。
    await page.getByRole('button', { name: '编辑 Beta 停用' }).click()
    await drawer.getByTestId('gateway-key-enabled').click()
    await drawer.getByTestId('gateway-key-save').click()
    await expect(drawer).toHaveCount(0)
    expect(state.patched.at(-1)).toMatchObject({ name: 'Beta 停用', enabled: true })
    await expect(keyRows(page).filter({ hasText: 'Beta 停用' })).toContainText('启用')
  })

  test('吊销：确认后可见状态变化，已吊销行禁止重复吊销；同名创建 409 保留表单', async ({ page }) => {
    const state = await mockGateway(page, { duplicateName409: true })
    await page.goto('/gateway/keys')

    // 已吊销行的吊销按钮禁用。
    await page.getByTestId('gateway-keys-pagination').locator('.el-pager li', { hasText: '2' }).click()
    await expect(page.getByRole('button', { name: '吊销 Gamma 吊销' })).toBeDisabled()

    // 吊销 Alpha 5：确认后刷新为已吊销。
    await page.getByTestId('gateway-keys-pagination').locator('.el-pager li', { hasText: '1' }).click()
    await page.getByRole('button', { name: '吊销 Alpha 5' }).click()
    const confirm = page.getByTestId('astra-confirm-dialog')
    await expect(confirm).toContainText('确认吊销「Alpha 5」？吊销后该 Key 立即失效且不可恢复。')
    await confirm.getByRole('button', { name: '吊销' }).click()
    await expect(page.locator('.el-notification').filter({ hasText: 'Key 已吊销' })).toBeVisible()
    expect(state.revokes).toEqual(['k5'])
    await expect(keyRows(page).filter({ hasText: 'Alpha 5' })).toContainText('已吊销')

    // 同名创建：服务端 409，抽屉保留输入并展示服务端文案。
    await page.getByTestId('gateway-keys-create').click()
    const drawer = page.getByTestId('gateway-key-drawer')
    await drawer.getByLabel('名称').fill('Alpha 1')
    await drawer.getByTestId('gateway-key-save').click()
    await expect(drawer.getByTestId('gateway-key-error')).toContainText('Gateway Key 名称已存在，无法重复创建')
    await expect(drawer.getByLabel('名称')).toHaveValue('Alpha 1')
    expect(state.created).toHaveLength(0)
    await expect(keyTotal(page)).toContainText('共 12 条')
  })

  test('未保存修改提醒：继续编辑保留表单，放弃关闭不发请求', async ({ page }) => {
    const state = await mockGateway(page)
    await page.goto('/gateway/keys')

    await page.getByRole('button', { name: '编辑 Alpha 1' }).click()
    const drawer = page.getByTestId('gateway-key-drawer')
    await drawer.getByLabel('名称').fill('Alpha 1 改')
    await expect(drawer.getByTestId('gateway-key-dirty')).toBeVisible()

    await drawer.getByRole('button', { name: '取消' }).click()
    const confirm = page.getByTestId('astra-confirm-dialog')
    await expect(confirm).toContainText('放弃未保存修改')
    await confirm.getByRole('button', { name: '继续编辑' }).click()
    await expect(drawer).toBeVisible()
    await expect(drawer.getByLabel('名称')).toHaveValue('Alpha 1 改')

    await drawer.getByRole('button', { name: '取消' }).click()
    await confirm.getByRole('button', { name: '放弃并关闭' }).click()
    await expect(drawer).toHaveCount(0)
    expect(state.patched).toHaveLength(0)
    await expect(keyRows(page).filter({ hasText: 'Alpha 1 改' })).toHaveCount(0)
  })

  test('加载失败展示错误并可重试成功；401 断开回到接入页', async ({ page }) => {
    await mockGateway(page, { failFirstKeys: true })
    await page.goto('/gateway/keys')

    const alert = page.getByTestId('gateway-keys-error')
    await expect(alert).toContainText('网关控制面暂时不可用')
    await alert.getByTestId('gateway-keys-retry').click()
    await expect(alert).toHaveCount(0)
    await expect(keyRows(page)).toHaveCount(10)

    await mockGateway(page, { keysUnauthorized: true })
    await page.goto('/gateway/keys')
    await expect(page.getByTestId('gateway-connect')).toBeVisible()
  })
})
