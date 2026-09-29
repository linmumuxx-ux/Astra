import { expect, test, type Page } from '@playwright/test'

const CANDIDATE_ID = 'k-review'
const PUBLISHED_FAIL_ID = 'k-pub-fail'

const SPACE = {
  id: 'space-rev', name: '审核目录', description: '', parent_id: null, sort_order: 0, status: 'active', access_scope: 'public',
  knowledge_count: 2, subtree_knowledge_count: 2, children: [],
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
}

function candidateDetail() {
  return {
    id: CANDIDATE_ID, space_id: 'space-rev', space_name: '审核目录', title: '超时重试候选经验', type: 'experience',
    summary: '候选摘要', status: 'candidate', verification_status: 'unverified', tags: ['超时', '重试'],
    source_type: 'task', source_task_id: 't-source', reference_count: 2, helpful_count: 1,
    updated_at: '2026-09-08T00:00:00Z', published_at: null, content_md: '## 问题现象\n\n原始正文内容',
    source_ref: null, source_employee_id: 'emp-1', source_employee_name: '员工甲', source_task_title: '处理超时告警', source_session_id: 'ses-1',
    experience_type: 'exception_fix', verified_at: null, verification_session_status: null,
    experience_data: { problem_symptom: '任务卡在运行中', handling: '重启 Control Worker 后重试', retry_result: '通过' },
    review_note: null, created_by: 'bot', updated_by: 'bot', published_by: null, created_at: '2026-09-07T00:00:00Z',
    sources: [{ id: 1, source_type: 'task_log', source_id: null, source_name: '执行日志', source_uri: 'https://example.invalid/log', version: 'v1', created_at: '2026-09-07T00:00:00Z' }],
    evidence: [{ id: 1, task_id: 't-source', source_session_id: 'ses-1', message_id: null, part_id: null, file_path: null, diff_hash: null, evidence_type: '异常日志', content: '50004 timeout', uri: null, result: 'success', created_at: '2026-09-07T00:00:00Z' }],
    is_favorite: false, user_helpful: false,
  }
}

const PUBLISHED_FAIL_DETAIL = {
  ...candidateDetail(), id: PUBLISHED_FAIL_ID, title: '已发布但验证失败的知识', status: 'published', verification_status: 'failed',
  source_type: 'manual', source_task_id: null, source_task_title: null, source_session_id: null, verified_at: null,
  experience_data: {}, review_note: null, sources: [], evidence: [], published_at: '2026-09-08T00:00:00Z',
}

interface MockOptions { canManage?: boolean; canReview?: boolean; failPublish?: boolean; failReject?: boolean }

async function mockLibrary(page: Page, options: MockOptions = {}) {
  const canManage = options.canManage ?? false
  const canReview = options.canReview ?? true
  const server = { candidate: candidateDetail(), failed: PUBLISHED_FAIL_DETAIL }
  const calls = { publish: [] as Record<string, unknown>[], supplement: [] as { reason: string }[], reject: [] as { reason: string }[] }
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => {
    const { pathname } = new URL(route.request().url())
    const method = route.request().method()
    const body = JSON.parse(route.request().postData() ?? '{}')
    if (pathname === '/api/events/stream') return route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: '' })
    if (pathname === '/api/library/permissions') return route.fulfill({ json: { user_id: 'e2e', role: canManage ? 'admin' : 'reviewer', can_manage: canManage, can_review: canReview } })
    if (pathname === '/api/library/stats') return route.fulfill({ json: { knowledge_pages: 1, visible_knowledge_total: 2, knowledge_spaces: 1, weekly_references: 2, published_experiences: 0, candidate_experiences: 1 } })
    if (pathname === '/api/library/spaces') return route.fulfill({ json: [SPACE] })
    if (pathname === '/api/library/usage/summary') return route.fulfill({ json: { days: 7, total_references: 2, used_resources: 1, feedback_count: 0, top_knowledge: [], trend: [] } })
    if (pathname === '/api/library/service/status') return route.fulfill({ json: { enabled: true, healthy: true, message: '', last_synced_at: null, pending_count: 0, failed_count: 0 } })
    if (pathname === '/api/library/knowledge' && method === 'GET') return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 20, pages: 1 } })
    if (pathname === `/api/library/knowledge/${CANDIDATE_ID}/usages`) return route.fulfill({ json: [{ id: 1, employee_id: 'emp-1', employee_name: '员工甲', task_id: 't-use', task_title: '引用任务', action: 'reference', used_at: '2026-09-09T00:00:00Z' }] })
    if (pathname === `/api/library/knowledge/${CANDIDATE_ID}/related-tasks`) return route.fulfill({ json: [
      { id: 't-source', title: '处理超时告警', status: 'completed', relation: 'source', last_used_at: null },
      { id: 't-use', title: '引用任务', status: 'running', relation: 'reference', last_used_at: '2026-09-09T00:00:00Z' },
    ] })
    if (pathname === `/api/library/knowledge/${CANDIDATE_ID}/publish` && method === 'POST') {
      calls.publish.push(body)
      if (options.failPublish) return route.fulfill({ status: 500, json: { detail: '发布失败：标题冲突' } })
      server.candidate = { ...server.candidate, ...body, status: 'published', published_at: '2026-09-09T01:00:00Z', updated_at: '2026-09-09T01:00:00Z' }
      return route.fulfill({ json: server.candidate })
    }
    if (pathname === `/api/library/knowledge/${CANDIDATE_ID}/request-supplement` && method === 'POST') {
      calls.supplement.push({ reason: body.reason })
      server.candidate = { ...server.candidate, review_note: body.reason, updated_at: '2026-09-09T02:00:00Z' }
      return route.fulfill({ json: server.candidate })
    }
    if (pathname === `/api/library/knowledge/${CANDIDATE_ID}/reject` && method === 'POST') {
      calls.reject.push({ reason: body.reason })
      if (options.failReject) return route.fulfill({ status: 500, json: { detail: '驳回操作失败' } })
      server.candidate = { ...server.candidate, status: 'rejected', review_note: body.reason, updated_at: '2026-09-09T03:00:00Z' }
      return route.fulfill({ json: server.candidate })
    }
    if (pathname === `/api/library/knowledge/${CANDIDATE_ID}`) return route.fulfill({ json: server.candidate })
    if (pathname === `/api/library/knowledge/${PUBLISHED_FAIL_ID}`) return route.fulfill({ json: server.failed })
    return route.fulfill({ json: {} })
  })
  return { calls, server }
}

async function openDetail(page: Page, id: string) {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/library?knowledge=${id}`)
  const dialog = page.getByTestId('knowledge-detail-dialog')
  await expect(dialog).toBeVisible()
  return dialog
}

test('详情抽屉独立展示审核状态、验证状态、元数据、来源证据与引用记录', async ({ page }) => {
  await mockLibrary(page)
  const dialog = await openDetail(page, CANDIDATE_ID)

  await expect(dialog.getByRole('heading', { name: '超时重试候选经验' })).toBeVisible()
  await expect(dialog.getByText('审核状态 · 待人工审核')).toBeVisible()
  await expect(dialog.getByText('证据状态 · 未验证')).toBeVisible()

  const descriptions = dialog.locator('.el-descriptions').first()
  await expect(descriptions.getByText('审核目录')).toBeVisible()
  await expect(descriptions.getByText('任务沉淀')).toBeVisible()
  await expect(descriptions.getByText('员工甲')).toBeVisible()
  await expect(descriptions.getByText('ses-1')).toBeVisible()

  await expect(dialog.getByText('来源证据', { exact: true })).toBeVisible()
  await expect(dialog.getByRole('link', { name: '来源任务：t-source' })).toBeVisible()
  const evidenceTable = dialog.locator('section[aria-label="候选经验来源与证据"] .el-table')
  await expect(evidenceTable.getByText('异常日志')).toBeVisible()
  await expect(evidenceTable.getByText('50004 timeout')).toBeVisible()
  await expect(dialog.getByText('执行日志')).toBeVisible()

  await expect(dialog.getByText('引用任务')).toBeVisible()
  await dialog.getByRole('button', { name: '查看关联任务' }).click()
  await expect(dialog.getByRole('link', { name: '处理超时告警' })).toBeVisible()

  await expect(dialog.locator('.markdown-body')).toContainText('原始正文内容')
})

test('已发布但验证失败：业务状态与验证状态互不覆盖', async ({ page }) => {
  await mockLibrary(page)
  const dialog = await openDetail(page, PUBLISHED_FAIL_ID)
  await expect(dialog.getByText('审核状态 · 已发布')).toBeVisible()
  await expect(dialog.getByText('证据状态 · 验证失败')).toBeVisible()
  await expect(dialog.getByText('来源证据', { exact: true })).toHaveCount(0)
  await expect(dialog.locator('.detail-footer__review')).toHaveCount(0)
})

test('权限：无审核权限隐藏审核操作，无管理权限隐藏管理编辑', async ({ page }) => {
  await mockLibrary(page, { canManage: false, canReview: false })
  const dialog = await openDetail(page, CANDIDATE_ID)
  await expect(dialog.getByRole('button', { name: '发布', exact: true })).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: '驳回', exact: true })).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: '退回补充', exact: true })).toHaveCount(0)
  await expect(dialog.getByTestId('knowledge-detail-review-edit')).toHaveCount(0)
  await expect(dialog.getByTestId('knowledge-detail-edit')).toHaveCount(0)
  await expect(dialog.getByTestId('knowledge-detail-favorite')).toBeVisible()

  await mockLibrary(page, { canManage: false, canReview: true })
  const reviewerDialog = await openDetail(page, CANDIDATE_ID)
  await expect(reviewerDialog.getByRole('button', { name: '发布', exact: true })).toBeVisible()
  await expect(reviewerDialog.getByTestId('knowledge-detail-edit')).toHaveCount(0)

  await mockLibrary(page, { canManage: true, canReview: false })
  const managerDialog = await openDetail(page, CANDIDATE_ID)
  await expect(managerDialog.getByTestId('knowledge-detail-edit')).toBeVisible()
  await expect(managerDialog.getByRole('button', { name: '发布', exact: true })).toHaveCount(0)
})

test('发布前补充编辑未保存时：切换预览与关闭均需确认，取消不丢失', async ({ page }) => {
  const mock = await mockLibrary(page)
  const dialog = await openDetail(page, CANDIDATE_ID)

  await dialog.getByTestId('knowledge-detail-review-edit').click()
  await expect(dialog.getByRole('heading', { name: '发布前编辑' })).toBeVisible()
  await expect(dialog.getByLabel('标题')).toHaveValue('超时重试候选经验')

  await dialog.getByLabel('标题').fill('编辑中的候选经验')
  await expect(dialog.getByText('有未保存修改')).toBeVisible()

  await dialog.getByRole('button', { name: '预览正文' }).click()
  const confirm = page.getByTestId('astra-confirm-dialog')
  await expect(confirm).toBeVisible()
  await expect(confirm).toContainText('放弃未保存的审核补充编辑')
  await confirm.getByRole('button', { name: '取消', exact: true }).click()
  await expect(dialog.getByLabel('标题')).toHaveValue('编辑中的候选经验')

  await dialog.getByRole('button', { name: '关闭知识详情' }).click()
  await expect(confirm).toBeVisible()
  await confirm.getByRole('button', { name: '取消', exact: true }).click()
  await expect(dialog.getByLabel('标题')).toHaveValue('编辑中的候选经验')

  await dialog.getByRole('button', { name: '预览正文' }).click()
  await expect(confirm).toBeVisible()
  await confirm.getByRole('button', { name: '放弃修改' }).click()
  await expect(dialog.getByRole('heading', { name: '发布前编辑' })).toHaveCount(0)
  await expect(dialog.locator('.markdown-body')).toContainText('原始正文内容')
  await expect(dialog.getByText('有未保存修改')).toHaveCount(0)

  await dialog.getByTestId('knowledge-detail-review-edit').click()
  await dialog.getByLabel('摘要').fill('未保存的摘要')
  await dialog.getByRole('button', { name: '关闭知识详情' }).click()
  await expect(confirm).toBeVisible()
  await confirm.getByRole('button', { name: '放弃并关闭' }).click()
  await expect(page.getByTestId('knowledge-detail-dialog')).toHaveCount(0)
  expect(mock.calls.publish).toHaveLength(0)
})

test('发布携带编辑内容成功：状态同步为已发布且不宣称同步完成', async ({ page }) => {
  const mock = await mockLibrary(page)
  const dialog = await openDetail(page, CANDIDATE_ID)

  await dialog.getByTestId('knowledge-detail-review-edit').click()
  await dialog.getByLabel('标题').fill('修订后的候选经验')
  await dialog.getByLabel('Markdown 正文').fill('## 补充正文\n\n已核对证据')
  await dialog.getByTestId('knowledge-detail-publish').click()

  await expect(page.locator('.el-notification').filter({ hasText: '候选经验已发布，数字员工现可立即检索' })).toBeVisible()
  await expect(page.locator('.el-notification').filter({ hasText: '同步完成' })).toHaveCount(0)
  expect(mock.calls.publish).toHaveLength(1)
  expect(mock.calls.publish[0]).toMatchObject({ space_id: 'space-rev', title: '修订后的候选经验', content_md: '## 补充正文\n\n已核对证据', tags: ['超时', '重试'], verification_status: 'unverified' })

  await expect(dialog.getByText('审核状态 · 已发布')).toBeVisible()
  await expect(dialog.getByRole('heading', { name: '修订后的候选经验' })).toBeVisible()
  await expect(dialog.getByText('有未保存修改')).toHaveCount(0)
  await expect(dialog.locator('.detail-footer__review')).toHaveCount(0)
})

test('发布失败：详情保持候选状态、错误可见且编辑内容不丢失', async ({ page }) => {
  const mock = await mockLibrary(page, { failPublish: true })
  const dialog = await openDetail(page, CANDIDATE_ID)

  await dialog.getByTestId('knowledge-detail-review-edit').click()
  await dialog.getByLabel('标题').fill('会冲突的标题')
  await dialog.getByTestId('knowledge-detail-publish').click()

  await expect(dialog.locator('.detail-error')).toContainText('发布失败：标题冲突')
  await expect(page.locator('.el-notification').filter({ hasText: '发布失败：标题冲突' })).toBeVisible()
  await expect(dialog.getByText('审核状态 · 待人工审核')).toBeVisible()
  await expect(dialog.getByLabel('标题')).toHaveValue('会冲突的标题')
  await expect(dialog.getByText('有未保存修改')).toBeVisible()
  expect(mock.server.candidate.status).toBe('candidate')
})

test('退回补充：理由少于两字不可提交，成功后审核意见同步更新', async ({ page }) => {
  const mock = await mockLibrary(page)
  const dialog = await openDetail(page, CANDIDATE_ID)

  await dialog.getByRole('button', { name: '退回补充', exact: true }).click()
  const panel = dialog.locator('.review-request-panel')
  await expect(panel).toBeVisible()
  const confirmButton = panel.getByRole('button', { name: '确认退回补充', exact: true })
  await expect(confirmButton).toBeDisabled()
  await panel.locator('textarea').fill('字')
  await expect(confirmButton).toBeDisabled()

  await panel.locator('textarea').fill('请补充异常场景的验证证据')
  await expect(confirmButton).toBeEnabled()
  await confirmButton.click()

  await expect(page.locator('.el-notification').filter({ hasText: '已记录退回补充要求' })).toBeVisible()
  await expect(panel).toHaveCount(0)
  expect(mock.calls.supplement).toEqual([{ reason: '请补充异常场景的验证证据' }])
  await expect(dialog.getByText('请补充异常场景的验证证据')).toBeVisible()
})
