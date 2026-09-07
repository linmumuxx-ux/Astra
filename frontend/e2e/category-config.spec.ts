import { expect, test } from '@playwright/test'

test('分类初始化、展开、还原不误报；双提示词保存后刷新保持一致', async ({ page, request }) => {
  const response = await request.post('/api/task-categories', { data: { name: `提示词回归-${Date.now()}`, task_prompt: null, question_prompt: null } })
  expect(response.ok()).toBeTruthy()
  const category = await response.json()
  await page.route('**/api/task-categories?include_disabled=true', async route => {
    await new Promise(resolve => setTimeout(resolve, 500))
    await route.continue()
  })
  await page.goto('/settings?tab=categories')
  await expect(page.getByText('正在加载任务分类…')).toBeVisible()
  await expect(page.getByRole('button', { name: '保存分类', exact: true })).toHaveCount(0)
  const row = page.locator(`[data-category-id="${category.id}"]`)
  await expect(row).toBeVisible()
  await expect(page.getByRole('button', { name: '保存分类', exact: true })).toHaveCount(0)
  await row.getByRole('button', { name: '编辑', exact: true }).click()
  const task = page.getByLabel('任务提示词', { exact: true })
  const question = page.getByLabel('问题提示词', { exact: true })
  await expect(task).toBeEditable()
  await expect(question).toBeEditable()
  await expect(page.getByRole('button', { name: '保存分类', exact: true })).toHaveCount(0)
  await task.fill('临时修改')
  await expect(page.getByRole('button', { name: '保存分类', exact: true })).toBeVisible()
  await task.fill('')
  await expect(page.getByRole('button', { name: '保存分类', exact: true })).toHaveCount(0)
  const taskText = '  Task 123\n任务提示词 {{input}}  '
  const questionText = '问题提示词\nQuestion?'
  await task.fill(taskText)
  await question.fill(questionText)
  await page.getByRole('button', { name: '保存分类', exact: true }).click()
  await expect(page.getByRole('status')).toHaveText('任务分类已保存。')
  await expect(page.getByRole('button', { name: '保存分类', exact: true })).toHaveCount(0)
  await page.reload()
  await expect(page).toHaveURL(/tab=categories/)
  await row.getByRole('button', { name: '编辑', exact: true }).click()
  await expect(task).toHaveValue(taskText)
  await expect(question).toHaveValue(questionText)
  await page.screenshot({ path: '../artifacts/category-config/saved-prompts.png', fullPage: true })
  await expect(page.getByRole('button', { name: '保存分类', exact: true })).toHaveCount(0)
  await task.fill('')
  await question.fill('')
  await page.getByRole('button', { name: '保存分类', exact: true }).click()
  await expect(page.getByRole('status')).toHaveText('任务分类已保存。')
  await page.reload()
  await row.getByRole('button', { name: '编辑', exact: true }).click()
  await expect(task).toHaveValue('')
  await expect(question).toHaveValue('')
})

test('初次加载失败保持非修改状态，重试成功', async ({ page }) => {
  let failed = false
  await page.route('**/api/task-categories?include_disabled=true', async route => {
    if (!failed) { failed = true; await route.fulfill({ status: 500, json: { detail: '分类加载失败测试' } }) }
    else await route.continue()
  })
  await page.goto('/settings?tab=categories')
  await expect(page.getByRole('button', { name: '重新加载' })).toBeVisible()
  await expect(page.getByRole('button', { name: '保存分类', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '重新加载' }).click()
  await expect(page.locator('[data-category-id]').first()).toBeVisible()
  await expect(page.getByRole('button', { name: '保存分类', exact: true })).toHaveCount(0)
})

test('部分保存失败后重试不重复创建，失败内容保留', async ({ page, request }) => {
  await page.goto('/settings?tab=categories')
  await expect(page.locator('[data-category-id]').first()).toBeVisible()
  const prefix = `重试-${Date.now()}`
  for (const suffix of ['A', 'B']) {
    await page.getByRole('button', { name: '新增分类', exact: true }).click()
    await page.getByRole('textbox', { name: '分类名称', exact: true }).last().fill(`${prefix}-${suffix}`)
  }
  let attempts = 0
  await page.route('**/api/task-categories', async route => {
    if (route.request().method() === 'POST' && ++attempts === 2) {
      await route.fulfill({ status: 500, json: { detail: '第二行保存失败测试' } })
    } else await route.continue()
  })
  await page.getByRole('button', { name: '保存分类', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('第二行保存失败测试')
  await expect(page.getByRole('textbox', { name: '分类名称', exact: true }).last()).toHaveValue(`${prefix}-B`)
  await page.getByRole('button', { name: '保存分类', exact: true }).click()
  await expect(page.getByRole('status')).toHaveText('任务分类已保存。')
  expect(attempts).toBe(3)
  const rows = await (await request.get('/api/task-categories?include_disabled=true')).json()
  expect(rows.filter((row: { name: string }) => row.name.startsWith(prefix))).toHaveLength(2)
})
