import { expect, test } from '@playwright/test'

const latinPlatformFonts = new Set(['Times New Roman', 'Liberation Serif'])
const cjkPlatformFonts = new Set(['Microsoft YaHei', 'WenQuanYi Zen Hei'])
const acceptedPlatformFonts = new Set([...latinPlatformFonts, ...cjkPlatformFonts])

test('主要页面、控件与弹层使用全局字体，实际中英文字形正确', async ({ page }) => {
  const routes = ['/', '/employees', '/employees/astra-01', '/tasks', '/tasks/T-20260827-003', '/library', '/settings', '/interventions']
  const cdp = await page.context().newCDPSession(page)
  await cdp.send('DOM.enable')
  await cdp.send('CSS.enable')
  for (const route of routes) {
    await page.goto(route)
    await page.locator('main').first().waitFor()
    await expect(page.locator('.error-banner')).toHaveCount(0)
    await expect(page.locator('.task-title h1')).toHaveCount(route.startsWith('/tasks/') ? 1 : 0)
    await page.evaluate(() => document.fonts.ready)
    const mismatches = await page.evaluate(() => Array.from(document.querySelectorAll('body *')).filter(el =>
      el.getBoundingClientRect().width > 0 && Array.from(el.childNodes).some(n => n.nodeType === Node.TEXT_NODE && n.textContent?.trim())
    ).filter(el => !getComputedStyle(el).fontFamily.startsWith('"Times New Roman", "Microsoft YaHei"')).map(el => ({ tag: el.tagName, text: el.textContent?.slice(0, 30), font: getComputedStyle(el).fontFamily })))
    expect(mismatches, route).toEqual([])
    // Reactive data can replace nodes during the CDP audit. Retry a fresh full
    // snapshot so detached node ids do not fail an otherwise valid font check.
    await expect(async () => {
      await page.evaluate(() => {
        document.querySelectorAll('body *').forEach(el => {
          if (el.getBoundingClientRect().width > 0 && Array.from(el.childNodes).some(n => n.nodeType === Node.TEXT_NODE && /[A-Za-z0-9\u4e00-\u9fff]/.test(n.textContent || ''))) el.setAttribute('data-font-audit', '')
        })
      })
      const documentNode = await cdp.send('DOM.getDocument')
      const textNodes = await cdp.send('DOM.querySelectorAll', { nodeId: documentNode.root.nodeId, selector: '[data-font-audit]' })
      for (const nodeId of textNodes.nodeIds) {
        const { fonts } = await cdp.send('CSS.getPlatformFontsForNode', { nodeId })
        expect(fonts.every((font: { familyName: string }) => acceptedPlatformFonts.has(font.familyName)), `${route}: ${JSON.stringify(fonts)}`).toBeTruthy()
      }
    }).toPass({ timeout: 5000, intervals: [100, 250, 500] })

    // 旧全局样式中的 22px 页面级标题字号已随 theme/typography.css 移除，业务页面允许视觉变化；
    // 基础层仍然保证页面级标题可见、加粗并使用全局字体主题。
    // 统一标题区由 AstraPageHeader 渲染，页面主标题统一是 .astra-page-header__title。
    const titles = page.locator('.astra-page-header__title, .employee-detail__identity h2, .task-hero h2, .task-title h1')
    for (const title of await titles.all()) {
      await expect(title).toBeVisible()
      await expect(title).toHaveCSS('font-family', '"Times New Roman", "Microsoft YaHei", 微软雅黑, serif')
      await expect(title).toHaveCSS('font-weight', '700')
    }
    await page.screenshot({ path: `../artifacts/typography/${route.replaceAll('/', '_') || 'home'}.png`, fullPage: true })
  }
  // Chromium exposes installed platform font names. Ubuntu CI substitutes metrically
  // compatible fonts when the Windows fonts are unavailable, so verify the semantic
  // Latin/CJK family rather than a single operating-system-specific family name.
  for (const weight of [400, 700]) {
    for (const [text, accepted] of [
      ['中文正文，。测试', cjkPlatformFonts],
      ['English 0123456789,.;:!?()', latinPlatformFonts],
    ] as const) {
      await page.evaluate(({ text, weight }) => {
        document.getElementById('font-probe')?.remove()
        const probe = document.createElement('span')
        probe.id = 'font-probe'; probe.textContent = text
        probe.style.fontWeight = String(weight)
        document.body.append(probe)
      }, { text, weight })
      await page.evaluate(async () => { await document.fonts.ready; await new Promise(requestAnimationFrame) })
      const { root } = await cdp.send('DOM.getDocument')
      const { nodeId } = await cdp.send('DOM.querySelector', { nodeId: root.nodeId, selector: '#font-probe' })
      const { fonts } = await cdp.send('CSS.getPlatformFontsForNode', { nodeId })
      expect(fonts.length).toBeGreaterThan(0)
      expect(fonts.every((font: { familyName: string }) => accepted.has(font.familyName)), JSON.stringify(fonts)).toBeTruthy()
    }
  }
  await page.goto('/tasks')
  await page.getByRole('button', { name: /创建任务/ }).first().click()
  const drawer = page.getByTestId('task-create-modal')
  await expect(drawer).toBeVisible()
  await expect(drawer.locator('input').first()).toHaveCSS('font-family', '"Times New Roman", "Microsoft YaHei", 微软雅黑, serif')
  await page.screenshot({ path: '../artifacts/typography/task-dialog.png', fullPage: true })
})

test('知识正文与设置各页签使用全局字体，代码块保持等宽', async ({ page }) => {
  await page.route('**/api/library/knowledge/font-qa', route => route.fulfill({ json: {
    id: 'font-qa', title: '排版验证 Typography 2026', type: 'document', status: 'published',
    verification_status: 'verified', tags: ['中文', 'English 123'], summary: '字体测试',
    updated_at: '2026-09-07T00:00:00Z', reference_count: 12, helpful_count: 3,
    content_md: '# 一级标题 Heading 1\n\n中文正文 English 123,.;:!?\n\n## 二级标题 Heading 2\n\n**中文加粗 Bold 456**，*English italic*\n\n### 三级标题 Heading 3\n\n| 中文列 | English |\n|---|---|\n| 数据 | 123.45 |\n\n`代码 code 789`\n\n```text\n中文日志 Log 2026\n```',
    sources: [], evidence: [], experience_data: {}, is_favorite: false, user_helpful: false,
  } }))
  await page.route('**/api/library/knowledge/font-qa/usages*', route => route.fulfill({ json: [] }))
  await page.goto('/library?knowledge=font-qa')
  const dialog = page.getByTestId('knowledge-detail-dialog')
  await expect(dialog.locator('.markdown-body table')).toBeVisible()
  // 全局字体覆盖正文、表格与按钮；预格式代码块不再被旧全局样式强制为衬线字体，
  // 保留浏览器等宽回退以保证代码可读性。行内 code 的呈现仍归业务组件样式。
  for (const element of await dialog.locator('h1,h2,h3,p,th,td,button').all()) {
    await expect(element).toHaveCSS('font-family', '"Times New Roman", "Microsoft YaHei", 微软雅黑, serif')
  }
  for (const element of await dialog.locator('pre').all()) {
    expect(await element.evaluate((el) => getComputedStyle(el).fontFamily), 'code block stays monospace').toContain('monospace')
  }
  await page.screenshot({ path: '../artifacts/typography/knowledge-dialog.png', fullPage: true })
  await page.goto('/settings')
  await expect(page.getByTestId('settings-page')).toBeVisible()
  await page.screenshot({ path: '../artifacts/typography/settings-categories.png', fullPage: true })
  await page.goto('/employees')
  await page.getByRole('button', { name: '查看 员工-01' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByRole('dialog').locator('h2')).toHaveCSS('font-weight', '700')
  await page.screenshot({ path: '../artifacts/typography/employee-drawer.png', fullPage: true })
})
