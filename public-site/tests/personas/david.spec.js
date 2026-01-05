/**
 * David - Concerned Citizen Persona Test
 *
 * Background: Resident worried about local issues, moderate tech skills
 * Goals: Understand what happened at meetings, find decisions on topics he cares about
 * Behaviors: Uses filters, skims summaries, watches some videos
 */

import { test, expect } from '@playwright/test';
import { ObservationCollector } from '../utils/observation-collector.js';

const BASE_URL = process.env.BASE_URL || 'http://localhost:4321/council-meeting-analyzer';

export const PERSONA = {
  name: 'David - Concerned Citizen',
  background: 'Resident worried about local issues, moderate tech skills',
  goals: 'Understand what happened at meetings, find decisions on topics he cares about',
  behaviors: 'Uses filters, skims summaries, watches some videos'
};

test.describe.serial('David - Concerned Citizen', () => {
  const collector = new ObservationCollector(PERSONA.name);

  test.beforeAll(async () => {
    collector.startSession();
  });

  test.beforeEach(async ({ page }) => {
    page.on('console', msg => {
      if (msg.type() === 'error') {
        collector.recordError(msg.text());
      }
    });

    page.on('load', () => collector.trackPageLoad());
  });

  test.afterAll(async () => {
    collector.endSession();
    collector.saveToFile();
  });

  test('Task 1: Filter to see only City Council meetings', async ({ page }) => {
    const startTime = Date.now();
    let success = false;
    let notes = '';

    await page.goto(BASE_URL);
    await collector.captureScreenshot(page, 'homepage', 'Task 1: Looking for filter options');

    try {
      // Look for filter buttons
      const filterButtons = page.locator('.btn:has-text("City Council"), button:has-text("City Council")');

      if (await filterButtons.count() > 0) {
        await filterButtons.first().click();
        collector.trackClick();

        await page.waitForTimeout(500);
        await collector.captureScreenshot(page, 'filtered-city-council', 'Task 1: Filtered to City Council');

        // Verify URL or content changed
        const url = page.url();
        if (url.includes('type=') || url.includes('City')) {
          success = true;
          notes = 'Filter applied successfully, URL updated';
        } else {
          // Check if content changed
          const cards = page.locator('.card');
          const firstCardText = await cards.first().textContent();
          if (firstCardText && firstCardText.includes('City Council')) {
            success = true;
            notes = 'Filter applied, content shows City Council meetings';
          } else {
            notes = 'Filter clicked but unclear if it worked';
            collector.addObservation('confusion', 'Filter button clicked but no clear feedback', 'Filter buttons');
          }
        }
      } else {
        // Look for other filter mechanisms
        const typeFilter = page.locator('select, [class*="filter"]');
        if (await typeFilter.count() > 0) {
          notes = 'Found filter UI but no City Council button';
        } else {
          notes = 'No filter options found';
          collector.addObservation('frustration', 'Cannot filter meetings by type', 'Homepage');
        }
      }
    } catch (error) {
      notes = `Error: ${error.message}`;
    }

    collector.recordTask('Filter to City Council meetings', success, Date.now() - startTime, notes);
  });

  test('Task 2: Find meetings about parks or recreation', async ({ page }) => {
    const startTime = Date.now();
    let success = false;
    let notes = '';

    await page.goto(BASE_URL);

    try {
      // First try search
      const searchInput = page.locator('#search-input');

      if (await searchInput.isVisible({ timeout: 3000 })) {
        await searchInput.click();
        await searchInput.fill('parks');
        collector.trackSearch();

        const results = page.locator('.search-result, [data-pagefind-result]');
        try {
          await results.first().waitFor({ state: 'visible', timeout: 5000 });
          await collector.captureScreenshot(page, 'search-parks', 'Task 2: Searching for parks');
          success = true;
          notes = `Found ${await results.count()} results for parks`;
        } catch (waitError) {
          // No search results, try browsing
          notes = 'Search returned no results for parks';
        }
      }

      // Also scan visible meeting cards for parks topics
      if (!success) {
        const cards = await page.locator('.card').all();
        for (const card of cards.slice(0, 10)) {
          const text = await card.textContent();
          if (text && /park|recreation|outdoor/i.test(text)) {
            success = true;
            notes = 'Found parks-related content in meeting list';
            break;
          }
        }
      }

      if (!success) {
        notes = 'Could not find parks/recreation related meetings';
        collector.addObservation('note', 'Topic search may require different keywords', 'Search/browse');
      }
    } catch (error) {
      notes = `Error: ${error.message}`;
    }

    collector.recordTask('Find parks/recreation meetings', success, Date.now() - startTime, notes);
  });

  test('Task 3: Understand recent meeting decisions', async ({ page }) => {
    const startTime = Date.now();
    let success = false;
    let notes = '';

    await page.goto(BASE_URL);

    try {
      // Find and click the most recent meeting (should be first)
      const firstMeeting = page.locator('a[href*="/meetings/"]').first();

      if (await firstMeeting.count() > 0) {
        await firstMeeting.click();
        collector.trackClick();

        await page.waitForTimeout(500);
        await collector.captureScreenshot(page, 'recent-meeting', 'Task 3: Viewing recent meeting');

        // Look for summary section
        const summary = page.locator('h2:has-text("Summary"), [class*="summary"]');
        if (await summary.count() > 0) {
          await summary.first().scrollIntoViewIfNeeded();
          await collector.captureScreenshot(page, 'summary-section', 'Task 3: Reading summary');

          // Check if summary has content
          const summaryList = page.locator('ul li').first();
          if (await summaryList.count() > 0) {
            const summaryText = await summaryList.textContent();
            if (summaryText && summaryText.length > 10) {
              success = true;
              notes = 'Found summary with decision points';
            } else {
              notes = 'Summary section exists but appears empty';
              collector.addObservation('confusion', 'Summary section lacks detail', 'Meeting page');
            }
          }
        }

        // Also check for votes as indicators of decisions
        const votes = page.locator('text=Votes');
        if (await votes.count() > 0) {
          await votes.first().scrollIntoViewIfNeeded();
          await collector.captureScreenshot(page, 'votes-decisions', 'Task 3: Checking vote decisions');

          if (!success) {
            success = true;
            notes = 'Found voting records indicating decisions';
          }
        }

        if (!success) {
          collector.addObservation('frustration', 'Cannot easily understand what was decided', 'Meeting page');
        }
      }
    } catch (error) {
      notes = `Error: ${error.message}`;
    }

    collector.recordTask('Understand recent meeting decisions', success, Date.now() - startTime, notes);
  });

  test('Task 4: Click through to watch a video', async ({ page }) => {
    const startTime = Date.now();
    let success = false;
    let notes = '';

    await page.goto(BASE_URL);

    try {
      // Navigate to a meeting
      await page.locator('a[href*="/meetings/"]').first().click();
      collector.trackClick();
      await page.waitForTimeout(500);

      // Look for video link
      const videoLink = page.locator('a:has-text("Watch Video"), a:has-text("Video"), a[href*="granicus"]');
      await collector.captureScreenshot(page, 'looking-for-video', 'Task 4: Looking for video link');

      if (await videoLink.count() > 0) {
        const href = await videoLink.first().getAttribute('href');
        const target = await videoLink.first().getAttribute('target');

        if (href && (href.includes('http') || href.includes('granicus'))) {
          success = true;
          notes = `Found video link: ${href.substring(0, 50)}...`;

          // Check if it opens in new tab
          if (target === '_blank') {
            collector.addObservation('success', 'Video link opens in new tab (good UX)', 'Video link');
          } else {
            collector.addObservation('note', 'Video link might navigate away from archive', 'Video link');
          }
        } else {
          notes = 'Video element found but no external link';
        }
      } else {
        notes = 'No video link found on meeting page';
        collector.addObservation('frustration', 'Cannot find how to watch meeting video', 'Meeting page');
      }
    } catch (error) {
      notes = `Error: ${error.message}`;
    }

    collector.recordTask('Find and click video link', success, Date.now() - startTime, notes);
  });

  test('Free Exploration: Casual browsing', async ({ page }) => {
    const startTime = Date.now();

    await page.goto(BASE_URL);
    collector.addObservation('note', 'Starting casual browse as concerned citizen', 'Homepage');
    await collector.captureScreenshot(page, 'casual-start', 'Exploration: Starting casual browse');

    // Simulate how a citizen might browse
    const actions = [
      // Scroll through homepage
      async () => {
        await page.evaluate(() => window.scrollTo(0, 500));
        await page.waitForTimeout(1000);
        await page.evaluate(() => window.scrollTo(0, 1000));
        await collector.captureScreenshot(page, 'scrolled-homepage', 'Exploration: Browsing meeting list');
      },
      // Try different filter
      async () => {
        const allButton = page.locator('.btn:has-text("All")');
        if (await allButton.count() > 0) {
          await allButton.click();
          collector.trackClick();
        }
      },
      // Click random meeting
      async () => {
        const meetings = page.locator('a[href*="/meetings/"]');
        const count = await meetings.count();
        if (count > 3) {
          const randomIndex = Math.floor(Math.random() * Math.min(count, 5));
          await meetings.nth(randomIndex).click();
          collector.trackClick();
          await page.waitForTimeout(500);
          await collector.captureScreenshot(page, 'random-meeting', 'Exploration: Viewing random meeting');
        }
      },
      // Go back
      async () => {
        await page.goBack();
        collector.trackBackNavigation();
        await page.waitForTimeout(500);
      }
    ];

    for (const action of actions) {
      try {
        await action();
      } catch (e) {
        collector.addObservation('note', `Exploration interrupted: ${e.message}`, 'Casual browsing');
      }
    }

    await collector.captureScreenshot(page, 'casual-end', 'Exploration: Finished browsing');
    collector.recordTask('Casual exploration', true, Date.now() - startTime, 'Completed casual browse');
  });
});

export default PERSONA;
