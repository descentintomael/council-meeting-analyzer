// Playwright tests for Chico Council Archive site
import { test, expect } from '@playwright/test';

const BASE_URL = process.env.BASE_URL || 'http://localhost:4321/council-meeting-analyzer';

test.describe('Site Navigation', () => {
  test('homepage loads successfully', async ({ page }) => {
    const response = await page.goto(BASE_URL);
    expect(response.status()).toBe(200);
    await expect(page.locator('h1')).toContainText('Chico City Council Archive');
  });

  test('meeting cards link to meeting pages', async ({ page }) => {
    await page.goto(BASE_URL);

    // Get first meeting card link
    const firstCard = page.locator('a[href*="/meetings/"]').first();
    await expect(firstCard).toBeVisible();

    const href = await firstCard.getAttribute('href');
    expect(href).toMatch(/\/council-meeting-analyzer\/meetings\/\d+/);

    // Click and verify navigation
    await firstCard.click();
    await expect(page).toHaveURL(/\/meetings\/\d+/);
    await expect(page.locator('h1')).toBeVisible();
  });

  test('back link from meeting page works', async ({ page }) => {
    await page.goto(BASE_URL);

    // Navigate to a meeting
    await page.locator('a[href*="/meetings/"]').first().click();
    await expect(page).toHaveURL(/\/meetings\/\d+/);

    // Click back link
    await page.locator('a:has-text("Back to meetings")').click();
    await expect(page).toHaveURL(/\/council-meeting-analyzer\/?$/);
  });

  test('filter buttons work', async ({ page }) => {
    await page.goto(BASE_URL);

    // Click City Council filter (use the filter area, not nav)
    await page.locator('.btn:has-text("City Council")').click();
    await expect(page).toHaveURL(/type=City%20Council/);

    // Click All to clear filter
    await page.locator('.btn:has-text("All")').click();
    await expect(page).not.toHaveURL(/type=/);
  });

  test('nav links work', async ({ page }) => {
    await page.goto(BASE_URL);

    // Test Meetings nav link (use first() for desktop nav, there's also one in mobile dropdown)
    const meetingsLink = page.locator('header nav a:has-text("Meetings")').first();
    await expect(meetingsLink).toHaveAttribute('href', /\/council-meeting-analyzer\//);

    // Test Members nav link
    const membersLink = page.locator('header nav a:has-text("Members")');
    await expect(membersLink).toHaveAttribute('href', /\/council-meeting-analyzer\/members/);

    // Test Topics nav link
    const topicsLink = page.locator('header nav a:has-text("Topics")');
    await expect(topicsLink).toHaveAttribute('href', /\/council-meeting-analyzer\/topics/);
  });
});

test.describe('Meeting Page Content', () => {
  test('meeting page has required sections', async ({ page }) => {
    await page.goto(BASE_URL);
    await page.locator('a[href*="/meetings/"]').first().click();

    // Check for key sections (use heading role for specificity)
    await expect(page.locator('h1')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Summary' })).toBeVisible();
    await expect(page.getByRole('heading', { name: /Votes/ })).toBeVisible();
  });

  test('video link opens external URL', async ({ page }) => {
    await page.goto(BASE_URL);
    await page.locator('a[href*="/meetings/"]').first().click();

    const videoLink = page.locator('a:has-text("Watch Video")');
    if (await videoLink.count() > 0) {
      const href = await videoLink.getAttribute('href');
      expect(href).toMatch(/^https?:\/\//);
      expect(await videoLink.getAttribute('target')).toBe('_blank');
    }
  });

  test('vote table expands to show individual votes', async ({ page }) => {
    await page.goto(BASE_URL);
    await page.locator('a[href*="/meetings/"]').first().click();

    const details = page.locator('details:has-text("View individual votes")').first();
    if (await details.count() > 0) {
      await details.click();
      await expect(details.locator('.badge')).toBeVisible();
    }
  });

  test('transcript section is collapsible', async ({ page }) => {
    await page.goto(BASE_URL);
    await page.locator('a[href*="/meetings/"]').first().click();

    const transcriptDetails = page.locator('details:has-text("Click to expand transcript")');
    if (await transcriptDetails.count() > 0) {
      // Initially collapsed
      const content = transcriptDetails.locator('.prose');
      await expect(content).not.toBeVisible();

      // Expand
      await transcriptDetails.click();
      await expect(content).toBeVisible();
    }
  });
});

test.describe('No Broken Links', () => {
  test('all internal links return 200', async ({ page }) => {
    await page.goto(BASE_URL);

    // Get all hrefs at once using evaluate
    const hrefs = await page.$$eval('a[href^="/council-meeting-analyzer"]', anchors =>
      anchors.map(a => a.getAttribute('href')).filter(Boolean)
    );

    const checkedUrls = new Set();
    const brokenLinks = [];

    // Check unique URLs (limit to 20 for speed)
    const uniqueHrefs = [...new Set(hrefs)].slice(0, 20);

    for (const href of uniqueHrefs) {
      if (checkedUrls.has(href)) continue;
      checkedUrls.add(href);

      const response = await page.goto(`http://localhost:4321${href}`, { timeout: 10000 });
      if (response && response.status() >= 400) {
        brokenLinks.push({ href, status: response.status() });
      }
    }

    expect(brokenLinks).toEqual([]);
  });
});
