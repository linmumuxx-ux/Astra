import { expect, test, type Page } from '@playwright/test'

interface Seed { id: string; title: string; status: string; verification_status: string; type: string }

const SEEDS: Seed[] = [
  { id: 'k-draft', title: '草稿知识', status: 'draft', verification_status: 'unverified', type: 'document' },
  { id: 'k-candidate', title: '候选经验知识', status: 'candidate', verification_status: 'unverified', type: 'experience' },
  { id: 'k-ok', title: '已发布已验证知识', status: 'published', verification_status: 'verified', type: 'guide' },
  { id: 'k-failed', title: '已发布验证失败知识', status: 'published', verification_status: 'failed', type: 'rule' },
  { id: 'k-rejected', title: '被驳回知识', status: 'rejected', verification_status: 'verified', type: 'example' },
  { id: 'k-archived', title: '已归档知识', status: 'archived', verification_status: 'verified', type: 'faq' },
]

const SPACES = [
  {
    id: 'space-root', name: '公共知识库', description: '', parent_id: null, sort_order: 0, status: 'active', access_scope: 'public',
    knowledge_count: 6, subtree_knowledge_count: 7, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    children: [
      { id: 'dir-child', name: '工程目录', description: '', parent_id: 'space-root', sort_order: 0, status: 'active', access_scope: 'public', knowledge_count: 1, subtree_knowledge_count: 1, children: [], created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
    ],
  },
]

function itemFor(seed: Seed) {
  return {
    id: seed.id,
    space_id: 'space-root',
    space_name: '公共知识库',
    title: seed.title,
    type: seed.type,
    summary: `${seed.title}的摘要说明`,
    status: seed.status,
    verification_status: seed.verification_status,
    tags: ['回归'],
    source_type: seed.status === 'candidate' ? 'task' : 'manual',
    source_task_id: seed.status === 'candidate' ? 'T-E2E-1' : null,
    reference_count: 3,
    helpful_count: 0,
    updated_at: '2026-09-08T00:00:00Z',
    published_at: seed.status === 'published' ? '2026-09-07T00:00:00Z' : null,
  }
}

function detailFor(seed: Seed) {
  return {
    ...itemFor(seed),
    content_md: '## 详情正文\n\n用于回归验证。',
    source_ref: null,
    source_employee_id: null,
    source_employee_name: null,
    source_task_title: null,
    source_session_id: null,
    experience_type: null,
    verified_at: null,
    verification_session_status: null,
    experience_data: {},
    review_note: null,
    created_by: 'e2e',
    updated_by: 'e2e',
    published_by: null,
    created_at: '2026-09-01T00:00:00Z',
    sources: [],
    evidence: [],
    is_favorite: false,
    user_helpful: false,
  }
}

async function mockLibrary(page: Page, permissions: { role: string; can_manage: boolean; can_review: boolean }, total = SEEDS.length) {
  const listRequests: URLSearchParams[] = []
  const batchCalls: Array<{ path: string; body: Record<string, unknown> }> = []
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => {
    const { pathname, searchParams } = new URL(route.request().url())
    const method = route.request().method()
    if (pathname === '/api/events/stream') {
      return route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: '' })
    }
    if (pathname === '/api/library/permissions') {
      return route.fulfill({ json: { user_id: 'e2e', role: permissions.role, can_manage: permissions.can_manage, can_review: permissions.can_review } })
    }
    if (pathname === '/api/library/stats') {
      return route.fulfill({ json: { knowledge_pages: 1, visible_knowledge_total: total, knowledge_spaces: 2, weekly_references: 0, published_experiences: 2, candidate_experiences: 1 } })
    }
    if (pathname === '/api/library/spaces') return route.fulfill({ json: SPACES })
    if (pathname === '/api/library/usage/summary') {
      return route.fulfill({ json: { days: 7, total_references: 0, used_resources: 0, feedback_count: 0, top_knowledge: [], trend: [] } })
    }
    if (pathname === '/api/library/service/status') {
      return route.fulfill({ json: { enabled: true, healthy: true, message: '', last_synced_at: null, pending_count: 0, failed_count: 0 } })
    }
    if (method === 'POST' && /^\/api\/library\/knowledge\/batch-(move|archive|publish|delete)$/.test(pathname)) {
      batchCalls.push({ path: pathname, body: JSON.parse(route.request().postData() ?? '{}') })
      return route.fulfill({ json: { moved: 1, archived: 1, published: 1, deleted: 1 } })
    }
    if (method === 'GET' && /^\/api\/library\/knowledge\/[^/]+\/usages$/.test(pathname)) return route.fulfill({ json: [] })
    const detailMatch = pathname.match(/^\/api\/library\/knowledge\/([^/]+)$/)
    if (detailMatch && method === 'GET') {
      const seed = SEEDS.find((item) => item.id === detailMatch[1])
      if (!seed) return route.fulfill({ status: 404, json: { detail: '未找到知识' } })
      return route.fulfill({ json: detailFor(seed) })
    }
    if (pathname === '/api/library/knowledge' && method === 'GET') {
      listRequests.push(searchParams)
      const pageSize = Number(searchParams.get('page_size') ?? '20')
      const pageNumber = Number(searchParams.get('page') ?? '1')
      return route.fulfill({
        json: { items: SEEDS.map(itemFor), total, page: pageNumber, page_size: pageSize, pages: Math.max(1, Math.ceil(total / pageSize)) },
      })
    }
    return route.fulfill({ json: {} })
  })
  return { listRequests, batchCalls }
}

function listLocator(page: Page) {
  return page.getByTestId('digital-library-page').locator('.knowledge-list')
}

function rowOf(list: ReturnType<typeof listLocator>, title: string) {
  return list.locator('.el-table__row').filter({ hasText: title })
}

test('知识列表按后端字段区分审核状态与验证状态，并按业务状态给出操作', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await mockLibrary(page, { role: 'admin', can_manage: true, can_review: true })
  await page.goto('/library')
  const list = listLocator(page)

  await expect(list.locator('.el-table__header-wrapper th')).toHaveCount(8)
  const headerText = await list.locator('.el-table__header-wrapper th').allInnerTexts()
  expect(headerText.filter(Boolean)).toEqual(['标题', '类型', '所属目录', '审核状态', '验证状态', '更新时间', '操作'])

  await expect(rowOf(list, '草稿知识').locator('td').nth(4).locator('.el-tag')).toHaveText('草稿')
  await expect(rowOf(list, '草稿知识').locator('td').nth(5).locator('.el-tag')).toHaveText('未验证')
  await expect(rowOf(list, '候选经验知识').locator('td').nth(4).locator('.el-tag')).toHaveText('待人工审核')
  await expect(rowOf(list, '已发布已验证知识').locator('td').nth(4).locator('.el-tag')).toHaveText('已发布')
  await expect(rowOf(list, '已发布已验证知识').locator('td').nth(5).locator('.el-tag')).toHaveText('已验证')
  // 审核状态与验证状态是独立维度：已发布但验证失败必须原样呈现，不得合并成单一状态。
  await expect(rowOf(list, '已发布验证失败知识').locator('td').nth(4).locator('.el-tag')).toHaveText('已发布')
  await expect(rowOf(list, '已发布验证失败知识').locator('td').nth(5).locator('.el-tag')).toHaveText('验证失败')
  await expect(rowOf(list, '被驳回知识').locator('td').nth(4).locator('.el-tag')).toHaveText('已驳回')
  await expect(rowOf(list, '已归档知识').locator('td').nth(4).locator('.el-tag')).toHaveText('已归档')
  await expect(rowOf(list, '草稿知识').locator('td').nth(2)).toHaveText('文档')
  await expect(rowOf(list, '草稿知识').locator('td').nth(3)).toHaveText('公共知识库')

  await expect(rowOf(list, '候选经验知识').getByRole('button', { name: '审核发布 候选经验知识' })).toBeVisible()
  await expect(rowOf(list, '草稿知识').getByRole('button', { name: '审核发布 草稿知识' })).toBeVisible()
  await expect(rowOf(list, '已发布已验证知识').getByRole('button', { name: /^审核发布/ })).toHaveCount(0)
  await expect(rowOf(list, '已归档知识').getByRole('button', { name: /^归档/ })).toHaveCount(0)
  await expect(rowOf(list, '已归档知识').getByRole('button', { name: '删除 已归档知识' })).toBeVisible()

  await rowOf(list, '草稿知识').locator('.knowledge-cell strong').click()
  const detail = page.getByTestId('knowledge-detail-dialog')
  await expect(detail).toBeVisible()
  await expect(detail.getByRole('heading', { name: '草稿知识' })).toBeVisible()
  await detail.getByRole('button', { name: '关闭知识详情' }).click()
  await expect(detail).toHaveCount(0)
})

test('只读身份无选择列，行操作仅查看且状态筛选仅已发布', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await mockLibrary(page, { role: 'viewer', can_manage: false, can_review: false })
  await page.goto('/library')
  const list = listLocator(page)

  await expect(list.locator('.el-table .el-checkbox')).toHaveCount(0)
  const firstRow = list.locator('.el-table__row').first()
  await expect(firstRow.getByRole('button')).toHaveCount(1)
  await expect(firstRow.getByRole('button', { name: /^查看 / })).toBeVisible()
  await expect(list.locator('.knowledge-list__batch')).toHaveCount(0)

  await list.getByTestId('knowledge-filter-status').locator('.el-select__wrapper').click()
  await expect(page.locator('.el-select-dropdown:visible .el-select-dropdown__item')).toHaveText(['已发布'])
  await page.keyboard.press('Escape')

  await firstRow.getByRole('button', { name: /^查看 / }).click()
  await expect(page.getByTestId('knowledge-detail-dialog')).toBeVisible()
})

test('批量归档、批量发布与批量移动沿用父视图既有流程', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  const mock = await mockLibrary(page, { role: 'admin', can_manage: true, can_review: true })
  await page.goto('/library')
  const list = listLocator(page)
  const batch = list.locator('.knowledge-list__batch')

  await rowOf(list, '已发布已验证知识').locator('.el-checkbox').click()
  await rowOf(list, '已发布验证失败知识').locator('.el-checkbox').click()
  await expect(batch).toContainText('已选 2 条')
  await batch.getByRole('button', { name: '归档', exact: true }).click()
  await expect(page.locator('.el-notification').filter({ hasText: '已批量归档' })).toBeVisible()
  expect(mock.batchCalls.find((call) => call.path.endsWith('batch-archive'))?.body).toEqual({ knowledge_ids: ['k-ok', 'k-failed'] })
  await expect(batch).toHaveCount(0)

  await rowOf(list, '候选经验知识').locator('.el-checkbox').click()
  await batch.getByRole('button', { name: '发布', exact: true }).click()
  const publishDialog = page.getByTestId('knowledge-publish-dialog')
  await expect(publishDialog).toBeVisible()
  await expect(publishDialog.getByRole('button', { name: '发布', exact: true })).toBeDisabled()
  await publishDialog.getByLabel('目标目录').selectOption('dir-child')
  await publishDialog.getByRole('button', { name: '发布', exact: true }).click()
  await expect(page.locator('.el-notification').filter({ hasText: '候选经验已发布' })).toBeVisible()
  expect(mock.batchCalls.find((call) => call.path.endsWith('batch-publish'))?.body).toEqual({ knowledge_ids: ['k-candidate'], space_id: 'dir-child', verification_status: 'verified' })
  await expect(publishDialog).toHaveCount(0)

  await rowOf(list, '被驳回知识').locator('.el-checkbox').click()
  await batch.getByRole('button', { name: '移动', exact: true }).click()
  const picker = page.getByTestId('directory-picker-dialog')
  await expect(picker).toBeVisible()
  await picker.locator('.el-tree-node__content').filter({ has: page.locator('strong[title="工程目录"]') }).locator('strong').click()
  await picker.getByRole('button', { name: '移动', exact: true }).click()
  await expect(page.locator('.el-notification').filter({ hasText: '知识已移动' })).toBeVisible()
  expect(mock.batchCalls.find((call) => call.path.endsWith('batch-move'))?.body).toEqual({ knowledge_ids: ['k-rejected'], space_id: 'dir-child' })
})

test('批量操作失败呈现错误反馈而非成功话术', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await mockLibrary(page, { role: 'admin', can_manage: true, can_review: true })
  await page.route('**/api/library/knowledge/batch-archive', (route) =>
    route.fulfill({ status: 500, json: { detail: '批量归档失败' } }),
  )
  await page.goto('/library')
  const list = listLocator(page)
  await rowOf(list, '草稿知识').locator('.el-checkbox').click()
  await list.locator('.knowledge-list__batch').getByRole('button', { name: '归档', exact: true }).click()
  await expect(page.locator('.el-notification').filter({ hasText: '批量归档失败' })).toBeVisible()
})

test('搜索按钮保留目录范围并重置分页，翻页请求携带 page', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  const mock = await mockLibrary(page, { role: 'admin', can_manage: true, can_review: true }, 45)
  await page.goto('/library')
  const list = listLocator(page)

  const rootRow = page.locator('.space-panel .el-tree-node__content').filter({ hasText: '公共知识库' })
  await rootRow.locator('.el-tree-node__expand-icon').click()
  await page.locator('.space-panel .el-tree-node__content').filter({ hasText: '工程目录' }).locator('.space-node__name').click()
  await expect.poll(() => mock.listRequests.at(-1)?.get('space_id')).toBe('dir-child')

  await page.getByLabel('搜索当前空间').fill('回归')
  await list.getByRole('button', { name: '搜索', exact: true }).click()
  await expect.poll(() => mock.listRequests.at(-1)?.get('keyword')).toBe('回归')
  expect(mock.listRequests.at(-1)?.get('space_id')).toBe('dir-child')
  expect(mock.listRequests.at(-1)?.get('page')).toBe('1')

  await expect(list.locator('footer')).toContainText('共 45 条')
  await list.locator('.el-pager li').filter({ hasText: '3' }).click()
  await expect.poll(() => mock.listRequests.at(-1)?.get('page')).toBe('3')
})
