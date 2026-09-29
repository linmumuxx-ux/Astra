import { expect, test, type Page } from '@playwright/test'

const SPACE_ROOT = {
  id: 'space-root', name: '公共知识库', description: '', parent_id: null, sort_order: 0, status: 'active', access_scope: 'public',
  knowledge_count: 2, subtree_knowledge_count: 2, children: [],
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
}

const BASE_ITEM = {
  space_id: 'space-root', space_name: '公共知识库', reference_count: 1, helpful_count: 0,
  source_task_id: null, updated_at: '2026-09-08T00:00:00Z', published_at: '2026-09-07T00:00:00Z',
}

const DRAFT_ITEM = { ...BASE_ITEM, id: 'k-draft', title: '超时处理草稿', type: 'document', summary: '列表摘要', status: 'draft', verification_status: 'unverified', tags: ['列表标签'], source_type: 'manual' }
const PUBLISHED_ITEM = { ...BASE_ITEM, id: 'k-pub', title: '已发布经验', type: 'experience', summary: '列表摘要', status: 'published', verification_status: 'verified', tags: ['列表标签'], source_type: 'task' }

function detailFor(id: string) {
  const item = id === 'k-pub' ? PUBLISHED_ITEM : DRAFT_ITEM
  return {
    ...item, content_md: `## 最新正文\n\n${item.title} 的详情内容`, summary: '最新摘要', tags: ['最新', '标签'],
    source_ref: null, source_employee_id: null, source_employee_name: null, source_task_title: null, source_session_id: null,
    experience_type: null, verified_at: null, verification_session_status: null, experience_data: {}, review_note: null,
    created_by: 'e2e', updated_by: 'e2e', published_by: null, created_at: '2026-09-01T00:00:00Z', sources: [], evidence: [], is_favorite: false, user_helpful: false,
  }
}

interface MockOptions { canManage?: boolean; canReview?: boolean; updateStatus?: number; updateDetail?: string }

async function mockLibrary(page: Page, options: MockOptions = {}) {
  const canManage = options.canManage ?? true
  const canReview = options.canReview ?? true
  const updateCalls: Array<{ id: string; body: Record<string, unknown> }> = []
  const counters = { list: 0, stats: 0, detail: 0 }
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => {
    const { pathname, searchParams } = new URL(route.request().url())
    const method = route.request().method()
    if (pathname === '/api/events/stream') return route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: '' })
    if (pathname === '/api/library/permissions') return route.fulfill({ json: { user_id: 'e2e', role: canManage ? 'admin' : 'member', can_manage: canManage, can_review: canReview } })
    if (pathname === '/api/library/stats') { counters.stats += 1; return route.fulfill({ json: { knowledge_pages: 1, visible_knowledge_total: 2, knowledge_spaces: 1, weekly_references: 0, published_experiences: 1, candidate_experiences: 0 } }) }
    if (pathname === '/api/library/spaces') return route.fulfill({ json: [SPACE_ROOT] })
    if (pathname === '/api/library/usage/summary') return route.fulfill({ json: { days: 7, total_references: 0, used_resources: 0, feedback_count: 0, top_knowledge: [], trend: [] } })
    if (pathname === '/api/library/service/status') return route.fulfill({ json: { enabled: true, healthy: true, message: '', last_synced_at: null, pending_count: 0, failed_count: 0 } })
    if (pathname === '/api/library/knowledge' && method === 'GET') {
      counters.list += 1
      const status = searchParams.get('status')
      const items = status ? [] : [DRAFT_ITEM, PUBLISHED_ITEM]
      return route.fulfill({ json: { items, total: items.length, page: Number(searchParams.get('page') ?? '1'), page_size: 20, pages: 1 } })
    }
    const knowledgeMatch = pathname.match(/^\/api\/library\/knowledge\/([^/]+)$/)
    if (knowledgeMatch && method === 'GET') { counters.detail += 1; return route.fulfill({ json: detailFor(knowledgeMatch[1]) }) }
    if (knowledgeMatch && method === 'PUT') {
      const id = knowledgeMatch[1]
      const body = JSON.parse(route.request().postData() ?? '{}')
      updateCalls.push({ id, body })
      if ((options.updateStatus ?? 200) >= 400) return route.fulfill({ status: options.updateStatus!, json: { detail: options.updateDetail ?? '更新失败' } })
      return route.fulfill({ json: { ...detailFor(id), ...body } })
    }
    if (/^\/api\/library\/knowledge\/[^/]+\/usages$/.test(pathname)) return route.fulfill({ json: [] })
    return route.fulfill({ json: {} })
  })
  return { updateCalls, counters }
}

async function gotoLibrary(page: Page) {
  await page.setViewportSize({ width: 1280, height: 860 })
  await page.goto('/library')
  await expect(page.getByTestId('digital-library-page')).toBeVisible()
}

async function openEditFromList(page: Page, title: string) {
  await page.getByRole('button', { name: `编辑 ${title}`, exact: true }).click()
  const drawer = page.getByTestId('knowledge-editor-drawer')
  await expect(drawer).toBeVisible()
  return drawer
}

test('编辑入口按 can_manage 控制：管理员可见，非管理角色隐藏', async ({ page }) => {
  await mockLibrary(page)
  await gotoLibrary(page)
  await expect(page.getByRole('button', { name: '编辑 超时处理草稿', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '编辑 已发布经验', exact: true })).toBeVisible()

  await mockLibrary(page, { canManage: false, canReview: false })
  await gotoLibrary(page)
  await expect(page.getByRole('button', { name: /^编辑 / })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '新建知识', exact: true })).toHaveCount(0)
})

test('编辑草稿：加载最新详情回填全字段，无改动关闭不触发确认', async ({ page }) => {
  const mock = await mockLibrary(page)
  await gotoLibrary(page)
  const drawer = await openEditFromList(page, '超时处理草稿')

  await expect(drawer.locator('.el-drawer__title')).toHaveText('编辑知识')
  await expect(drawer.getByLabel('知识标题')).toHaveValue('超时处理草稿')
  await expect(drawer.getByLabel('Markdown 正文编辑区')).toHaveValue(/最新正文/)
  await expect(drawer.getByLabel('摘要')).toHaveValue('最新摘要')
  await expect(drawer.getByLabel('标签')).toHaveValue('最新, 标签')
  await expect(drawer.locator('.el-form-item').filter({ hasText: '所属目录' }).locator('.el-select')).toContainText('公共知识库')
  await expect(drawer.locator('.el-form-item').filter({ hasText: '知识类型' }).locator('.el-select')).toContainText('文档')
  await expect(drawer.locator('.el-form-item').filter({ hasText: '验证状态' }).locator('.el-select')).toContainText('未验证')
  expect(mock.counters.detail).toBeGreaterThanOrEqual(1)

  await expect(drawer.getByText('有未保存修改')).toHaveCount(0)
  await drawer.getByRole('button', { name: '取消', exact: true }).click()
  await expect(page.getByTestId('astra-confirm-dialog')).toHaveCount(0)
  await expect(drawer).toHaveCount(0)
  expect(mock.updateCalls).toHaveLength(0)
})

test('编辑草稿：修改后保存发 PUT，成功后关闭并刷新列表与概览', async ({ page }) => {
  const mock = await mockLibrary(page)
  await gotoLibrary(page)
  const drawer = await openEditFromList(page, '超时处理草稿')

  await drawer.getByLabel('知识标题').fill('超时处理草稿（修订）')
  await drawer.getByLabel('Markdown 正文编辑区').fill('## 修订正文\n\n补充处理步骤')
  await expect(drawer.getByText('有未保存修改')).toBeVisible()
  await drawer.getByRole('button', { name: '保存修改', exact: true }).click()

  await expect(page.locator('.el-notification').filter({ hasText: '知识修改已保存' })).toBeVisible()
  await expect(page.locator('.el-notification').filter({ hasText: '已进入同步准备' })).toHaveCount(0)
  await expect(drawer).toHaveCount(0)

  expect(mock.updateCalls).toHaveLength(1)
  expect(mock.updateCalls[0].id).toBe('k-draft')
  expect(mock.updateCalls[0].body).toEqual({
    space_id: 'space-root',
    title: '超时处理草稿（修订）',
    type: 'document',
    verification_status: 'unverified',
    tags: ['最新', '标签'],
    summary: '最新摘要',
    content_md: '## 修订正文\n\n补充处理步骤',
  })
  expect(mock.counters.list).toBeGreaterThanOrEqual(2)
  expect(mock.counters.stats).toBeGreaterThanOrEqual(2)
})

test('编辑已发布知识：回填类型与验证状态，保存通知进入同步准备而非同步完成', async ({ page }) => {
  const mock = await mockLibrary(page)
  await gotoLibrary(page)
  const drawer = await openEditFromList(page, '已发布经验')

  await expect(drawer.locator('.el-form-item').filter({ hasText: '知识类型' }).locator('.el-select')).toContainText('经验')
  await expect(drawer.locator('.el-form-item').filter({ hasText: '验证状态' }).locator('.el-select')).toContainText('已验证')
  await expect(drawer.getByText('已发布，保存后将进入同步准备')).toBeVisible()

  await drawer.getByLabel('Markdown 正文编辑区').fill('## 已发布修订\n\n更新结论')
  await drawer.getByLabel('标签').fill('超时, 重试')
  await drawer.getByRole('button', { name: '保存修改', exact: true }).click()

  const success = page.locator('.el-notification').filter({ hasText: '知识修改已保存，已进入同步准备' })
  await expect(success).toBeVisible()
  await expect(success).not.toContainText('同步完成')
  await expect(drawer).toHaveCount(0)

  expect(mock.updateCalls).toHaveLength(1)
  expect(mock.updateCalls[0].id).toBe('k-pub')
  expect(mock.updateCalls[0].body).toMatchObject({ title: '已发布经验', type: 'experience', verification_status: 'verified', tags: ['超时', '重试'] })
  expect(mock.updateCalls[0].body).not.toHaveProperty('source_type')
})

test('编辑保存失败：抽屉保持打开、错误可见且已填内容保留', async ({ page }) => {
  const mock = await mockLibrary(page, { updateStatus: 500, updateDetail: '同目录下标题已存在' })
  await gotoLibrary(page)
  const drawer = await openEditFromList(page, '超时处理草稿')

  await drawer.getByLabel('知识标题').fill('冲突标题')
  await drawer.getByRole('button', { name: '保存修改', exact: true }).click()

  const error = drawer.getByTestId('knowledge-editor-error')
  await expect(error).toBeVisible()
  await expect(error).toContainText('同目录下标题已存在')
  await expect(drawer).toBeVisible()
  await expect(drawer.getByLabel('知识标题')).toHaveValue('冲突标题')
  await expect(drawer.getByText('有未保存修改')).toBeVisible()
  await expect(page.locator('.el-notification').filter({ hasText: '知识修改已保存' })).toHaveCount(0)
  expect(mock.updateCalls).toHaveLength(1)
})

test('编辑脏关闭：取消二次确认保留修改，放弃后关闭且不发 PUT', async ({ page }) => {
  const mock = await mockLibrary(page)
  await gotoLibrary(page)
  const drawer = await openEditFromList(page, '已发布经验')

  await drawer.getByLabel('摘要').fill('改了但没保存')
  await drawer.getByRole('button', { name: '取消', exact: true }).click()
  const confirm = page.getByTestId('astra-confirm-dialog')
  await expect(confirm).toBeVisible()
  await expect(confirm).toContainText('放弃未保存的知识修改')
  await confirm.getByRole('button', { name: '取消', exact: true }).click()
  await expect(drawer).toBeVisible()
  await expect(drawer.getByLabel('摘要')).toHaveValue('改了但没保存')

  await drawer.getByRole('button', { name: '取消', exact: true }).click()
  await confirm.getByRole('button', { name: '放弃并关闭' }).click()
  await expect(drawer).toHaveCount(0)
  expect(mock.updateCalls).toHaveLength(0)
})

test('从详情打开编辑：保存后当前详情展示最新内容', async ({ page }) => {
  const mock = await mockLibrary(page)
  await gotoLibrary(page)
  await page.getByRole('button', { name: '查看 超时处理草稿', exact: true }).click()
  const detailDialog = page.getByTestId('knowledge-detail-dialog')
  await expect(detailDialog).toContainText('超时处理草稿')

  await page.getByTestId('knowledge-detail-edit').click()
  const drawer = page.getByTestId('knowledge-editor-drawer')
  await expect(drawer).toBeVisible()
  await expect(drawer.getByLabel('知识标题')).toHaveValue('超时处理草稿')

  await drawer.getByLabel('知识标题').fill('超时处理草稿（详情入口修订）')
  await drawer.getByRole('button', { name: '保存修改', exact: true }).click()
  await expect(drawer).toHaveCount(0)

  await expect(detailDialog).toContainText('超时处理草稿（详情入口修订）')
  expect(mock.updateCalls.map((call) => call.id)).toEqual(['k-draft'])
})
