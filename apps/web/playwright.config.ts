import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './e2e', fullyParallel: false, workers: 1, timeout: 60000, expect: { timeout: 15000 },
  use: { baseURL: process.env.ASTRA_WEB_URL || 'http://127.0.0.1:5273', viewport: { width: 1600, height: 1000 }, trace: 'off', screenshot: 'off', video: 'off', launchOptions: { executablePath: process.env.ASTRA_E2E_BROWSER, args: ['--enable-webgl', '--use-gl=angle', '--use-angle=swiftshader'] } },
  reporter: [['list'], ['json', { outputFile: 'test-results/results.json' }]],
})
