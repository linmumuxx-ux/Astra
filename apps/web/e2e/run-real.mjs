import { spawn } from 'node:child_process'
import { mkdtemp, realpath, rm } from 'node:fs/promises'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const root = resolve(webRoot, '../..')
const temporary = await realpath(await mkdtemp(resolve(tmpdir(), 'astra-web-real-')))
const children = []
const python = process.env.ASTRA_PYTHON || resolve(root, process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python')
const env = { ...process.env, ASTRA_V1_DATABASE_URL: `sqlite+aiosqlite:///${temporary}/database.db`, ASTRA_V1_MEMORY_ROOT: resolve(temporary, 'memory') }
function freePort() { return new Promise((accept, reject) => { const server = createServer(); server.on('error', reject); server.listen(0, '127.0.0.1', () => { const port = server.address().port; server.close(() => accept(port)) }) }) }
function start(command, args, cwd, environment = env) {
  const child = spawn(command, args, { cwd, env: environment, stdio: ['ignore', 'pipe', 'pipe'] })
  let output = ''
  child.stdout.on('data', data => { output = (output + data).slice(-12000) })
  child.stderr.on('data', data => { output = (output + data).slice(-12000) })
  child.result = new Promise((accept, reject) => { child.on('error', reject); child.on('exit', code => code === 0 ? accept() : reject(new Error(`${command} 返回 ${code}\n${output}`))) })
  // 长运行服务的失败在 readiness 或测试阶段处理，避免异步未捕获异常。
  child.result.catch(() => {})
  children.push(child)
  return child
}
async function ready(url) { for (let attempt = 0; attempt < 120; attempt++) { try { if ((await fetch(url)).ok) return } catch {} await new Promise(accept => setTimeout(accept, 200)) } throw new Error(`服务未能就绪 ${url}`) }
try {
  const apiPort = await freePort(), webPort = await freePort()
  await start(python, ['-m', 'apps.api.manage', 'migrate'], root).result
  await start(python, ['-m', 'apps.api.manage', 'bootstrap', '--name', '界面验收管理员', '--token-file', resolve(temporary, 'access.token')], root).result
  start(python, ['-m', 'apps.api.manage', 'serve', '--port', String(apiPort)], root)
  await ready(`http://127.0.0.1:${apiPort}/api/v1/health`)
  start(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', String(webPort)], webRoot, { ...env, ASTRA_API_URL: `http://127.0.0.1:${apiPort}` })
  await ready(`http://127.0.0.1:${webPort}`)
  const testProcess = spawn(process.execPath, ['node_modules/@playwright/test/cli.js', 'test'], { cwd: webRoot, env: { ...env, ASTRA_E2E_TOKEN_FILE: resolve(temporary, 'access.token'), ASTRA_E2E_API_URL: `http://127.0.0.1:${apiPort}/api/v1`, ASTRA_WEB_URL: `http://127.0.0.1:${webPort}` }, stdio: 'inherit' })
  const code = await new Promise((accept, reject) => { testProcess.on('error', reject); testProcess.on('exit', accept) })
  process.exitCode = Number(code) || 0
} catch (error) { console.error(error.message); process.exitCode = 1 }
finally { for (const child of children) if (child.exitCode === null) child.kill('SIGTERM'); await new Promise(accept => setTimeout(accept, 400)); await rm(temporary, { recursive: true, force: true }) }
