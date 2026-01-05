/**
 * Report Generator for Persona Tests
 * Consolidates observations and LLM analysis into prioritized action items
 */

import fs from 'fs';
import path from 'path';
import { analyzeSession, isOllamaAvailable } from './ollama-client.js';

// Persona definitions for LLM context
const PERSONAS = {
  'maria-campaign-researcher': {
    name: 'Maria - Campaign Researcher',
    background: 'Works for a local candidate, researches voting records and positions',
    goals: 'Find specific votes, track council member positions, extract quotes',
    behaviors: 'Heavy search user, reads transcripts, exports data mentally'
  },
  'david-concerned-citizen': {
    name: 'David - Concerned Citizen',
    background: 'Resident worried about local issues, moderate tech skills',
    goals: 'Understand what happened at meetings, find decisions on topics he cares about',
    behaviors: 'Uses filters, skims summaries, watches some videos'
  },
  'sarah-local-journalist': {
    name: 'Sarah - Local Journalist',
    background: 'Reporter for local news, needs accurate quotes and facts',
    goals: 'Fact-check claims, find source material, verify voting records',
    behaviors: 'Precise searches, reads full transcripts, checks video links'
  },
  'james-first-time-visitor': {
    name: 'James - First-Time Visitor',
    background: "Just heard about the site, doesn't know what it offers",
    goals: 'Understand what this site is and if it\'s useful',
    behaviors: 'Reads about page, browses randomly, may leave quickly if confused'
  },
  'alex-accessibility-auditor': {
    name: 'Alex - Accessibility Auditor',
    background: 'Tests for WCAG compliance and usability',
    goals: 'Ensure site works for all users regardless of ability',
    behaviors: 'Keyboard-only navigation, screen reader simulation, contrast checks'
  },
  'elena-ui-designer': {
    name: 'Elena - UI Designer',
    background: 'Senior UI/UX designer with 10+ years experience, opinionated about design quality',
    goals: 'Evaluate visual design, usability, user flows, and suggest bold improvements',
    behaviors: 'Scrutinizes every detail - colors, typography, spacing, hierarchy, consistency'
  }
};

/**
 * Load observations from test results directory
 */
function loadObservations(baseDir = 'test-results/personas') {
  const resultsPath = path.resolve(process.cwd(), baseDir);
  const observations = [];

  if (!fs.existsSync(resultsPath)) {
    console.warn(`Results directory not found: ${resultsPath}`);
    return observations;
  }

  const personaDirs = fs.readdirSync(resultsPath, { withFileTypes: true })
    .filter(d => d.isDirectory())
    .map(d => d.name);

  for (const personaDir of personaDirs) {
    const obsPath = path.join(resultsPath, personaDir, 'observations.json');
    if (fs.existsSync(obsPath)) {
      try {
        const data = JSON.parse(fs.readFileSync(obsPath, 'utf-8'));
        observations.push({
          personaId: personaDir,
          ...data
        });
      } catch (e) {
        console.warn(`Failed to load ${obsPath}: ${e.message}`);
      }
    }
  }

  return observations;
}

/**
 * Generate LLM analysis for each persona's session
 */
async function generateLLMAnalysis(observations, options = {}) {
  const { skipLLM = false, model } = options;
  const results = [];

  if (skipLLM) {
    console.log('Skipping LLM analysis (--skip-llm flag)');
    return observations.map(obs => ({
      persona: obs.persona,
      analysis: extractBasicFindings(obs)
    }));
  }

  const ollamaUp = await isOllamaAvailable();
  if (!ollamaUp) {
    console.warn('Ollama not available - using basic analysis only');
    return observations.map(obs => ({
      persona: obs.persona,
      analysis: extractBasicFindings(obs)
    }));
  }

  for (const obs of observations) {
    const personaContext = PERSONAS[obs.personaId] || {
      name: obs.persona,
      background: 'Unknown persona',
      goals: 'Complete assigned tasks',
      behaviors: 'Standard browsing'
    };

    try {
      console.log(`Analyzing session for ${personaContext.name}...`);
      const result = await analyzeSession(personaContext, obs, { model });
      results.push(result);
    } catch (e) {
      console.warn(`LLM analysis failed for ${personaContext.name}: ${e.message}`);
      results.push({
        persona: personaContext.name,
        analysis: extractBasicFindings(obs)
      });
    }
  }

  return results;
}

/**
 * Extract basic findings without LLM (fallback)
 */
function extractBasicFindings(observations) {
  const actionItems = [];

  // Convert observations to action items
  for (const obs of observations.observations || []) {
    if (obs.type === 'frustration') {
      actionItems.push({
        category: 'ui',
        priority: 'high',
        issue: obs.description,
        location: obs.location || 'Unknown',
        recommendation: 'Review and address user frustration point'
      });
    } else if (obs.type === 'confusion') {
      actionItems.push({
        category: 'ui',
        priority: 'medium',
        issue: obs.description,
        location: obs.location || 'Unknown',
        recommendation: 'Clarify or improve user guidance'
      });
    } else if (obs.type === 'note' && /missing|lack|no\s/i.test(obs.description)) {
      actionItems.push({
        category: 'content',
        priority: 'low',
        issue: obs.description,
        location: obs.location || 'Unknown',
        recommendation: 'Consider adding missing feature or content'
      });
    }
  }

  // Check task failures
  for (const task of observations.taskResults || []) {
    if (!task.success) {
      actionItems.push({
        category: 'ui',
        priority: 'high',
        issue: `Task failed: ${task.task}`,
        location: 'User journey',
        recommendation: task.notes || 'Investigate task failure'
      });
    }
  }

  // Calculate score based on task success
  const tasks = observations.taskResults || [];
  const successRate = tasks.length > 0
    ? tasks.filter(t => t.success).length / tasks.length
    : 0;
  const overallScore = Math.round(successRate * 10 * 10) / 10;

  return {
    action_items: actionItems,
    overall_score: overallScore,
    top_frustration: actionItems.find(a => a.priority === 'high')?.issue || 'None identified'
  };
}

/**
 * Deduplicate and consolidate action items across personas
 */
function consolidateActionItems(analyses) {
  const allItems = [];
  const itemMap = new Map();

  for (const analysis of analyses) {
    const items = analysis.analysis?.action_items || [];
    for (const item of items) {
      // Create a key for deduplication
      const key = `${item.category}:${item.issue?.toLowerCase().substring(0, 50)}`;

      if (itemMap.has(key)) {
        // Increase priority if multiple personas report same issue
        const existing = itemMap.get(key);
        existing.reportedBy.push(analysis.persona);
        if (item.priority === 'high' || (item.priority === 'medium' && existing.priority === 'low')) {
          existing.priority = item.priority;
        }
      } else {
        itemMap.set(key, {
          ...item,
          reportedBy: [analysis.persona]
        });
      }
    }
  }

  // Sort by priority and number of reports
  const priorityOrder = { high: 0, medium: 1, low: 2 };
  return Array.from(itemMap.values()).sort((a, b) => {
    if (priorityOrder[a.priority] !== priorityOrder[b.priority]) {
      return priorityOrder[a.priority] - priorityOrder[b.priority];
    }
    return b.reportedBy.length - a.reportedBy.length;
  });
}

/**
 * Generate final consolidated report
 */
export async function generateReport(options = {}) {
  const {
    outputDir = 'reports',
    skipLLM = false,
    model
  } = options;

  console.log('Loading persona observations...');
  const observations = loadObservations();

  if (observations.length === 0) {
    console.error('No observations found. Run persona tests first: npm run test:personas');
    return null;
  }

  console.log(`Found ${observations.length} persona sessions`);

  // Generate analysis
  console.log('Generating analysis...');
  const analyses = await generateLLMAnalysis(observations, { skipLLM, model });

  // Consolidate findings
  console.log('Consolidating findings...');
  const consolidatedItems = consolidateActionItems(analyses);

  // Calculate overall metrics
  const overallScore = analyses.reduce((sum, a) =>
    sum + (a.analysis?.overall_score || 0), 0) / analyses.length;

  const report = {
    generated: new Date().toISOString(),
    summary: {
      personasAnalyzed: observations.length,
      totalTasks: observations.reduce((sum, o) => sum + (o.taskResults?.length || 0), 0),
      tasksSucceeded: observations.reduce((sum, o) =>
        sum + (o.taskResults?.filter(t => t.success).length || 0), 0),
      overallScore: Math.round(overallScore * 10) / 10,
      actionItemsCount: consolidatedItems.length,
      highPriorityCount: consolidatedItems.filter(i => i.priority === 'high').length
    },
    personaResults: analyses.map(a => ({
      persona: a.persona,
      score: a.analysis?.overall_score || 0,
      topFrustration: a.analysis?.top_frustration || 'None',
      itemCount: a.analysis?.action_items?.length || 0
    })),
    actionItems: consolidatedItems,
    rawAnalyses: analyses
  };

  // Save report
  const reportsPath = path.resolve(process.cwd(), outputDir);
  if (!fs.existsSync(reportsPath)) {
    fs.mkdirSync(reportsPath, { recursive: true });
  }

  const jsonPath = path.join(reportsPath, 'action-items.json');
  fs.writeFileSync(jsonPath, JSON.stringify(report, null, 2));
  console.log(`Report saved to ${jsonPath}`);

  // Generate markdown summary
  const mdPath = path.join(reportsPath, 'summary.md');
  fs.writeFileSync(mdPath, generateMarkdownSummary(report));
  console.log(`Summary saved to ${mdPath}`);

  return report;
}

/**
 * Generate markdown summary
 */
function generateMarkdownSummary(report) {
  const lines = [
    '# Persona UX Testing Report',
    '',
    `Generated: ${report.generated}`,
    '',
    '## Summary',
    '',
    `| Metric | Value |`,
    `|--------|-------|`,
    `| Personas Analyzed | ${report.summary.personasAnalyzed} |`,
    `| Total Tasks | ${report.summary.totalTasks} |`,
    `| Tasks Succeeded | ${report.summary.tasksSucceeded} |`,
    `| Overall Score | ${report.summary.overallScore}/10 |`,
    `| Action Items | ${report.summary.actionItemsCount} |`,
    `| High Priority | ${report.summary.highPriorityCount} |`,
    '',
    '## Persona Results',
    ''
  ];

  for (const persona of report.personaResults) {
    lines.push(`### ${persona.persona}`);
    lines.push(`- Score: ${persona.score}/10`);
    lines.push(`- Top Frustration: ${persona.topFrustration}`);
    lines.push(`- Issues Found: ${persona.itemCount}`);
    lines.push('');
  }

  lines.push('## Priority Action Items');
  lines.push('');

  const highItems = report.actionItems.filter(i => i.priority === 'high');
  const mediumItems = report.actionItems.filter(i => i.priority === 'medium');

  if (highItems.length > 0) {
    lines.push('### High Priority');
    lines.push('');
    for (const item of highItems) {
      lines.push(`- **${item.issue}**`);
      lines.push(`  - Location: ${item.location}`);
      lines.push(`  - Recommendation: ${item.recommendation}`);
      lines.push(`  - Reported by: ${item.reportedBy.join(', ')}`);
      lines.push('');
    }
  }

  if (mediumItems.length > 0) {
    lines.push('### Medium Priority');
    lines.push('');
    for (const item of mediumItems.slice(0, 10)) {
      lines.push(`- **${item.issue}**`);
      lines.push(`  - Location: ${item.location}`);
      lines.push(`  - Recommendation: ${item.recommendation}`);
      lines.push('');
    }
  }

  return lines.join('\n');
}

// CLI support
if (process.argv[1].endsWith('report-generator.js')) {
  const skipLLM = process.argv.includes('--skip-llm');
  generateReport({ skipLLM }).then(report => {
    if (report) {
      console.log('\n=== Report Summary ===');
      console.log(`Score: ${report.summary.overallScore}/10`);
      console.log(`High Priority Items: ${report.summary.highPriorityCount}`);
      console.log(`Total Action Items: ${report.summary.actionItemsCount}`);
    }
  });
}

export default { generateReport };
