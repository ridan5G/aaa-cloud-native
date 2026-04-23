import { test, expect } from '@playwright/test'

const E2E_DOMAIN = `e2e-test-${Date.now()}`

test.describe('Routing Domains page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/routing-domains')
  })

  test('page heading is visible', async ({ page }) => {
    await expect(page.getByText('Networking', { exact: true })).toBeVisible()
    await expect(page.locator('h1')).toContainText('Routing Domains')
  })

  test('New Domain button is present', async ({ page }) => {
    await expect(page.getByRole('button', { name: '+ New Domain' })).toBeVisible()
  })

  test('list renders table or empty state', async ({ page }) => {
    const table = page.locator('table.tbl')
    const empty = page.getByText('No routing domains configured.')
    await expect(table.or(empty)).toBeVisible({ timeout: 10_000 })
  })

  test('table has expected column headers when domains exist', async ({ page }) => {
    const table = page.locator('table.tbl')
    const isEmpty = !(await table.isVisible().catch(() => false))
    if (isEmpty) { test.skip(); return }
    await expect(page.getByRole('columnheader', { name: 'Name' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'Description' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'Allowed Prefixes' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'Pools' })).toBeVisible()
  })

  test('New Domain modal opens and closes', async ({ page }) => {
    await page.getByRole('button', { name: '+ New Domain' }).click()
    await expect(page.getByRole('heading', { name: 'New Routing Domain' })).toBeVisible()
    await expect(page.getByLabel('Name *')).toBeVisible()
    await page.getByRole('button', { name: '×' }).click()
    await expect(page.getByRole('heading', { name: 'New Routing Domain' })).not.toBeVisible()
  })

  test('create routing domain, verify in list, then delete it', async ({ page }) => {
    // Open modal and create
    await page.getByRole('button', { name: '+ New Domain' }).click()
    await page.getByLabel('Name *').fill(E2E_DOMAIN)
    await page.getByLabel('Description (optional)').fill('Created by E2E test — safe to delete')
    await page.getByRole('button', { name: 'Create Domain' }).click()

    // Modal should close and domain should appear in the list
    await expect(page.getByRole('heading', { name: 'New Routing Domain' })).not.toBeVisible()
    await expect(page.getByText(E2E_DOMAIN)).toBeVisible({ timeout: 10_000 })

    // Navigate to detail page via clicking the row
    await page.getByText(E2E_DOMAIN).click()
    await expect(page).toHaveURL(/\/routing-domains\//)
    await expect(page.locator('h2').first()).toContainText(E2E_DOMAIN)

    // Delete
    await page.getByRole('button', { name: 'Delete' }).click()
    page.once('dialog', d => d.accept())
    await expect(page).toHaveURL(/\/routing-domains$/, { timeout: 10_000 })
    await expect(page.getByText(E2E_DOMAIN)).not.toBeVisible()
  })
})
