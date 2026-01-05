/**
 * Elena - UI Designer Persona Test
 *
 * Background: Senior UI/UX designer with 10+ years experience, opinionated about design quality
 * Goals: Evaluate visual design, usability, user flows, and suggest bold improvements
 * Behaviors: Scrutinizes every detail - colors, typography, spacing, hierarchy, consistency
 *
 * Elena is not afraid to suggest major redesigns where warranted. She looks at both
 * the forest (overall experience) and the trees (pixel-level details).
 */

import { test, expect } from '@playwright/test';
import { ObservationCollector } from '../utils/observation-collector.js';

const BASE_URL = process.env.BASE_URL || 'http://localhost:4321/council-meeting-analyzer';

export const PERSONA = {
  name: 'Elena - UI Designer',
  background: 'Senior UI/UX designer with 10+ years experience, opinionated about design quality',
  goals: 'Evaluate visual design, usability, user flows, and suggest bold improvements',
  behaviors: 'Scrutinizes every detail - colors, typography, spacing, hierarchy, consistency'
};

test.describe.serial('Elena - UI Designer', () => {
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

  test('Task 1: Evaluate visual hierarchy and first impressions', async ({ page }) => {
    const startTime = Date.now();
    let success = true;
    let notes = '';

    await page.goto(BASE_URL);
    await collector.captureScreenshot(page, 'homepage-full', 'Task 1: Homepage first impression');

    try {
      // Analyze visual hierarchy
      const hierarchy = await page.evaluate(() => {
        const h1 = document.querySelector('h1');
        const h2s = document.querySelectorAll('h2');
        const cards = document.querySelectorAll('.card');
        const buttons = document.querySelectorAll('.btn');

        // Get computed styles for key elements
        const h1Style = h1 ? window.getComputedStyle(h1) : null;
        const bodyStyle = window.getComputedStyle(document.body);

        return {
          hasH1: !!h1,
          h1Text: h1?.textContent?.trim(),
          h1FontSize: h1Style?.fontSize,
          h1FontWeight: h1Style?.fontWeight,
          h2Count: h2s.length,
          cardCount: cards.length,
          buttonCount: buttons.length,
          bodyBgColor: bodyStyle.backgroundColor,
          bodyTextColor: bodyStyle.color,
          bodyFontFamily: bodyStyle.fontFamily
        };
      });

      // Evaluate hierarchy
      if (!hierarchy.hasH1) {
        collector.addObservation('frustration', 'Missing primary heading (H1) - unclear page purpose', 'Homepage');
      } else {
        // Check if H1 is prominent enough
        const fontSize = parseInt(hierarchy.h1FontSize);
        if (fontSize < 24) {
          collector.addObservation('note', `H1 font size (${hierarchy.h1FontSize}) may be too small for primary heading`, 'Typography');
        }
      }

      // Check card density
      if (hierarchy.cardCount > 6) {
        collector.addObservation('note', `${hierarchy.cardCount} cards visible - consider pagination or "load more" for better scannability`, 'Layout');
      }

      notes = `Visual hierarchy: H1="${hierarchy.h1Text?.substring(0, 30)}...", ${hierarchy.cardCount} cards, ${hierarchy.buttonCount} buttons`;

      // Scroll to check below-fold content
      await page.evaluate(() => window.scrollTo(0, 600));
      await collector.captureScreenshot(page, 'homepage-scrolled', 'Task 1: Below the fold');

    } catch (error) {
      notes = `Error: ${error.message}`;
      success = false;
    }

    collector.recordTask('Evaluate visual hierarchy', success, Date.now() - startTime, notes);
  });

  test('Task 2: Analyze color palette and contrast', async ({ page }) => {
    const startTime = Date.now();
    let success = true;
    let notes = '';

    await page.goto(BASE_URL);

    try {
      // Extract color palette from the page
      const colors = await page.evaluate(() => {
        const elements = document.querySelectorAll('*');
        const colorSet = new Set();
        const bgColorSet = new Set();

        elements.forEach(el => {
          const style = window.getComputedStyle(el);
          if (style.color && style.color !== 'rgba(0, 0, 0, 0)') {
            colorSet.add(style.color);
          }
          if (style.backgroundColor && style.backgroundColor !== 'rgba(0, 0, 0, 0)') {
            bgColorSet.add(style.backgroundColor);
          }
        });

        // Get specific UI element colors
        const primaryBtn = document.querySelector('.btn-primary');
        const card = document.querySelector('.card');
        const link = document.querySelector('a:not(.btn)');

        return {
          uniqueTextColors: colorSet.size,
          uniqueBgColors: bgColorSet.size,
          primaryBtnBg: primaryBtn ? window.getComputedStyle(primaryBtn).backgroundColor : null,
          primaryBtnColor: primaryBtn ? window.getComputedStyle(primaryBtn).color : null,
          cardBg: card ? window.getComputedStyle(card).backgroundColor : null,
          linkColor: link ? window.getComputedStyle(link).color : null,
          textColors: Array.from(colorSet).slice(0, 5),
          bgColors: Array.from(bgColorSet).slice(0, 5)
        };
      });

      await collector.captureScreenshot(page, 'color-analysis', 'Task 2: Color palette analysis');

      // Evaluate color consistency
      if (colors.uniqueTextColors > 8) {
        collector.addObservation('note', `${colors.uniqueTextColors} unique text colors detected - consider consolidating for consistency`, 'Color palette');
      }

      if (colors.uniqueBgColors > 6) {
        collector.addObservation('note', `${colors.uniqueBgColors} unique background colors - may create visual noise`, 'Color palette');
      }

      // Check for primary action color
      if (!colors.primaryBtnBg) {
        collector.addObservation('frustration', 'No clear primary action button color identified', 'Color system');
      }

      notes = `Color audit: ${colors.uniqueTextColors} text colors, ${colors.uniqueBgColors} bg colors`;

      // Navigate to meeting page to check consistency
      await page.locator('a[href*="/meetings/"]').first().click();
      collector.trackClick();
      await page.waitForTimeout(500);

      const meetingColors = await page.evaluate(() => {
        const body = window.getComputedStyle(document.body);
        return {
          bgColor: body.backgroundColor,
          textColor: body.color
        };
      });

      await collector.captureScreenshot(page, 'meeting-page-colors', 'Task 2: Meeting page color consistency');

      notes += ` | Meeting page maintains color consistency`;

    } catch (error) {
      notes = `Error: ${error.message}`;
      success = false;
    }

    collector.recordTask('Analyze color palette', success, Date.now() - startTime, notes);
  });

  test('Task 3: Evaluate typography and readability', async ({ page }) => {
    const startTime = Date.now();
    let success = true;
    let notes = '';

    await page.goto(BASE_URL);

    try {
      // Analyze typography
      const typography = await page.evaluate(() => {
        const body = document.body;
        const bodyStyle = window.getComputedStyle(body);
        const h1 = document.querySelector('h1');
        const h2 = document.querySelector('h2');
        const p = document.querySelector('p');
        const card = document.querySelector('.card');

        const getTypoDetails = (el) => {
          if (!el) return null;
          const style = window.getComputedStyle(el);
          return {
            fontFamily: style.fontFamily,
            fontSize: style.fontSize,
            fontWeight: style.fontWeight,
            lineHeight: style.lineHeight,
            letterSpacing: style.letterSpacing
          };
        };

        // Check line length for readability
        const textContainer = document.querySelector('.prose, p, .card');
        const containerWidth = textContainer ? textContainer.getBoundingClientRect().width : 0;

        return {
          body: getTypoDetails(body),
          h1: getTypoDetails(h1),
          h2: getTypoDetails(h2),
          paragraph: getTypoDetails(p),
          cardText: card ? getTypoDetails(card.querySelector('p') || card) : null,
          maxTextWidth: containerWidth,
          fontFamiliesUsed: new Set([
            bodyStyle.fontFamily,
            h1 ? window.getComputedStyle(h1).fontFamily : null,
            h2 ? window.getComputedStyle(h2).fontFamily : null
          ].filter(Boolean)).size
        };
      });

      await collector.captureScreenshot(page, 'typography-analysis', 'Task 3: Typography analysis');

      // Evaluate typography choices
      if (typography.body) {
        const bodyFontSize = parseInt(typography.body.fontSize);
        if (bodyFontSize < 14) {
          collector.addObservation('frustration', `Body font size (${typography.body.fontSize}) too small for comfortable reading`, 'Typography');
        } else if (bodyFontSize < 16) {
          collector.addObservation('note', `Body font size (${typography.body.fontSize}) could be larger for better readability`, 'Typography');
        }

        // Check line height
        const lineHeight = parseFloat(typography.body.lineHeight);
        const fontSize = parseFloat(typography.body.fontSize);
        const lineHeightRatio = lineHeight / fontSize;
        if (lineHeightRatio < 1.4) {
          collector.addObservation('note', 'Line height may be too tight for comfortable reading - consider 1.5-1.6', 'Typography');
        }
      }

      // Check for too many font families
      if (typography.fontFamiliesUsed > 3) {
        collector.addObservation('note', `${typography.fontFamiliesUsed} different font families detected - consider limiting to 2-3`, 'Typography');
      }

      // Check text width for readability (optimal: 45-75 characters, ~450-750px at 16px)
      if (typography.maxTextWidth > 800) {
        collector.addObservation('note', `Text container width (${Math.round(typography.maxTextWidth)}px) may be too wide - optimal is 600-700px for readability`, 'Typography');
      }

      notes = `Typography: ${typography.body?.fontFamily?.split(',')[0]} at ${typography.body?.fontSize}, ${typography.fontFamiliesUsed} font families`;

      // Check transcript readability
      await page.locator('a[href*="/meetings/"]').first().click();
      collector.trackClick();
      await page.waitForTimeout(500);

      const transcript = page.locator('details:has-text("transcript")');
      if (await transcript.count() > 0) {
        await transcript.click();
        collector.trackClick();
        await page.waitForTimeout(300);
        await collector.captureScreenshot(page, 'transcript-typography', 'Task 3: Transcript readability');

        const transcriptTypo = await page.evaluate(() => {
          const prose = document.querySelector('.prose');
          if (!prose) return null;
          const style = window.getComputedStyle(prose);
          return {
            fontSize: style.fontSize,
            lineHeight: style.lineHeight,
            width: prose.getBoundingClientRect().width
          };
        });

        if (transcriptTypo && transcriptTypo.width > 800) {
          collector.addObservation('frustration', 'Transcript text is too wide - hurts readability for long-form content. Consider max-width: 65ch', 'Typography');
        }
      }

    } catch (error) {
      notes = `Error: ${error.message}`;
      success = false;
    }

    collector.recordTask('Evaluate typography', success, Date.now() - startTime, notes);
  });

  test('Task 4: Assess spacing, alignment and visual rhythm', async ({ page }) => {
    const startTime = Date.now();
    let success = true;
    let notes = '';

    await page.goto(BASE_URL);

    try {
      // Analyze spacing consistency
      const spacing = await page.evaluate(() => {
        const cards = document.querySelectorAll('.card');
        const gaps = [];
        const paddings = [];

        cards.forEach(card => {
          const style = window.getComputedStyle(card);
          paddings.push(style.padding);
        });

        // Check section spacing
        const sections = document.querySelectorAll('section, .space-y-4, .space-y-6, .space-y-8');
        const margins = [];
        sections.forEach(section => {
          const style = window.getComputedStyle(section);
          margins.push(style.marginBottom);
        });

        // Check grid/flex gaps
        const grids = document.querySelectorAll('.grid, .flex');
        grids.forEach(grid => {
          const style = window.getComputedStyle(grid);
          if (style.gap && style.gap !== 'normal') {
            gaps.push(style.gap);
          }
        });

        // Get unique values
        const uniquePaddings = [...new Set(paddings)];
        const uniqueGaps = [...new Set(gaps)];

        return {
          cardCount: cards.length,
          uniquePaddings,
          uniqueGaps,
          paddingVariations: uniquePaddings.length,
          gapVariations: uniqueGaps.length
        };
      });

      await collector.captureScreenshot(page, 'spacing-analysis', 'Task 4: Spacing analysis');

      // Evaluate spacing consistency
      if (spacing.paddingVariations > 4) {
        collector.addObservation('note', `${spacing.paddingVariations} different padding values - consider using a spacing scale (4, 8, 16, 24, 32px)`, 'Spacing');
      }

      if (spacing.gapVariations > 3) {
        collector.addObservation('note', `${spacing.gapVariations} different gap values - inconsistent spacing rhythm`, 'Spacing');
      }

      notes = `Spacing: ${spacing.paddingVariations} padding variations, ${spacing.gapVariations} gap variations`;

      // Check alignment on meeting page
      await page.locator('a[href*="/meetings/"]').first().click();
      collector.trackClick();
      await page.waitForTimeout(500);

      await collector.captureScreenshot(page, 'meeting-spacing', 'Task 4: Meeting page spacing');

      // Check for visual alignment issues
      const alignmentIssues = await page.evaluate(() => {
        const issues = [];

        // Check if content sections align
        const headings = document.querySelectorAll('h1, h2, h3');
        const leftPositions = new Set();

        headings.forEach(h => {
          const rect = h.getBoundingClientRect();
          leftPositions.add(Math.round(rect.left / 8) * 8); // Round to 8px grid
        });

        if (leftPositions.size > 2) {
          issues.push('Headings not aligned to consistent left edge');
        }

        return issues;
      });

      if (alignmentIssues.length > 0) {
        alignmentIssues.forEach(issue => {
          collector.addObservation('note', issue, 'Alignment');
        });
      }

    } catch (error) {
      notes = `Error: ${error.message}`;
      success = false;
    }

    collector.recordTask('Assess spacing and alignment', success, Date.now() - startTime, notes);
  });

  test('Task 5: Evaluate user flow - homepage to meeting detail', async ({ page }) => {
    const startTime = Date.now();
    let success = true;
    let notes = '';

    await page.goto(BASE_URL);
    await collector.captureScreenshot(page, 'flow-start', 'Task 5: User flow start');

    try {
      // Track the user flow
      const flowSteps = [];

      // Step 1: Can user identify what to do?
      const ctaVisible = await page.evaluate(() => {
        const cards = document.querySelectorAll('.card');
        const searchInput = document.getElementById('search-input');
        const filterBtns = document.querySelectorAll('.btn');

        return {
          hasCards: cards.length > 0,
          cardsClickable: cards[0]?.tagName === 'A' || cards[0]?.querySelector('a'),
          hasSearch: !!searchInput,
          hasFilters: filterBtns.length > 2
        };
      });

      if (!ctaVisible.cardsClickable) {
        collector.addObservation('frustration', 'Meeting cards don\'t appear clickable - add hover states or explicit "View" links', 'User flow');
      }

      flowSteps.push('Homepage loaded');

      // Step 2: Use search (primary action)
      const searchInput = page.locator('#search-input');
      if (await searchInput.isVisible({ timeout: 2000 })) {
        await searchInput.click();
        await searchInput.fill('budget');
        collector.trackSearch();

        const results = page.locator('.search-result, [data-pagefind-result]');
        try {
          await results.first().waitFor({ state: 'visible', timeout: 5000 });
          flowSteps.push('Search works');
          await collector.captureScreenshot(page, 'flow-search', 'Task 5: Search results');

          // Click search result
          await results.first().click();
          collector.trackClick();
          await page.waitForTimeout(500);
          flowSteps.push('Navigated from search');
        } catch (e) {
          collector.addObservation('note', 'Search returned no results for common term "budget"', 'User flow');
        }
      }

      // Step 3: On meeting page - can user find key info quickly?
      await collector.captureScreenshot(page, 'flow-meeting', 'Task 5: Meeting page in flow');

      const meetingPageUX = await page.evaluate(() => {
        // Find elements by text content (can't use :has-text() in browser context)
        const headings = document.querySelectorAll('h2');
        let summary = null;
        let votes = null;
        headings.forEach(h => {
          const text = h.textContent?.toLowerCase() || '';
          if (text.includes('summary')) summary = h;
          if (text.includes('vote')) votes = h;
        });

        // Fallback to class-based selectors
        if (!summary) summary = document.querySelector('[class*="summary"]');
        if (!votes) votes = document.querySelector('[class*="votes"]');

        // Find video and back links by text content
        const links = document.querySelectorAll('a');
        let video = null;
        let backLink = null;
        links.forEach(a => {
          const text = a.textContent?.toLowerCase() || '';
          if (text.includes('watch') || text.includes('video')) video = a;
          if (text.includes('back')) backLink = a;
        });

        // Check if key actions are above the fold
        const viewportHeight = window.innerHeight;
        const summaryPos = summary?.getBoundingClientRect().top || 9999;
        const votesPos = votes?.getBoundingClientRect().top || 9999;

        return {
          hasSummary: !!summary,
          hasVotes: !!votes,
          hasVideo: !!video,
          hasBackLink: !!backLink,
          summaryAboveFold: summaryPos < viewportHeight,
          votesAboveFold: votesPos < viewportHeight
        };
      });

      if (!meetingPageUX.summaryAboveFold) {
        collector.addObservation('note', 'Summary section not visible above fold - key content requires scrolling', 'User flow');
      }

      if (!meetingPageUX.hasBackLink) {
        collector.addObservation('frustration', 'No clear back navigation - user may feel trapped', 'User flow');
      } else {
        flowSteps.push('Back link available');
      }

      // Step 4: Go back to homepage
      const backLink = page.locator('a:has-text("Back")').first();
      if (await backLink.count() > 0) {
        await backLink.click();
        collector.trackClick();
        collector.trackBackNavigation();
        await page.waitForTimeout(500);
        flowSteps.push('Returned to homepage');
      }

      await collector.captureScreenshot(page, 'flow-end', 'Task 5: Flow complete');

      notes = `User flow: ${flowSteps.join(' → ')}`;

    } catch (error) {
      notes = `Error: ${error.message}`;
      success = false;
    }

    collector.recordTask('Evaluate user flow', success, Date.now() - startTime, notes);
  });

  test('Task 6: Review interactive elements and feedback', async ({ page }) => {
    const startTime = Date.now();
    let success = true;
    let notes = '';

    await page.goto(BASE_URL);

    try {
      // Check button and link styling
      const interactiveStyles = await page.evaluate(() => {
        const buttons = document.querySelectorAll('.btn');
        const links = document.querySelectorAll('a:not(.btn):not(.card)');
        const cards = document.querySelectorAll('.card');

        // Get button styles
        const btnStyles = [];
        buttons.forEach(btn => {
          const style = window.getComputedStyle(btn);
          btnStyles.push({
            padding: style.padding,
            borderRadius: style.borderRadius,
            fontSize: style.fontSize,
            hasHoverClass: btn.classList.contains('hover:') || true // Check if hover styles exist
          });
        });

        // Check for consistent border radius
        const radii = new Set(btnStyles.map(b => b.borderRadius));

        return {
          buttonCount: buttons.length,
          linkCount: links.length,
          cardCount: cards.length,
          borderRadiusVariations: radii.size,
          borderRadii: Array.from(radii)
        };
      });

      await collector.captureScreenshot(page, 'interactive-elements', 'Task 6: Interactive elements');

      if (interactiveStyles.borderRadiusVariations > 2) {
        collector.addObservation('note', `${interactiveStyles.borderRadiusVariations} different border-radius values (${interactiveStyles.borderRadii.join(', ')}) - consider standardizing`, 'Visual consistency');
      }

      // Test hover states
      const firstCard = page.locator('.card').first();
      if (await firstCard.count() > 0) {
        await firstCard.hover();
        await page.waitForTimeout(200);
        await collector.captureScreenshot(page, 'card-hover', 'Task 6: Card hover state');

        const hasHoverChange = await page.evaluate(() => {
          const card = document.querySelector('.card:hover');
          if (!card) return false;
          const style = window.getComputedStyle(card);
          // Check if there's visual feedback on hover
          return style.transform !== 'none' ||
                 style.boxShadow !== 'none' ||
                 style.borderColor !== 'rgb(0, 0, 0)';
        });

        if (!hasHoverChange) {
          collector.addObservation('note', 'Cards lack clear hover feedback - add shadow, border, or transform', 'Interactivity');
        }
      }

      // Check filter button states
      const filterBtns = page.locator('.btn-primary, .btn-ghost');
      const activeFilterVisible = await page.evaluate(() => {
        const activeBtn = document.querySelector('.btn-primary');
        const inactiveBtn = document.querySelector('.btn-ghost');
        if (!activeBtn || !inactiveBtn) return true;

        const activeStyle = window.getComputedStyle(activeBtn);
        const inactiveStyle = window.getComputedStyle(inactiveBtn);

        // Check if there's clear visual distinction
        return activeStyle.backgroundColor !== inactiveStyle.backgroundColor ||
               activeStyle.color !== inactiveStyle.color;
      });

      if (!activeFilterVisible) {
        collector.addObservation('note', 'Active/inactive filter states not clearly distinguished', 'Interactivity');
      }

      notes = `Interactive elements: ${interactiveStyles.buttonCount} buttons, ${interactiveStyles.cardCount} cards`;

      // Navigate to meeting page and check expandable sections
      await page.locator('a[href*="/meetings/"]').first().click();
      collector.trackClick();
      await page.waitForTimeout(500);

      const details = page.locator('details').first();
      if (await details.count() > 0) {
        await details.click();
        collector.trackClick();
        await page.waitForTimeout(300);
        await collector.captureScreenshot(page, 'expandable-section', 'Task 6: Expandable section');

        // Check if expansion is animated
        collector.addObservation('note', 'Consider adding smooth expand/collapse animation for details sections', 'Interactivity');
      }

    } catch (error) {
      notes = `Error: ${error.message}`;
      success = false;
    }

    collector.recordTask('Review interactive elements', success, Date.now() - startTime, notes);
  });

  test('Task 7: Mobile phone responsiveness', async ({ page }) => {
    const startTime = Date.now();
    let success = true;
    let notes = '';
    const issues = [];

    // Test multiple phone viewport sizes
    const phoneViewports = [
      { name: 'iPhone SE', width: 375, height: 667 },
      { name: 'iPhone 14', width: 390, height: 844 },
      { name: 'Samsung Galaxy', width: 360, height: 800 },
      { name: 'iPhone 14 Pro Max', width: 430, height: 932 }
    ];

    try {
      for (const viewport of phoneViewports) {
        await page.setViewportSize({ width: viewport.width, height: viewport.height });
        await page.goto(BASE_URL);

        if (viewport.name === 'iPhone SE') {
          await collector.captureScreenshot(page, 'phone-homepage-small', `Task 7: ${viewport.name} homepage`);
        }

        // Check for horizontal overflow (common mobile issue)
        const hasHorizontalScroll = await page.evaluate(() => {
          return document.documentElement.scrollWidth > document.documentElement.clientWidth;
        });

        if (hasHorizontalScroll) {
          issues.push(`${viewport.name}: Horizontal scroll detected`);
          collector.addObservation('frustration', `Horizontal scrolling on ${viewport.name} (${viewport.width}px) - fix overflow`, 'Mobile layout');
        }

        // Check navigation accessibility
        const navCheck = await page.evaluate(() => {
          const header = document.querySelector('header');
          const navLinks = document.querySelectorAll('header a');
          const headerRect = header?.getBoundingClientRect();

          return {
            headerHeight: headerRect?.height || 0,
            navLinksVisible: Array.from(navLinks).filter(a =>
              a.getBoundingClientRect().width > 0
            ).length,
            headerOverflows: headerRect ? headerRect.width > window.innerWidth : false
          };
        });

        if (navCheck.headerOverflows) {
          issues.push(`${viewport.name}: Header overflows`);
          collector.addObservation('frustration', `Navigation header overflows on ${viewport.name}`, 'Mobile navigation');
        }

        // Check search input usability
        const searchCheck = await page.evaluate(() => {
          const searchInput = document.getElementById('search-input');
          if (!searchInput) return { accessible: false };

          const rect = searchInput.getBoundingClientRect();
          const style = window.getComputedStyle(searchInput);

          return {
            accessible: rect.width > 0,
            width: rect.width,
            fontSize: parseInt(style.fontSize),
            fitScreen: rect.width <= window.innerWidth - 32
          };
        });

        if (searchCheck.accessible && !searchCheck.fitScreen) {
          collector.addObservation('note', `Search input overflows on ${viewport.name}`, 'Mobile search');
        }

        if (searchCheck.fontSize < 16) {
          collector.addObservation('note', `Search input font size ${searchCheck.fontSize}px may trigger zoom on iOS (min 16px recommended)`, 'Mobile input');
        }

        // Check text readability
        const textCheck = await page.evaluate(() => {
          const bodyStyle = window.getComputedStyle(document.body);
          const paragraphs = document.querySelectorAll('p');
          let smallTextCount = 0;

          paragraphs.forEach(p => {
            const style = window.getComputedStyle(p);
            if (parseInt(style.fontSize) < 14) smallTextCount++;
          });

          return {
            bodyFontSize: parseInt(bodyStyle.fontSize),
            smallTextElements: smallTextCount,
            lineHeight: parseFloat(bodyStyle.lineHeight) / parseInt(bodyStyle.fontSize)
          };
        });

        if (textCheck.smallTextElements > 3) {
          collector.addObservation('note', `${textCheck.smallTextElements} text elements with font size <14px may be hard to read on mobile`, 'Mobile readability');
        }

        // Check card layout on mobile
        const cardCheck = await page.evaluate(() => {
          const cards = document.querySelectorAll('.card');
          const grid = document.querySelector('.grid');
          const gridStyle = grid ? window.getComputedStyle(grid) : null;

          return {
            cardCount: cards.length,
            gridColumns: gridStyle?.gridTemplateColumns || 'none',
            cardsOverflow: Array.from(cards).some(card =>
              card.getBoundingClientRect().width > window.innerWidth
            ),
            firstCardWidth: cards[0]?.getBoundingClientRect().width || 0
          };
        });

        if (cardCheck.cardsOverflow) {
          issues.push(`${viewport.name}: Cards overflow screen width`);
          collector.addObservation('frustration', `Meeting cards overflow on ${viewport.name}`, 'Mobile cards');
        }

        // Check touch targets
        const touchTargets = await page.evaluate(() => {
          const interactives = document.querySelectorAll('a, button, input, .btn, [role="button"]');
          let smallCount = 0;

          interactives.forEach(el => {
            const rect = el.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0) {
              if (rect.width < 44 || rect.height < 44) smallCount++;
            }
          });

          return { smallCount, total: interactives.length };
        });

        if (touchTargets.smallCount > 0) {
          collector.addObservation('note', `${touchTargets.smallCount} touch targets below 44px minimum on ${viewport.name}`, 'Mobile touch');
        }
      }

      // Test mobile meeting page
      await page.setViewportSize({ width: 375, height: 667 });
      await page.goto(BASE_URL);
      await page.locator('a[href*="/meetings/"]').first().click();
      collector.trackClick();
      await page.waitForTimeout(500);
      await collector.captureScreenshot(page, 'phone-meeting-page', 'Task 7: Phone meeting page');

      // Check mobile meeting page layout
      const meetingMobileCheck = await page.evaluate(() => {
        const sidebar = document.querySelector('aside');
        const mainContent = document.querySelector('.lg\\:col-span-2, [class*="col-span"]');
        const voteTable = document.querySelector('table');
        const breadcrumbs = document.querySelector('.breadcrumbs, nav[aria-label="Breadcrumb"]');

        return {
          sidebarStacked: sidebar && mainContent ?
            sidebar.getBoundingClientRect().top > mainContent.getBoundingClientRect().bottom - 100 : true,
          tableScrollable: voteTable ?
            voteTable.getBoundingClientRect().width > window.innerWidth : false,
          breadcrumbsVisible: breadcrumbs ?
            breadcrumbs.getBoundingClientRect().width <= window.innerWidth : true
        };
      });

      if (!meetingMobileCheck.sidebarStacked) {
        collector.addObservation('note', 'Sidebar should stack below main content on mobile', 'Mobile layout');
      }

      if (meetingMobileCheck.tableScrollable) {
        collector.addObservation('note', 'Vote table requires horizontal scroll on mobile - consider card layout for votes', 'Mobile tables');
      }

      // Test expandable sections on mobile
      const details = page.locator('details').first();
      if (await details.count() > 0) {
        await details.click();
        collector.trackClick();
        await page.waitForTimeout(300);
        await collector.captureScreenshot(page, 'phone-expanded-section', 'Task 7: Phone expanded section');
      }

      notes = `Phone tests: ${phoneViewports.length} viewports, ${issues.length} critical issues`;

      // Reset viewport
      await page.setViewportSize({ width: 1280, height: 720 });

    } catch (error) {
      notes = `Error: ${error.message}`;
      success = false;
    }

    collector.recordTask('Mobile phone responsiveness', success, Date.now() - startTime, notes);
  });

  test('Task 8: Tablet responsiveness', async ({ page }) => {
    const startTime = Date.now();
    let success = true;
    let notes = '';
    const issues = [];

    // Test tablet viewport sizes
    const tabletViewports = [
      { name: 'iPad Mini Portrait', width: 768, height: 1024 },
      { name: 'iPad Mini Landscape', width: 1024, height: 768 },
      { name: 'iPad Pro 11 Portrait', width: 834, height: 1194 },
      { name: 'iPad Pro 11 Landscape', width: 1194, height: 834 },
      { name: 'Android Tablet', width: 800, height: 1280 }
    ];

    try {
      for (const viewport of tabletViewports) {
        await page.setViewportSize({ width: viewport.width, height: viewport.height });
        await page.goto(BASE_URL);

        if (viewport.name === 'iPad Mini Portrait') {
          await collector.captureScreenshot(page, 'tablet-portrait-homepage', `Task 8: ${viewport.name} homepage`);
        } else if (viewport.name === 'iPad Mini Landscape') {
          await collector.captureScreenshot(page, 'tablet-landscape-homepage', `Task 8: ${viewport.name} homepage`);
        }

        // Check grid layout for tablets
        const gridCheck = await page.evaluate(() => {
          const grid = document.querySelector('.grid');
          const cards = document.querySelectorAll('.card');
          const gridStyle = grid ? window.getComputedStyle(grid) : null;

          // Count visible columns by checking card positions
          const cardPositions = Array.from(cards).slice(0, 6).map(card =>
            card.getBoundingClientRect().left
          );
          const uniqueLeftPositions = new Set(cardPositions.map(p => Math.round(p / 10) * 10));

          return {
            columnsDetected: uniqueLeftPositions.size,
            gridGap: gridStyle?.gap || gridStyle?.gridGap || 'unknown',
            cardsVisible: cards.length
          };
        });

        // Tablets should show 2-3 columns typically
        if (viewport.width >= 768 && gridCheck.columnsDetected < 2) {
          collector.addObservation('note', `Only ${gridCheck.columnsDetected} column(s) on ${viewport.name} - consider showing more`, 'Tablet layout');
        }

        // Check content width utilization
        const contentCheck = await page.evaluate(() => {
          const main = document.querySelector('main');
          const container = main?.querySelector('.container, [class*="container"]') || main;
          const containerRect = container?.getBoundingClientRect();

          return {
            containerWidth: containerRect?.width || 0,
            viewportWidth: window.innerWidth,
            utilizationPercent: containerRect ?
              Math.round((containerRect.width / window.innerWidth) * 100) : 0
          };
        });

        if (contentCheck.utilizationPercent < 80 && viewport.width < 1024) {
          collector.addObservation('note', `Content only uses ${contentCheck.utilizationPercent}% of screen on ${viewport.name}`, 'Tablet spacing');
        }

        // Check hero section on tablet
        const heroCheck = await page.evaluate(() => {
          const hero = document.querySelector('section.bg-base-200, [class*="hero"]');
          const heroRect = hero?.getBoundingClientRect();
          const searchInput = document.getElementById('search-input');
          const searchRect = searchInput?.getBoundingClientRect();

          return {
            heroWidth: heroRect?.width || 0,
            heroFullWidth: heroRect ? heroRect.width >= window.innerWidth - 64 : false,
            searchWidth: searchRect?.width || 0,
            searchProportional: searchRect ? searchRect.width >= 300 && searchRect.width <= 600 : true
          };
        });

        if (!heroCheck.searchProportional) {
          collector.addObservation('note', `Search bar width (${heroCheck.searchWidth}px) may not be optimal on ${viewport.name}`, 'Tablet search');
        }

        // Check for wasted whitespace
        const whitespaceCheck = await page.evaluate(() => {
          const body = document.body;
          const main = document.querySelector('main');
          const mainStyle = main ? window.getComputedStyle(main) : null;

          return {
            paddingLeft: parseInt(mainStyle?.paddingLeft || '0'),
            paddingRight: parseInt(mainStyle?.paddingRight || '0'),
            totalPadding: parseInt(mainStyle?.paddingLeft || '0') + parseInt(mainStyle?.paddingRight || '0')
          };
        });

        // Large padding on tablets might waste space
        if (viewport.width >= 768 && viewport.width < 1024 && whitespaceCheck.totalPadding > 64) {
          collector.addObservation('note', `Consider reducing padding on ${viewport.name} to use space better`, 'Tablet spacing');
        }
      }

      // Test tablet meeting page in portrait
      await page.setViewportSize({ width: 768, height: 1024 });
      await page.goto(BASE_URL);
      await page.locator('a[href*="/meetings/"]').first().click();
      collector.trackClick();
      await page.waitForTimeout(500);
      await collector.captureScreenshot(page, 'tablet-meeting-page', 'Task 8: Tablet meeting page');

      // Check meeting page layout on tablet
      const meetingTabletCheck = await page.evaluate(() => {
        const grid = document.querySelector('.grid.gap-8, .grid[class*="lg:grid-cols"]');
        const sidebar = document.querySelector('aside');
        const mainContent = document.querySelector('.lg\\:col-span-2, [class*="col-span-2"]');

        // Check if it's using side-by-side or stacked layout
        const sidebarRect = sidebar?.getBoundingClientRect();
        const mainRect = mainContent?.getBoundingClientRect();

        const isSideBySide = sidebarRect && mainRect ?
          Math.abs(sidebarRect.top - mainRect.top) < 50 : false;

        return {
          layoutType: isSideBySide ? 'side-by-side' : 'stacked',
          sidebarWidth: sidebarRect?.width || 0,
          mainContentWidth: mainRect?.width || 0,
          viewportWidth: window.innerWidth
        };
      });

      if (meetingTabletCheck.layoutType === 'stacked' && page.viewportSize().width >= 1024) {
        collector.addObservation('note', 'Meeting page uses stacked layout on landscape tablet - could use side-by-side', 'Tablet layout');
      }

      // Test pagination on tablet
      await page.goto(BASE_URL);
      const paginationCheck = await page.evaluate(() => {
        const pagination = document.querySelector('nav[aria-label="Pagination"], .pagination');
        const paginationRect = pagination?.getBoundingClientRect();

        return {
          exists: !!pagination,
          centered: paginationRect ?
            Math.abs((paginationRect.left + paginationRect.width / 2) - window.innerWidth / 2) < 50 : true,
          touchFriendly: pagination ?
            Array.from(pagination.querySelectorAll('a, button')).every(el =>
              el.getBoundingClientRect().height >= 44
            ) : true
        };
      });

      if (paginationCheck.exists && !paginationCheck.touchFriendly) {
        collector.addObservation('note', 'Pagination buttons may be too small for comfortable tablet touch', 'Tablet navigation');
      }

      notes = `Tablet tests: ${tabletViewports.length} viewports, ${issues.length} critical issues`;

      // Reset viewport
      await page.setViewportSize({ width: 1280, height: 720 });

    } catch (error) {
      notes = `Error: ${error.message}`;
      success = false;
    }

    collector.recordTask('Tablet responsiveness', success, Date.now() - startTime, notes);
  });

  test('Free Exploration: Bold design recommendations', async ({ page }) => {
    const startTime = Date.now();

    await page.goto(BASE_URL);
    collector.addObservation('note', 'Beginning comprehensive design review', 'Overall');
    await collector.captureScreenshot(page, 'design-review-start', 'Exploration: Starting design review');

    // Comprehensive design audit with bold recommendations
    const actions = [
      // Overall page assessment
      async () => {
        const pageMetrics = await page.evaluate(() => {
          const body = document.body;
          const rect = body.getBoundingClientRect();

          return {
            pageHeight: document.documentElement.scrollHeight,
            contentWidth: rect.width,
            elementsCount: document.querySelectorAll('*').length,
            imagesCount: document.querySelectorAll('img, svg').length
          };
        });

        if (pageMetrics.elementsCount > 1000) {
          collector.addObservation('note', `Page has ${pageMetrics.elementsCount} DOM elements - consider optimizing for performance`, 'Performance');
        }

        // Bold recommendation: Overall design direction
        collector.addObservation('note', 'BOLD RECOMMENDATION: Consider a more modern card design with larger imagery or iconography to make meetings more visually distinct and scannable', 'Design direction');
      },
      // Check visual hierarchy strength
      async () => {
        await collector.captureScreenshot(page, 'hierarchy-review', 'Exploration: Visual hierarchy');

        collector.addObservation('note', 'BOLD RECOMMENDATION: Add a hero section with site purpose, key stats (218 meetings, date range), and prominent search - current design buries the value proposition', 'Design direction');
      },
      // Check meeting page design
      async () => {
        await page.locator('a[href*="/meetings/"]').first().click();
        collector.trackClick();
        await page.waitForTimeout(500);
        await collector.captureScreenshot(page, 'meeting-design-review', 'Exploration: Meeting page design');

        collector.addObservation('note', 'BOLD RECOMMENDATION: Meeting page could benefit from a timeline or agenda view instead of collapsed sections - surface more information upfront', 'Design direction');
        collector.addObservation('note', 'BOLD RECOMMENDATION: Add visual vote indicators (green/red/yellow dots) instead of text-only badges for at-a-glance understanding', 'Design direction');
      },
      // Review navigation
      async () => {
        await page.goto(BASE_URL);
        await collector.captureScreenshot(page, 'nav-review', 'Exploration: Navigation review');

        collector.addObservation('note', 'BOLD RECOMMENDATION: Add breadcrumbs, "Recent meetings" quick links, or a calendar view for alternative navigation patterns', 'Navigation');
      },
      // Check consistency across pages
      async () => {
        // Visit About page
        const aboutLink = page.locator('a:has-text("About")').first();
        if (await aboutLink.count() > 0) {
          await aboutLink.click();
          collector.trackClick();
          await page.waitForTimeout(500);
          await collector.captureScreenshot(page, 'about-design', 'Exploration: About page design');

          collector.addObservation('note', 'About page is well-structured with clear sections', 'Consistency');
        }
      }
    ];

    for (const action of actions) {
      try {
        await action();
      } catch (e) {
        collector.addObservation('note', `Review action failed: ${e.message}`, 'Design review');
      }
    }

    await collector.captureScreenshot(page, 'design-review-end', 'Exploration: Design review complete');
    collector.recordTask('Bold design recommendations', true, Date.now() - startTime, 'Completed comprehensive design review with recommendations');
  });
});

export default PERSONA;
