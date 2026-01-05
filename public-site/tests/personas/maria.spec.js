/**
 * Maria - Campaign Researcher Persona Test
 *
 * Background: Works for a local candidate, researches voting records and positions
 * Goals: Find specific votes, track council member positions, extract quotes
 * Behaviors: Heavy search user, reads transcripts, exports data mentally
 */

import { test, expect } from '@playwright/test';
import { ObservationCollector } from '../utils/observation-collector.js';

const BASE_URL = process.env.BASE_URL || 'http://localhost:4321/council-meeting-analyzer';

export const PERSONA = {
  name: 'Maria - Campaign Researcher',
  background: 'Works for a local candidate, researches voting records and positions',
  goals: 'Find specific votes, track council member positions, extract quotes',
  behaviors: 'Heavy search user, reads transcripts, exports data mentally'
};

test.describe.serial('Maria - Campaign Researcher', () => {
  // Shared collector across all tests in this file
  const collector = new ObservationCollector(PERSONA.name);

  test.beforeAll(async () => {
    collector.startSession();
  });

  test.beforeEach(async ({ page }) => {
    // Listen for console errors
    page.on('console', msg => {
      if (msg.type() === 'error') {
        collector.recordError(msg.text());
      }
    });

    // Track page navigations
    page.on('load', () => collector.trackPageLoad());
  });

  test.afterAll(async () => {
    collector.endSession();
    collector.saveToFile();
  });

  test('Task 1: Search for "housing" and find relevant meetings', async ({ page }) => {
    const startTime = Date.now();
    let success = false;
    let notes = '';

    await page.goto(BASE_URL);
    await collector.captureScreenshot(page, 'homepage-start', 'Task 1: Beginning housing search');

    try {
      // Look for search functionality
      const searchInput = page.locator('#search-input');

      if (await searchInput.isVisible({ timeout: 3000 })) {
        collector.trackClick();
        await searchInput.click();
        await searchInput.fill('housing');
        collector.trackSearch();

        // Wait for search results to appear (with timeout)
        const results = page.locator('.search-result, [data-pagefind-result]');
        try {
          await results.first().waitFor({ state: 'visible', timeout: 5000 });
          await collector.captureScreenshot(page, 'search-housing', 'Task 1: Search results for housing');

          const resultCount = await results.count();
          if (resultCount > 0) {
            notes = `Found ${resultCount} search results for housing`;
            success = true;

            // Click first result
            await results.first().click();
            collector.trackClick();
            await page.waitForTimeout(500);
            await collector.captureScreenshot(page, 'search-result-click', 'Task 1: Clicked search result');
          }
        } catch (waitError) {
          // Results didn't appear in time
          await collector.captureScreenshot(page, 'search-no-results', 'Task 1: No results appeared');
          notes = 'Search executed but no results appeared within timeout';
          collector.addObservation('confusion', 'Search results not appearing or taking too long', 'Search results area');
        }
      } else {
        notes = 'Could not locate search input';
        collector.addObservation('frustration', 'Search functionality not easily discoverable', 'Homepage');
      }
    } catch (error) {
      notes = `Error during search: ${error.message}`;
      collector.addObservation('frustration', error.message, 'Search functionality');
    }

    collector.recordTask('Search for housing meetings', success, Date.now() - startTime, notes);
  });

  test('Task 2: Find how a council member voted on a topic', async ({ page }) => {
    const startTime = Date.now();
    let success = false;
    let notes = '';

    await page.goto(BASE_URL);

    try {
      // Navigate to a meeting with votes
      const meetingLink = page.locator('a[href*="/meetings/"]').first();
      await meetingLink.click();
      collector.trackClick();
      collector.trackPageLoad();

      await page.waitForTimeout(500);
      await collector.captureScreenshot(page, 'meeting-page', 'Task 2: Viewing meeting page');

      // Look for votes section
      const votesSection = page.locator('text=Votes').first();
      if (await votesSection.count() > 0) {
        await votesSection.scrollIntoViewIfNeeded();
        await collector.captureScreenshot(page, 'votes-section', 'Task 2: Votes section');

        // Look for expandable vote details
        const voteDetails = page.locator('details:has-text("View individual votes")');
        if (await voteDetails.count() > 0) {
          await voteDetails.first().click();
          collector.trackClick();
          await page.waitForTimeout(300);
          await collector.captureScreenshot(page, 'vote-details-expanded', 'Task 2: Individual votes expanded');

          // Check if individual votes are shown
          const badges = page.locator('details:has-text("View individual votes") .badge');
          if (await badges.count() > 0) {
            success = true;
            notes = `Found individual vote records with ${await badges.count()} vote badges`;
          } else {
            notes = 'Vote details expanded but no individual votes displayed';
            collector.addObservation('confusion', 'Vote details section lacks individual breakdown', 'Vote details');
          }
        } else {
          notes = 'No expandable vote details found';
          collector.addObservation('note', 'Vote details not expandable - may need UI enhancement', 'Votes section');
        }
      } else {
        notes = 'Votes section not found on meeting page';
        collector.addObservation('frustration', 'Cannot find voting information', 'Meeting page');
      }
    } catch (error) {
      notes = `Error: ${error.message}`;
    }

    collector.recordTask('Find council member votes', success, Date.now() - startTime, notes);
  });

  test('Task 3: Locate meeting from specific date range', async ({ page }) => {
    const startTime = Date.now();
    let success = false;
    let notes = '';

    await page.goto(BASE_URL);
    await collector.captureScreenshot(page, 'homepage-dates', 'Task 3: Looking for date filtering');

    try {
      // Look for date filter or date information
      const dateFilter = page.locator('input[type="date"], select:has-text("date"), [class*="date"]');

      if (await dateFilter.count() > 0) {
        notes = 'Date filter UI found';
        success = true;
      } else {
        // Check if meetings show dates
        const meetingCards = page.locator('.card');
        const firstCard = meetingCards.first();

        if (await firstCard.count() > 0) {
          const cardText = await firstCard.textContent();
          // Look for date-like patterns
          if (cardText && /\d{4}|january|february|march|april|may|june|july|august|september|october|november|december/i.test(cardText)) {
            notes = 'Meetings show dates but no date range filter available';
            success = true; // Partial success - dates visible
            collector.addObservation('note', 'Date information visible but no date range filtering', 'Meeting cards');
          } else {
            notes = 'No date information visible on meeting cards';
            collector.addObservation('frustration', 'Cannot identify meetings by date', 'Homepage');
          }
        }
      }

      // Look at multiple cards to understand date organization
      const cards = await page.locator('.card').all();
      if (cards.length > 2) {
        await collector.captureScreenshot(page, 'meeting-list', 'Task 3: Reviewing meeting dates');
      }
    } catch (error) {
      notes = `Error: ${error.message}`;
    }

    collector.recordTask('Locate meetings by date', success, Date.now() - startTime, notes);
  });

  test('Task 4: Find quotes about Valley\'s Edge development', async ({ page }) => {
    const startTime = Date.now();
    let success = false;
    let notes = '';

    await page.goto(BASE_URL);

    try {
      // Search for Valley's Edge
      const searchInput = page.locator('#search-input');

      if (await searchInput.isVisible({ timeout: 3000 })) {
        await searchInput.click();
        await searchInput.fill("Valley's Edge");
        collector.trackSearch();

        const results = page.locator('.search-result, [data-pagefind-result]');
        try {
          await results.first().waitFor({ state: 'visible', timeout: 5000 });
          await collector.captureScreenshot(page, 'search-valleys-edge', "Task 4: Search for Valley's Edge");

          const resultCount = await results.count();
          if (resultCount > 0) {
            // Click into a result
            await results.first().click();
            collector.trackClick();
            await page.waitForTimeout(500);

            // Look for transcript
            const transcript = page.locator('details:has-text("transcript")');
            if (await transcript.count() > 0) {
              await transcript.click();
              collector.trackClick();
              await page.waitForTimeout(300);
              await collector.captureScreenshot(page, 'transcript-view', 'Task 4: Viewing transcript for quotes');

              success = true;
              notes = 'Found search results and accessed transcript';

              // Check if quotes are highlighted or easy to find
              const highlightedText = page.locator('mark, .highlight, [class*="highlight"]');
              if (await highlightedText.count() === 0) {
                collector.addObservation('note', 'Search matches not highlighted in transcript', 'Transcript section');
              }
            } else {
              notes = 'Found results but transcript not available';
              collector.addObservation('frustration', 'Cannot access full transcript from search result', 'Meeting page');
            }
          }
        } catch (waitError) {
          notes = "No search results for Valley's Edge";
          collector.addObservation('note', "Search for Valley's Edge returned no results", 'Search');
        }
      } else {
        notes = 'Search not available';
        collector.addObservation('frustration', 'Cannot search for specific topics', 'Homepage');
      }
    } catch (error) {
      notes = `Error: ${error.message}`;
    }

    collector.recordTask("Find Valley's Edge quotes", success, Date.now() - startTime, notes);
  });

  test('Free Exploration: Campaign research workflow', async ({ page }) => {
    const startTime = Date.now();

    await page.goto(BASE_URL);
    collector.addObservation('note', 'Beginning free exploration as campaign researcher', 'Homepage');
    await collector.captureScreenshot(page, 'exploration-start', 'Free exploration: Starting');

    // Simulate research workflow
    const actions = [
      // Browse different meeting types
      async () => {
        const cityCouncilFilter = page.locator('.btn:has-text("City Council")');
        if (await cityCouncilFilter.count() > 0) {
          await cityCouncilFilter.click();
          collector.trackClick();
          await page.waitForTimeout(500);
          await collector.captureScreenshot(page, 'filter-city-council', 'Exploration: Filtered to City Council');
        }
      },
      // Check About page for data accuracy info
      async () => {
        const aboutLink = page.locator('a:has-text("About")');
        if (await aboutLink.count() > 0) {
          await aboutLink.click();
          collector.trackClick();
          await page.waitForTimeout(500);
          await collector.captureScreenshot(page, 'about-page', 'Exploration: Checking About page');
          collector.addObservation('note', 'Researcher checking data sources and accuracy disclaimers', 'About page');
        }
      },
      // Go back and explore a meeting deeply
      async () => {
        await page.goto(BASE_URL);
        collector.trackBackNavigation();
        const meeting = page.locator('a[href*="/meetings/"]').nth(2);
        if (await meeting.count() > 0) {
          await meeting.click();
          collector.trackClick();
          await page.waitForTimeout(500);

          // Scroll through the page
          await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight / 2));
          await collector.captureScreenshot(page, 'meeting-deep-dive', 'Exploration: Deep dive into meeting');
        }
      }
    ];

    for (const action of actions) {
      try {
        await action();
      } catch (e) {
        collector.addObservation('note', `Exploration action failed: ${e.message}`, 'Free exploration');
      }
    }

    await collector.captureScreenshot(page, 'exploration-end', 'Free exploration: Complete');
    collector.recordTask('Free exploration', true, Date.now() - startTime, 'Completed exploration workflow');
  });
});

export default PERSONA;
