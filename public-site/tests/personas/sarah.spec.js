/**
 * Sarah - Local Journalist Persona Test
 *
 * Background: Reporter for local news, needs accurate quotes and facts
 * Goals: Fact-check claims, find source material, verify voting records
 * Behaviors: Precise searches, reads full transcripts, checks video links
 */

import { test, expect } from '@playwright/test';
import { ObservationCollector } from '../utils/observation-collector.js';

const BASE_URL = process.env.BASE_URL || 'http://localhost:4321/council-meeting-analyzer';

export const PERSONA = {
  name: 'Sarah - Local Journalist',
  background: 'Reporter for local news, needs accurate quotes and facts',
  goals: 'Fact-check claims, find source material, verify voting records',
  behaviors: 'Precise searches, reads full transcripts, checks video links'
};

test.describe.serial('Sarah - Local Journalist', () => {
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

  test('Task 1: Search for specific phrase to verify quote', async ({ page }) => {
    const startTime = Date.now();
    let success = false;
    let notes = '';

    await page.goto(BASE_URL);
    await collector.captureScreenshot(page, 'homepage', 'Task 1: Starting quote search');

    try {
      const searchInput = page.locator('#search-input');

      if (await searchInput.isVisible({ timeout: 3000 })) {
        // Search for a specific phrase
        await searchInput.click();
        await searchInput.fill('budget concerns');
        collector.trackSearch();

        const results = page.locator('.search-result, [data-pagefind-result]');
        try {
          await results.first().waitFor({ state: 'visible', timeout: 5000 });
          await collector.captureScreenshot(page, 'quote-search', 'Task 1: Search results');

          const resultCount = await results.count();
          if (resultCount > 0) {
            await results.first().click();
            collector.trackClick();
            await page.waitForTimeout(500);
            await collector.captureScreenshot(page, 'quote-result', 'Task 1: Viewing search result');

            const transcript = page.locator('[data-pagefind-body], .transcript, .prose');
            if (await transcript.count() > 0) {
              success = true;
              notes = 'Found searchable content for quote verification';
            }
          }
        } catch (waitError) {
          notes = 'No results for phrase search';
          collector.addObservation('note', 'Phrase search returned no results', 'Search');
        }
      } else {
        notes = 'Search not available';
        collector.addObservation('frustration', 'Cannot search for specific phrases', 'Homepage');
      }
    } catch (error) {
      notes = `Error: ${error.message}`;
    }

    collector.recordTask('Search for specific phrase', success, Date.now() - startTime, notes);
  });

  test('Task 2: Find exact vote count on a motion', async ({ page }) => {
    const startTime = Date.now();
    let success = false;
    let notes = '';

    await page.goto(BASE_URL);

    try {
      // Navigate to a meeting with votes
      await page.locator('a[href*="/meetings/"]').first().click();
      collector.trackClick();
      await page.waitForTimeout(500);

      // Find votes section
      const votesHeading = page.getByRole('heading', { name: /Votes/i });
      if (await votesHeading.count() > 0) {
        await votesHeading.scrollIntoViewIfNeeded();
        await collector.captureScreenshot(page, 'votes-section', 'Task 2: Examining vote counts');

        // Look for vote count information (e.g., "5-2", "Passed 7-0")
        const voteText = await page.locator('table, .vote, [class*="vote"]').first().textContent();

        if (voteText) {
          // Check for clear vote tallies
          if (/\d+-\d+|pass|fail|approve|deny/i.test(voteText)) {
            success = true;
            notes = 'Found vote count information';

            // Check if vote details are expandable
            const details = page.locator('details:has-text("individual votes")');
            if (await details.count() > 0) {
              await details.first().click();
              collector.trackClick();
              await page.waitForTimeout(300);
              await collector.captureScreenshot(page, 'vote-details', 'Task 2: Individual vote breakdown');
              collector.addObservation('success', 'Vote breakdown available for verification', 'Vote details');
            }
          } else {
            notes = 'Vote section found but counts unclear';
            collector.addObservation('confusion', 'Vote tallies not clearly displayed', 'Votes section');
          }
        }
      } else {
        notes = 'No votes section found';
        collector.addObservation('frustration', 'Cannot find voting information for fact-checking', 'Meeting page');
      }
    } catch (error) {
      notes = `Error: ${error.message}`;
    }

    collector.recordTask('Find exact vote count', success, Date.now() - startTime, notes);
  });

  test('Task 3: Verify meeting date and details', async ({ page }) => {
    const startTime = Date.now();
    let success = false;
    let notes = '';

    await page.goto(BASE_URL);

    try {
      // Click into a meeting
      await page.locator('a[href*="/meetings/"]').first().click();
      collector.trackClick();
      await page.waitForTimeout(500);
      await collector.captureScreenshot(page, 'meeting-details', 'Task 3: Checking meeting details');

      // Look for meeting info sidebar or header
      const meetingInfo = page.locator('h1, [class*="header"], [class*="info"]');

      // Check for date
      const pageContent = await page.content();
      const hasDate = /\d{4}|january|february|march|april|may|june|july|august|september|october|november|december/i.test(pageContent);

      // Check for meeting type
      const hasType = /city council|planning|commission|board/i.test(pageContent);

      if (hasDate && hasType) {
        success = true;
        notes = 'Meeting date and type clearly displayed';

        // Look for additional verification info
        const sidebar = page.locator('[class*="sidebar"], aside, .bg-base-200');
        if (await sidebar.count() > 0) {
          const sidebarText = await sidebar.first().textContent();
          if (sidebarText && sidebarText.includes('Duration')) {
            collector.addObservation('success', 'Meeting metadata well organized in sidebar', 'Meeting info');
          }
        }
      } else {
        notes = 'Meeting details incomplete';
        collector.addObservation('confusion', 'Cannot verify all meeting details', 'Meeting page');
      }
    } catch (error) {
      notes = `Error: ${error.message}`;
    }

    collector.recordTask('Verify meeting date and details', success, Date.now() - startTime, notes);
  });

  test('Task 4: Check if transcript matches video source', async ({ page }) => {
    const startTime = Date.now();
    let success = false;
    let notes = '';

    await page.goto(BASE_URL);

    try {
      await page.locator('a[href*="/meetings/"]').first().click();
      collector.trackClick();
      await page.waitForTimeout(500);

      // Find video link
      const videoLink = page.locator('a:has-text("Watch Video"), a:has-text("Granicus"), a[href*="granicus"]');
      let hasVideoLink = false;
      let videoUrl = '';

      if (await videoLink.count() > 0) {
        hasVideoLink = true;
        videoUrl = await videoLink.first().getAttribute('href');
        await collector.captureScreenshot(page, 'video-link', 'Task 4: Found video source');
      }

      // Find transcript
      const transcript = page.locator('details:has-text("transcript"), [class*="transcript"]');
      let hasTranscript = false;

      if (await transcript.count() > 0) {
        hasTranscript = true;
        await transcript.first().click();
        collector.trackClick();
        await page.waitForTimeout(300);
        await collector.captureScreenshot(page, 'transcript-view', 'Task 4: Viewing transcript');
      }

      if (hasVideoLink && hasTranscript) {
        success = true;
        notes = `Both video (${videoUrl.substring(0, 30)}...) and transcript available for cross-reference`;

        // Check for timestamp linking (ideal feature)
        const pageText = await page.content();
        if (!/\d+:\d+:\d+|\d+:\d+/i.test(pageText)) {
          collector.addObservation('note', 'Transcript lacks timestamps for video correlation', 'Transcript');
        }
      } else if (hasVideoLink) {
        notes = 'Video link found but no transcript';
        success = true; // Partial success
        collector.addObservation('note', 'Video available but no transcript for text search', 'Meeting page');
      } else if (hasTranscript) {
        notes = 'Transcript found but no video link';
        success = true; // Partial success
        collector.addObservation('note', 'Transcript available but cannot verify against video', 'Meeting page');
      } else {
        notes = 'Neither video link nor transcript found';
        collector.addObservation('frustration', 'Cannot verify source material', 'Meeting page');
      }
    } catch (error) {
      notes = `Error: ${error.message}`;
    }

    collector.recordTask('Check transcript/video correlation', success, Date.now() - startTime, notes);
  });

  test('Free Exploration: Fact-checking workflow', async ({ page }) => {
    const startTime = Date.now();

    await page.goto(BASE_URL);
    collector.addObservation('note', 'Beginning fact-checking exploration', 'Homepage');
    await collector.captureScreenshot(page, 'factcheck-start', 'Exploration: Starting');

    const actions = [
      // Check About page for data source info
      async () => {
        const aboutLink = page.locator('a:has-text("About")');
        if (await aboutLink.count() > 0) {
          await aboutLink.click();
          collector.trackClick();
          await page.waitForTimeout(500);
          await collector.captureScreenshot(page, 'about-sources', 'Exploration: Checking data sources');

          // Look for accuracy disclaimers
          const pageText = await page.content();
          if (/accuracy|disclaimer|ai-generated|verify/i.test(pageText)) {
            collector.addObservation('success', 'Found accuracy/verification information', 'About page');
          } else {
            collector.addObservation('note', 'About page should clarify data accuracy', 'About page');
          }
        }
      },
      // Search for a specific topic
      async () => {
        await page.goto(BASE_URL);
        const search = page.locator('#search-input, input[type="search"]');
        if (await search.count() > 0) {
          await search.fill('homeless');
          collector.trackSearch();
          await page.waitForTimeout(1500);
          await collector.captureScreenshot(page, 'topic-search', 'Exploration: Topic search');
        }
      },
      // Deep dive into a transcript
      async () => {
        await page.goto(BASE_URL);
        await page.locator('a[href*="/meetings/"]').nth(1).click();
        collector.trackClick();
        await page.waitForTimeout(500);

        const transcript = page.locator('details:has-text("transcript")');
        if (await transcript.count() > 0) {
          await transcript.click();
          collector.trackClick();
          await page.evaluate(() => window.scrollTo(0, 800));
          await collector.captureScreenshot(page, 'transcript-deep', 'Exploration: Reading transcript');
        }
      }
    ];

    for (const action of actions) {
      try {
        await action();
      } catch (e) {
        collector.addObservation('note', `Exploration action failed: ${e.message}`, 'Fact-checking');
      }
    }

    await collector.captureScreenshot(page, 'factcheck-end', 'Exploration: Complete');
    collector.recordTask('Fact-checking exploration', true, Date.now() - startTime, 'Completed workflow');
  });
});

export default PERSONA;
