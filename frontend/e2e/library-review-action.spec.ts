import { expect, test, type Page } from '@playwright/test'

const KNOWLEDGE_ID = 'review-action-long-md'

const LONG_MARKDOWN = Array.from({ length: 45 }, (_, index) =>
  [
    `## 章节 ${index + 1}`,
    '',
    `这是用于撑高知识详情滚动区域的正文段落 ${index + 1}，需要足够多的文字，才能保证审核操作表单在打开时原本位于滚动视口之外。`,
    '',
    `- 要点 ${index + 1}-A`,
    `- 要点 ${index + 1}-B`,
  ].join('\n'),
).join('\n\n')

const SPACES = [
  {
    id: 'space-e2e',
    name: '公共知识库',
    description: '',
    parent_id: null,
    sort_order: 0,
    status: 'active',
    access_scope: 'public',
    knowledge_count: 1,
    subtree_knowledge_count: 1,
    children: [],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

const DETAIL = {
  id: KNOWLEDGE_ID,
  space_id: 'space-e2e',
  space_name: '公共知识库',
  title: '长正文候选经验审核回归',
  type: 'experience',
  summary: '用于验证长 Markdown 正文下审核操作交互的回归用例。',
  status: 'candidate',
  verification_status: 'unverified',
  tags: ['回归'],
  source_type: 'task',
  source_task_id: null,
  reference_count: 0,
  helpful_count: 0,
  updated_at: '2026-09-08T00:00:00Z',
  published_at: null,
  content_md: LONG_MARKDOWN,
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
  created_at: '2026-09-08T00:00:00Z',
  sources: [],
  evidence: [],
  is_favorite: false,
  user_helpful: false,
}

async function mockLibraryApi(page: Page) {
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => {
    const { pathname } = new URL(route.request().url())
    if (pathname === '/api/events/stream') {
      return route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: '' })
    }
    if (pathname === '/api/library/permissions') {
      return route.fulfill({ json: { user_id: 'e2e', role: 'reviewer', can_manage: false, can_review: true } })
    }
    if (pathname === '/api/library/stats') {
      return route.fulfill({ json: { knowledge_pages: 1, visible_knowledge_total: 1, knowledge_spaces: 1, weekly_references: 0, published_experiences: 0, candidate_experiences: 1 } })
    }
    if (pathname === '/api/library/spaces') return route.fulfill({ json: SPACES })
    if (pathname === '/api/library/usage/summary') {
      return route.fulfill({ json: { days: 7, total_references: 0, used_resources: 0, feedback_count: 0, top_knowledge: [], trend: [] } })
    }
    if (pathname === '/api/library/service/status') {
      return route.fulfill({ json: { enabled: true, healthy: true, message: '', last_synced_at: null, pending_count: 0, failed_count: 0 } })
    }
    if (pathname === `/api/library/knowledge/${KNOWLEDGE_ID}/usages`) return route.fulfill({ json: [] })
    if (pathname === `/api/library/knowledge/${KNOWLEDGE_ID}`) return route.fulfill({ json: DETAIL })
    if (pathname === '/api/library/knowledge') {
      return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 20, pages: 1 } })
    }
    return route.fulfill({ json: {} })
  })
}

async function openLongDetail(page: Page) {
  await page.setViewportSize({ width: 1280, height: 800 })
  await mockLibraryApi(page)
  await page.goto(`/library?knowledge=${KNOWLEDGE_ID}`)
  const dialog = page.getByTestId('knowledge-detail-dialog')
  await expect(dialog).toBeVisible()
  const scroll = dialog.locator('.detail-scroll')
  await expect.poll(() => scroll.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true)
  return { dialog, scroll }
}

async function expectInsideScrollViewport(scroll: ReturnType<Page['locator']>, target: ReturnType<Page['locator']>) {
  const container = await scroll.boundingBox()
  const box = await target.boundingBox()
  expect(container, '滚动容器应有可见区域').not.toBeNull()
  expect(box, '目标输入区域应已渲染').not.toBeNull()
  expect(box!.y, '输入区域顶部应进入滚动容器可视范围').toBeGreaterThanOrEqual(container!.y - 1)
  expect(box!.y + box!.height, '输入区域底部应进入滚动容器可视范围').toBeLessThanOrEqual(container!.y + container!.height + 1)
}

test('长正文候选经验点击审核按钮后表单进入滚动视口并获得焦点', async ({ page }) => {
  const { dialog, scroll } = await openLongDetail(page)

  await dialog.getByRole('button', { name: '退回补充', exact: true }).click()

  const panel = dialog.locator('.review-request-panel')
  await expect(panel).toBeVisible()
  const textarea = panel.locator('textarea')
  await expect(textarea).toBeFocused()
  await expectInsideScrollViewport(scroll, textarea)

  await textarea.fill('请补充异常场景下的验证证据')
  await expect(textarea).toHaveValue('请补充异常场景下的验证证据')
})

test('切换审核操作与取消后保留已填写内容', async ({ page }) => {
  const { dialog } = await openLongDetail(page)

  await dialog.getByRole('button', { name: '驳回', exact: true }).click()
  const textarea = dialog.locator('.review-request-panel textarea')
  await textarea.fill('证据不足，需要补充来源会话')
  await expect(textarea).toBeFocused()

  await dialog.getByRole('button', { name: '退回补充', exact: true }).click()
  await expect(textarea).toHaveValue('证据不足，需要补充来源会话')

  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  await expect(dialog.locator('.review-request-panel')).toHaveCount(0)

  await dialog.getByRole('button', { name: '退回补充', exact: true }).click()
  await expect(dialog.locator('.review-request-panel textarea')).toHaveValue('证据不足，需要补充来源会话')
})

test('提交失败后重新打开仍保留已填写内容', async ({ page }) => {
  const { dialog } = await openLongDetail(page)
  await page.route(`**/api/library/knowledge/${KNOWLEDGE_ID}/reject`, (route) =>
    route.fulfill({ status: 500, json: { detail: '驳回操作失败' } }),
  )

  await dialog.getByRole('button', { name: '驳回', exact: true }).click()
  const textarea = dialog.locator('.review-request-panel textarea')
  await textarea.fill('证据不足，需要补充来源会话')
  await dialog.getByRole('button', { name: '确认驳回', exact: true }).click()

  await expect(dialog.locator('.detail-error')).toContainText('驳回操作失败')
  await dialog.getByRole('button', { name: '驳回', exact: true }).click()
  await expect(dialog.locator('.review-request-panel textarea')).toHaveValue('证据不足，需要补充来源会话')
})

test('提交失败时显示错误 Toast', async ({ page }) => {
  const { dialog } = await openLongDetail(page)
  await page.route(`**/api/library/knowledge/${KNOWLEDGE_ID}/reject`, (route) =>
    route.fulfill({ status: 500, json: { detail: '驳回操作失败' } }),
  )

  await dialog.getByRole('button', { name: '驳回', exact: true }).click()
  await dialog.locator('.review-request-panel textarea').fill('证据不足，需要补充来源会话')
  await dialog.getByRole('button', { name: '确认驳回', exact: true }).click()

  await expect(page.locator('.el-notification:has(.el-notification--error)')).toContainText('驳回操作失败')
})