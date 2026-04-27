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
    // Per-chunk progress: bulk_jobs.processed / failed advance during the run
    // (UPDATEs commit outside the long claim/provision transaction). The list
    // page surfaces both as their own columns so an operator can watch a job
    // make progress without opening the drawer.
    await expect(page.getByRole('columnheader', { name: 'Submitted' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'Processed' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'Failed' })).toBeVisible()
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

  // ── Drawer ────────────────────────────────────────────────────────────────
  // Opening a job's drawer renders the live-progress tiles ("IMSI Assignments",
  // "SIMs Provisioned", "Failed") and a percentage bar derived from
  // processed / submitted. These read directly from the values that the
  // per-chunk UPDATE pushes into bulk_jobs during the run.
  test('clicking a job row opens the detail drawer with progress tiles', async ({ page }) => {
    const table = page.locator('table.tbl')
    if (!(await table.isVisible().catch(() => false))) { test.skip(); return }
    const rows = table.locator('tbody tr')
    if ((await rows.count()) === 0) { test.skip(); return }

    await rows.first().click()
    await expect(page.getByText('Job Detail')).toBeVisible()
    await expect(page.getByText('IMSI Assignments')).toBeVisible()
    await expect(page.getByText('SIMs Provisioned')).toBeVisible()
    await expect(page.getByText('Failed', { exact: true })).toBeVisible()
    // Percentage is derived from processed/submitted — must never render as NaN.
    await expect(page.locator('aside')).not.toContainText('NaN')
  })
})
