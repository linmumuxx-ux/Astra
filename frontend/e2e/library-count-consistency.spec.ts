import { expect, test, type Page } from '@playwright/test'

const SPACES = [
  {
    id: 'space-root',
    name: '公共知识库',
    description: '',
    parent_id: null,
    sort_order: 0,
    status: 'active',
    access_scope: 'public',
    knowledge_count: 2,
    subtree_knowledge_count: 3,
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

async function mockLibraryApi(page: Page) {
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => {
    const { pathname, searchParams } = new URL(route.request().url())
    if (pathname === '/api/events/stream') {
      return route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: '' })
    }
    if (pathname === '/api/library/permissions') {
      return route.fulfill({ json: { user_id: 'e2e', role: 'admin', can_manage: true, can_review: true } })
    }
    if (pathname === '/api/library/stats') {
      return route.fulfill({
        json: {
          knowledge_pages: 6,
          visible_knowledge_total: 39,
          knowledge_spaces: 1,
          weekly_references: 0,
          published_experiences: 0,
          candidate_experiences: 0,
        },
      })
    }
    if (pathname === '/api/library/spaces') return route.fulfill({ json: SPACES })
    if (pathname === '/api/library/usage/summary') {
      return route.fulfill({ json: { days: 7, total_references: 0, used_resources: 0, feedback_count: 0, top_knowledge: [], trend: [] } })
    }
    if (pathname === '/api/library/service/status') {
      return route.fulfill({ json: { enabled: true, healthy: true, message: '', last_synced_at: null, pending_count: 0, failed_count: 0 } })
    }
    if (pathname === '/api/library/knowledge') {
      // 与后端一致：目录查询包含其子目录，因此返回子树数
      const spaceId = searchParams.get('space_id')
      const total = spaceId === 'dir-child' ? 1 : spaceId ? 3 : 39
      return route.fulfill({ json: { items: [], total, page: 1, page_size: 20, pages: Math.max(1, Math.ceil(total / 20)) } })
    }
    return route.fulfill({ json: {} })
  })
}

test('左树数量与右侧同一视图的列表总数保持一致', async ({ page }) => {
  await mockLibraryApi(page)
  await page.goto('/library')
  await expect(page.getByTestId('digital-library-page').getByRole('heading', { name: '数字图书馆', level: 2 })).toBeVisible()

  // 根节点展示“当前身份可见的全部知识”，不再是仅已发布的数量
  const rootButton = page.locator('.space-all')
  await expect(rootButton.locator('strong')).toHaveText('39')
  await expect(page.locator('.knowledge-list__header p')).toHaveText('39 条知识')
  await expect(rootButton).toHaveAttribute('title', /可见的全部知识 39 条/)

  // 展开根空间，目录节点展示与查询范围一致的子树数
  const rootRow = page.locator('.space-row').filter({ hasText: '公共知识库' })
  await rootRow.locator('.space-caret').first().click()
  await expect(rootRow.locator('strong')).toHaveText('3')
  await expect(rootRow.locator('strong')).toHaveAttribute('title', /含子目录/)

  const childRow = page.locator('.space-row').filter({ hasText: '工程目录' })
  await expect(childRow).toBeVisible()
  await expect(childRow.locator('strong')).toHaveText('1')

  // 选中根空间：查询包含子目录，右侧总数与节点展示的子树数一致
  await rootRow.locator('.space-main').click()
  await expect(page.locator('.knowledge-list__header p')).toHaveText('3 条知识')

  // 选中子目录：查询范围收窄，右侧总数同步为子树内的数量
  await childRow.locator('.space-main').click()
  await expect(page.locator('.knowledge-list__header p')).toHaveText('1 条知识')
})