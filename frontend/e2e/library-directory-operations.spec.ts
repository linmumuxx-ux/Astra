import { expect, test, type Locator, type Page } from '@playwright/test'

declare module '@playwright/test' {
  interface Matchers<R> {
    toBeCurrentNode(): R
  }
}

expect.extend({
  async toBeCurrentNode(row: Locator) {
    const wrapper = row.locator('xpath=..')
    try {
      await expect(wrapper).toHaveClass(/is-current/, { timeout: 5000 })
      return { pass: true, message: () => 'expected row not to be the current node' }
    } catch {
      return { pass: false, message: () => 'expected row to be the current node' }
    }
  },
})

interface Dir {
  id: string
  name: string
  parent_id: string | null
  knowledge_count: number
  children: Dir[]
}

const NOW = '2026-01-01T00:00:00Z'
let seq = 0

function dir(id: string, name: string, parent: string | null, knowledge: number, children: Dir[] = []): Dir {
  return { id, name, parent_id: parent, knowledge_count: knowledge, children }
}

function seedTree(): Dir[] {
  seq = 0
  return [
    dir('space-a', '空间 A', null, 1, [
      dir('dir-b', '目录 B', 'space-a', 2, [dir('dir-c', '目录 C', 'dir-b', 0)]),
      dir('dir-d', '目录 D', 'space-a', 3),
    ]),
    dir('space-e', '空间 E', null, 5),
  ]
}

function toApi(node: Dir): Record<string, unknown> {
  const children = node.children.map(toApi)
  return {
    id: node.id,
    name: node.name,
    description: '',
    parent_id: node.parent_id,
    sort_order: 0,
    status: 'active',
    access_scope: 'public',
    knowledge_count: node.knowledge_count,
    subtree_knowledge_count: subtreeCount(node),
    children,
    created_at: NOW,
    updated_at: NOW,
  }
}

function findNode(nodes: Dir[], id: string): Dir | null {
  for (const node of nodes) {
    if (node.id === id) return node
    const found = findNode(node.children, id)
    if (found) return found
  }
  return null
}
function subtreeCount(node: Dir): number {
  return node.knowledge_count + node.children.reduce((total, child) => total + subtreeCount(child), 0)
}
function totalKnowledge(nodes: Dir[]): number {
  return nodes.reduce((total, node) => total + subtreeCount(node), 0)
}
function detach(nodes: Dir[], id: string): Dir | null {
  for (const [index, node] of nodes.entries()) {
    if (node.id === id) return nodes.splice(index, 1)[0]
    const found = detach(node.children, id)
    if (found) {
      found.parent_id = null
      return found
    }
  }
  return null
}

interface MockState {
  ops: Array<{ action: string; detail: Record<string, unknown> }>
  failCreate: boolean
  failRename: boolean
  deletes: string[]
}

async function mockLibraryApi(page: Page, tree: Dir[], state: MockState) {
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => {
    const { pathname, searchParams } = new URL(route.request().url())
    const method = route.request().method()
    const body = method === 'GET' ? {} : JSON.parse(route.request().postData() ?? '{}')

    if (pathname === '/api/events/stream') {
      return route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: '' })
    }
    if (method === 'GET' && pathname === '/api/library/spaces') return route.fulfill({ json: tree.map(toApi) })
    if (method === 'POST' && pathname === '/api/library/spaces') {
      state.ops.push({ action: 'create', detail: body })
      if (state.failCreate) {
        state.failCreate = false
        return route.fulfill({ status: 409, json: { detail: '名称已存在' } })
      }
      const created = dir(`new-${++seq}`, String(body.name), body.parent_id ?? null, 0)
      if (body.parent_id) {
        const parent = findNode(tree, String(body.parent_id))
        if (!parent) return route.fulfill({ status: 404, json: { detail: '父目录不存在' } })
        parent.children.push(created)
      } else {
        tree.push(created)
      }
      return route.fulfill({ status: 201, json: toApi(created) })
    }
    const spaceMatch = pathname.match(/^\/api\/library\/spaces\/([^/]+)$/)
    if (spaceMatch && method === 'PUT') {
      const node = findNode(tree, spaceMatch[1])
      if (!node) return route.fulfill({ status: 404, json: { detail: '目录不存在' } })
      state.ops.push({ action: 'rename', detail: { id: node.id, name: body.name } })
      if (state.failRename) {
        state.failRename = false
        return route.fulfill({ status: 500, json: { detail: '重命名失败' } })
      }
      node.name = String(body.name)
      return route.fulfill({ json: toApi(node) })
    }
    if (spaceMatch && method === 'DELETE') {
      const node = findNode(tree, spaceMatch[1])
      if (!node) return route.fulfill({ status: 404, json: { detail: '目录不存在' } })
      state.deletes.push(node.id)
      if (node.children.length || node.knowledge_count > 0) {
        return route.fulfill({ status: 409, json: { detail: '目录非空' } })
      }
      detach(tree, node.id)
      return route.fulfill({ json: { deleted: node.id } })
    }
    const moveMatch = pathname.match(/^\/api\/library\/spaces\/([^/]+)\/move$/)
    if (moveMatch && method === 'POST') {
      const node = findNode(tree, moveMatch[1])
      const targetId = body.target_parent_id as string | null
      if (!node) return route.fulfill({ status: 404, json: { detail: '目录不存在' } })
      state.ops.push({ action: 'move', detail: { id: node.id, target: targetId } })
      if (!targetId) {
        detach(tree, node.id)
        tree.push(node)
        return route.fulfill({ json: toApi(node) })
      }
      const target = findNode(tree, targetId)
      if (!target) return route.fulfill({ status: 404, json: { detail: '目标目录不存在' } })
      detach(tree, node.id)
      node.parent_id = targetId
      target.children.push(node)
      return route.fulfill({ json: toApi(node) })
    }
    if (pathname === '/api/library/permissions') {
      return route.fulfill({ json: { user_id: 'e2e', role: 'admin', can_manage: true, can_review: true } })
    }
    if (pathname === '/api/library/stats') {
      return route.fulfill({ json: { knowledge_pages: 0, visible_knowledge_total: totalKnowledge(tree), knowledge_spaces: 1, weekly_references: 0, published_experiences: 0, candidate_experiences: 0 } })
    }
    if (pathname === '/api/library/knowledge') {
      const spaceId = searchParams.get('space_id')
      const node = spaceId ? findNode(tree, spaceId) : null
      const total = spaceId ? (node ? subtreeCount(node) : 0) : totalKnowledge(tree)
      return route.fulfill({ json: { items: [], total, page: 1, page_size: 20, pages: 1 } })
    }
    if (pathname === '/api/library/usage/summary') {
      return route.fulfill({ json: { days: 7, total_references: 0, used_resources: 0, feedback_count: 0, top_knowledge: [], trend: [] } })
    }
    if (pathname === '/api/library/service/status') {
      return route.fulfill({ json: { enabled: true, healthy: true, message: '', last_synced_at: null, pending_count: 0, failed_count: 0 } })
    }
    return route.fulfill({ json: {} })
  })
}

async function openLibrary(page: Page, tree: Dir[], state: MockState) {
  await mockLibraryApi(page, tree, state)
  await page.goto('/library')
  await expect(page.getByTestId('digital-library-page').getByRole('heading', { name: '数字图书馆', level: 2 })).toBeVisible()
}

function treeRows(page: Page) {
  return page.locator('.space-panel .el-tree-node__content')
}
function rowFor(page: Page, name: string) {
  return treeRows(page).filter({ has: page.locator(`.space-node__name[title="${name}"]`) })
}
async function expandRow(page: Page, name: string) {
  await rowFor(page, name).locator('.el-tree-node__expand-icon').click()
}
async function menuFor(page: Page, name: string) {
  await rowFor(page, name).getByRole('button', { name: `管理目录 ${name}` }).click()
  const menu = page.locator('.el-dropdown-menu:visible')
  await expect(menu).toBeVisible()
  return menu
}
async function runMenuAction(page: Page, name: string, action: string) {
  const menu = await menuFor(page, name)
  await menu.getByText(action, { exact: true }).click()
  await expect(page.locator('.el-dropdown-menu:visible')).toHaveCount(0)
}
function picker(page: Page) {
  return page.getByTestId('directory-picker-dialog')
}
function pickerRow(page: Page, name: string) {
  return picker(page).locator('.el-tree-node__content').filter({ has: page.locator(`strong[title="${name}"]`) })
}

test('创建根空间与子目录：尊重后端响应，自动选中并保持位置', async ({ page }) => {
  const tree = seedTree()
  const state: MockState = { ops: [], failCreate: false, failRename: false, deletes: [] }
  await openLibrary(page, tree, state)
  await expect(page.locator('.space-all strong')).toHaveText('11')

  // 创建根空间
  await page.getByRole('button', { name: '新建知识空间', exact: true }).click()
  const rootInput = page.getByLabel('知识空间名称')
  await expect(rootInput).toBeVisible()
  state.failCreate = true
  await rootInput.fill('空间 X')
  await rootInput.press('Enter')
  // 后端 409：弹窗保持打开并保留输入，错误提示出现
  await expect(rootInput).toHaveValue('空间 X')
  await expect(page.locator('.el-notification').filter({ hasText: '名称已存在' })).toBeVisible()
  await rootInput.fill('空间 Y')
  await rootInput.press('Enter')
  await expect(rootInput).not.toBeVisible()
  await expect(rowFor(page, '空间 Y')).toBeVisible()
  await expect(rowFor(page, '空间 Y')).toBeCurrentNode()
  await expect(page.locator('.knowledge-list__header h3')).toHaveText('空间 Y')
  await expect(page.getByTestId('knowledge-total')).toHaveText('共 0 条')

  // 在新空间下创建子目录
  await runMenuAction(page, '空间 Y', '新建子目录')
  const childInput = page.getByLabel('子目录名称')
  await expect(page.getByRole('dialog').filter({ hasText: '在「空间 Y」下新建子目录' })).toBeVisible()
  await childInput.fill('目录 H')
  await page.getByRole('button', { name: '创建' }).click()
  await expect(childInput).not.toBeVisible()
  await expect(rowFor(page, '目录 H')).toBeVisible()
  await expect(rowFor(page, '目录 H')).toBeCurrentNode()
  await expect(page.locator('.knowledge-list__header h3')).toHaveText('空间 Y / 目录 H')

  // 计数一致性：新建目录为空，徽标为 0；总数仍为 11
  await expect(rowFor(page, '空间 Y').locator('.space-node__count')).toHaveText('0')
  await expect(rowFor(page, '目录 H').locator('.space-node__count')).toHaveText('0')
  await expect(page.locator('.space-all strong')).toHaveText('11')
  expect(state.ops.filter((op) => op.action === 'create').map((op) => op.detail)).toEqual([
    { name: '空间 X', parent_id: null },
    { name: '空间 Y', parent_id: null },
    { name: '目录 H', parent_id: expect.any(String) },
  ])
})

test('重命名保留展开与选中，失败时不关闭弹窗', async ({ page }) => {
  const tree = seedTree()
  const state: MockState = { ops: [], failCreate: false, failRename: false, deletes: [] }
  await openLibrary(page, tree, state)

  await expandRow(page, '空间 A')
  await expect(rowFor(page, '目录 C')).not.toBeVisible()
  await expandRow(page, '目录 B')
  await rowFor(page, '目录 B').locator('.space-node__name').click()
  await expect(page.getByTestId('knowledge-total')).toHaveText('共 2 条')

  await runMenuAction(page, '目录 B', '重命名')
  const nameInput = page.getByLabel('目录名称')
  await expect(nameInput).toHaveValue('目录 B')
  await nameInput.fill('目录 B2')
  await nameInput.press('Enter')
  await expect(nameInput).not.toBeVisible()

  // 展开、选中、路径与计数全部保持
  await expect(rowFor(page, '目录 B2')).toBeVisible()
  await expect(rowFor(page, '目录 B2')).toBeCurrentNode()
  await expect(rowFor(page, '目录 C')).toBeVisible()
  await expect(page.locator('.knowledge-list__header h3')).toHaveText('空间 A / 目录 B2')
  await expect(page.getByTestId('knowledge-total')).toHaveText('共 2 条')
  await expect(rowFor(page, '空间 A').locator('.space-node__count')).toHaveText('6')
  await expect(rowFor(page, '目录 B2').locator('.space-node__count')).toHaveText('2')

  // 后端失败：弹窗保持打开、保留输入，取消后数据不变
  state.failRename = true
  await runMenuAction(page, '目录 D', '重命名')
  const failInput = page.getByLabel('目录名称')
  await failInput.fill('目录 D2')
  await failInput.press('Enter')
  await expect(failInput).toHaveValue('目录 D2')
  await expect(page.locator('.el-notification').filter({ hasText: '重命名失败' })).toBeVisible()
  await page.getByRole('button', { name: '取消' }).click()
  await expect(rowFor(page, '目录 D')).toBeVisible()
  await expect(rowFor(page, '目录 D2')).toHaveCount(0)
  expect(state.ops.some((op) => op.action === 'rename' && op.detail.id === 'dir-d' && op.detail.name === '目录 D2')).toBe(true)
})

test('移动目录使用选择树：排除自身与子孙，计数按后端结果刷新', async ({ page }) => {
  const tree = seedTree()
  const state: MockState = { ops: [], failCreate: false, failRename: false, deletes: [] }
  await openLibrary(page, tree, state)

  await expandRow(page, '空间 A')
  await rowFor(page, '目录 B').locator('.space-node__name').click()
  await expect(rowFor(page, '目录 B')).toBeCurrentNode()

  // 打开移动弹窗：默认选中当前父目录；自身被禁用；候选限定在同根目录树内
  await runMenuAction(page, '目录 D', '移动到…')
  await expect(picker(page)).toBeVisible()
  await expect(pickerRow(page, '目录 D').locator('xpath=..')).toHaveAttribute('aria-disabled', 'true')
  await expect(pickerRow(page, '空间 A')).toBeCurrentNode()
  await expect(pickerRow(page, '目录 B')).toBeVisible()
  await expect(pickerRow(page, '空间 E')).toHaveCount(0)
  await expect(picker(page).getByRole('button', { name: '移动' })).toBeEnabled()

  // 点击被排除的自身不会改变选择
  await pickerRow(page, '目录 D').locator('strong').click()
  await expect(pickerRow(page, '空间 A')).toBeCurrentNode()

  // 搜索收窄：命中路径保持可见，未命中的兄弟目录隐藏
  await page.getByLabel('搜索目录').fill('目录 C')
  await expect(pickerRow(page, '目录 C')).toBeVisible()
  await expect(pickerRow(page, '目录 D')).not.toBeVisible()
  await pickerRow(page, '目录 C').locator('strong').click()
  await picker(page).getByRole('button', { name: '移动' }).click()
  await expect(picker(page)).toHaveCount(0)
  await expect(page.locator('.el-notification').filter({ hasText: '已移动「目录 D」' })).toBeVisible()

  // 左树：父链自动展开使 D 可见；选中与列表保持；计数按后端结果一致刷新
  await expect(rowFor(page, '目录 D')).toBeVisible()
  await expect(rowFor(page, '目录 B')).toBeCurrentNode()
  await expect(page.getByTestId('knowledge-total')).toHaveText('共 2 条')
  await expect(rowFor(page, '目录 B').locator('.space-node__count')).toHaveText('5')
  await expect(rowFor(page, '目录 C').locator('.space-node__count')).toHaveText('3')
  await expect(rowFor(page, '空间 A').locator('.space-node__count')).toHaveText('6')
  await expect(rowFor(page, '空间 E').locator('.space-node__count')).toHaveText('5')
  await expect(page.locator('.space-all strong')).toHaveText('11')
  expect(state.ops.filter((op) => op.action === 'move')).toEqual([
    { action: 'move', detail: { id: 'dir-d', target: 'dir-c' } },
  ])

  // 移动后回到 D：选择树再次排除自身，默认选中其新父目录
  await runMenuAction(page, '目录 D', '移动到…')
  await expect(pickerRow(page, '目录 D').locator('xpath=..')).toHaveAttribute('aria-disabled', 'true')
  await expect(pickerRow(page, '目录 C')).toBeCurrentNode()
  await picker(page).getByRole('button', { name: '取消' }).click()
  await expect(picker(page)).toHaveCount(0)
})

test('删除保护：非空目录不发请求，空目录删除后计数与选中联动', async ({ page }) => {
  const tree = seedTree()
  const state: MockState = { ops: [], failCreate: false, failRename: false, deletes: [] }
  await openLibrary(page, tree, state)

  await expandRow(page, '空间 A')
  await expandRow(page, '目录 B')

  // 非空目录（目录 B：1 个子目录、2 条直接知识）只展示保护说明，不发 DELETE
  await runMenuAction(page, '目录 B', '删除')
  const blocked = page.getByTestId('knowledge-space-delete-blocked')
  await expect(blocked).toBeVisible()
  await expect(blocked).toContainText('1 个直接子目录')
  await expect(blocked).toContainText('2 条直接知识')
  await expect(blocked).toContainText('子树共 2 条知识')
  await blocked.getByRole('button', { name: '知道了' }).click()
  expect(state.deletes).toEqual([])

  // 选中空目录 C 并删除：目录消失，计数与后端一致，选中回到全部知识
  await rowFor(page, '目录 C').locator('.space-node__name').click()
  await expect(page.getByTestId('knowledge-total')).toHaveText('共 0 条')
  await runMenuAction(page, '目录 C', '删除')
  const confirm = page.getByTestId('astra-confirm-dialog')
  await expect(confirm).toContainText('确认删除「目录 C」？')
  await confirm.getByRole('button', { name: '删除目录' }).click()
  await expect(rowFor(page, '目录 C')).toHaveCount(0)
  expect(state.deletes).toEqual(['dir-c'])
  await expect(rowFor(page, '空间 A').locator('.space-node__count')).toHaveText('6')
  await expect(rowFor(page, '目录 B').locator('.space-node__count')).toHaveText('2')
  await expect(page.locator('.space-all strong')).toHaveText('11')
  await expect(page.locator('.knowledge-list__header h3')).toHaveText('全部知识')
  await expect(page.getByTestId('knowledge-total')).toHaveText('共 11 条')
})

test('大量节点：展开、选中、重命名后保持滚动与状态，不跳动', async ({ page }) => {
  const CHILD_COUNT = 300
  const tree = seedTree()
  tree.unshift(dir('stress-root', '压力空间', null, 0, Array.from({ length: CHILD_COUNT }, (_, index) => dir(`stress-${index}`, `压力目录 ${index + 1}`, 'stress-root', 1))))
  const state: MockState = { ops: [], failCreate: false, failRename: false, deletes: [] }
  await openLibrary(page, tree, state)

  const nav = page.locator('.space-panel nav')
  await expandRow(page, '压力空间')
  await expect(treeRows(page)).toHaveCount(3 + CHILD_COUNT) // 压力空间 + 300 子目录 + 空间 A + 空间 E

  // 滚动到底部并选中最后一个子目录
  await nav.evaluate((element) => { element.scrollTop = element.scrollHeight })
  await rowFor(page, '压力目录 300').locator('.space-node__name').click()
  await expect(rowFor(page, '压力目录 300')).toBeCurrentNode()
  await expect(page.getByTestId('knowledge-total')).toHaveText('共 1 条')
  const scrollBefore = await nav.evaluate((element) => element.scrollTop)
  expect(scrollBefore).toBeGreaterThan(0)

  // 重命名后：选中、展开、滚动位置与计数保持
  await runMenuAction(page, '压力目录 300', '重命名')
  const nameInput = page.getByLabel('目录名称')
  await nameInput.fill('压力目录 改名')
  await nameInput.press('Enter')
  await expect(nameInput).not.toBeVisible()
  await expect(rowFor(page, '压力目录 改名')).toBeCurrentNode()
  await expect(rowFor(page, '压力目录 300')).toHaveCount(0)
  await expect(treeRows(page)).toHaveCount(3 + CHILD_COUNT)
  const scrollAfter = await nav.evaluate((element) => element.scrollTop)
  expect(Math.abs(scrollAfter - scrollBefore), '重命名后滚动位置不应跳动').toBeLessThanOrEqual(4)
  await expect(rowFor(page, '压力目录 改名').locator('.space-node__count')).toHaveText('1')
  await expect(rowFor(page, '压力空间').locator('.space-node__count')).toHaveText(`${CHILD_COUNT}`)
  await expect(page.locator('.space-all strong')).toHaveText(`${CHILD_COUNT + 11}`)

  // 搜索命中时自动展开父路径；清空搜索回到用户自己的展开状态，不污染
  await page.getByLabel('搜索知识空间').fill('压力目录 250')
  await expect(treeRows(page)).toHaveCount(2) // 压力空间（命中父）+ 压力目录 250
  await expect(rowFor(page, '压力目录 250')).toBeVisible()
  await expect(rowFor(page, '空间 A')).not.toBeVisible()
  await page.getByLabel('搜索知识空间').fill('')
  await expect(treeRows(page)).toHaveCount(3 + CHILD_COUNT)
  await expect(rowFor(page, '目录 B')).not.toBeVisible() // 空间 A 仍保持用户此前的折叠状态
})
