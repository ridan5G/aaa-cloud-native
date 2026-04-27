import { test, expect } from '@playwright/test'

const NAV_ITEMS = [
  { label: 'Dashboard',        url: /\/dashboard/ },
  { label: 'SIMs',             url: /\/devices/ },
  { label: 'IP Pools',         url: /\/pools/ },
  { label: 'Routing Domains',  url: /\/routing-domains/ },
  { label: 'SIM Range configs',url: /\/iccid-range-configs/ },
  { label: 'Bulk Jobs',        url: /\/bulk-jobs/ },
  { label: 'New SIM',          url: /\/sim-profile-types/ },
  { label: 'Documentation',    url: /\/documentation/ },
]

test.describe('Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/dashboard')
  })

  test('sidebar renders all nav items', async ({ page }) => {
    const nav = page.locator('nav')
    for (const item of NAV_ITEMS) {
      await expect(nav.getByText(item.label, { exact: true })).toBeVisible()
    }
  })

  test('each nav link navigates to the correct route', async ({ page }) => {
    for (const item of NAV_ITEMS) {
      const nav = page.locator('nav')
      await nav.getByText(item.label, { exact: true }).click()
      await expect(page).toHaveURL(item.url)
    }
  })

  test('toggle sidebar collapses and expands nav labels', async ({ page }) => {
    const toggleBtn = page.getByRole('button', { name: 'Toggle sidebar' })
    await toggleBtn.click()
    // After collapse, text labels should be hidden (sidebar is icon-only)
    await expect(page.locator('nav').getByText('Dashboard', { exact: true })).not.toBeVisible()
    await toggleBtn.click()
    await expect(page.locator('nav').getByText('Dashboard', { exact: true })).toBeVisible()
  })
})
