import { expect, test, type Page } from '@playwright/test'

async function checkHelp(page: Page, label: string, text: string) {
  const icon = page.getByRole('button', { name: `${label}说明`, exact: true })
  await expect(icon).toBeVisible()
  await page.mouse.move(0, 0)
  await icon.scrollIntoViewIfNeeded()
  await expect(page.getByRole('tooltip')).toHaveCount(0)
  const field = icon.locator('xpath=ancestor::*[contains(concat(" ",normalize-space(@class)," ")," astra-form-field ") or contains(concat(" ",normalize-space(@class)," ")," el-form-item ")][1]')
  // 冷启动时弹框数据 hydration 会带来一次性 reflow；先等字段位置稳定再取基线，
  // 避免把异步渲染误判成 tooltip 移位，悬停后不允许移位的断言本身保持不变。
  let before = await field.boundingBox()
  await expect.poll(async () => {
    await new Promise((resolve) => setTimeout(resolve, 150))
    const settled = await field.boundingBox()
    const unchanged = Boolean(before && settled && before!.x === settled.x && before!.y === settled.y)
    before = settled
    return unchanged
  }, 'field layout settled before baseline').toBe(true)
  await icon.hover()
  const tooltip = page.getByRole('tooltip')
  await expect(tooltip).toBeVisible()
  await expect(tooltip).toContainText(text)
  expect(await field.boundingBox()).toEqual(before)
  const bounds = await tooltip.boundingBox()
  const viewport = page.viewportSize()!
  expect(bounds!.x).toBeGreaterThanOrEqual(0)
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width)
  await page.mouse.move(0, 0)
  await expect(tooltip).toHaveCount(0)
  await icon.focus()
  await expect(tooltip).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(tooltip).toHaveCount(0)
  await icon.blur()
}

// 旧的 .form-grid 两列布局随全局 theme/forms CSS 一起移除，业务页面允许视觉变化。
// 基础框架层面的校验收敛为：成对字段控件仍然可见、可交互，并继承全局字体主题。
async function expectFormControlsUsable(page: Page) {
  const grids = page.locator('.config-form .form-grid, .task-create-card .form-grid')
  let checked = 0
  for (const grid of await grids.all()) {
    const controls = grid.locator(':scope > label > input, :scope > label > select, :scope > .astra-form-field > input, :scope > .astra-form-field > select')
    if (await controls.count() !== 2) continue
    for (const control of await controls.all()) {
      await expect(control).toBeVisible()
      const box = await control.boundingBox()
      expect(box, 'paired control renders').not.toBeNull()
      expect(box!.width, 'paired control width').toBeGreaterThan(0)
      expect(box!.height, 'paired control height').toBeGreaterThan(0)
      await expect(control).toHaveCSS('font-family', '"Times New Roman", "Microsoft YaHei", 微软雅黑, serif')
      checked += 1
    }
  }
  expect(checked, 'paired form controls found').toBeGreaterThan(0)
}

// 抽屉表单：单列、标签左对齐且同宽、字段控件统一高度。
async function expectDrawerLayoutUnified(page: Page) {
  const drawer = page.getByTestId('employee-config-modal')
  const items = drawer.locator('.el-form-item')
  expect(await items.count(), 'grouped form items').toBeGreaterThan(12)
  const labelWidths = new Set<number>()
  for (const label of await drawer.locator('.el-form-item__label').all()) {
    const box = await label.boundingBox()
    expect(box, 'label renders').not.toBeNull()
    labelWidths.add(Math.round(box!.width))
    await expect(label).toHaveCSS('text-align', 'left')
  }
  expect(labelWidths.size, 'uniform label column').toBe(1)
  let lastBottom = 0
  const leftEdges = new Set<number>()
  for (const item of await items.all()) {
    const box = await item.boundingBox()
    expect(box, 'form item renders').not.toBeNull()
    leftEdges.add(Math.round(box!.x))
    expect(box!.y, 'single column stacking').toBeGreaterThanOrEqual(lastBottom - 1)
    lastBottom = box!.y + box!.height
  }
  expect(leftEdges.size, 'one property per row').toBe(1)
  const wrappers = await drawer.locator('.el-form-item .el-input__wrapper, .el-form-item .el-select__wrapper').all()
  const heights = new Set<number>()
  for (const wrapper of wrappers) {
    const box = await wrapper.boundingBox()
    expect(box, 'control renders').not.toBeNull()
    expect(box!.width, 'control fills row').toBeGreaterThan(100)
    heights.add(Math.round(box!.height))
  }
  expect(wrappers.length, 'controls found').toBeGreaterThan(5)
  expect(heights.size, 'uniform control height').toBe(1)
}

test('员工配置抽屉分组布局、说明悬停与环境检测保持可见', async ({ page }) => {
  await page.goto('/employees?edit=astra-01')
  const drawer = page.getByTestId('employee-config-modal')
  await expect(drawer).toBeVisible()
  for (const section of ['基本信息', '工作范围', '运行配置', '环境配置']) {
    await expect(drawer.getByText(section, { exact: true })).toBeVisible()
  }
  await checkHelp(page, '默认办公区域', '无特定任务场景')
  await expectDrawerLayoutUnified(page)
  const enabled = drawer.getByRole('switch', { name: '启用员工', exact: true })
  const before = await enabled.getAttribute('aria-checked')
  await drawer.getByRole('button', { name: '启用员工说明', exact: true }).click()
  await expect(enabled).toHaveAttribute('aria-checked', before!)
  await page.mouse.move(0, 0)
  await checkHelp(page, '问题', '缺陷、故障、异常')
  await checkHelp(page, '需求', '新功能、能力增强')
  await expect(drawer.locator('.el-checkbox__label small')).toHaveCount(0)
  await page.screenshot({ path: '../artifacts/form-help/employee-scope.png', fullPage: true })
  await checkHelp(page, '自动领取任务', '空闲时可以领取')
  await checkHelp(page, '允许自主执行', '领取后自动启动')
  await checkHelp(page, 'Agent 可执行文件', '正式 Runtime')
  await checkHelp(page, 'Agent 模型', '留空时使用')
  await page.getByRole('button', { name: '工作空间说明', exact: true }).hover()
  await page.screenshot({ path: '../artifacts/form-help/environment-tooltip.png', fullPage: true })
  await page.mouse.move(0, 0)
  await checkHelp(page, 'OpenCode Server Port', '人工配置固定端口')
  await page.route('**/api/employees/astra-01/environment/test', route => route.fulfill({ json: { status: 'ERROR', checked_at: '2026-09-07T00:00:00Z', checks: [{ name: '连接检查', passed: false, detail: '测试异常：Server 无法连接' }] } }))
  await drawer.getByRole('button', { name: '测试连接', exact: true }).click()
  await expect(page.getByTestId('environment-checks')).toContainText('测试异常：Server 无法连接')
  await expect(page.getByTestId('environment-checks')).toBeVisible()
  await expect(page.getByTestId('form-message')).toContainText('环境异常，请根据检查项处理。')
  await drawer.locator('label.el-radio-button', { hasText: 'Linux 远程' }).click()
  await expect(drawer.getByLabel('SSH Host', { exact: true })).toBeVisible()
  await checkHelp(page, 'SSH 密码', '接口不回显')
  await page.screenshot({ path: '../artifacts/form-help/remote-environment.png', fullPage: true })
})

test('员工配置抽屉必填校验、工作范围校验与未保存关闭', async ({ page }) => {
  await page.goto('/employees?create=1')
  const drawer = page.getByTestId('employee-config-modal')
  await expect(drawer).toBeVisible()
  await expect(drawer.getByRole('button', { name: '创建员工', exact: true })).toBeDisabled()
  await drawer.getByLabel('员工名称', { exact: true }).fill('校验员工')
  await drawer.getByRole('button', { name: '创建员工', exact: true }).click()
  await expect(drawer.getByText('请输入员工 ID')).toBeVisible()
  await expect(drawer.getByText('请输入岗位')).toBeVisible()
  await expect(drawer.getByText('请输入工作空间')).toBeVisible()
  await expect(drawer).toBeVisible()
  await drawer.getByRole('button', { name: '取消', exact: true }).click()
  const confirm = page.getByTestId('astra-confirm-dialog')
  await expect(confirm).toContainText('放弃未保存的员工配置')
  await confirm.getByRole('button', { name: '放弃并关闭', exact: true }).click()
  await expect(drawer).toBeHidden()

  await page.goto('/employees?edit=astra-01')
  await drawer.getByLabel('员工名称', { exact: true }).fill('表单验收员工')
  for (const checkbox of await drawer.locator('.el-checkbox').all()) {
    if (await checkbox.locator('input').isChecked()) await checkbox.click()
  }
  await page.route('**/api/employees/astra-01', route => route.fulfill({ status: 503, json: { detail: '测试保存失败：请稍后重试' } }))
  await drawer.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByTestId('form-message')).toHaveAttribute('data-error', 'true')
  await expect(page.getByTestId('form-message')).toContainText('工作范围至少需要一种任务类型和一个任务分类')
  await expect(page.getByTestId('form-message')).toBeVisible()
})

test('任务创建和系统偏好使用统一提示，附件反馈保持可见', async ({ page }) => {
  await page.goto('/tasks')
  await page.getByRole('button', { name: '创建任务', exact: true }).click()
  await checkHelp(page, '完成策略', '很高/高优先级默认人工确认')
  await expectFormControlsUsable(page)
  await checkHelp(page, '分配方式', '员工启用状态')
  await page.locator('.task-create-card input[type=file]').setInputFiles({ name: '说明.txt', mimeType: 'text/plain', buffer: Buffer.from('测试附件') })
  await expect(page.locator('.task-create-card .attachment-chips li')).toHaveCount(1)
  await expect(page.locator('.task-create-card .attachment-chips li')).toContainText('说明.txt')
  await page.getByRole('button', { name: '完成策略说明', exact: true }).hover()
  await page.screenshot({ path: '../artifacts/form-help/task-create-tooltip.png', fullPage: true })
  await page.goto('/settings?tab=system')
  const icon = page.locator('.astra-form-help').first()
  await icon.hover()
  await expect(page.getByRole('tooltip')).toContainText('关闭数字办公室的工作动画')
  await page.mouse.move(0, 0)
  await expect(page.getByRole('tooltip')).toHaveCount(0)
  await page.screenshot({ path: '../artifacts/form-help/system-settings.png', fullPage: true })
})


test('知识编辑、分类、来源表单保留字段，待处理进入 Workspace', async ({ page }) => {
  await page.goto('/library')
  await page.getByRole('button', { name: '新建知识', exact: true }).click()
  const editor = page.locator('.knowledge-editor')
  await expect(editor).toBeVisible()
  await expect(editor.getByLabel('知识标题 *')).toHaveAttribute('required', '')
  await expect(editor.getByLabel('摘要')).toBeVisible()
  await expect(editor.locator('label > small')).toHaveCount(0)
  await page.screenshot({ path: '../artifacts/form-help/knowledge-editor.png', fullPage: true })
  for (const tab of ['categories', 'sources']) {
    await page.goto(`/settings?tab=${tab}`)
    await expect(page.locator('.config-table')).toBeVisible()
    await page.screenshot({ path: `../artifacts/form-help/settings-${tab}.png`, fullPage: true })
  }
  await page.goto('/interventions')
  const pending = page.getByTestId('intervention-page')
  await expect(pending.getByRole('heading', { name: '待处理', exact: true }).first()).toBeVisible()
  // 人工介入已收敛到任务 Workspace：待处理列表只提供进入 Workspace 的入口。
  const item = pending.locator('.intervention-task').filter({ hasText: '新增回调场景自动化覆盖' })
  await expect(item).toBeVisible()
  await expect(item.getByRole('link', { name: '进入任务详情' })).toHaveAttribute('href', '/tasks/T-20260827-002')
  await page.screenshot({ path: '../artifacts/form-help/intervention-form.png', fullPage: true })
})