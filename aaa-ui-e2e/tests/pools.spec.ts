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

  // ── Pool detail ────────────────────────────────────────────────────────────
  // GET /pools/{id}/stats now sums across the lazy `ip_pool_subnets` table
  // (total = SUM(end_ip - start_ip + 1) over all subnets, allocated = total -
  // available watermark). The detail page renders Total/Allocated/Available
  // tiles + a utilization bar — these must remain non-NaN and consistent under
  // the new query.
  test('clicking a pool row opens the detail page with utilization tiles', async ({ page }) => {
    const table = page.locator('table.tbl')
    if (!(await table.isVisible().catch(() => false))) {
      test.skip()
      return
    }
    const firstRow = table.locator('tbody tr').first()
    if ((await firstRow.count()) === 0) { test.skip(); return }

    await firstRow.click()
    await expect(page).toHaveURL(/\/pools\/[0-9a-f-]{36}/)

    // Identity fields rendered from /pools/{id}
    await expect(page.getByText('Subnet', { exact: true })).toBeVisible()
    await expect(page.getByText('Start IP', { exact: true })).toBeVisible()
    await expect(page.getByText('End IP', { exact: true })).toBeVisible()

    // Stats tiles + utilization gauge — these read from the new lazy
    // multi-subnet stats query. Numbers render with toLocaleString(), so they
    // never appear as 'NaN'.
    await expect(page.getByText('Utilization')).toBeVisible()
    await expect(page.getByText('Total', { exact: true })).toBeVisible()
    await expect(page.getByText('Allocated', { exact: true })).toBeVisible()
    await expect(page.getByText('Available', { exact: true })).toBeVisible()
    await expect(page.locator('body')).not.toContainText('NaN')
  })

  test('detail page breadcrumb returns to the list', async ({ page }) => {
    const table = page.locator('table.tbl')
    if (!(await table.isVisible().catch(() => false))) { test.skip(); return }
    const firstRow = table.locator('tbody tr').first()
    if ((await firstRow.count()) === 0) { test.skip(); return }

    await firstRow.click()
    await expect(page).toHaveURL(/\/pools\/[0-9a-f-]{36}/)
    await page.getByRole('button', { name: 'IP Pools' }).click()
    await expect(page).toHaveURL(/\/pools$/)
  })
})
