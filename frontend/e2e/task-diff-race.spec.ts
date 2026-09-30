import { expect, test, type Page, type Route } from '@playwright/test'

// 真实组件 + 真实浏览器 + 真实 fetch；只用请求拦截注入网络时序，不替换实现。
// 关键序列是 累计 → 未提交 → 累计：只有回到同一模式时，旧的晚到响应才会与当前请求
// 争抢同一个 mode，暴露"只有当前请求能写状态"这一约束。
const task = process.env.ASTRA_DIFF_RACE_TASK
const diff = (file: string) => [{ file, patch: `+${file}`, additions: 1, deletions: 0 }]

async function fulfil(route: Route, file: string) {
  await route.fulfill({ json: diff(file) })
}

async function openDrawer(page: Page) {
  await page.goto(`/tasks/${task}`)
  await page.getByRole('button', { name: '代码变更' }).click()
  await expect(page.getByText('正在读取 Git 变更…')).toBeVisible()
}

test.describe('代码变更抽屉的请求身份', () => {
  test.use({ actionTimeout: 30_000 })
  test.describe.configure({ mode: 'serial', timeout: 240_000 })
  test.skip(!task, '需要真实任务：ASTRA_DIFF_RACE_TASK')

  test('晚到的旧累计请求不得覆盖回到累计后的新数据', async ({ page }) => {
    let taskCalls = 0
    await page.route('**/vcs/diff?mode=*', async route => {
      const mode = new URL(route.request().url()).searchParams.get('mode')
      if (mode === 'git') return fulfil(route, 'git-fresh.txt')
      taskCalls += 1
      if (taskCalls === 1) {
        await new Promise(resolve => setTimeout(resolve, 12_000))
        return fulfil(route, 'task-stale.txt')
      }
      return fulfil(route, 'task-fresh.txt')
    })
    await openDrawer(page)
    await page.getByRole('tab', { name: '当前未提交' }).click()
    await expect(page.getByText('git-fresh.txt').first()).toBeVisible({ timeout: 20_000 })
    await page.getByRole('tab', { name: '任务累计变更' }).click()
    await expect(page.getByText('task-fresh.txt').first()).toBeVisible({ timeout: 20_000 })
    // 首个累计请求此刻才晚到：数据、加载态都必须仍是第三次请求的结果。
    await page.waitForTimeout(15_000)
    await expect(page.getByText('task-fresh.txt').first()).toBeVisible()
    await expect(page.getByText('task-stale.txt')).toHaveCount(0)
    await expect(page.getByText('正在读取 Git 变更…')).toHaveCount(0)
    await expect(page.getByText('读取 Git 变更超时，请重试')).toHaveCount(0)
  })

  test('晚到的旧超时不得覆盖成功读取的数据与加载态', async ({ page }) => {
    let taskCalls = 0
    await page.route('**/vcs/diff?mode=*', async route => {
      const mode = new URL(route.request().url()).searchParams.get('mode')
      if (mode === 'git') return fulfil(route, 'git-fresh.txt')
      taskCalls += 1
      if (taskCalls === 1) {
        // 超过组件 20 秒上界：请求最终会失败，但已不是当前请求。
        await new Promise(resolve => setTimeout(resolve, 30_000))
        return route.fulfill({ json: diff('task-stale.txt') })
      }
      return fulfil(route, 'task-fresh.txt')
    })
    await openDrawer(page)
    await page.getByRole('tab', { name: '当前未提交' }).click()
    await expect(page.getByText('git-fresh.txt').first()).toBeVisible({ timeout: 20_000 })
    await page.getByRole('tab', { name: '任务累计变更' }).click()
    await expect(page.getByText('task-fresh.txt').first()).toBeVisible({ timeout: 20_000 })
    await page.waitForTimeout(28_000)
    await expect(page.getByText('task-fresh.txt').first()).toBeVisible()
    await expect(page.getByText('task-stale.txt')).toHaveCount(0)
    await expect(page.getByText('读取 Git 变更超时，请重试')).toHaveCount(0)
    await expect(page.getByText('正在读取 Git 变更…')).toHaveCount(0)
  })

  test('当前请求超时给出可读错误并结束加载态', async ({ page }) => {
    await page.route('**/vcs/diff?mode=*', async route => {
      const mode = new URL(route.request().url()).searchParams.get('mode')
      if (mode === 'git') return fulfil(route, 'git-fresh.txt')
      await new Promise(resolve => setTimeout(resolve, 40_000))
      return fulfil(route, 'task-stale.txt')
    })
    await openDrawer(page)
    await expect(page.getByText('读取 Git 变更超时，请重试')).toBeVisible({ timeout: 40_000 })
    await expect(page.getByText('正在读取 Git 变更…')).toHaveCount(0)
  })

  test('切换模式会取消上一请求', async ({ page }) => {
    const aborted: string[] = []
    page.on('requestfailed', request => {
      if (request.url().includes('/vcs/diff?mode=task')) aborted.push('task')
    })
    await page.route('**/vcs/diff?mode=*', async route => {
      const mode = new URL(route.request().url()).searchParams.get('mode')
      if (mode === 'git') return fulfil(route, 'git-fresh.txt')
      await new Promise(resolve => setTimeout(resolve, 60_000))
      return fulfil(route, 'task-stale.txt')
    })
    await openDrawer(page)
    await page.getByRole('tab', { name: '当前未提交' }).click()
    await expect(page.getByText('git-fresh.txt').first()).toBeVisible({ timeout: 20_000 })
    await expect.poll(() => aborted.length, { timeout: 15_000 }).toBeGreaterThan(0)
  })

  test('离开任务页会中止在途的 Diff 请求', async ({ page }) => {
    const aborted: string[] = []
    page.on('requestfailed', request => {
      if (request.url().includes('/vcs/diff')) aborted.push(request.url())
    })
    await page.route('**/vcs/diff?mode=*', async route => {
      await new Promise(resolve => setTimeout(resolve, 60_000))
      return fulfil(route, 'task-stale.txt')
    })
    await openDrawer(page)
    // 关闭抽屉但保持请求在途，再做 SPA 内导航：整页刷新会自己取消请求，
    // 只有组件卸载才能证明这一条。
    await page.keyboard.press('Escape')
    await expect(page.getByText('正在读取 Git 变更…')).toBeHidden()
    await page.getByRole('menuitem', { name: '任务管理' }).click()
    await expect(page.getByRole('heading', { name: '任务管理' })).toBeVisible()
    await expect.poll(() => aborted.length, { timeout: 15_000 }).toBeGreaterThan(0)
  })
})
