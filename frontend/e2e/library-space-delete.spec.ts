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
    knowledge_count: 0,
    subtree_knowledge_count: 3,
    children: [
      {
        id: 'dir-nonempty',
        name: '工程目录',
        description: '',
        parent_id: 'space-root',
        sort_order: 0,
        status: 'active',
        access_scope: 'public',
        knowledge_count: 2,
        subtree_knowledge_count: 3,
        children: [
          {
            id: 'dir-sub',
            name: '子目录',
            description: '',
            parent_id: 'dir-nonempty',
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
      {
        id: 'dir-empty',
        name: '空目录',
        description: '',
        parent_id: 'space-root',
        sort_order: 1,
        status: 'active',
        access_scope: 'public',
        knowledge_count: 0,
        subtree_knowledge_count: 0,
        children: [],
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
    ],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

async function mockLibraryApi(page: Page, deletes: string[]) {
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => {
    const { pathname } = new URL(route.request().url())
    const method = route.request().method()
    if (method === 'DELETE' && pathname.startsWith('/api/library/spaces/')) {
      deletes.push(pathname)
      return route.fulfill({ json: { deleted: pathname.split('/').pop() } })
    }
    if (pathname === '/api/events/stream') {
      return route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: '' })
    }
    if (pathname === '/api/library/permissions') {
      return route.fulfill({ json: { user_id: 'e2e', role: 'admin', can_manage: true, can_review: true } })
    }
    if (pathname === '/api/library/stats') {
      return route.fulfill({ json: { knowledge_pages: 0, knowledge_spaces: 1, weekly_references: 0, published_experiences: 0, candidate_experiences: 0 } })
    }
    if (pathname === '/api/library/spaces') return route.fulfill({ json: SPACES })
    if (pathname === '/api/library/usage/summary') {
      return route.fulfill({ json: { days: 7, total_references: 0, used_resources: 0, feedback_count: 0, top_knowledge: [], trend: [] } })
    }
    if (pathname === '/api/library/service/status') {
      return route.fulfill({ json: { enabled: true, healthy: true, message: '', last_synced_at: null, pending_count: 0, failed_count: 0 } })
    }
    if (pathname === '/api/library/knowledge') {
      return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 20, pages: 1 } })
    }
    return route.fulfill({ json: {} })
  })
}

async function expandRoot(page: Page) {
  await page.goto('/library')
  await expect(page.getByTestId('digital-library-page').getByRole('heading', { name: '数字图书馆', level: 2 })).toBeVisible()
  const rootRow = page.locator('.space-row').filter({ hasText: '公共知识库' })
  await rootRow.locator('.space-caret').first().click()
  await expect(page.locator('.space-row').filter({ hasText: '工程目录' })).toBeVisible()
}

async function openDeleteMenu(page: Page, name: string) {
  const row = page.locator('.space-row').filter({ hasText: name })
  await row.getByRole('button', { name: `管理目录 ${name}` }).click()
  const menu = row.locator('.space-menu')
  await expect(menu).toBeVisible()
  await menu.getByRole('button', { name: '删除' }).click()
}

test('删除非空目录只展示计数与指导，不发删除请求', async ({ page }) => {
  const deletes: string[] = []
  await mockLibraryApi(page, deletes)
  await expandRoot(page)

  await openDeleteMenu(page, '工程目录')

  const blocked = page.getByTestId('knowledge-space-delete-blocked')
  await expect(blocked).toBeVisible()
  await expect(blocked).toContainText('1 个直接子目录')
  await expect(blocked).toContainText('2 条直接知识')
  await expect(blocked).toContainText('子树共 3 条知识')
  await expect(blocked).toContainText('请先删除或移动这些子目录与知识')

  // 危险确认框不再出现，也不会发出注定被后端拒绝的删除请求
  await expect(page.getByTestId('astra-confirm-dialog')).toHaveCount(0)
  expect(deletes).toEqual([])

  await blocked.getByRole('button', { name: '知道了' }).click()
  await expect(blocked).toHaveCount(0)
})

test('删除空目录仍保留危险确认并可成功删除', async ({ page }) => {
  const deletes: string[] = []
  await mockLibraryApi(page, deletes)
  await expandRoot(page)

  await openDeleteMenu(page, '空目录')

  const confirm = page.getByTestId('astra-confirm-dialog')
  await expect(confirm).toBeVisible()
  await expect(confirm).toContainText('确认删除「空目录」？')
  await expect(page.getByTestId('knowledge-space-delete-blocked')).toHaveCount(0)

  await confirm.getByRole('button', { name: '删除目录' }).click()
  await expect(confirm).toHaveCount(0)
  expect(deletes).toEqual(['/api/library/spaces/dir-empty'])
  await expect(page.locator('.astra-toast').filter({ hasText: '目录已删除' })).toBeVisible()
})