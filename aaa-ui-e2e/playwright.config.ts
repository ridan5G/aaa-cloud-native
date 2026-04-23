import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  bail: 1,
  timeout: 30_000,
  reporter: [['html', { open: 'never' }]],
  use: {
    baseURL: process.env.UI_BASE_URL ?? 'http://localhost:8090',
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium' },
    },
  ],
})
