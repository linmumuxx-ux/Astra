import { expect, test, type Page } from '@playwright/test'

// 「配置草稿与版本」重构回归：/api/gateway/config/* 全部本地 mock（版本 store 可被发布/回滚改写），
// 覆盖 publish 权限门禁、草稿校验失败/警告/通过、发布 payload 与失败保留重试、
// 版本记录状态语义、回滚确认/取消/失败、快照详情与加载失败、发布对账、加载失败重试与 401 断开。
const CONTROL_TOKEN = 'e2e-gateway-versions-token'

type Json = Record<string, unknown>

interface MockOptions {
  roles?: string[]
  draftInvalid?: boolean
  failFirstDraft?: boolean
  draftUnauthorized?: boolean
  publishReject?: boolean
  failFirstPublish?: boolean
  rollbackFails?: boolean
  detailFails?: boolean
  reconcileChanged?: number
}

interface MockState {
  versions: Json[]
  draftAttempts: number
  publishes: Json[]
  rollbacks: Json[]
  reconciles: number
}

function draftValid(): Json {
  return {
    valid: true,
    errors: [],
    warnings: [],
    counts: { pools: 2, nodes: 5, routes: 3, active_routes: 2, keys: 4 },
  }
}

function draftInvalid(): Json {
  return {
    valid: false,
    errors: [
      { code: 'NODE_ORPHAN', message: '节点 pool-gone 引用的资源池不存在', resource_type: 'node', resource_id: 'pool-gone' },
      { code: 'ROUTE_MODEL', message: '路由模型名与其它路由冲突', resource_type: 'route', resource_id: 'route-9' },
    ],
    warnings: ['路由 route-7 指向的节点全部处于 DRAINING。'],
    counts: { pools: 2, nodes: 5, routes: 3, keys: 4 },
  }
}

function versionFixture(id: number, version: number, status: string, extra: Json = {}): Json {
  return {
    id, version, status, source_version: null, note: `第 ${version} 次发布`,
    published_by: 'e2e-admin', published_at: `2026-01-0${version}T08:30:00Z`,
    created_at: `2026-01-0${version}T08:30:00Z`, ...extra,
  }
}

function buildVersions(): Json[] {
  return [
    versionFixture(1, 4, 'FAILED', { source_version: 1, note: '回滚未生效' }),
    versionFixture(2, 3, 'PENDING', { source_version: 2, note: '等待实例确认' }),
    versionFixture(3, 2, 'CURRENT', { note: '调整路由权重' }),
    versionFixture(4, 1, 'SUPERSEDED', { note: '初始发布' }),
  ]
}

function appendVersion(state: MockState, fields: Json): Json {
  const next = Math.max(...state.versions.map((item) => Number(item.version))) + 1
  state.versions = state.versions.map((item) =>
    item.status === 'CURRENT' ? { ...item, status: 'SUPERSEDED' } : item,
  )
  const created = {
    ...versionFixture(state.versions.length + 1, next, 'CURRENT'),
    note: '',
    ...fields,
  }
  state.versions = [created, ...state.versions]
  return created
}

async function mockGateway(page: Page, options: MockOptions = {}): Promise<MockState> {
  const state: MockState = {
    versions: buildVersions(),
    draftAttempts: 0,
    publishes: [],
    rollbacks: [],
    reconciles: 0,
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
      return json({ actor: 'e2e-admin', roles: options.roles ?? ['publish'] })
    }
    if (pathname === '/api/gateway/config/draft' && method === 'GET') {
      state.draftAttempts += 1
      if (options.draftUnauthorized) return json({ detail: '凭据无效' }, 401)
      if (options.failFirstDraft && state.draftAttempts === 1) {
        return json({ detail: '网关控制面暂时不可用' }, 500)
      }
      return json(options.draftInvalid ? draftInvalid() : draftValid())
    }
    if (pathname === '/api/gateway/config/versions' && method === 'GET') {
      return json(state.versions)
    }
    const single = /^\/api\/gateway\/config\/versions\/(\d+)$/.exec(pathname)
    if (single && method === 'GET') {
      const version = Number(single[1])
      const row = state.versions.find((item) => item.version === version)
      if (!row) return json({ detail: `版本 v${version} 不存在` }, 404)
      if (options.detailFails) return json({ detail: '快照存储暂时不可用' }, 500)
      return json({
        ...row,
        snapshot: {
          pools: [{ id: 'pool-1', name: '默认资源池' }],
          nodes: [{ id: 'node-1', base_url: 'https://node.example' }],
          routes: [{ id: 'route-1', model: 'gpt-test' }],
          keys: [{ id: 'key-1', key_prefix: 'agw_e2e', key_digest_withheld: true }],
        },
      })
    }
    if (pathname === '/api/gateway/config/publish' && method === 'POST') {
      const payload = body()
      if (options.publishReject) return json({ detail: '草稿校验未通过，禁止发布' }, 409)
      if (options.failFirstPublish && state.publishes.length === 0) {
        state.publishes.push(payload)
        return json({ detail: '网关状态存储暂时不可用' }, 500)
      }
      state.publishes.push(payload)
      return json(appendVersion(state, { note: String(payload.note ?? '') }))
    }
    if (pathname === '/api/gateway/config/rollback' && method === 'POST') {
      const payload = body()
      state.rollbacks.push(payload)
      if (options.rollbackFails) return json({ detail: '回滚目标版本不存在' }, 409)
      return json(appendVersion(state, {
        source_version: Number(payload.version),
        note: `回滚自 v${payload.version}`,
      }))
    }
    if (pathname === '/api/gateway/config/reconcile' && method === 'POST') {
      state.reconciles += 1
      return json({ changed: options.reconcileChanged ?? 0 })
    }
    return json({ detail: `未 mock 的网关请求：${method} ${pathname}` })
  })
  return state
}

function versionRows(page: Page) {
  return page.getByTestId('gateway-versions-table').locator('.el-table__row')
}

async function gotoVersions(page: Page) {
  await page.goto('/gateway/versions')
  await expect(page.getByTestId('gateway-versions-table')).toBeVisible()
}

test.describe('API 中转 · 配置草稿与版本', () => {
  test('只读账号：无发布/回滚/对账入口，版本状态语义完整', async ({ page }) => {
    await mockGateway(page, { roles: ['view'] })
    await gotoVersions(page)

    await expect(page.getByRole('heading', { level: 3, name: '配置草稿与版本' })).toBeVisible()
    await expect(page.getByTestId('gateway-versions-reconcile')).toHaveCount(0)
    await expect(page.getByTestId('gateway-publish')).toHaveCount(0)
    await expect(page.getByTestId('gateway-publish-note')).toHaveCount(0)
    await expect(page.getByTestId('gateway-publish-locked')).toContainText('当前凭据缺少 publish 角色，只能查看。')
    await expect(page.getByTestId('gateway-draft-ok')).toBeVisible()
    await expect(page.getByTestId('gateway-draft-counts')).toContainText('启用路由')
    await expect(page.getByTestId('gateway-draft-counts')).toContainText('5')

    // 四个版本、状态标签与来源展示；只读账号没有回滚按钮，但仍可查看快照。
    await expect(page.getByTestId('gateway-version-history-card')).toContainText('共 4 个版本')
    await expect(versionRows(page)).toHaveCount(4)
    await expect(versionRows(page).nth(0)).toContainText('v4')
    await expect(versionRows(page).nth(0)).toContainText('发布失败')
    await expect(versionRows(page).nth(0)).toContainText('v1')
    await expect(versionRows(page).nth(1)).toContainText('v3')
    await expect(versionRows(page).nth(1)).toContainText('待确认')
    await expect(versionRows(page).nth(2)).toContainText('v2')
    await expect(versionRows(page).nth(2)).toContainText('当前版本')
    await expect(versionRows(page).nth(3)).toContainText('v1')
    await expect(versionRows(page).nth(3)).toContainText('历史版本')
    await expect(page.getByRole('button', { name: '回滚到 v1' })).toHaveCount(0)
    await page.getByRole('button', { name: '查看 v2 快照' }).click()
    await expect(page.getByTestId('gateway-version-detail')).toBeVisible()
  })

  test('草稿校验失败：错误表、警告与发布门禁（禁用按钮不发请求）', async ({ page }) => {
    const state = await mockGateway(page, { draftInvalid: true })
    await gotoVersions(page)

    await expect(page.getByTestId('gateway-draft-card')).toContainText('发现 2 项错误')
    const fail = page.getByTestId('gateway-draft-fail')
    await expect(fail).toContainText('校验未通过：发现 2 项错误，修复后才可发布')
    const errorRows = page.getByTestId('gateway-draft-errors').locator('.el-table__row')
    await expect(errorRows).toHaveCount(2)
    await expect(errorRows.filter({ hasText: 'NODE_ORPHAN' })).toContainText('节点 pool-gone 引用的资源池不存在')
    await expect(errorRows.filter({ hasText: 'NODE_ORPHAN' })).toContainText('node / pool-gone')
    await expect(errorRows.filter({ hasText: 'ROUTE_MODEL' })).toContainText('route / route-9')
    await expect(page.getByTestId('gateway-draft-warnings')).toContainText('路由 route-7 指向的节点全部处于 DRAINING。')
    await expect(page.getByTestId('gateway-draft-ok')).toHaveCount(0)

    // 发布门禁：草稿未通过校验时按钮禁用，不发 publish 请求。
    await expect(page.getByTestId('gateway-publish')).toBeDisabled()
    expect(state.publishes).toHaveLength(0)
  })

  test('发布成功：payload 裁剪说明、刷新后新版本置顶且原 CURRENT 转历史', async ({ page }) => {
    const state = await mockGateway(page, { reconcileChanged: 2 })
    await gotoVersions(page)

    await page.getByTestId('gateway-publish-note').fill('  E2E 发布  ')
    await page.getByTestId('gateway-publish').click()
    await expect(page.locator('.el-notification').filter({ hasText: '配置已发布' })).toBeVisible()
    expect(state.publishes).toEqual([{ note: 'E2E 发布' }])
    await expect(page.getByTestId('gateway-publish-note')).toHaveValue('')

    // 新 v5 置顶为当前版本，原 v2 转为历史版本，共 5 个版本。
    await expect(page.getByTestId('gateway-version-history-card')).toContainText('共 5 个版本')
    await expect(versionRows(page).first()).toContainText('v5')
    await expect(versionRows(page).first()).toContainText('当前版本')
    await expect(versionRows(page).first()).toContainText('E2E 发布')
    await expect(versionRows(page).nth(3)).toContainText('v2')
    await expect(versionRows(page).nth(3)).toContainText('历史版本')

    // 发布对账：payload 为空 POST，changed 文案随响应变化。
    await page.getByTestId('gateway-versions-reconcile').click()
    await expect(page.locator('.el-notification').filter({ hasText: '已收敛 2 个未决发布' })).toBeVisible()
    expect(state.reconciles).toBe(1)
  })

  test('发布失败：服务端 500 保留发布说明，重试成功', async ({ page }) => {
    const state = await mockGateway(page, { failFirstPublish: true })
    await gotoVersions(page)

    await page.getByTestId('gateway-publish-note').fill('重试发布')
    await page.getByTestId('gateway-publish').click()
    await expect(page.locator('.el-notification').filter({ hasText: '网关状态存储暂时不可用' })).toBeVisible()
    await expect(page.getByTestId('gateway-publish-note')).toHaveValue('重试发布')
    await expect(versionRows(page)).toHaveCount(4)

    await page.getByTestId('gateway-publish').click()
    await expect(page.locator('.el-notification').filter({ hasText: '配置已发布' })).toBeVisible()
    await expect(page.getByTestId('gateway-publish-note')).toHaveValue('')
    expect(state.publishes).toEqual([{ note: '重试发布' }, { note: '重试发布' }])
    await expect(versionRows(page)).toHaveCount(5)
  })

  test('回滚：取消不发请求；确认后 payload 正确、来源标注；失败保留列表', async ({ page }) => {
    const state = await mockGateway(page)
    await gotoVersions(page)

    // 当前版本行没有回滚入口。
    await expect(page.getByRole('button', { name: '回滚到 v2' })).toHaveCount(0)

    await page.getByRole('button', { name: '回滚到 v1' }).click()
    const confirm = page.getByTestId('astra-confirm-dialog')
    await expect(confirm).toContainText('确认以 v1 的内容生成新版本？进行中的请求继续使用原快照。')
    await confirm.getByRole('button', { name: '取消' }).click()
    await expect(confirm).toHaveCount(0)
    expect(state.rollbacks).toHaveLength(0)
    await expect(versionRows(page)).toHaveCount(4)

    await page.getByRole('button', { name: '回滚到 v3' }).click()
    await confirm.getByRole('button', { name: '回滚' }).click()
    await expect(page.locator('.el-notification').filter({ hasText: '已从 v3 生成新版本' })).toBeVisible()
    expect(state.rollbacks).toEqual([{ version: 3 }])
    await expect(versionRows(page).first()).toContainText('v5')
    await expect(versionRows(page).first()).toContainText('回滚自 v3')
    await expect(versionRows(page).first()).toContainText('v3')

    // 服务端 409：错误文案透出，版本列表不变。
    await mockGateway(page, { rollbackFails: true })
    await page.reload()
    await expect(versionRows(page)).toHaveCount(4)
    await page.getByRole('button', { name: '回滚到 v1' }).click()
    await confirm.getByRole('button', { name: '回滚' }).click()
    await expect(page.locator('.el-notification').filter({ hasText: '回滚目标版本不存在' })).toBeVisible()
    await expect(versionRows(page)).toHaveCount(4)
  })

  test('快照详情：脱敏 JSON 与元信息展示；加载失败关闭并提示', async ({ page }) => {
    await mockGateway(page)
    await gotoVersions(page)

    await page.getByRole('button', { name: '查看 v3 快照' }).click()
    const dialog = page.getByTestId('gateway-version-detail')
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText('版本 v3 快照')
    await expect(dialog).toContainText('已脱敏：不含节点密文与 Key 摘要')
    await expect(dialog.locator('pre')).toContainText('"model": "gpt-test"')
    await expect(dialog).toContainText('待确认')
    await expect(dialog).toContainText('e2e-admin')
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()

    await mockGateway(page, { detailFails: true })
    await page.reload()
    await page.getByRole('button', { name: '查看 v2 快照' }).click()
    await expect(page.locator('.el-notification').filter({ hasText: '快照存储暂时不可用' })).toBeVisible()
    await expect(page.getByTestId('gateway-version-detail')).toBeHidden()
  })

  test('加载失败展示错误并可重试成功；401 断开回到接入页', async ({ page }) => {
    await mockGateway(page, { failFirstDraft: true })
    await page.goto('/gateway/versions')

    const alert = page.getByTestId('gateway-versions-error')
    await expect(alert).toContainText('网关控制面暂时不可用')
    await expect(page.getByTestId('gateway-draft-card')).toContainText('暂无草稿数据')
    await alert.getByTestId('gateway-versions-retry').click()
    await expect(alert).toHaveCount(0)
    await expect(page.getByTestId('gateway-draft-ok')).toBeVisible()
    await expect(versionRows(page)).toHaveCount(4)

    await mockGateway(page, { draftUnauthorized: true })
    await page.goto('/gateway/versions')
    await expect(page.getByTestId('gateway-connect')).toBeVisible()
  })
})
