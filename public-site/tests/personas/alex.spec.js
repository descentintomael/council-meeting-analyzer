/**
 * Alex - Accessibility Auditor Persona Test
 *
 * Background: Tests for WCAG compliance and usability
 * Goals: Ensure site works for all users regardless of ability
 * Behaviors: Keyboard-only navigation, screen reader simulation, contrast checks
 */

import { test, expect } from '@playwright/test';
import { ObservationCollector } from '../utils/observation-collector.js';

const BASE_URL = process.env.BASE_URL || 'http://localhost:4321/council-meeting-analyzer';

export const PERSONA = {
  name: 'Alex - Accessibility Auditor',
  background: 'Tests for WCAG compliance and usability',
  goals: 'Ensure site works for all users regardless of ability',
  behaviors: 'Keyboard-only navigation, screen reader simulation, contrast checks'
};

test.describe.serial('Alex - Accessibility Auditor', () => {
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

  test('Task 1: Keyboard-only navigation through site', async ({ page }) => {
    const startTime = Date.now();
    let success = false;
    let notes = '';
    let tabCount = 0;
    const maxTabs = 30;

    await page.goto(BASE_URL);
    await collector.captureScreenshot(page, 'keyboard-start', 'Task 1: Starting keyboard navigation');

    try {
      // Tab through the page
      const focusedElements = [];

      for (let i = 0; i < maxTabs; i++) {
        await page.keyboard.press('Tab');
        tabCount++;

        const focused = await page.evaluate(() => {
          const el = document.activeElement;
          return {
            tag: el.tagName,
            text: el.textContent?.substring(0, 30),
            href: el.getAttribute('href'),
            hasVisibleFocus: window.getComputedStyle(el).outlineStyle !== 'none' ||
                            el.classList.contains('focus') ||
                            el.matches(':focus-visible')
          };
        });

        focusedElements.push(focused);

        // Check if we've tabbed to a meeting link
        if (focused.href && focused.href.includes('/meetings/')) {
          await collector.captureScreenshot(page, 'keyboard-meeting-focus', 'Task 1: Meeting link focused');

          // Press Enter to navigate
          await page.keyboard.press('Enter');
          await page.waitForTimeout(500);
          await collector.captureScreenshot(page, 'keyboard-entered-meeting', 'Task 1: Navigated via keyboard');
          break;
        }
      }

      // Analyze focus behavior
      const uniqueTags = [...new Set(focusedElements.map(e => e.tag))];
      const withoutVisibleFocus = focusedElements.filter(e => !e.hasVisibleFocus && e.tag !== 'BODY');

      if (tabCount > 5 && focusedElements.some(e => e.href?.includes('/meetings/'))) {
        success = true;
        notes = `Reached meeting link in ${tabCount} tabs`;

        if (withoutVisibleFocus.length > 3) {
          collector.addObservation('note', `${withoutVisibleFocus.length} elements lack visible focus state`, 'Focus management');
        }
      } else {
        notes = `Tabbed ${tabCount} times but could not reach meeting links`;
        collector.addObservation('frustration', 'Key content not easily accessible via keyboard', 'Keyboard navigation');
      }
    } catch (error) {
      notes = `Error: ${error.message}`;
    }

    collector.recordTask('Keyboard navigation', success, Date.now() - startTime, notes);
  });

  test('Task 2: Check focus states on interactive elements', async ({ page }) => {
    const startTime = Date.now();
    let success = false;
    let notes = '';

    await page.goto(BASE_URL);

    try {
      // Get all interactive elements
      const focusIssues = await page.evaluate(() => {
        const interactives = document.querySelectorAll('a, button, input, select, textarea, [tabindex], details summary');
        const issues = [];

        interactives.forEach((el, index) => {
          // Check for visible focus styles
          el.focus();
          const styles = window.getComputedStyle(el);
          const pseudoStyles = window.getComputedStyle(el, ':focus');

          const hasOutline = styles.outlineStyle !== 'none' && styles.outlineWidth !== '0px';
          const hasBoxShadow = styles.boxShadow !== 'none';
          const hasBorderChange = styles.borderColor !== 'rgb(0, 0, 0)';
          const hasFocusClass = el.classList.contains('focus-visible') || el.matches(':focus-visible');

          if (!hasOutline && !hasBoxShadow && !hasFocusClass) {
            issues.push({
              element: el.tagName,
              text: el.textContent?.substring(0, 20),
              issue: 'No visible focus indicator'
            });
          }

          // Check for keyboard accessibility
          if (el.tagName === 'DIV' && el.getAttribute('onclick') && !el.getAttribute('tabindex')) {
            issues.push({
              element: 'DIV',
              text: el.textContent?.substring(0, 20),
              issue: 'Clickable div not keyboard accessible'
            });
          }
        });

        return {
          total: interactives.length,
          issues: issues.slice(0, 10) // Limit for reporting
        };
      });

      await collector.captureScreenshot(page, 'focus-audit', 'Task 2: Focus state audit');

      if (focusIssues.issues.length === 0) {
        success = true;
        notes = `All ${focusIssues.total} interactive elements have focus states`;
      } else if (focusIssues.issues.length < 5) {
        success = true;
        notes = `Minor focus issues: ${focusIssues.issues.length} of ${focusIssues.total} elements`;
        focusIssues.issues.forEach(issue => {
          collector.addObservation('note', `${issue.element}: ${issue.issue}`, issue.text || 'Interactive element');
        });
      } else {
        notes = `Significant focus issues: ${focusIssues.issues.length} elements`;
        collector.addObservation('frustration', `${focusIssues.issues.length} elements lack proper focus states`, 'Focus management');
      }
    } catch (error) {
      notes = `Error: ${error.message}`;
    }

    collector.recordTask('Check focus states', success, Date.now() - startTime, notes);
  });

  test('Task 3: Verify heading hierarchy', async ({ page }) => {
    const startTime = Date.now();
    let success = false;
    let notes = '';

    await page.goto(BASE_URL);
    await collector.captureScreenshot(page, 'heading-audit-home', 'Task 3: Homepage heading audit');

    try {
      // Analyze heading structure on homepage
      const homeHeadings = await page.evaluate(() => {
        const headings = document.querySelectorAll('h1, h2, h3, h4, h5, h6');
        return Array.from(headings).map(h => ({
          level: parseInt(h.tagName[1]),
          text: h.textContent?.trim().substring(0, 50),
          isEmpty: !h.textContent?.trim()
        }));
      });

      // Check for proper hierarchy
      let h1Count = homeHeadings.filter(h => h.level === 1).length;
      let hierarchyIssues = [];

      // Should have exactly one h1
      if (h1Count !== 1) {
        hierarchyIssues.push(`Found ${h1Count} h1 elements (should be 1)`);
      }

      // Check for skipped levels
      for (let i = 1; i < homeHeadings.length; i++) {
        const current = homeHeadings[i].level;
        const previous = homeHeadings[i - 1].level;
        if (current > previous + 1) {
          hierarchyIssues.push(`Skipped from h${previous} to h${current}`);
        }
      }

      // Check empty headings
      const emptyHeadings = homeHeadings.filter(h => h.isEmpty);
      if (emptyHeadings.length > 0) {
        hierarchyIssues.push(`${emptyHeadings.length} empty heading elements`);
      }

      // Also check a meeting page
      await page.locator('a[href*="/meetings/"]').first().click();
      collector.trackClick();
      await page.waitForTimeout(500);
      await collector.captureScreenshot(page, 'heading-audit-meeting', 'Task 3: Meeting page heading audit');

      const meetingHeadings = await page.evaluate(() => {
        const headings = document.querySelectorAll('h1, h2, h3, h4, h5, h6');
        return Array.from(headings).map(h => ({
          level: parseInt(h.tagName[1]),
          text: h.textContent?.trim().substring(0, 50)
        }));
      });

      const meetingH1 = meetingHeadings.filter(h => h.level === 1).length;
      if (meetingH1 !== 1) {
        hierarchyIssues.push(`Meeting page has ${meetingH1} h1 elements`);
      }

      if (hierarchyIssues.length === 0) {
        success = true;
        notes = 'Heading hierarchy is correct';
      } else if (hierarchyIssues.length <= 2) {
        success = true;
        notes = `Minor hierarchy issues: ${hierarchyIssues.join(', ')}`;
        hierarchyIssues.forEach(issue => {
          collector.addObservation('note', issue, 'Heading structure');
        });
      } else {
        notes = `Heading hierarchy issues: ${hierarchyIssues.length} problems`;
        collector.addObservation('frustration', `Multiple heading hierarchy issues: ${hierarchyIssues.slice(0, 3).join('; ')}`, 'Document structure');
      }
    } catch (error) {
      notes = `Error: ${error.message}`;
    }

    collector.recordTask('Verify heading hierarchy', success, Date.now() - startTime, notes);
  });

  test('Task 4: Check images for alt text', async ({ page }) => {
    const startTime = Date.now();
    let success = false;
    let notes = '';

    await page.goto(BASE_URL);

    try {
      // Check all images on homepage
      const homeImages = await page.evaluate(() => {
        const images = document.querySelectorAll('img');
        const svgs = document.querySelectorAll('svg');

        const imgIssues = Array.from(images).filter(img => {
          const alt = img.getAttribute('alt');
          const isDecorative = img.getAttribute('role') === 'presentation' ||
                              img.getAttribute('aria-hidden') === 'true';
          return !alt && !isDecorative;
        }).map(img => ({
          src: img.src?.substring(0, 50),
          issue: 'Missing alt text'
        }));

        // SVGs should have accessible names
        const svgIssues = Array.from(svgs).filter(svg => {
          const hasTitle = svg.querySelector('title');
          const hasAriaLabel = svg.getAttribute('aria-label');
          const isHidden = svg.getAttribute('aria-hidden') === 'true';
          const inButton = svg.closest('button, a');
          return !hasTitle && !hasAriaLabel && !isHidden && !inButton;
        }).length;

        return {
          totalImages: images.length,
          totalSvgs: svgs.length,
          imgIssues,
          svgIssues
        };
      });

      await collector.captureScreenshot(page, 'image-audit', 'Task 4: Image accessibility audit');

      // Navigate to meeting page too
      await page.locator('a[href*="/meetings/"]').first().click();
      collector.trackClick();
      await page.waitForTimeout(500);

      const meetingImages = await page.evaluate(() => {
        const images = document.querySelectorAll('img');
        return Array.from(images).filter(img => !img.getAttribute('alt')).length;
      });

      const totalIssues = homeImages.imgIssues.length + homeImages.svgIssues + meetingImages;

      if (totalIssues === 0) {
        success = true;
        notes = 'All images have appropriate alt text or are decorative';
      } else if (totalIssues <= 3) {
        success = true;
        notes = `Minor image accessibility issues: ${totalIssues} items`;
        collector.addObservation('note', `${totalIssues} images/icons may need alt text review`, 'Image accessibility');
      } else {
        notes = `Image accessibility issues: ${totalIssues} items missing alt text`;
        collector.addObservation('frustration', `${totalIssues} images lack alt text for screen readers`, 'Image accessibility');
      }
    } catch (error) {
      notes = `Error: ${error.message}`;
    }

    collector.recordTask('Check image alt text', success, Date.now() - startTime, notes);
  });

  test('Task 5: Verify links have descriptive text', async ({ page }) => {
    const startTime = Date.now();
    let success = false;
    let notes = '';

    await page.goto(BASE_URL);

    try {
      const linkAudit = await page.evaluate(() => {
        const links = document.querySelectorAll('a');
        const issues = [];

        links.forEach(link => {
          const text = link.textContent?.trim();
          const ariaLabel = link.getAttribute('aria-label');
          const title = link.getAttribute('title');
          const img = link.querySelector('img');
          const imgAlt = img?.getAttribute('alt');

          const accessibleName = text || ariaLabel || title || imgAlt;

          // Check for vague link text
          if (['click here', 'here', 'read more', 'more', 'link'].includes(accessibleName?.toLowerCase())) {
            issues.push({ text: accessibleName, issue: 'Vague link text' });
          }

          // Check for empty links
          if (!accessibleName) {
            issues.push({ href: link.href?.substring(0, 30), issue: 'Empty link (no accessible name)' });
          }
        });

        return {
          total: links.length,
          issues
        };
      });

      await collector.captureScreenshot(page, 'link-audit', 'Task 5: Link accessibility audit');

      if (linkAudit.issues.length === 0) {
        success = true;
        notes = `All ${linkAudit.total} links have descriptive text`;
      } else if (linkAudit.issues.length <= 3) {
        success = true;
        notes = `Minor link text issues: ${linkAudit.issues.length} of ${linkAudit.total}`;
        linkAudit.issues.forEach(issue => {
          collector.addObservation('note', `Link issue: ${issue.issue}`, issue.text || issue.href || 'Link');
        });
      } else {
        notes = `Link accessibility issues: ${linkAudit.issues.length} links`;
        collector.addObservation('frustration', `${linkAudit.issues.length} links lack descriptive text`, 'Link accessibility');
      }
    } catch (error) {
      notes = `Error: ${error.message}`;
    }

    collector.recordTask('Verify link text', success, Date.now() - startTime, notes);
  });

  test('Free Exploration: Full accessibility sweep', async ({ page }) => {
    const startTime = Date.now();

    await page.goto(BASE_URL);
    collector.addObservation('note', 'Beginning comprehensive accessibility audit', 'Full site');
    await collector.captureScreenshot(page, 'a11y-start', 'Exploration: Starting audit');

    const actions = [
      // Check color contrast (basic check via computed styles)
      async () => {
        const contrastIssues = await page.evaluate(() => {
          const textElements = document.querySelectorAll('p, span, a, h1, h2, h3, h4, li');
          let potentialIssues = 0;

          textElements.forEach(el => {
            const style = window.getComputedStyle(el);
            const color = style.color;
            const bgColor = style.backgroundColor;

            // Basic check: if both are very similar, may be contrast issue
            // This is a simplified check; real audit would use WCAG formula
            if (color === bgColor && color !== 'rgba(0, 0, 0, 0)') {
              potentialIssues++;
            }
          });

          return potentialIssues;
        });

        if (contrastIssues > 0) {
          collector.addObservation('note', `${contrastIssues} potential contrast issues detected`, 'Color contrast');
        } else {
          collector.addObservation('success', 'No obvious contrast issues detected', 'Color contrast');
        }
      },
      // Check for ARIA usage
      async () => {
        const ariaUsage = await page.evaluate(() => {
          const withAria = document.querySelectorAll('[aria-label], [aria-describedby], [aria-labelledby], [role]');
          const regions = document.querySelectorAll('[role="main"], [role="navigation"], [role="banner"], main, nav, header');
          return {
            ariaElements: withAria.length,
            landmarks: regions.length
          };
        });

        if (ariaUsage.landmarks >= 2) {
          collector.addObservation('success', `${ariaUsage.landmarks} landmark regions defined`, 'Document structure');
        } else {
          collector.addObservation('note', 'Consider adding more landmark regions (main, nav, etc.)', 'Document structure');
        }
      },
      // Test skip link
      async () => {
        await page.goto(BASE_URL);
        await page.keyboard.press('Tab');

        const skipLink = await page.evaluate(() => {
          const active = document.activeElement;
          return active?.textContent?.toLowerCase().includes('skip') ||
                 active?.getAttribute('href')?.includes('#main');
        });

        if (skipLink) {
          collector.addObservation('success', 'Skip link available for keyboard users', 'Navigation');
        } else {
          collector.addObservation('note', 'Consider adding skip-to-main-content link', 'Navigation');
        }
      },
      // Check form labels
      async () => {
        const formAudit = await page.evaluate(() => {
          const inputs = document.querySelectorAll('input:not([type="hidden"]), select, textarea');
          let unlabeled = 0;

          inputs.forEach(input => {
            const id = input.id;
            const label = id ? document.querySelector(`label[for="${id}"]`) : null;
            const ariaLabel = input.getAttribute('aria-label');
            const placeholder = input.getAttribute('placeholder');

            if (!label && !ariaLabel && !placeholder) {
              unlabeled++;
            }
          });

          return { total: inputs.length, unlabeled };
        });

        if (formAudit.unlabeled > 0) {
          collector.addObservation('note', `${formAudit.unlabeled} form inputs may lack labels`, 'Form accessibility');
        }
      }
    ];

    for (const action of actions) {
      try {
        await action();
      } catch (e) {
        collector.addObservation('note', `Audit check failed: ${e.message}`, 'Accessibility sweep');
      }
    }

    await collector.captureScreenshot(page, 'a11y-end', 'Exploration: Audit complete');
    collector.recordTask('Full accessibility sweep', true, Date.now() - startTime, 'Completed comprehensive audit');
  });
});

export default PERSONA;
