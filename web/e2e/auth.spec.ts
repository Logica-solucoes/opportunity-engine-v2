import { expect, test } from '@playwright/test'
import { loggedInAdmin } from './helpers'

test('first login forces a password change, then shows the workspaces', async ({ page }) => {
  await loggedInAdmin(page)
  await expect(page).toHaveURL(/\/$/)
})
