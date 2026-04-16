/**
 * diagnostic-context extension — primary orchestration for canary.
 *
 * Responsibilities:
 *   - Register CLI flags and local LLM provider
 *   - Inject initial context (function + diagnostic) into the system prompt
 *   - After each agent turn: apply SEARCH/REPLACE, compile, validate, steer or terminate
 *
 * The agent loop:
 *   before_agent_start → [read current source, build system prompt]
 *   agent outputs SEARCH/REPLACE
 *   agent_end → [apply, compile, validate] → sendUserMessage (followUp) or terminate
 *   before_agent_start fires again → [read updated source, build new system prompt]
 *   ... repeat up to max-turns ...
 */

import type { ExtensionFactory } from '@mariozechner/pi-coding-agent';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

import { state } from './shared-state.js';
import {
  findSourceFile,
  extractFunction,
  numberLines,
  extractFileContext,
  findRemarkFiles,
  cleanRemarkFiles,
  parseRemarksForFunction,
  ablateRemarks,
  checkVectorizationSuccess,
  parseSearchReplace,
  applySearchReplace,
  runMake,
  runValidator,
  extractCompileErrors,
} from './utils.js';

// Resolve prompt template relative to this file's location in the compiled output.
// Both source (extensions/) and compiled (dist/extensions/) sit one level below
// the repo root, so ../prompts/optimization.md works in both cases.
const PROMPT_PATH = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
  'prompts',
  'optimization.md',
);

// ---------------------------------------------------------------------------
// Extension factory
// ---------------------------------------------------------------------------

const extension: ExtensionFactory = (pi) => {

  // ── Flag registration ─────────────────────────────────────────────────────

  pi.registerFlag('bench-path', {
    type: 'string',
    description: 'Path to the per-function benchmark directory (required)',
  });
  pi.registerFlag('target-function', {
    type: 'string',
    description: 'Name of the C/C++ function to optimize (required)',
  });
  pi.registerFlag('ablation-level', {
    type: 'string',
    default: '5',
    description: 'Diagnostic ablation level 0-5 (0=type only, 5=full remark)',
  });
  pi.registerFlag('make-command', {
    type: 'string',
    default: 'make',
    description: 'Shell command used to compile the benchmark',
  });
  pi.registerFlag('validator', {
    type: 'string',
    description: 'Shell command for the semantic validator (see validator contract in PLAN.md)',
  });
  pi.registerFlag('max-turns', {
    type: 'string',
    default: '5',
    description: 'Maximum number of agent turns before declaring failure',
  });
  pi.registerFlag('compiler', {
    type: 'string',
    default: 'clang',
    description: 'Compiler family: clang (default) or intel',
  });

  // ── Local LLM provider registration ──────────────────────────────────────

  const llmUrl = process.env['LOCAL_LLM_URL'] ?? 'http://localhost:8000/v1';
  const llmKey = process.env['LOCAL_LLM_API_KEY'] ?? 'local';

  pi.registerProvider('local-llm', {
    baseUrl: llmUrl,
    apiKey: llmKey,
    api: 'openai-completions',
    authHeader: true,
    models: [
      {
        id: 'Qwen/Qwen2.5-Coder-14B-Instruct',
        name: 'Qwen2.5-Coder 14B',
        reasoning: false,
        input: ['text'],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 32768,
        maxTokens: 4096,
        compat: {
          supportsStore: false,
          supportsReasoningEffort: false,
          supportsStrictMode: false,
        },
      },
      {
        id: 'Qwen/Qwen3-9B',
        name: 'Qwen3 9B',
        reasoning: false,
        input: ['text'],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 32768,
        maxTokens: 4096,
        compat: {
          supportsStore: false,
          supportsReasoningEffort: false,
          supportsStrictMode: false,
        },
      },
    ],
  });

  // ── session_start: populate shared state from flags ───────────────────────

  pi.on('session_start', (_event, _ctx) => {
    state.benchPath    = (pi.getFlag('bench-path') as string | undefined) ?? '';
    state.targetFunction = (pi.getFlag('target-function') as string | undefined) ?? '';
    state.ablationLevel  = parseInt((pi.getFlag('ablation-level') as string | undefined) ?? '5', 10);
    state.makeCommand    = (pi.getFlag('make-command') as string | undefined) ?? 'make';
    state.validatorPath  = (pi.getFlag('validator') as string | undefined) ?? '';
    state.maxTurns       = parseInt((pi.getFlag('max-turns') as string | undefined) ?? '5', 10);
    state.isClang        = (pi.getFlag('compiler') as string | undefined) !== 'intel';

    if (!state.benchPath || !state.targetFunction) {
      console.error('[canary] ERROR: --bench-path and --target-function are required');
      return;
    }

    const src = findSourceFile(state.benchPath);
    if (!src) {
      console.error(`[canary] ERROR: no C/C++ source file found in ${state.benchPath}`);
      return;
    }
    state.sourceFile = src;
  });

  // ── before_agent_start: build/update system prompt each loop ─────────────

  pi.on('before_agent_start', async (_event, _ctx) => {
    if (!state.benchPath || !state.sourceFile) return;

    // On the very first start: run an initial compilation to produce baseline remarks.
    if (!state.initialized) {
      cleanRemarkFiles(state.benchPath);
      await runMake(state.benchPath, state.makeCommand);
      state.initialized = true;
    }

    const source = fs.readFileSync(state.sourceFile, 'utf-8');
    const funcInfo = extractFunction(source, state.targetFunction);
    if (!funcInfo) {
      console.error(`[canary] ERROR: function '${state.targetFunction}' not found in ${state.sourceFile}`);
      return;
    }

    // Record initial slice size on first pass
    if (state.initialSliceLines === 0) {
      state.initialSliceLines = funcInfo.fullText.split('\n').length;
    }

    // Read and ablate current remarks
    const remarkFiles = findRemarkFiles(state.benchPath, state.sourceFile);
    const rawRemarks = parseRemarksForFunction(remarkFiles, state.targetFunction);
    const ablated = ablateRemarks(rawRemarks, state.ablationLevel);

    // Build context strings
    const fileContext = extractFileContext(source);
    const numberedFunc = numberLines(funcInfo.fullText, funcInfo.startLine);

    // Load prompt template (graceful fallback if file missing)
    let template = '';
    try {
      template = fs.readFileSync(PROMPT_PATH, 'utf-8');
    } catch {
      template = 'You are a performance engineer optimizing C/C++ code for vectorization.';
    }

    const systemPrompt = [
      template,
      '',
      `## Function to Optimize`,
      ``,
      `Function \`${funcInfo.name}\` starts at line ${funcInfo.startLine}:`,
      '```c',
      numberedFunc,
      '```',
      '',
      `## Program Context`,
      '```c',
      fileContext,
      '```',
      '',
      `## Compiler Diagnostic (ablation level ${state.ablationLevel})`,
      '',
      ablated || '*(no optimization remarks available for this function)*',
    ].join('\n');

    return { systemPrompt };
  });

  // ── agent_end: apply transform → compile → validate → steer/terminate ────

  pi.on('agent_end', async (event, _ctx) => {
    if (state.terminated || !state.benchPath || !state.sourceFile) return;

    // ── Extract assistant text ──────────────────────────────────────────────
    const messages = event.messages;
    const lastAssistant = [...messages].reverse().find(m => m.role === 'assistant');
    if (!lastAssistant) return;

    // AgentMessage is a union that includes custom message types without .content.
    // We checked role === 'assistant', so cast to access the typed content array.
    const assistantContent = (lastAssistant as unknown as { content: Array<{ type: string; text?: string }> }).content ?? [];
    const text = assistantContent
      .filter(c => c.type === 'text')
      .map(c => c.text ?? '')
      .join('\n');

    // ── Oscillation check ───────────────────────────────────────────────────
    if (state.previousOutputs.includes(text)) {
      state.terminated = true;
      state.failureMode = 'oscillation';
      return;
    }
    state.previousOutputs.push(text);

    // ── Parse SEARCH/REPLACE ────────────────────────────────────────────────
    const blocks = parseSearchReplace(text);
    if (blocks.length === 0) {
      sendFeedback(pi,
        'No search-replace block found. Output exactly one block:\n\n' +
        '<<<<<<< SEARCH\nexact code to find\n=======\nreplacement code\n>>>>>>> REPLACE',
      );
      return;
    }

    // ── Apply transformation ────────────────────────────────────────────────
    const source = fs.readFileSync(state.sourceFile, 'utf-8');
    const modified = applySearchReplace(source, blocks[0]);
    if (modified === null) {
      sendFeedback(pi,
        `SEARCH block not found in source. It must exactly match existing code.\n\n` +
        `Search text was:\n\`\`\`\n${blocks[0].search}\n\`\`\``,
      );
      return;
    }
    fs.writeFileSync(state.sourceFile, modified, 'utf-8');

    // ── Compile ─────────────────────────────────────────────────────────────
    cleanRemarkFiles(state.benchPath);
    const compileResult = await runMake(state.benchPath, state.makeCommand);

    const currentSource = fs.readFileSync(state.sourceFile, 'utf-8');
    const funcInfo = extractFunction(currentSource, state.targetFunction);

    if (!compileResult.success) {
      state.consecutiveCompileFailures++;
      if (state.consecutiveCompileFailures >= 3) {
        state.terminated = true;
        state.failureMode = 'persistent_syntax_error';
        return;
      }

      const errors = funcInfo
        ? extractCompileErrors(compileResult.stderr, state.sourceFile, funcInfo.startLine, funcInfo.endLine)
        : compileResult.stderr.slice(0, 2000);

      const feedback = `Compilation failed (attempt ${state.consecutiveCompileFailures}/3).\n\n` +
        `Fix the syntax errors and output a new search-replace block:\n\n\`\`\`\n${errors}\n\`\`\``;
      state.lastCompilerFeedback = feedback;
      sendFeedback(pi, feedback);
      return;
    }

    state.consecutiveCompileFailures = 0;

    // ── Check vectorization ─────────────────────────────────────────────────
    const remarkFiles = findRemarkFiles(state.benchPath, state.sourceFile);
    const rawRemarks = parseRemarksForFunction(remarkFiles, state.targetFunction);
    const vectorized = checkVectorizationSuccess(rawRemarks, state.isClang);

    // ── Run validator ───────────────────────────────────────────────────────
    let semanticPass = true;
    let validatorError = '';
    if (state.validatorPath) {
      const vr = await runValidator(
        state.validatorPath,
        state.benchPath,
        state.targetFunction,
        state.makeCommand,
        state.sourceFile,
      );
      semanticPass = vr.pass;
      validatorError = vr.errorMessage;
    }

    // ── Success ─────────────────────────────────────────────────────────────
    if (vectorized && semanticPass) {
      state.success = true;
      state.terminated = true;
      return; // let the agent loop end naturally
    }

    // ── Build feedback for next turn ────────────────────────────────────────
    const ablated = ablateRemarks(rawRemarks, state.ablationLevel);
    const parts: string[] = [];

    if (vectorized) {
      parts.push('The loop was vectorized, but semantic equivalence check failed.');
      parts.push('The transformation must preserve the exact behavior of the original function.');
    } else {
      parts.push('The loop was not vectorized after your change.');
      if (ablated) {
        parts.push('\nUpdated compiler optimization remarks:\n' + ablated);
      }
    }

    if (!semanticPass && validatorError) {
      parts.push(`\nValidator: ${validatorError}`);
    }

    parts.push('\nPlease revise your approach and output a new search-replace block.');

    const feedback = parts.join('\n');
    state.lastCompilerFeedback = feedback;
    sendFeedback(pi, feedback);
  });

};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Inject a user message that restarts the agent loop with compiler feedback. */
function sendFeedback(pi: Parameters<ExtensionFactory>[0], text: string): void {
  pi.sendUserMessage(text, { deliverAs: 'followUp' });
}

export default extension;
