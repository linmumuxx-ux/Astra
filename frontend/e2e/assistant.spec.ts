import { expect, test } from '@playwright/test'

test('平台助手入口可打开抽屉并展示输入区', async ({ page }) => {
  await page.goto('/')
  const launcher = page.getByTestId('assistant-launcher')
  await expect(launcher).toBeVisible()
  await launcher.click()

  const drawer = page.getByRole('dialog', { name: '平台助手' })
  await expect(drawer).toBeVisible()
  // 服务可用时显示连接状态；OpenCode 未启动时显示服务异常，入口仍然存在
  await expect(drawer.getByText(/服务异常|已连接|连接中/).first()).toBeVisible()
  await expect(drawer.getByRole('textbox')).toBeVisible()

  await drawer.getByRole('button', { name: '关闭助手' }).click()
  await expect(drawer).toBeHidden()
})

test('平台助手真实消息可流式完成并在刷新后恢复', async ({ page }) => {
  test.skip(process.env.ASTRA_ASSISTANT_E2E_REAL !== '1', '需要本地 Backend 与助手 OpenCode Server')

  await page.goto('/')
  await page.getByTestId('assistant-launcher').click()
  const drawer = page.getByRole('dialog', { name: '平台助手' })
  await expect(drawer.getByText('已连接')).toBeVisible({ timeout: 15_000 })
  await drawer.getByTitle('新建会话').click()

  const input = drawer.getByRole('textbox')
  await expect(input).toBeEnabled()
  await input.fill('请列出当前数字员工的姓名和状态。')
  await input.press('Enter')
  await expect(drawer.getByText('请列出当前数字员工的姓名和状态。')).toBeVisible()
  await expect(drawer.getByText(/Astra-01/).last()).toBeVisible({ timeout: 45_000 })

  await page.reload()
  await page.getByTestId('assistant-launcher').click()
  const restored = page.getByRole('dialog', { name: '平台助手' })
  await expect(restored.getByText('请列出当前数字员工的姓名和状态。')).toBeVisible({
    timeout: 15_000,
  })
  await expect(restored.getByText(/Astra-01/).last()).toBeVisible()
})
