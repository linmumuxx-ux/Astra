// 真实 OpenCode 业务验收专用；复用 Python 运行中的隔离 API，不模拟任何接口。
import { chromium, expect } from '@playwright/test'
import { spawn } from 'node:child_process'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { createServer } from 'node:net'
import { resolve } from 'node:path'
const port = await new Promise((accept, reject) => { const socket = createServer(); socket.on('error', reject); socket.listen(0, '127.0.0.1', () => { const value = socket.address().port; socket.close(() => accept(value)) }) })
const web = spawn(process.execPath, ['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port',String(port)], { cwd: resolve('.'), env: process.env, stdio: 'ignore' })
let browser
async function readHistory(page) {
  await page.getByRole('button', {name:'查看原生证据', exact:true}).first().click()
  const dialog = page.getByRole('dialog', {name:'原生执行证据', exact:true})
  await expect(dialog.getByText('Ran 5 tests', {exact:false}).first()).toBeVisible({timeout:15000})
  await page.screenshot({path:resolve('../../docs/astra-1.0/evidence/task-native-history.png'),fullPage:true,animations:'disabled'})
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
}
try {
  for (let attempt = 0; attempt < 100; attempt++) { try { if ((await fetch(`http://127.0.0.1:${port}`)).ok) break } catch {} await new Promise(resolve => setTimeout(resolve, 100)) }
  browser = await chromium.launch({ executablePath: process.env.ASTRA_E2E_BROWSER })
  const page = await browser.newPage({ viewport: { width:1600, height:1200 } })
  await page.goto(`http://127.0.0.1:${port}/tasks/${process.env.ASTRA_LIVE_TASK_ID}`)
  await page.getByLabel('访问凭据', { exact:true }).fill((await readFile(process.env.ASTRA_E2E_TOKEN_FILE,'utf8')).trim())
  await page.getByRole('button',{name:'进入数字空间'}).click()
  await expect(page.getByText('实时同步', { exact:true })).toBeVisible({ timeout:15000 })
  await page.goto(`http://127.0.0.1:${port}/tasks/${process.env.ASTRA_LIVE_TASK_ID}`)
  await expect(page.getByRole('radio', {name:'全部工作', exact:true})).toBeAttached()
  if (process.env.ASTRA_LIVE_READ_ONLY === '1') {
    await expect(page.locator('.task-detail')).toContainText('独立验收结论')
    await page.screenshot({path:resolve('../../docs/astra-1.0/evidence/task-employee-completed.png'),fullPage:true,animations:'disabled'})
    await readHistory(page)
    await writeFile(process.env.ASTRA_LIVE_REVIEW_RESULT, JSON.stringify({ history_verified:true }))
  } else {
  const panel = page.getByRole('region', { name:'逐条独立验收' })
  await expect(panel).toBeVisible({ timeout:15000 }).catch(async error => { await page.screenshot({path:resolve('../../docs/astra-1.0/evidence/task-review-failure.png'),fullPage:true}); throw new Error(`${error.message}\n${(await page.locator('body').innerText()).slice(-4000)}`) })
  await panel.getByText('查看原生工具证据', {exact:true}).click()
  await expect(panel.getByText('Ran 5 tests', {exact:false}).first()).toBeVisible()
  await panel.getByLabel('标准 1 已通过').check()
  await panel.getByLabel('标准 1 的验收依据', {exact:true}).fill('独立复验五项原始测试退出码0，原始测试 SHA256 未变；审查真实命令输出。')
  await panel.getByLabel('标准 1 的证据', {exact:true}).click()
  await page.getByRole('option',{name: `bash · ${process.env.ASTRA_LIVE_EVIDENCE_PART_ID}`, exact:true}).click()
  await panel.getByLabel('标准 1 的原文摘录',{exact:true}).fill('Ran 5 tests')
  const evidenceDir = resolve('../../docs/astra-1.0/evidence')
  await mkdir(evidenceDir,{recursive:true})
  await page.screenshot({path:resolve(evidenceDir,'task-native-review.png'),fullPage:true,animations:'disabled'})
  const response = page.waitForResponse(value => value.url().endsWith(`/tasks/${process.env.ASTRA_LIVE_TASK_ID}/review`) && value.request().method()==='POST')
  await panel.getByRole('button',{name:'提交验收结论'}).click()
  const result=await response
  expect(result.ok()).toBeTruthy()
  const review=await result.json()
  await expect(page.getByText('独立验收结论已保存',{exact:true})).toBeVisible()
  await expect(page.locator('.task-detail')).toContainText('已完成')
  await readHistory(page)
  await page.screenshot({path:resolve(evidenceDir,'task-native-completed.png'),fullPage:true,animations:'disabled'})
  await writeFile(process.env.ASTRA_LIVE_REVIEW_RESULT,JSON.stringify({review,request_body:result.request().postDataJSON(),operation_key:result.request().headers()['idempotency-key']}))
  }
} finally { if(browser) await browser.close(); web.kill('SIGTERM'); await new Promise(resolve=>web.once('exit',resolve)) }
