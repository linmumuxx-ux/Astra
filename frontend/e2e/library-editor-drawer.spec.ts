import { expect, test, type Page } from '@playwright/test'

const SPACE_ROOT = {
  id: 'space-root', name: '公共知识库', description: '', parent_id: null, sort_order: 0, status: 'active', access_scope: 'public',
  knowledge_count: 1, subtree_knowledge_count: 2,
  children: [{ id: 'dir-child', name: '工程目录', description: '', parent_id: 'space-root', sort_order: 0, status: 'active', access_scope: 'public', knowledge_count: 0, subtree_knowledge_count: 0, children: [], created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }],
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
}

const LIST_ITEM = {
  id: 'k-existing', space_id: 'space-root', space_name: '公共知识库', title: '已有知识', type: 'document', summary: '摘要',
  status: 'published', verification_status: 'verified', tags: [], source_type: 'manual', source_task_id: null,
  reference_count: 0, helpful_count: 0, updated_at: '2026-09-08T00:00:00Z', published_at: '2026-09-07T00:00:00Z',
}

function detailFor(id: string, content = '## 详情\n\n正文') {
  return {
    ...LIST_ITEM, id, content_md: content, source_ref: null, source_employee_id: null, source_employee_name: null,
    source_task_title: null, source_session_id: null, experience_type: null, verified_at: null,
    verification_session_status: null, experience_data: {}, review_note: null, created_by: 'e2e', updated_by: 'e2e',
    published_by: null, created_at: '2026-09-01T00:00:00Z', sources: [], evidence: [], is_favorite: false, user_helpful: false,
  }
}

interface MockOptions { createStatus?: number; createDetail?: string }

async function mockLibrary(page: Page, options: MockOptions = {}) {
  const createCalls: Array<Record<string, unknown>> = []
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => {
    const { pathname, searchParams } = new URL(route.request().url())
    const method = route.request().method()
    if (pathname === '/api/events/stream') return route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: '' })
    if (pathname === '/api/library/permissions') return route.fulfill({ json: { user_id: 'e2e', role: 'admin', can_manage: true, can_review: true } })
    if (pathname === '/api/library/stats') return route.fulfill({ json: { knowledge_pages: 1, visible_knowledge_total: 2, knowledge_spaces: 2, weekly_references: 0, published_experiences: 1, candidate_experiences: 0 } })
    if (pathname === '/api/library/spaces') return route.fulfill({ json: [SPACE_ROOT] })
    if (pathname === '/api/library/usage/summary') return route.fulfill({ json: { days: 7, total_references: 0, used_resources: 0, feedback_count: 0, top_knowledge: [], trend: [] } })
    if (pathname === '/api/library/service/status') return route.fulfill({ json: { enabled: true, healthy: true, message: '', last_synced_at: null, pending_count: 0, failed_count: 0 } })
    if (method === 'POST' && pathname === '/api/library/knowledge') {
      createCalls.push(JSON.parse(route.request().postData() ?? '{}'))
      const status = options.createStatus ?? 200
      if (status >= 400) return route.fulfill({ status, json: { detail: options.createDetail ?? '知识保存失败' } })
      return route.fulfill({ status: 201, json: detailFor('k-new') })
    }
    if (method === 'GET' && /^\/api\/library\/knowledge\/[^/]+\/usages$/.test(pathname)) return route.fulfill({ json: [] })
    const detailMatch = pathname.match(/^\/api\/library\/knowledge\/([^/]+)$/)
    if (detailMatch && method === 'GET') return route.fulfill({ json: detailFor(detailMatch[1]) })
    if (pathname === '/api/library/knowledge' && method === 'GET') {
      return route.fulfill({ json: { items: [LIST_ITEM], total: 1, page: Number(searchParams.get('page') ?? '1'), page_size: 20, pages: 1 } })
    }
    return route.fulfill({ json: {} })
  })
  return { createCalls }
}

async function openEditor(page: Page) {
  await page.setViewportSize({ width: 1280, height: 860 })
  await page.goto('/library')
  const header = page.getByTestId('library-header')
  await header.getByRole('button', { name: '新建知识', exact: true }).click()
  const drawer = page.getByTestId('knowledge-editor-drawer')
  await expect(drawer).toBeVisible()
  return drawer
}

test('抽屉为原生 ElDrawer 单列结构，默认目录已选中且每属性一行', async ({ page }) => {
  await mockLibrary(page)
  const drawer = await openEditor(page)
  await expect(drawer.locator('.el-drawer__title')).toHaveText('新建知识')
  await expect(drawer.locator('.el-form-item')).toHaveCount(7)
  for (const label of ['知识标题', '所属目录', '知识类型', '验证状态', '标签', '摘要', 'Markdown 正文']) {
    await expect(drawer.locator('.el-form-item__label').filter({ hasText: label })).toBeVisible()
  }
  await expect(drawer.locator('.el-form-item').filter({ hasText: '所属目录' }).locator('.el-select')).toContainText('公共知识库')
  await expect(drawer.getByRole('button', { name: '取消', exact: true })).toBeVisible()
  await expect(drawer.getByRole('button', { name: '保存草稿', exact: true })).toBeVisible()
})

test('创建知识保存草稿：按 payload 提交并携带 manual 来源，成功后关闭并提示', async ({ page }) => {
  const mock = await mockLibrary(page)
  const drawer = await openEditor(page)
  await drawer.getByLabel('知识标题').fill('接口超时复盘')
  await drawer.getByLabel('标签').fill('超时, 重试 ，网络')
  await drawer.getByLabel('摘要').fill('一次典型超时问题的处理记录')
  await drawer.getByLabel('Markdown 正文编辑区').fill('## 现象\n\n50004 超时')
  await drawer.getByRole('button', { name: '保存草稿', exact: true }).click()

  await expect(page.locator('.el-notification').filter({ hasText: '知识草稿已保存' })).toBeVisible()
  await expect(drawer).toHaveCount(0)
  expect(mock.createCalls).toHaveLength(1)
  expect(mock.createCalls[0]).toMatchObject({
    space_id: 'space-root',
    title: '接口超时复盘',
    type: 'document',
    verification_status: 'unverified',
    summary: '一次典型超时问题的处理记录',
    content_md: '## 现象\n\n50004 超时',
    tags: ['超时', '重试', '网络'],
    source_type: 'manual',
  })
})

test('校验：标题与正文为空时阻止保存并给出字段级提示', async ({ page }) => {
  const mock = await mockLibrary(page)
  const drawer = await openEditor(page)
  await drawer.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(drawer.getByText('请输入知识标题')).toBeVisible()
  await expect(drawer.getByText('请输入 Markdown 正文')).toBeVisible()
  expect(mock.createCalls).toHaveLength(0)
  await expect(drawer).toBeVisible()

  await drawer.getByLabel('知识标题').fill('仅标题')
  await drawer.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(drawer.getByText('请输入 Markdown 正文')).toBeVisible()
  await expect(drawer.getByText('请输入知识标题')).toHaveCount(0)
  expect(mock.createCalls).toHaveLength(0)
})

test('Markdown 预览渲染标题并过滤脚本，切回编辑保留内容', async ({ page }) => {
  await mockLibrary(page)
  const drawer = await openEditor(page)
  await drawer.getByLabel('Markdown 正文编辑区').fill('## 问题现象\n\n返回 50004。\n\n<script>window.__xss=1</script>')
  await drawer.locator('label.el-radio-button', { hasText: '预览' }).click()
  const preview = drawer.locator('.markdown-editor__preview')
  await expect(preview).toBeVisible()
  await expect(preview.locator('h2')).toHaveText('问题现象')
  await expect(preview.locator('script')).toHaveCount(0)
  expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined()
  await drawer.locator('label.el-radio-button', { hasText: '编辑' }).click()
  await expect(drawer.getByLabel('Markdown 正文编辑区')).toHaveValue(/问题现象/)
})

test('导入 .md：填充正文并在标题为空时用文件名补全', async ({ page }) => {
  await mockLibrary(page)
  const drawer = await openEditor(page)
  await drawer.getByRole('button', { name: '导入 .md' }).click()
  await drawer.locator('.markdown-editor__file').setInputFiles({ name: '故障复盘.md', mimeType: 'text/markdown', buffer: Buffer.from('# 故障复盘\n\n导入的正文') })
  await expect(drawer.getByLabel('Markdown 正文编辑区')).toHaveValue(/导入的正文/)
  await expect(drawer.getByLabel('知识标题')).toHaveValue('故障复盘')
})

test('未保存修改关闭需二次确认：取消保留草稿，放弃才关闭', async ({ page }) => {
  const mock = await mockLibrary(page)
  const drawer = await openEditor(page)
  await drawer.getByLabel('知识标题').fill('待放弃的草稿')
  await expect(drawer.getByText('有未保存修改')).toBeVisible()

  await drawer.getByRole('button', { name: '取消', exact: true }).click()
  const confirm = page.getByTestId('astra-confirm-dialog')
  await expect(confirm).toBeVisible()
  await expect(confirm).toContainText('放弃未保存的知识草稿')
  await confirm.getByRole('button', { name: '取消', exact: true }).click()
  await expect(confirm).toHaveCount(0)
  await expect(drawer).toBeVisible()
  await expect(drawer.getByLabel('知识标题')).toHaveValue('待放弃的草稿')

  await drawer.getByRole('button', { name: '取消', exact: true }).click()
  await confirm.getByRole('button', { name: '放弃并关闭' }).click()
  await expect(drawer).toHaveCount(0)
  expect(mock.createCalls).toHaveLength(0)
})

test('保存失败反馈：接口 500 时抽屉保持打开并展示错误', async ({ page }) => {
  await mockLibrary(page, { createStatus: 500, createDetail: '同目录下标题已存在' })
  const drawer = await openEditor(page)
  await drawer.getByLabel('知识标题').fill('重复标题')
  await drawer.getByLabel('Markdown 正文编辑区').fill('## 正文')
  await drawer.getByRole('button', { name: '保存草稿', exact: true }).click()

  const error = drawer.getByTestId('knowledge-editor-error')
  await expect(error).toBeVisible()
  await expect(error).toContainText('同目录下标题已存在')
  await expect(drawer).toBeVisible()
  await expect(page.locator('.el-notification').filter({ hasText: '知识草稿已保存' })).toHaveCount(0)
})

test('顶部导入知识走编辑器并标记 import 来源', async ({ page }) => {
  const mock = await mockLibrary(page)
  await page.setViewportSize({ width: 1280, height: 860 })
  await page.goto('/library')
  const header = page.getByTestId('library-header')
  await page.getByTestId('library-import-input').setInputFiles({ name: '运维手册.md', mimeType: 'text/markdown', buffer: Buffer.from('## 手册\n\n导入内容') })
  const drawer = page.getByTestId('knowledge-editor-drawer')
  await expect(drawer).toBeVisible()
  await expect(drawer.getByLabel('知识标题')).toHaveValue('运维手册')
  await expect(drawer.getByLabel('Markdown 正文编辑区')).toHaveValue(/导入内容/)
  await drawer.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(drawer).toHaveCount(0)
  expect(mock.createCalls.at(-1)).toMatchObject({ source_type: 'import', title: '运维手册' })
})
