import { expect, test, type Page } from '@playwright/test'
import type { KnowledgeListItem, KnowledgeSpace } from '../src/api/types'

const VIEWPORT = { width: 1280, height: 800 }
const TOP_SPACE_COUNT = 10
const SUBDIRS_PER_SPACE = 12
const PAGE_SIZE = 20
const ALL_TOTAL = 1000
const LONG_SPACE_NAME =
  '研发中心统一构建部署与故障回滚标准操作流程知识空间（超长目录名用于验证文本省略与操作菜单可达性）'
const NOW = '2026-01-01T00:00:00Z'

function subtreeTotal(index: number) {
  if (index === 0) return ALL_TOTAL
  if (index === 1) return 240
  return 60 + index
}

function buildSpaces(): KnowledgeSpace[] {
  return Array.from({ length: TOP_SPACE_COUNT }, (_, index) => {
    const id = `space-${index}`
    const name = index === 1 ? LONG_SPACE_NAME : `知识空间 ${index + 1}`
    const children: KnowledgeSpace[] = Array.from({ length: SUBDIRS_PER_SPACE }, (_, child) => ({
      id: `${id}-dir-${child}`,
      name: index === 1 && child === 0 ? `${LONG_SPACE_NAME} 子目录` : `目录 ${index + 1}-${child + 1}`,
      description: '',
      parent_id: id,
      sort_order: child,
      status: 'active',
      access_scope: 'public',
      knowledge_count: 5,
      subtree_knowledge_count: 5,
      children: [],
      created_at: NOW,
      updated_at: NOW,
    }))
    return {
      id,
      name,
      description: '',
      parent_id: null,
      sort_order: index,
      status: 'active',
      access_scope: 'public',
      knowledge_count: index === 0 ? 100 : 0,
      subtree_knowledge_count: subtreeTotal(index),
      children,
      created_at: NOW,
      updated_at: NOW,
    }
  })
}

const SPACES = buildSpaces()
const SPACE_NAMES = new Map(SPACES.map((space) => [space.id, space.name]))
const SPACE_TOTALS = new Map(SPACES.map((space) => [space.id, space.subtree_knowledge_count]))

function buildKnowledgeItems(spaceId: string | null, pageNumber: number): KnowledgeListItem[] {
  const spaceName = (spaceId ? SPACE_NAMES.get(spaceId) : undefined) ?? '全部知识'
  const idBase = spaceId ?? 'all'
  return Array.from({ length: PAGE_SIZE }, (_, index) => {
    const seq = (pageNumber - 1) * PAGE_SIZE + index
    return {
      id: `${idBase}-kb-${seq}`,
      space_id: spaceId ?? 'space-0',
      space_name: spaceId ? spaceName : SPACE_NAMES.get('space-0') ?? null,
      title: `${spaceName} · 知识条目 ${seq + 1}`,
      type: 'experience',
      summary: '用于验证压力回归场景下数字图书馆树与列表的布局、滚动与省略行为。',
      status: 'published',
      verification_status: 'verified',
      tags: ['e2e', 'stress'],
      source_type: 'manual',
      source_task_id: null,
      reference_count: seq,
      helpful_count: 0,
      updated_at: NOW,
      published_at: NOW,
    }
  })
}

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
          knowledge_pages: ALL_TOTAL,
          visible_knowledge_total: ALL_TOTAL,
          knowledge_spaces: TOP_SPACE_COUNT,
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
      const spaceId = searchParams.get('space_id')
      const pageNumber = Number(searchParams.get('page') ?? '1') || 1
      const total = spaceId ? SPACE_TOTALS.get(spaceId) ?? 0 : ALL_TOTAL
      return route.fulfill({
        json: {
          items: buildKnowledgeItems(spaceId, pageNumber),
          total,
          page: pageNumber,
          page_size: PAGE_SIZE,
          pages: Math.max(1, Math.ceil(total / PAGE_SIZE)),
        },
      })
    }
    return route.fulfill({ json: {} })
  })
}

test('图书馆在 1000 条知识与 120+ 目录节点压力下保持布局、滚动与省略正确', async ({ page }) => {
  await page.setViewportSize(VIEWPORT)
  await mockLibraryApi(page)
  await page.goto('/library')

  const library = page.getByTestId('digital-library-page')
  await expect(library.getByRole('heading', { name: '数字图书馆', level: 2 })).toBeVisible()

  const list = library.locator('.knowledge-list')
  const listHeader = list.locator('.knowledge-list__header')

  // 分页契约：total=1000、当前页 20 条、共 50 页；总数只在分页左侧出现一次
  await expect(listHeader.locator('h3')).toHaveText('全部知识')
  await expect(listHeader.locator('p')).toHaveCount(0)
  await expect(list.getByTestId('knowledge-total')).toHaveText(`共 ${ALL_TOTAL} 条`)
  await expect(list.locator('tbody tr')).toHaveCount(PAGE_SIZE)
  await expect(list.locator('footer')).toContainText(`共 ${ALL_TOTAL} 条`)
  await expect(list.locator('footer .el-pager li').last()).toHaveText(String(ALL_TOTAL / PAGE_SIZE))

  // 展开全部顶层空间，形成 10 + 120 = 130 个可见树节点
  const topSpaces = page.locator('.space-panel .el-tree > .el-tree-node > .el-tree-node__content')
  await expect(topSpaces).toHaveCount(TOP_SPACE_COUNT)
  for (let index = 0; index < TOP_SPACE_COUNT; index += 1) {
    await topSpaces.nth(index).locator('.el-tree-node__expand-icon').click()
  }
  const treeRows = page.locator('.space-panel .el-tree-node__content')
  await expect(treeRows).toHaveCount(TOP_SPACE_COUNT * (SUBDIRS_PER_SPACE + 1))
  expect(await treeRows.count()).toBeGreaterThanOrEqual(120)

  // 左树可独立滚动
  const treeNav = page.locator('.space-panel nav')
  const treeMetrics = await treeNav.evaluate((element) => ({
    scrollHeight: element.scrollHeight,
    clientHeight: element.clientHeight,
    overflowY: getComputedStyle(element).overflowY,
  }))
  expect(treeMetrics.overflowY).toMatch(/auto|scroll/)
  expect(treeMetrics.scrollHeight).toBeGreaterThan(treeMetrics.clientHeight)
  await treeNav.evaluate((element) => { element.scrollTop = element.scrollHeight })
  expect(await treeNav.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)

  // 右列表可独立滚动，且滚动后表头仍固定在列表顶部
  const tableWrap = list.locator('.knowledge-table-wrap')
  const bodyScroller = tableWrap.locator('.el-table__body-wrapper .el-scrollbar__wrap')
  const tableMetrics = await bodyScroller.evaluate((element) => ({
    scrollHeight: element.scrollHeight,
    clientHeight: element.clientHeight,
    overflowY: getComputedStyle(element).overflowY,
  }))
  expect(tableMetrics.overflowY).toMatch(/auto|scroll/)
  expect(tableMetrics.scrollHeight).toBeGreaterThan(tableMetrics.clientHeight)
  await bodyScroller.evaluate((element) => { element.scrollTop = element.scrollHeight })
  expect(await bodyScroller.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)

  const wrapBox = await tableWrap.boundingBox()
  const headBox = await tableWrap.locator('.el-table__header-wrapper').boundingBox()
  expect(wrapBox, '列表容器应被渲染').not.toBeNull()
  expect(headBox, '列表表头应被渲染').not.toBeNull()
  expect(headBox!.y, '表头滚动后应贴在列表顶部').toBeGreaterThanOrEqual(wrapBox!.y - 1)
  expect(headBox!.y + headBox!.height, '表头滚动后不应移出列表可视区').toBeLessThanOrEqual(wrapBox!.y + wrapBox!.height + 1)

  // 页面与工作区在 1280 宽下不产生横向溢出
  const overflow = await page.evaluate(() => {
    const pageElement = document.querySelector('.digital-library-page')
    return {
      documentScrollWidth: document.documentElement.scrollWidth,
      documentClientWidth: document.documentElement.clientWidth,
      pageScrollWidth: pageElement?.scrollWidth ?? 0,
      pageClientWidth: pageElement?.clientWidth ?? 0,
    }
  })
  expect(overflow.documentScrollWidth).toBeLessThanOrEqual(overflow.documentClientWidth + 1)
  expect(overflow.pageScrollWidth).toBeLessThanOrEqual(overflow.pageClientWidth + 1)

  // 超长目录名以省略号收尾，且操作菜单按钮仍处于可点击的最上层
  const longRow = page.locator('.space-panel .el-tree > .el-tree-node > .el-tree-node__content').filter({
    has: page.locator(`.space-node__name[title="${LONG_SPACE_NAME}"]`),
  })
  await expect(longRow).toBeVisible()
  const longLabel = longRow.locator('.space-node__name')
  const labelMetrics = await longLabel.evaluate((element) => ({
    scrollWidth: element.scrollWidth,
    clientWidth: element.clientWidth,
    textOverflow: getComputedStyle(element).textOverflow,
    whiteSpace: getComputedStyle(element).whiteSpace,
  }))
  expect(labelMetrics.textOverflow).toBe('ellipsis')
  expect(labelMetrics.whiteSpace).toBe('nowrap')
  expect(labelMetrics.scrollWidth).toBeGreaterThan(labelMetrics.clientWidth)

  await longRow.scrollIntoViewIfNeeded()
  const menuButton = longRow.getByRole('button', { name: `管理目录 ${LONG_SPACE_NAME}` })
  await expect(menuButton).toBeVisible()
  const menuHit = await menuButton.evaluate((element) => {
    const rect = element.getBoundingClientRect()
    const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)
    return hit === element || element.contains(hit)
  })
  expect(menuHit, '超长目录名不应遮挡其操作菜单按钮').toBe(true)

  // 空间切换后路径与数量同步更新
  await longRow.locator('.space-node__name').click()
  await expect(listHeader.locator('h3')).toHaveText(LONG_SPACE_NAME)
  await expect(list.getByTestId('knowledge-total')).toHaveText('共 240 条')
  await expect(list.locator('footer')).toContainText('共 240 条')
  await expect(list.locator('footer .el-pager li').last()).toHaveText('12')
  await expect(list.locator('tbody tr')).toHaveCount(PAGE_SIZE)

  const firstSpaceRow = page.locator('.space-panel .el-tree > .el-tree-node > .el-tree-node__content').filter({
    has: page.locator('.space-node__name[title="知识空间 1"]'),
  })
  await firstSpaceRow.locator('.space-node__name').click()
  await expect(listHeader.locator('h3')).toHaveText('知识空间 1')
  await expect(listHeader.locator('p')).toHaveCount(0)
  await expect(list.getByTestId('knowledge-total')).toHaveText(`共 ${ALL_TOTAL} 条`)
})