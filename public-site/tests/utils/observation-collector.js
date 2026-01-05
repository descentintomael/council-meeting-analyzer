/**
 * Observation Collector for Persona Tests
 * Captures screenshots, metrics, and observations during user journey simulations
 */

import fs from 'fs';
import path from 'path';

export class ObservationCollector {
  constructor(personaName, outputDir = 'test-results/personas') {
    this.personaName = personaName;
    this.outputDir = path.resolve(process.cwd(), outputDir, personaName.toLowerCase().replace(/\s+/g, '-'));
    this.observations = [];
    this.screenshots = [];
    this.taskResults = [];
    this.metrics = {
      startTime: null,
      endTime: null,
      pageLoads: 0,
      clicks: 0,
      searches: 0,
      backNavigations: 0,
      errors: []
    };

    // Ensure output directory exists
    if (!fs.existsSync(this.outputDir)) {
      fs.mkdirSync(this.outputDir, { recursive: true });
    }
  }

  startSession() {
    this.metrics.startTime = Date.now();
  }

  endSession() {
    this.metrics.endTime = Date.now();
    return this.metrics.endTime - this.metrics.startTime;
  }

  /**
   * Capture a screenshot with context
   * @param {import('@playwright/test').Page} page
   * @param {string} name - Description of what's being captured
   * @param {string} context - Additional context (task, exploration phase)
   */
  async captureScreenshot(page, name, context = '') {
    const timestamp = Date.now();
    const filename = `${timestamp}-${name.toLowerCase().replace(/\s+/g, '-')}.png`;
    const filepath = path.join(this.outputDir, filename);

    await page.screenshot({ path: filepath, fullPage: false });

    // Read as base64 for LLM processing
    const base64 = fs.readFileSync(filepath, { encoding: 'base64' });

    const screenshot = {
      timestamp,
      name,
      context,
      filename,
      filepath,
      base64,
      url: page.url(),
      title: await page.title()
    };

    this.screenshots.push(screenshot);
    return screenshot;
  }

  /**
   * Record task completion
   * @param {string} taskName
   * @param {boolean} success
   * @param {number} duration - Time taken in ms
   * @param {string} notes - Any observations
   */
  recordTask(taskName, success, duration, notes = '') {
    this.taskResults.push({
      task: taskName,
      success,
      duration,
      notes,
      timestamp: Date.now()
    });
  }

  /**
   * Add a general observation
   * @param {string} type - 'confusion', 'frustration', 'success', 'note'
   * @param {string} description
   * @param {string} location - Page/element where it occurred
   */
  addObservation(type, description, location = '') {
    this.observations.push({
      type,
      description,
      location,
      timestamp: Date.now()
    });
  }

  /**
   * Track a page navigation
   */
  trackPageLoad() {
    this.metrics.pageLoads++;
  }

  /**
   * Track a click action
   */
  trackClick() {
    this.metrics.clicks++;
  }

  /**
   * Track a search action
   */
  trackSearch() {
    this.metrics.searches++;
  }

  /**
   * Track back navigation (potential confusion indicator)
   */
  trackBackNavigation() {
    this.metrics.backNavigations++;
  }

  /**
   * Record a console error
   * @param {string} error
   */
  recordError(error) {
    this.metrics.errors.push({
      error,
      timestamp: Date.now()
    });
  }

  /**
   * Extract visible text from key elements
   * @param {import('@playwright/test').Page} page
   */
  async extractPageContent(page) {
    const content = await page.evaluate(() => {
      const getText = (selector) => {
        const el = document.querySelector(selector);
        return el ? el.textContent.trim() : null;
      };

      const getAllText = (selector) => {
        return Array.from(document.querySelectorAll(selector))
          .map(el => el.textContent.trim())
          .filter(Boolean);
      };

      return {
        h1: getText('h1'),
        h2s: getAllText('h2'),
        navLinks: getAllText('nav a'),
        buttons: getAllText('button, .btn'),
        alerts: getAllText('.alert'),
        cardCount: document.querySelectorAll('.card').length,
        linkCount: document.querySelectorAll('a').length
      };
    });

    return content;
  }

  /**
   * Get summary for LLM processing
   */
  getSummary() {
    const duration = this.metrics.endTime
      ? (this.metrics.endTime - this.metrics.startTime) / 1000
      : null;

    return {
      persona: this.personaName,
      sessionDuration: duration,
      tasksCompleted: this.taskResults.filter(t => t.success).length,
      tasksFailed: this.taskResults.filter(t => !t.success).length,
      taskResults: this.taskResults,
      observations: this.observations,
      metrics: {
        pageLoads: this.metrics.pageLoads,
        clicks: this.metrics.clicks,
        searches: this.metrics.searches,
        backNavigations: this.metrics.backNavigations,
        errorCount: this.metrics.errors.length
      },
      screenshots: this.screenshots.map(s => ({
        name: s.name,
        context: s.context,
        url: s.url,
        title: s.title,
        base64: s.base64
      })),
      errors: this.metrics.errors
    };
  }

  /**
   * Save observations to disk
   */
  saveToFile() {
    const summary = this.getSummary();
    const filepath = path.join(this.outputDir, 'observations.json');
    fs.writeFileSync(filepath, JSON.stringify(summary, null, 2));
    return filepath;
  }
}

export default ObservationCollector;
