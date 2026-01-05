/**
 * Ollama Client for Persona UX Analysis
 * Connects to local Ollama instance for LLM-based UX feedback
 */

const OLLAMA_URL = process.env.OLLAMA_URL || 'http://localhost:11434';
const PRIMARY_MODEL = 'qwen2.5vl:72b';
const FALLBACK_MODEL = 'mistral:7b-instruct';

/**
 * Generate UX analysis prompt for a persona session
 */
function buildAnalysisPrompt(personaContext, observations) {
  return `You are a UX analyst reviewing a user journey through a local government meeting archive website.

PERSONA: ${personaContext.name}
BACKGROUND: ${personaContext.background}
GOALS: ${personaContext.goals}
BEHAVIORS: ${personaContext.behaviors}

The user completed these tasks:
${observations.taskResults.map((t, i) => `${i + 1}. ${t.task}: ${t.success ? 'SUCCESS' : 'FAILED'} (${Math.round(t.duration / 1000)}s)${t.notes ? ' - ' + t.notes : ''}`).join('\n')}

Session metrics:
- Duration: ${observations.sessionDuration?.toFixed(1)}s
- Page loads: ${observations.metrics.pageLoads}
- Clicks: ${observations.metrics.clicks}
- Searches: ${observations.metrics.searches}
- Back navigations: ${observations.metrics.backNavigations}
- Errors: ${observations.metrics.errorCount}

User observations during session:
${observations.observations.map(o => `- [${o.type}] ${o.description}${o.location ? ' @ ' + o.location : ''}`).join('\n') || 'None recorded'}

Screenshots attached show the user's view at key moments during their journey.

Based on this session, identify issues and improvements in two categories:

1. UI/UX ISSUES: Navigation problems, confusing layouts, missing features, poor affordances, unclear call-to-actions
2. CONTENT ISSUES: Unclear text, missing information, data accuracy concerns, labeling problems, confusing terminology

For each issue, provide:
- category: "ui" or "content"
- priority: "high" (blocks or fails task), "medium" (slows task or causes confusion), "low" (minor friction)
- issue: What went wrong or could be improved
- location: Page/element where issue occurred
- recommendation: Specific, actionable fix

Also provide:
- overall_score: 1-10 rating of the experience for this persona
- top_frustration: Single most important issue to fix

Return your analysis as valid JSON matching this structure:
{
  "action_items": [
    {
      "category": "ui|content",
      "priority": "high|medium|low",
      "issue": "description",
      "location": "page/element",
      "recommendation": "specific fix"
    }
  ],
  "overall_score": 7.5,
  "top_frustration": "description of main issue"
}

Only return the JSON object, no additional text.`;
}

/**
 * Call Ollama API with optional images
 * @param {string} prompt
 * @param {string[]} images - Array of base64-encoded images
 * @param {string} model
 */
async function callOllama(prompt, images = [], model = PRIMARY_MODEL) {
  const payload = {
    model,
    prompt,
    stream: false,
    format: 'json',
    options: {
      temperature: 0.3,
      num_predict: 2000
    }
  };

  // Add images if provided and model supports vision
  if (images.length > 0 && model.includes('vl')) {
    payload.images = images;
  }

  const response = await fetch(`${OLLAMA_URL}/api/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    throw new Error(`Ollama API error: ${response.status} ${response.statusText}`);
  }

  const data = await response.json();
  return data.response;
}

/**
 * Check if Ollama is running and model is available
 */
async function checkOllamaHealth(model = PRIMARY_MODEL) {
  try {
    const response = await fetch(`${OLLAMA_URL}/api/tags`);
    if (!response.ok) return { healthy: false, error: 'Ollama not responding' };

    const data = await response.json();
    const models = data.models.map(m => m.name);
    const hasModel = models.some(m => m.startsWith(model.split(':')[0]));

    return {
      healthy: true,
      hasModel,
      availableModels: models
    };
  } catch (error) {
    return { healthy: false, error: error.message };
  }
}

/**
 * Analyze a persona session using Ollama
 * @param {object} personaContext - Persona definition
 * @param {object} observations - Collected observations from session
 * @param {object} options - Analysis options
 */
export async function analyzeSession(personaContext, observations, options = {}) {
  const {
    model = PRIMARY_MODEL,
    maxImages = 5,
    retries = 2,
    timeout = 120000
  } = options;

  // Check Ollama health
  const health = await checkOllamaHealth(model);
  if (!health.healthy) {
    throw new Error(`Ollama not available: ${health.error}`);
  }

  let useModel = model;
  if (!health.hasModel) {
    console.warn(`Model ${model} not found, falling back to ${FALLBACK_MODEL}`);
    useModel = FALLBACK_MODEL;
  }

  // Build prompt
  const prompt = buildAnalysisPrompt(personaContext, observations);

  // Select screenshots (limit to maxImages for context window)
  const images = observations.screenshots
    .slice(0, maxImages)
    .map(s => s.base64);

  // Call Ollama with retries
  let lastError;
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), timeout);

      const response = await callOllama(prompt, images, useModel);
      clearTimeout(timeoutId);

      // Parse JSON response
      const analysis = JSON.parse(response);

      // Validate structure
      if (!analysis.action_items || !Array.isArray(analysis.action_items)) {
        throw new Error('Invalid response structure: missing action_items array');
      }

      return {
        persona: personaContext.name,
        model: useModel,
        analysis,
        rawResponse: response
      };
    } catch (error) {
      lastError = error;
      console.warn(`Ollama attempt ${attempt + 1} failed: ${error.message}`);
      if (attempt < retries) {
        await new Promise(r => setTimeout(r, 1000 * (attempt + 1)));
      }
    }
  }

  throw new Error(`Ollama analysis failed after ${retries + 1} attempts: ${lastError.message}`);
}

/**
 * Quick health check for test setup
 */
export async function isOllamaAvailable() {
  const health = await checkOllamaHealth();
  return health.healthy;
}

/**
 * Get available models
 */
export async function getAvailableModels() {
  const health = await checkOllamaHealth();
  return health.healthy ? health.availableModels : [];
}

export default {
  analyzeSession,
  isOllamaAvailable,
  getAvailableModels,
  PRIMARY_MODEL,
  FALLBACK_MODEL
};
