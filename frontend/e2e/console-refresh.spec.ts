import { expect, test } from '@playwright/test'

for (const [path, refreshId] of [
  ['/tasks', 'task-refresh'],
  ['/employees', 'employee-refresh'],
  ['/interventions', 'intervention-refresh'],
] as const) {
  test(`${path} 闲置和恢复可见不刷新，首次加载与手动刷新只发一批请求`, async ({ page }) => {
    await page.clock.install()
    const requests: string[] = []
    let holdMetrics = false
    let release!: () => void
    const gate = new Promise<void>(resolve => { release = resolve })
    await page.route(url => url.pathname.startsWith('/api/'), async route => {
      const pathname = new URL(route.request().url()).pathname
      // 助手首次健康检查独立于管理台快照，不计入这五个读取接口。
      if (!pathname.startsWith('/api/assistant/')) requests.push(pathname)
      if (pathname === '/api/system/metrics' && holdMetrics) await gate
      await route.fulfill({ json: pathname === '/api/system/metrics' ? {} : [] })
    })
    await page.goto(path)
    const refresh = page.getByTestId(refreshId)
    await expect(refresh).toBeEnabled()
    expect(requests).toHaveLength(5)
    expect(new Set(requests).size).toBe(5)
    const baseline = [...requests]
    await page.clock.fastForward(60_000)
    await page.evaluate(() => {
      document.dispatchEvent(new Event('visibilitychange'))
      window.dispatchEvent(new Event('online'))
      window.dispatchEvent(new Event('focus'))
    })
    await page.clock.runFor(500)
    expect(requests).toEqual(baseline)
    expect(requests).not.toContain('/api/events/stream')

    holdMetrics = true
    await refresh.click()
    await expect.poll(() => requests.length).toBe(10)
    await refresh.evaluate(button => { button.click(); button.click() })
    await page.clock.runFor(500)
    expect(requests).toHaveLength(10)
    release()
    await expect(refresh).toBeEnabled()
    expect(requests).toEqual([...baseline, ...baseline])
  })
}
