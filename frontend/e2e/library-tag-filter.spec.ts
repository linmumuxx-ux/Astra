import { expect, test, type Page } from '@playwright/test'

const PAGE1_TAG = '常见标签'
const PAGE2_TAG = '仅第二页标签'

const SPACES = [
  {
    id: 'space-root',
    name: '公共知识库',
    description: '',
    parent_id: null,
    sort_order: 0,
    status: 'active',
    access_scope: 'public',
    knowledge_count: 21,
    subtree_knowledge_count: 22,
    children: [
      {
        id: 'dir-child',
        name: '工程目录',
        description: '',
        parent_id: 'space-root',
        sort_order: 0,
        status: 'active',
        access_scope: 'public',
        knowledge_count: 1,
        subtree_knowledge_count: 1,
        children: [],
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

function knowledge(id: string, title: string, tags: string[], spaceId: string) {
  return {
    id,
    space_id: spaceId,
    space_name: spaceId === 'dir-child' ? '工程目录' : '公共知识库',
    title,
    type: 'experience',
    summary: '',
    status: 'published',
    verification_status: 'verified',
    tags,
    source_type: 'manual',
    source_task_id: null,
    reference_count: 0,
    helpful_count: 0,
    updated_at: '2026-09-01T00:00:00Z',
    published_at: '2026-09-01T00:00:00Z',
  }
}

const KNOWLEDGE = [
  ...Array.from({ length: 20 }, (_, index) =>
    knowledge(`k-page1-${index + 1}`, `第一页知识 ${String(index + 1).padStart(2, '0')}`, [PAGE1_TAG], 'space-root'),
  ),
  knowledge('k-page2', '第二页知识', [PAGE2_TAG], 'space-root'),
  knowledge('k-child', '子目录知识', [PAGE1_TAG], 'dir-child'),
]

async function mockLibraryApi(page: Page) {
  const knowledgeRequests: URLSearchParams[] = []
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => {
    const { pathname, searchParams } = new URL(route.request().url())
    if (pathname === '/api/events/stream') {
      return route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: '' })
    }
    if (pathname === '/api/library/permissions') {
      return route.fulfill({ json: { user_id: 'e2e', role: 'admin', can_manage: true, can_review: true } })
    }
    if (pathname === '/api/library/stats') {
      return route.fulfill({ json: { knowledge_pages: 2, visible_knowledge_total: 22, knowledge_spaces: 1, weekly_references: 0, published_experiences: 0, candidate_experiences: 0 } })
    }
    if (pathname === '/api/library/spaces') return route.fulfill({ json: SPACES })
    if (pathname === '/api/library/usage/summary') {
      return route.fulfill({ json: { days: 7, total_references: 0, used_resources: 0, feedback_count: 0, top_knowledge: [], trend: [] } })
    }
    if (pathname === '/api/library/service/status') {
      return route.fulfill({ json: { enabled: true, healthy: true, message: '', last_synced_at: null, pending_count: 0, failed_count: 0 } })
    }
    if (pathname === '/api/library/knowledge') {
      knowledgeRequests.push(searchParams)
      const tag = searchParams.get('tag')
      const spaceId = searchParams.get('space_id')
      const pageNumber = Number(searchParams.get('page') ?? '1')
      const pageSize = Number(searchParams.get('page_size') ?? '20')
      let items = KNOWLEDGE
      if (spaceId) items = items.filter((item) => item.space_id === spaceId)
      if (tag) items = items.filter((item) => item.tags.includes(tag))
      const total = items.length
      const start = (pageNumber - 1) * pageSize
      return route.fulfill({
        json: { items: items.slice(start, start + pageSize), total, page: pageNumber, page_size: pageSize, pages: Math.max(1, Math.ceil(total / pageSize)) },
      })
    }
    return route.fulfill({ json: {} })
  })
  return knowledgeRequests
}

async function openMoreFilters(page: Page) {
  await page.getByRole('button', { name: '更多筛选' }).click()
  await expect(page.getByLabel('知识标签')).toBeVisible()
}

test('第一页可输入并应用仅第二页存在的标签', async ({ page }) => {
  const requests = await mockLibraryApi(page)
  await page.goto('/library')
  await expect(page.locator('.knowledge-list__header p')).toHaveText('22 条知识')

  const secondPageTitle = page.getByText('第二页知识', { exact: true })
  await expect(secondPageTitle).toHaveCount(0)

  await openMoreFilters(page)

  // 建议值只来自当前页，第二页标签不在建议里
  const options = page.locator('#knowledge-tag-options option')
  await expect(options).toHaveCount(1)
  await expect(options.first()).toHaveAttribute('value', PAGE1_TAG)

  const input = page.getByLabel('知识标签')
  const beforeTyping = requests.length
  await input.pressSequentially(PAGE2_TAG)
  await expect(input).toHaveValue(PAGE2_TAG)
  // 逐字输入不应触发 API
  expect(requests.length).toBe(beforeTyping)

  await input.press('Enter')
  await expect.poll(() => requests.length).toBeGreaterThan(beforeTyping)
  expect(requests.at(-1)?.get('tag')).toBe(PAGE2_TAG)
  await expect(secondPageTitle).toBeVisible()
  await expect(page.getByText('第一页知识 01', { exact: true })).toHaveCount(0)
})

test('清除标签筛选后保留当前空间', async ({ page }) => {
  const requests = await mockLibraryApi(page)
  await page.goto('/library')

  const rootRow = page.locator('.space-row').filter({ hasText: '公共知识库' })
  await rootRow.locator('.space-caret').first().click()
  const childRow = page.locator('.space-row').filter({ hasText: '工程目录' })
  await childRow.locator('.space-main').click()
  await expect(page.locator('.knowledge-list__header h3')).toHaveText('公共知识库 / 工程目录')

  await openMoreFilters(page)
  await page.getByLabel('知识标签').fill('子目录')
  await page.getByLabel('应用标签筛选').click()
  await expect.poll(() => requests.at(-1)?.get('tag')).toBe('子目录')
  expect(requests.at(-1)?.get('space_id')).toBe('dir-child')
  await expect(page.getByText('子目录知识', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '清除筛选' }).click()
  await expect.poll(() => requests.at(-1)?.get('tag')).toBeNull()
  expect(requests.at(-1)?.get('space_id')).toBe('dir-child')
  await expect(page.locator('.knowledge-list__header h3')).toHaveText('公共知识库 / 工程目录')
  await expect(page.getByLabel('知识标签')).toHaveValue('')
  await expect(page.getByText('子目录知识', { exact: true })).toBeVisible()
})