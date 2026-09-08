import { expect, test } from '@playwright/test'

test('library service shows failures and queues a manual resync', async ({ page }) => {
  let resynced = false
  await page.route('**/api/library/service/status', (route) => route.fulfill({
    json: {
      enabled: true,
      healthy: resynced,
      message: resynced ? '源文件扫描已接受不代表知识加工完成' : '知识服务暂不可用：HTTP 请求超时',
      last_synced_at: '2026-09-08T12:00:00Z',
      pending_count: resynced ? 3 : 1,
      failed_count: resynced ? 0 : 2,
    },
  }))
  await page.route('**/api/library/service/resync', (route) => {
    expect(route.request().method()).toBe('POST')
    resynced = true
    return route.fulfill({ status: 202, json: { pending_count: 3 } })
  })
  await page.goto('/library')
  const service = page.getByRole('region', { name: '知识服务状态' })
  await expect(service.getByText('知识服务：异常')).toBeVisible()
  await expect(service.getByText('待同步 1 · 同步失败 2')).toBeVisible()
  await service.getByRole('button', { name: '重新同步' }).click()
  await expect(service.getByText('待同步 3 · 同步失败 0')).toBeVisible()
  await expect(service.getByText('知识服务：正常')).toBeVisible()
  await expect(page.getByText('已提交 3 条同步任务')).toBeVisible()
  await page.screenshot({ path: '../artifacts/library-service.png', fullPage: true })
})
