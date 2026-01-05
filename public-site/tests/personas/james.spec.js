/**
 * James - First-Time Visitor Persona Test
 *
 * Background: Just heard about the site, doesn't know what it offers
 * Goals: Understand what this site is and if it's useful
 * Behaviors: Reads about page, browses randomly, may leave quickly if confused
 */

import { test, expect } from '@playwright/test';
import { ObservationCollector } from '../utils/observation-collector.js';

const BASE_URL = process.env.BASE_URL || 'http://localhost:4321/council-meeting-analyzer';

export const PERSONA = {
  name: 'James - First-Time Visitor',
  background: 'Just heard about the site, doesn\'t know what it offers',
  goals: 'Understand what this site is and if it\'s useful',
  behaviors: 'Reads about page, browses randomly, may leave quickly if confused'
};

test.describe.serial('James - First-Time Visitor', () => {
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

  test('Task 1: Understand site purpose within 10 seconds', async ({ page }) => {
    const startTime = Date.now();
    let success = false;
    let notes = '';

    await page.goto(BASE_URL);

    // Capture what user sees immediately
    await collector.captureScreenshot(page, 'first-impression', 'Task 1: First impression');

    try {
      // Look for clear value proposition
      const h1 = page.locator('h1');
      const h1Text = await h1.textContent();

      // Check for explanatory subtitle or tagline
      const subtitle = page.locator('h1 + p, h1 + div, .hero p, [class*="subtitle"]');
      let hasSubtitle = false;
      if (await subtitle.count() > 0) {
        hasSubtitle = true;
      }

      // Check if purpose is clear from headline
      const pageContent = await page.content();
      const clarityIndicators = [
        /council|meeting|archive/i.test(h1Text || ''),
        /chico|city/i.test(h1Text || ''),
        /search|browse|find/i.test(pageContent)
      ];

      const clarityScore = clarityIndicators.filter(Boolean).length;

      if (clarityScore >= 2) {
        success = true;
        notes = `Clear headline: "${h1Text?.substring(0, 50)}"`;
      } else {
        notes = 'Site purpose not immediately clear';
        collector.addObservation('confusion', 'New visitor may not understand site purpose from homepage', 'Homepage hero');
      }

      // Check for visual hierarchy
      const cards = await page.locator('.card').count();
      if (cards > 0) {
        collector.addObservation('note', `${cards} meeting cards visible - content is discoverable`, 'Homepage');
      }

      // Record time to understand
      const understandingTime = Date.now() - startTime;
      if (understandingTime > 10000) {
        collector.addObservation('note', 'Understanding took longer than 10 seconds', 'Homepage');
      }
    } catch (error) {
      notes = `Error: ${error.message}`;
    }

    collector.recordTask('Understand site purpose', success, Date.now() - startTime, notes);
  });

  test('Task 2: Find and understand About page', async ({ page }) => {
    const startTime = Date.now();
    let success = false;
    let notes = '';

    await page.goto(BASE_URL);
    await collector.captureScreenshot(page, 'looking-for-about', 'Task 2: Looking for About link');

    try {
      // Look for About link
      const aboutLink = page.locator('a:has-text("About"), nav a:has-text("About")');

      if (await aboutLink.count() > 0) {
        await aboutLink.first().click();
        collector.trackClick();
        await page.waitForTimeout(500);
        await collector.captureScreenshot(page, 'about-page', 'Task 2: About page');

        // Check for key information sections
        const pageText = await page.content();

        const hasDataSource = /source|granicus|video|data/i.test(pageText);
        const hasAccuracy = /accuracy|ai|generated|verify/i.test(pageText);
        const hasFeatures = /feature|search|filter|transcript/i.test(pageText);

        const infoScore = [hasDataSource, hasAccuracy, hasFeatures].filter(Boolean).length;

        if (infoScore >= 2) {
          success = true;
          notes = 'About page explains site well';

          // Check for warning about AI content
          const warning = page.locator('.alert, [class*="warning"]');
          if (await warning.count() > 0) {
            collector.addObservation('success', 'Clear AI accuracy warning present', 'About page');
          }
        } else {
          notes = 'About page lacks key information';
          collector.addObservation('confusion', 'About page should better explain data sources and accuracy', 'About page');
        }
      } else {
        notes = 'About link not found';
        collector.addObservation('frustration', 'Cannot find About page to learn more', 'Navigation');
      }
    } catch (error) {
      notes = `Error: ${error.message}`;
    }

    collector.recordTask('Find and read About page', success, Date.now() - startTime, notes);
  });

  test('Task 3: Browse to meeting and understand structure', async ({ page }) => {
    const startTime = Date.now();
    let success = false;
    let notes = '';

    await page.goto(BASE_URL);

    try {
      // Find and click a meeting
      const meetingCard = page.locator('a[href*="/meetings/"], .card a').first();

      if (await meetingCard.count() > 0) {
        await collector.captureScreenshot(page, 'before-click', 'Task 3: Selecting a meeting');

        await meetingCard.click();
        collector.trackClick();
        await page.waitForTimeout(500);
        await collector.captureScreenshot(page, 'meeting-structure', 'Task 3: Meeting page structure');

        // Check for understandable structure
        const headings = await page.locator('h1, h2').all();
        const headingTexts = await Promise.all(headings.map(h => h.textContent()));

        // Look for familiar sections
        const hasTitle = headingTexts.some(t => t && t.length > 5);
        const hasSummary = headingTexts.some(t => /summary/i.test(t || ''));
        const hasVotes = headingTexts.some(t => /vote/i.test(t || ''));

        if (hasTitle && (hasSummary || hasVotes)) {
          success = true;
          notes = 'Meeting page structure is understandable';

          // Check for overwhelming content
          const pageHeight = await page.evaluate(() => document.body.scrollHeight);
          if (pageHeight > 3000) {
            collector.addObservation('note', 'Page is long - may overwhelm new visitors', 'Meeting page');
          }
        } else {
          notes = 'Meeting page structure unclear';
          collector.addObservation('confusion', 'New visitor may not understand meeting page sections', 'Meeting page');
        }

        // Check for back navigation
        const backLink = page.locator('a:has-text("Back"), a:has-text("Home"), a[href*="council-meeting"]');
        if (await backLink.count() > 0) {
          collector.addObservation('success', 'Clear navigation back to homepage', 'Meeting page');
        } else {
          collector.addObservation('note', 'Back navigation could be more prominent', 'Meeting page');
        }
      } else {
        notes = 'Could not find meetings to browse';
        collector.addObservation('frustration', 'No clear entry point to browse meetings', 'Homepage');
      }
    } catch (error) {
      notes = `Error: ${error.message}`;
    }

    collector.recordTask('Browse meeting and understand structure', success, Date.now() - startTime, notes);
  });

  test('Task 4: Attempt search without specific goal', async ({ page }) => {
    const startTime = Date.now();
    let success = false;
    let notes = '';

    await page.goto(BASE_URL);

    try {
      // Find search
      const searchInput = page.locator('#search-input');
      await collector.captureScreenshot(page, 'finding-search', 'Task 4: Looking for search');

      if (await searchInput.isVisible({ timeout: 3000 })) {
        // Check for placeholder text guidance
        const placeholder = await searchInput.getAttribute('placeholder');

        if (placeholder) {
          notes = `Search has placeholder: "${placeholder}"`;
          if (/example|try|keyword/i.test(placeholder)) {
            collector.addObservation('success', 'Search placeholder provides guidance', 'Search');
          }
        }

        // Try a vague search term
        await searchInput.click();
        collector.trackClick();
        await searchInput.fill('city');
        collector.trackSearch();

        const results = page.locator('.search-result, [data-pagefind-result]');
        try {
          await results.first().waitFor({ state: 'visible', timeout: 5000 });
          await collector.captureScreenshot(page, 'vague-search', 'Task 4: Search results');
          success = true;
          notes += ` - Found ${await results.count()} results for vague term`;

          // Check if results are understandable
          const resultText = await results.first().textContent();
          if (resultText && resultText.length > 20) {
            collector.addObservation('success', 'Search results show context', 'Search results');
          }
        } catch (waitError) {
          notes += ' - No results for common term';
          collector.addObservation('confusion', 'Search may need broader matching for new users', 'Search');
        }
      } else {
        notes = 'Search not readily visible';
        collector.addObservation('note', 'New visitor may not find search functionality', 'Homepage');
      }
    } catch (error) {
      notes = `Error: ${error.message}`;
    }

    collector.recordTask('Attempt exploratory search', success, Date.now() - startTime, notes);
  });

  test('Free Exploration: New user discovery', async ({ page }) => {
    const startTime = Date.now();

    await page.goto(BASE_URL);
    collector.addObservation('note', 'Starting new user discovery journey', 'Homepage');
    await collector.captureScreenshot(page, 'discovery-start', 'Exploration: First landing');

    // Simulate how a new user might explore
    const actions = [
      // Scroll to see what's below the fold
      async () => {
        await page.evaluate(() => window.scrollTo(0, 400));
        await page.waitForTimeout(800);
        await collector.captureScreenshot(page, 'below-fold', 'Exploration: Content below fold');

        const cardsVisible = await page.locator('.card:visible').count();
        if (cardsVisible < 3) {
          collector.addObservation('note', 'Limited content visible above fold', 'Homepage layout');
        }
      },
      // Click something that looks interesting
      async () => {
        const interestingElements = page.locator('.badge, .btn, a:not([href*="http"])');
        const count = await interestingElements.count();
        if (count > 0) {
          const randomIndex = Math.floor(Math.random() * Math.min(count, 5));
          await interestingElements.nth(randomIndex).click();
          collector.trackClick();
          await page.waitForTimeout(500);
          await collector.captureScreenshot(page, 'curious-click', 'Exploration: Curious click');
        }
      },
      // Try to go back
      async () => {
        await page.goBack();
        collector.trackBackNavigation();
        await page.waitForTimeout(500);

        // Check if we're back on a sensible page
        const url = page.url();
        if (!url.includes('council-meeting')) {
          collector.addObservation('confusion', 'Navigation led outside the archive', 'Navigation');
        }
      },
      // Look for help or instructions
      async () => {
        await page.goto(BASE_URL);
        const helpElements = page.locator('text=help, text=guide, text=how to, [class*="help"]');
        if (await helpElements.count() === 0) {
          collector.addObservation('note', 'No explicit help/guide for new users', 'Homepage');
        }
      }
    ];

    for (const action of actions) {
      try {
        await action();
      } catch (e) {
        collector.addObservation('note', `Exploration action failed: ${e.message}`, 'Discovery');
      }
    }

    await collector.captureScreenshot(page, 'discovery-end', 'Exploration: Complete');
    collector.recordTask('New user exploration', true, Date.now() - startTime, 'Completed discovery journey');
  });
});

export default PERSONA;
