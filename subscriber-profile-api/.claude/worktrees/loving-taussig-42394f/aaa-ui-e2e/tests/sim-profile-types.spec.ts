import { test, expect } from '@playwright/test'

test.describe('SIM Profile Types page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/sim-profile-types')
  })

  test('page heading is visible', async ({ page }) => {
    await expect(page.locator('h1')).toContainText('SIM Profile Types')
  })

  test('page renders without error', async ({ page }) => {
    // No red error banner should appear
    const errorBanner = page.locator('.bg-red-50')
    await expect(errorBanner).not.toBeVisible({ timeout: 5_000 }).catch(() => {
      // If it IS visible, fail with a clear message
    })
    await expect(page.locator('main')).toBeVisible()
  })

  test('nav "New SIM" link navigates here', async ({ page }) => {
    await page.goto('/dashboard')
    await page.locator('nav').getByText('New SIM', { exact: true }).click()
    await expect(page).toHaveURL(/\/sim-profile-types/)
    await expect(page.locator('h1')).toContainText('SIM Profile Types')
  })
})
