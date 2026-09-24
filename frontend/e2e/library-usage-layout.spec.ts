import { expect, test, type Page } from '@playwright/test'

interface Rect { x: number; y: number; width: number; height: number }

function intersects(a: Rect, b: Rect) {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height
}

const SPACES = [
  {
    id: 'space-e2e',
    name: '公共知识库',
    description: '',
    parent_id: null,
    sort_order: 0,
    status: 'active',
    access_scope: 'public',
    knowledge_count: 0,
    subtree_knowledge_count: 0,
    children: [],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

const KNOWLEDGE_ITEMS = Array.from({ length: 20 }, (_, index) => ({
  id: `kb-${index}`,
  space_id: 'space-e2e',
  space_name: '公共知识库',
  title: `知识条目 ${index}`,
  type: 'experience',
  summary: '用于验证数字图书馆工作区滚动与知识使用分析入口布局。',
  status: 'published',
  verification_status: 'verified',
  tags: [],
  source_type: 'manual',
  source_task_id: null,
  reference_count: index,
  helpful_count: 0,
  updated_at: '2026-01-01T00:00:00Z',
  published_at: '2026-01-01T00:00:00Z',
}))

const USAGE_SUMMARY = {
  days: 7,
  total_references: 12,
  used_resources: 4,
  feedback_count: 3,
  top_knowledge: [{ resource_id: 'kb-1', title: '构建失败排查经验', reference_count: 6 }],
  trend: [
    { date: '2026-01-01', reference_count: 1 },
    { date: '2026-01-02', reference_count: 3 },
    { date: '2026-01-03', reference_count: 2 },
  ],
}

const ZERO_USAGE_SUMMARY = {
  days: 7,
  total_references: 0,
  used_resources: 0,
  feedback_count: 0,
  top_knowledge: [],
  trend: [],
}

async function mockLibraryApi(page: Page, usage: unknown = USAGE_SUMMARY) {
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => {
    const { pathname } = new URL(route.request().url())
    if (pathname === '/api/events/stream') {
      return route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: '' })
    }
    if (pathname === '/api/library/permissions') {
      return route.fulfill({ json: { user_id: 'e2e', role: 'admin', can_manage: true, can_review: true } })
    }
    if (pathname === '/api/library/stats') {
      return route.fulfill({ json: { knowledge_pages: 20, knowledge_spaces: 1, weekly_references: 12, published_experiences: 3, candidate_experiences: 1 } })
    }
    if (pathname === '/api/library/spaces') return route.fulfill({ json: SPACES })
    if (pathname === '/api/library/usage/summary') return route.fulfill({ json: usage })
    if (pathname === '/api/library/service/status') {
      return route.fulfill({ json: { enabled: true, healthy: true, message: '', last_synced_at: null, pending_count: 0, failed_count: 0 } })
    }
    if (pathname === '/api/library/knowledge') {
      return route.fulfill({ json: { items: KNOWLEDGE_ITEMS, total: KNOWLEDGE_ITEMS.length, page: 1, page_size: 20, pages: 1 } })
    }
    return route.fulfill({ json: {} })
  })
}

async function openLibrary(page: Page, usage: unknown = USAGE_SUMMARY) {
  await page.setViewportSize({ width: 1280, height: 800 })
  await mockLibraryApi(page, usage)
  await page.goto('/library')
  const library = page.getByTestId('digital-library-page')
  await expect(library.getByRole('heading', { name: '数字图书馆', level: 2 })).toBeVisible()
  return library
}

test('知识使用分析以摘要入口呈现，详情在独立分析层展开且主工作区高度稳定', async ({ page }) => {
  const library = await openLibrary(page)

  // 底部始终是可见的轻量摘要入口，而不是铺开的 KPI 与图表。
  const summary = library.locator('.usage-summary')
  await expect(summary).toBeVisible()
  await expect(summary).toContainText('12 次引用')
  await expect(summary).toContainText('4 条知识被使用')
  await expect(summary.locator('.usage-kpis')).toHaveCount(0)
  await expect(summary.locator('.usage-trend')).toHaveCount(0)

  const trigger = summary.getByRole('button', { name: '查看详情' })
  await expect(trigger).toBeVisible()
  const triggerBox = await trigger.boundingBox()
  expect(triggerBox, '摘要入口应被渲染').not.toBeNull()
  expect(triggerBox!.y + triggerBox!.height, '摘要入口应在桌面视口内可见').toBeLessThanOrEqual(800)

  // 平台助手浮钮固定在右下角，不能遮挡摘要入口。
  const launcher = page.getByTestId('assistant-launcher')
  await expect(launcher).toBeVisible()
  const launcherBox = await launcher.boundingBox()
  expect(launcherBox, '平台助手浮钮应被渲染').not.toBeNull()
  expect(intersects(launcherBox!, triggerBox!), '摘要入口不应被平台助手浮钮遮挡').toBe(false)

  const workspace = library.locator('.library-workspace')
  const collapsedBox = await workspace.boundingBox()
  expect(collapsedBox!.height, 'workspace should keep a usable height').toBeGreaterThan(200)

  // 详情在独立可关闭的分析层内展示现有指标、TOP3 与趋势。
  await trigger.click()
  const dialog = page.getByTestId('knowledge-usage-dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText('总引用次数')).toBeVisible()
  await expect(dialog.getByText('最常引用知识 TOP3')).toBeVisible()
  await expect(dialog.getByText('构建失败排查经验')).toBeVisible()
  await expect(dialog.getByRole('heading', { name: '引用趋势' })).toBeVisible()

  const openedBox = await workspace.boundingBox()
  expect(Math.abs(openedBox!.height - collapsedBox!.height), '打开详情不应改变主工作区高度').toBeLessThanOrEqual(1)

  await dialog.getByRole('button', { name: '关闭' }).click()
  await expect(dialog).toHaveCount(0)
  const closedBox = await workspace.boundingBox()
  expect(Math.abs(closedBox!.height - collapsedBox!.height), '关闭详情不应改变主工作区高度').toBeLessThanOrEqual(1)
})

test('无引用时使用分析详情显示简洁空状态而非零值卡片与空图表', async ({ page }) => {
  const library = await openLibrary(page, ZERO_USAGE_SUMMARY)

  const summary = library.locator('.usage-summary')
  await expect(summary).toBeVisible()
  await summary.getByRole('button', { name: '查看详情' }).click()

  const dialog = page.getByTestId('knowledge-usage-dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText('暂无知识引用')).toBeVisible()
  await expect(dialog.getByText('总引用次数')).toHaveCount(0)
  await expect(dialog.locator('.usage-kpis')).toHaveCount(0)
  await expect(dialog.locator('.usage-trend')).toHaveCount(0)
})