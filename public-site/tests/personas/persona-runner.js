/**
 * Persona Test Runner
 * Orchestrates running all persona tests and generating the report
 *
 * Usage:
 *   node tests/personas/persona-runner.js [options]
 *
 * Options:
 *   --skip-llm    Skip LLM analysis (use basic findings only)
 *   --report-only Only generate report from existing results
 */

import { spawn } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';
import { generateReport } from '../utils/report-generator.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

async function runPlaywrightTests() {
  return new Promise((resolve, reject) => {
    console.log('\n========================================');
    console.log('Running Persona Tests');
    console.log('========================================\n');

    const playwright = spawn('npx', [
      'playwright', 'test',
      '--grep', '@persona',
      'tests/personas/'
    ], {
      cwd: path.resolve(__dirname, '../..'),
      stdio: 'inherit',
      shell: true
    });

    playwright.on('close', (code) => {
      if (code === 0) {
        resolve();
      } else {
        // Don't reject on test failures - we want the report anyway
        console.warn(`\nSome tests may have failed (exit code: ${code})`);
        resolve();
      }
    });

    playwright.on('error', (err) => {
      reject(err);
    });
  });
}

async function main() {
  const args = process.argv.slice(2);
  const skipLLM = args.includes('--skip-llm');
  const reportOnly = args.includes('--report-only');

  console.log('╔════════════════════════════════════════╗');
  console.log('║     Persona UX Testing Suite           ║');
  console.log('╚════════════════════════════════════════╝');
  console.log('');
  console.log('Personas:');
  console.log('  • Maria - Campaign Researcher');
  console.log('  • David - Concerned Citizen');
  console.log('  • Sarah - Local Journalist');
  console.log('  • James - First-Time Visitor');
  console.log('  • Alex - Accessibility Auditor');
  console.log('');

  if (!reportOnly) {
    try {
      await runPlaywrightTests();
    } catch (error) {
      console.error('Failed to run Playwright tests:', error.message);
      process.exit(1);
    }
  }

  console.log('\n========================================');
  console.log('Generating Report');
  console.log('========================================\n');

  try {
    const report = await generateReport({ skipLLM });

    if (report) {
      console.log('\n========================================');
      console.log('Final Results');
      console.log('========================================');
      console.log(`\nOverall Score: ${report.summary.overallScore}/10`);
      console.log(`Tasks: ${report.summary.tasksSucceeded}/${report.summary.totalTasks} succeeded`);
      console.log(`Action Items: ${report.summary.actionItemsCount} total`);
      console.log(`  • High Priority: ${report.summary.highPriorityCount}`);

      if (report.summary.highPriorityCount > 0) {
        console.log('\nTop Issues to Address:');
        const highItems = report.actionItems.filter(i => i.priority === 'high').slice(0, 3);
        highItems.forEach((item, i) => {
          console.log(`  ${i + 1}. ${item.issue}`);
        });
      }

      console.log('\nReports saved to:');
      console.log('  • reports/action-items.json');
      console.log('  • reports/summary.md');
    }
  } catch (error) {
    console.error('Failed to generate report:', error.message);
    process.exit(1);
  }
}

main();
