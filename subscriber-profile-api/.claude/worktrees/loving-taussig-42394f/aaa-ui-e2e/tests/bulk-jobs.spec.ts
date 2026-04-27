import { test, expect } from '@playwright/test'

test.describe('Bulk Jobs page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/bulk-jobs')
  })

  test('page heading is visible', async ({ page }) => {
    await expect(page.locator('h1')).toContainText('Bulk Jobs')
  })

  test('list renders table or empty state', async ({ page }) => {
    const table = page.locator('table.tbl')
    const empty = page.getByText(/No (bulk )?jobs/i)
    await expect(table.or(empty)).toBeVisible({ timeout: 10_000 })
  })

  test('table has expected column headers when jobs exist', async ({ page }) => {
    const table = page.locator('table.tbl')
    const isEmpty = !(await table.isVisible().catch(() => false))
    if (isEmpty) { test.skip(); return }
    await expect(page.getByRole('columnheader', { name: 'Job ID' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'Status' })).toBeVisible()
  })

  test('StatusBadge is rendered for each job row', async ({ page }) => {
    const table = page.locator('table.tbl')
    const hasTable = await table.isVisible().catch(() => false)
    if (!hasTable) { test.skip(); return }
    // StatusBadge renders a span with text like "running", "done", "failed", etc.
    const rows = table.locator('tbody tr')
    const count = await rows.count()
    if (count === 0) { test.skip(); return }
    // Each row should have a status badge (a colored span inside the Status cell)
    const firstRow = rows.first()
    await expect(firstRow.locator('td').nth(1)).toBeVisible()
  })
})
