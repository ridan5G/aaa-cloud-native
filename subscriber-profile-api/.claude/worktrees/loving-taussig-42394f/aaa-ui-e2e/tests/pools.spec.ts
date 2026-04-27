import { test, expect } from '@playwright/test'

test.describe('IP Pools page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/pools')
  })

  test('page heading is visible', async ({ page }) => {
    await expect(page.getByText('Networking', { exact: true })).toBeVisible()
    await expect(page.locator('h1')).toContainText('IP Pools')
  })

  test('New Pool button is present', async ({ page }) => {
    await expect(page.getByRole('button', { name: '+ New Pool' })).toBeVisible()
  })

  test('list renders table or empty state', async ({ page }) => {
    // Either a table with headers or the empty-state message should appear
    const table = page.locator('table.tbl')
    const empty = page.getByText('No pools configured.')
    await expect(table.or(empty)).toBeVisible({ timeout: 10_000 })
  })

  test('table has expected column headers when pools exist', async ({ page }) => {
    const table = page.locator('table.tbl')
    const empty = page.getByText('No pools configured.')
    const hasTable = await table.isVisible().catch(() => false)
    const hasEmpty = await empty.isVisible().catch(() => false)
    if (!hasTable && hasEmpty) {
      test.skip()
      return
    }
    await expect(page.getByRole('columnheader', { name: 'Pool Name' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'Routing Domain' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'Subnet' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'Status' })).toBeVisible()
  })

  test('New Pool button opens modal', async ({ page }) => {
    await page.getByRole('button', { name: '+ New Pool' }).click()
    await expect(page.getByRole('heading', { name: 'New IP Pool' })).toBeVisible()
    await expect(page.getByLabel('Pool Name *')).toBeVisible()
    await expect(page.getByLabel('Subnet (CIDR) *')).toBeVisible()
    // Close modal
    await page.getByRole('button', { name: '×' }).click()
    await expect(page.getByRole('heading', { name: 'New IP Pool' })).not.toBeVisible()
  })

  test('Free CIDR Finder section is present', async ({ page }) => {
    await expect(page.getByText('Free CIDR Finder')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Find Free CIDR' })).toBeVisible()
  })
})
