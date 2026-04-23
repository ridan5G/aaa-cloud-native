import { test, expect } from '@playwright/test'

test.describe('IMSI Range Configs page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/range-configs')
  })

  test('page heading is visible', async ({ page }) => {
    await expect(page.getByText('Configuration', { exact: true })).toBeVisible()
    await expect(page.locator('h1')).toContainText('IMSI Range Configs')
  })

  test('New Config button is present', async ({ page }) => {
    await expect(page.getByRole('button', { name: '+ New Config' })).toBeVisible()
  })

  test('list renders table or empty state', async ({ page }) => {
    const table = page.locator('table.tbl')
    const empty = page.getByText('No range configs configured.')
    await expect(table.or(empty)).toBeVisible({ timeout: 10_000 })
  })

  test('table has expected column headers when configs exist', async ({ page }) => {
    const table = page.locator('table.tbl')
    const isEmpty = !(await table.isVisible().catch(() => false))
    if (isEmpty) { test.skip(); return }
    await expect(page.getByRole('columnheader', { name: 'ID' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'Account' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'IMSI Range' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'IP Resolution' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'Status' })).toBeVisible()
  })
})
