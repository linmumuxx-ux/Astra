import { expect, test } from '@playwright/test'

// 知识服务状态并入页面首行的标题信息区，不再单独占一整行。
// 页面骨架与权限由本地 mock 提供，本用例只验证标题信息区里服务状态的展示与重新同步。
test('library service shows failures and queues a manual resync', async ({ page }) => {
  await page.clock.install()
  const requests: string[] = []
  let resynced = false
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => {
    const { pathname } = new URL(route.request().url())
    requests.push(pathname)
    if (pathname === '/api/events/stream') {
      return route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: '' })
    }
    if (pathname === '/api/library/service/resync') {
      resynced = true
      return route.fulfill({ status: 202, json: { pending_count: 3 } })
    }
    if (pathname === '/api/library/service/status') {
      return route.fulfill({
        json: {
          enabled: true,
          healthy: resynced,
          message: resynced ? '源文件扫描已接受不代表知识加工完成' : '知识服务暂不可用：HTTP 请求超时',
          last_synced_at: '2026-09-08T12:00:00Z',
          pending_count: resynced ? 3 : 1,
          failed_count: resynced ? 0 : 2,
        },
      })
    }
    if (pathname === '/api/library/permissions') {
      return route.fulfill({ json: { user_id: 'e2e', role: 'admin', can_manage: true, can_review: true } })
    }
    if (pathname === '/api/library/stats') {
      return route.fulfill({ json: { knowledge_pages: 1, visible_knowledge_total: 0, knowledge_spaces: 0, weekly_references: 0, published_experiences: 0, candidate_experiences: 0 } })
    }
    if (pathname === '/api/library/spaces') return route.fulfill({ json: [] })
    if (pathname === '/api/library/usage/summary') {
      return route.fulfill({ json: { days: 7, total_references: 0, used_resources: 0, feedback_count: 0, top_knowledge: [], trend: [] } })
    }
    if (pathname === '/api/library/knowledge') {
      return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 20, pages: 1 } })
    }
    return route.fulfill({ json: {} })
  })
  await page.goto('/library')
  const page_ = page.getByTestId('digital-library-page')
  const header = page_.getByTestId('library-header')

  // 统一标题区：主标题 + 说明在左，刷新与主操作在右。
  await expect(header.getByRole('heading', { name: '数字图书馆', level: 2 })).toBeVisible()
  await expect(header.getByTestId('library-header-actions').getByRole('button', { name: '刷新' })).toBeVisible()
  await expect(header.getByTestId('library-header-actions').getByRole('button', { name: '导入知识' })).toBeVisible()
  await expect(header.getByTestId('library-header-actions').getByRole('button', { name: '新建知识' })).toBeVisible()

  // 服务状态是标题信息区里的一行紧凑信息，不再是独立的一整行卡片。
  const meta = header.locator('.astra-page-header__meta')
  await expect(meta).toHaveCount(1)
  await expect(meta.getByTestId('library-service-state')).toHaveText('知识服务：异常')
  await expect(meta.getByTestId('library-service-queue')).toHaveText('待同步 1 · 同步失败 2')
  await expect(page_.locator('.library-service-bar')).toHaveCount(0)

  // 原 10 秒服务状态轮询不再运行；手动刷新仍可更新。
  const baseline = [...requests]
  await page.clock.fastForward(60_000)
  await page.clock.runFor(500)
  expect(requests).toEqual(baseline)
  expect(requests).not.toContain('/api/events/stream')
  await page_.getByTestId('library-refresh').click()
  await expect(page_.getByTestId('library-refresh')).toBeEnabled()
  expect(requests.filter(path => path === '/api/library/service/status')).toHaveLength(2)

  await meta.getByRole('button', { name: '重新同步' }).click()
  await expect(meta.getByTestId('library-service-queue')).toHaveText('待同步 3 · 同步失败 0')
  await expect(meta.getByTestId('library-service-state')).toHaveText('知识服务：正常')
  await expect(page.getByText('已提交 3 条同步任务')).toBeVisible()
  await page.screenshot({ path: '../artifacts/library-service.png', fullPage: true })
})
