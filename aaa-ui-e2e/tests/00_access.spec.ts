import { test, expect } from '@playwright/test'

const baseURL = process.env.UI_BASE_URL ?? 'http://localhost:8090'

test.describe('UI access check', () => {
  test('UI is reachable and serves HTML', async ({ page }) => {
    console.log(`[access] Targeting: ${baseURL}`)

    const response = await page.goto('/')
    expect(response).not.toBeNull()
    expect(response!.status()).toBeLessThan(500)

    const title = await page.title()
    expect(title.length).toBeGreaterThan(0)
    console.log(`[access] Page title: "${title}"`)
  })

  test('root path redirects to /dashboard', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveURL(/\/dashboard/)
  })
})
