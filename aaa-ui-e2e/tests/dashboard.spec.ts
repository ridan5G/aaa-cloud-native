import { test, expect } from '@playwright/test'

test.describe('Dashboard page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/dashboard')
  })

  test('page title and overview label are visible', async ({ page }) => {
    await expect(page.getByText('Overview')).toBeVisible()
    await expect(page.locator('h1')).toContainText('Dashboard')
  })

  test('all four stat cards are present', async ({ page }) => {
    await expect(page.getByText('Active SIMs')).toBeVisible()
    await expect(page.getByText('IP Pools')).toBeVisible()
    await expect(page.getByText('Running Jobs')).toBeVisible()
    await expect(page.getByText('Failed Jobs')).toBeVisible()
  })

  test('Pool Utilization section is present', async ({ page }) => {
    await expect(page.getByText('Pool Utilization')).toBeVisible()
    await expect(page.getByRole('link', { name: 'View all →' }).first()).toBeVisible()
  })

  test('Recent Bulk Jobs section is present', async ({ page }) => {
    await expect(page.getByText('Recent Bulk Jobs')).toBeVisible()
  })

  test('Quick Actions links are present', async ({ page }) => {
    await expect(page.getByText('Quick Actions')).toBeVisible()
    await expect(page.getByRole('link', { name: '+ New Profile' })).toBeVisible()
    await expect(page.getByRole('link', { name: '↑ Bulk Import' })).toBeVisible()
  })
})
