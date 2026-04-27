import { test, expect } from '@playwright/test'

test.describe('SIM Range Configs (ICCID) page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/iccid-range-configs')
  })

  test('page heading is visible', async ({ page }) => {
    await expect(page.getByText('Configuration', { exact: true })).toBeVisible()
    await expect(page.locator('h1')).toContainText('SIM Range Configs')
  })

  test('New Config button is present', async ({ page }) => {
    await expect(page.getByRole('button', { name: '+ New Config' })).toBeVisible()
  })

  test('list renders table or empty state', async ({ page }) => {
    const table = page.locator('table.tbl')
    // IccidRangeConfigs uses a different empty message — match either variant
    const empty = page.getByText(/No (sim|iccid|range) config/i)
    await expect(table.or(empty)).toBeVisible({ timeout: 10_000 })
  })

  test('nav link "SIM Range configs" navigates here', async ({ page }) => {
    await page.goto('/dashboard')
    await page.locator('nav').getByText('SIM Range configs', { exact: true }).click()
    await expect(page).toHaveURL(/\/iccid-range-configs/)
    await expect(page.locator('h1')).toContainText('SIM Range Configs')
  })
})
