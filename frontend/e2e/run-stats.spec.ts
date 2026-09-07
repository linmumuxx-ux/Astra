import { expect, test } from '@playwright/test'

test('统计保持全量口径，筛选重置分页且展示指标不可点击', async ({ page }) => {
  const requests: URLSearchParams[] = []
  await page.route('**/api/runs/page?*', async route => {
    const params = new URL(route.request().url()).searchParams
    requests.push(params)
    const filtered = Boolean(params.get('level') || params.get('retry'))
    await route.fulfill({ json: {
      items: [{ id: `RUN-${params.get('page')}`, task_id: 'TASK-01', task_title: '统计验收任务', employee_id: 'astra-01', status: 'COMPLETED', run_number: 1, started_at: null, finished_at: null, total_tokens: 100, tool_call_count: 2 }],
      page: Number(params.get('page')), page_size: 20, total: filtered ? 3 : 538,
      stats: { run_count: filtered ? 3 : 538, task_count: 312, completed_count: 420, failed_count: 58, retry_count: 36, waiting_input_count: 3, success_rate: 87.9, avg_duration_seconds: 365, total_tokens: 12900000 },
    } })
  })
  await page.goto('/runs')
  const stats = page.locator('.run-stats')
  await expect(stats.locator('.run-stat')).toHaveCount(4)
  await expect(stats).toContainText('538')
  await expect(stats).toContainText('6分05秒')
  await expect(stats).not.toContainText('工具调用')
  for (const label of ['平均执行时长', 'Token 消耗']) {
    await expect(stats.locator('article').filter({ hasText: label }).locator('button')).toHaveCount(0)
  }
  const before = await stats.innerText()
  await page.getByRole('button', { name: '下一页' }).click()
  await expect(page.locator('.run-pagination')).toContainText('第 2 / 27 页')
  expect(await stats.innerText()).toBe(before)
  await page.locator('.run-secondary').getByRole('button', { name: '失败 58' }).click()
  await expect(stats).toContainText('3')
  await expect(page.getByLabel('运行状态', { exact: true })).toHaveValue('FAILED')
  expect(requests.at(-1)?.get('page')).toBe('1')
  await stats.locator('.stat-value').click()
  await expect(page.getByLabel('运行状态', { exact: true })).toHaveValue('')
  await page.locator('.run-secondary').getByRole('button', { name: '重试 36' }).click()
  await expect(page.getByLabel('是否重试')).toHaveValue('true')
  await expect.poll(() => requests.at(-1)?.get('retry')).toBe('true')
  await page.screenshot({ path: '../artifacts/run-stats.png', fullPage: true })
})
