import { test, expect } from '@playwright/test'

test.describe('SIMs / Subscribers page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/devices')
  })

  test('page heading is visible', async ({ page }) => {
    await expect(page.getByText('Provisioning', { exact: true })).toBeVisible()
    await expect(page.locator('h1')).toContainText('SIMs')
  })

  test('filter inputs are present', async ({ page }) => {
    await expect(page.getByLabel('IMSI Prefix')).toBeVisible()
    await expect(page.getByLabel('ICCID Prefix')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Search' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Reset' })).toBeVisible()
  })

  test('action buttons are present', async ({ page }) => {
    await expect(page.getByRole('button', { name: /Export CSV/i })).toBeVisible()
    await expect(page.getByRole('link', { name: '+ New Profile' })).toBeVisible()
    await expect(page.getByRole('link', { name: '↑ Bulk Import' })).toBeVisible()
  })

  test('list renders table or empty state', async ({ page }) => {
    const table = page.locator('table')
    const empty = page.getByText(/No (profiles|devices|sims)/i)
    await expect(table.or(empty)).toBeVisible({ timeout: 10_000 })
  })

  test('global search bar is present in header', async ({ page }) => {
    await expect(page.getByPlaceholder('Search SIM or ICCID…')).toBeVisible()
  })
})
