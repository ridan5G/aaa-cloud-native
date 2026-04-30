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

  // ── Subnets panel ─────────────────────────────────────────────────────────
  // Pools have a primary subnet inserted on creation plus zero or more
  // secondary subnets appended via POST /pools/{id}/subnets. The detail page
  // surfaces them in a "Subnets" card with priority/range/claimed columns
  // and an "Add subnet" dialog that hits the same endpoint.
  test('detail page renders the Subnets panel with the primary subnet', async ({ page }) => {
    const table = page.locator('table.tbl')
    if (!(await table.isVisible().catch(() => false))) { test.skip(); return }
    const firstRow = table.locator('tbody tr').first()
    if ((await firstRow.count()) === 0) { test.skip(); return }

    await firstRow.click()
    await expect(page).toHaveURL(/\/pools\/[0-9a-f-]{36}/)

    await expect(page.getByRole('heading', { name: 'Subnets' })).toBeVisible()
    await expect(page.getByTestId('add-subnet-button')).toBeVisible()
    // Primary subnet row carries the "(primary)" tag and never offers Remove.
    await expect(page.getByText('(primary)')).toBeVisible()
  })

  test('Add Subnet button opens the dialog with CIDR + optional bounds', async ({ page }) => {
    const table = page.locator('table.tbl')
    if (!(await table.isVisible().catch(() => false))) { test.skip(); return }
    const firstRow = table.locator('tbody tr').first()
    if ((await firstRow.count()) === 0) { test.skip(); return }

    await firstRow.click()
    await page.getByTestId('add-subnet-button').click()

    const dialog = page.getByTestId('add-subnet-dialog')
    await expect(dialog).toBeVisible()
    await expect(dialog.getByText('Subnet (CIDR) *')).toBeVisible()
    await expect(dialog.getByText('Start IP')).toBeVisible()
    await expect(dialog.getByText('End IP')).toBeVisible()
    // Submit button is disabled until a CIDR is typed.
    await expect(page.getByTestId('add-subnet-submit')).toBeDisabled()
    await page.getByTestId('subnet-input').fill('10.99.0.0/24')
    await expect(page.getByTestId('add-subnet-submit')).toBeEnabled()
    // Close without submitting so we don't mutate cluster state.
    await dialog.getByRole('button', { name: '×' }).click()
    await expect(dialog).not.toBeVisible()
  })

  // ── Add-subnet Suggest-CIDR helper ────────────────────────────────────────
  // The Add-subnet dialog mirrors NewPoolModal: it carries a "Suggest a free
  // subnet" helper that hits GET /routing-domains/{id}/suggest-cidr?size=N and
  // auto-fills the CIDR field. The helper only renders when the pool's routing
  // domain advertises allowed_prefixes.
  test('Add Subnet dialog exposes the Suggest-CIDR helper when the domain has prefixes', async ({ page }) => {
    const table = page.locator('table.tbl')
    if (!(await table.isVisible().catch(() => false))) { test.skip(); return }
    const firstRow = table.locator('tbody tr').first()
    if ((await firstRow.count()) === 0) { test.skip(); return }

    await firstRow.click()
    await page.getByTestId('add-subnet-button').click()

    const dialog = page.getByTestId('add-subnet-dialog')
    await expect(dialog).toBeVisible()

    // Helper is conditional on allowed_prefixes — skip silently if the seeded
    // routing domain has none rather than failing the suite.
    const suggestInput = page.getByTestId('suggest-size-input')
    if (!(await suggestInput.isVisible().catch(() => false))) {
      await dialog.getByRole('button', { name: '×' }).click()
      test.skip()
      return
    }

    await expect(dialog.getByText('Suggest a free subnet')).toBeVisible()
    await expect(page.getByTestId('suggest-find-button')).toBeDisabled()
    await suggestInput.fill('64')
    await expect(page.getByTestId('suggest-find-button')).toBeEnabled()
    // Don't actually click Find — that would mutate nothing but depends on the
    // routing domain having free space; just close.
    await dialog.getByRole('button', { name: '×' }).click()
    await expect(dialog).not.toBeVisible()
  })
})
