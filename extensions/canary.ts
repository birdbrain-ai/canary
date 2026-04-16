/**
 * canary extension — instrumentation and termination for the canary agent.
 *
 * This extension does exactly three things:
 *   1. Register the local LLM provider (Qwen models via OpenAI-compatible API)
 *   2. Log per-turn metrics (tokens, tool calls, context size) to pi-agent-log.json
 *   3. Enforce termination: max-turns cutoff and oscillation detection
 *
 * Everything else — reading files, editing code, running make, checking remarks,
 * running the validator — is handled naturally by the agent using pi's native
 * read, edit, bash, and grep tools, directed by the system prompt.
 */

import type { ExtensionFactory } from '@mariozechner/pi-coding-agent';
import * as fs from 'node:fs';
import * as path from 'node:path';

// ---------------------------------------------------------------------------
// Session state (module-level singleton)
// ---------------------------------------------------------------------------

interface ToolCallLog {
  name: string;
  args: unknown;
  linesReturned: number;
  timestamp: number;
}

interface TurnLog {
  turnIndex: number;
  tokensIn: number;
  tokensOut: number;
  contextSize: number;
  toolCalls: ToolCallLog[];
  timestamp: number;
}

interface SessionState {
  benchPath: string;
  targetFunction: string;
  ablationLevel: number;
  maxTurns: number;
  initialSliceLines: number;

  turns: TurnLog[];
  previousOutputTexts: string[];
  terminatedBy: 'max_turns' | 'oscillation' | null;

  // per-turn scratch (reset on turn_start)
  currentContextSize: number;
  currentToolCalls: ToolCallLog[];
}

const s: SessionState = {
  benchPath: '',
  targetFunction: '',
  ablationLevel: 5,
  maxTurns: 5,
  initialSliceLines: 0,
  turns: [],
  previousOutputTexts: [],
  terminatedBy: null,
  currentContextSize: 0,
  currentToolCalls: [],
};

// ---------------------------------------------------------------------------
// Extension factory
// ---------------------------------------------------------------------------

const extension: ExtensionFactory = (pi) => {

  // ── Provider registration ─────────────────────────────────────────────────

  const llmUrl = process.env['LOCAL_LLM_URL'] ?? 'http://localhost:8000/v1';

  pi.registerProvider('local-llm', {
    baseUrl: llmUrl,
    apiKey: process.env['LOCAL_LLM_API_KEY'] ?? 'local',
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
        compat: { supportsStore: false, supportsReasoningEffort: false, supportsStrictMode: false },
      },
      {
        id: 'Qwen/Qwen3-9B',
        name: 'Qwen3 9B',
        reasoning: false,
        input: ['text'],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 32768,
        maxTokens: 4096,
        compat: { supportsStore: false, supportsReasoningEffort: false, supportsStrictMode: false },
      },
    ],
  });

  // ── Flag registration ─────────────────────────────────────────────────────

  pi.registerFlag('bench-path', {
    type: 'string',
    description: 'Benchmark directory path (for log output location)',
  });
  pi.registerFlag('target-function', {
    type: 'string',
    description: 'Name of the target function (for log metadata)',
  });
  pi.registerFlag('ablation-level', {
    type: 'string',
    default: '5',
    description: 'Diagnostic ablation level 0-5 (logged in session metadata)',
  });
  pi.registerFlag('max-turns', {
    type: 'string',
    default: '5',
    description: 'Maximum agent turns before forced termination',
  });
  pi.registerFlag('initial-slice-lines', {
    type: 'string',
    default: '0',
    description: 'Initial slice size in lines (computed by harness, logged here)',
  });

  // ── session_start ─────────────────────────────────────────────────────────

  pi.on('session_start', (_event, _ctx) => {
    s.benchPath         = (pi.getFlag('bench-path') as string | undefined) ?? '';
    s.targetFunction    = (pi.getFlag('target-function') as string | undefined) ?? '';
    s.ablationLevel     = parseInt((pi.getFlag('ablation-level') as string | undefined) ?? '5', 10);
    s.maxTurns          = parseInt((pi.getFlag('max-turns') as string | undefined) ?? '5', 10);
    s.initialSliceLines = parseInt((pi.getFlag('initial-slice-lines') as string | undefined) ?? '0', 10);

    // Reset mutable state in case of session reload
    s.turns = [];
    s.previousOutputTexts = [];
    s.terminatedBy = null;
    s.currentContextSize = 0;
    s.currentToolCalls = [];
  });

  // ── turn_start ────────────────────────────────────────────────────────────

  pi.on('turn_start', (_event, ctx) => {
    s.currentContextSize = ctx.getContextUsage()?.tokens ?? 0;
    s.currentToolCalls = [];
  });

  // ── turn_end ──────────────────────────────────────────────────────────────

  pi.on('turn_end', (event, ctx) => {
    // Collect token usage
    let tokensIn = 0;
    let tokensOut = 0;
    const msg = event.message;
    if (msg.role === 'assistant') {
      const usage = (msg as { usage?: { input?: number; output?: number } }).usage;
      tokensIn  = usage?.input  ?? 0;
      tokensOut = usage?.output ?? 0;
    }

    s.turns.push({
      turnIndex: event.turnIndex,
      tokensIn,
      tokensOut,
      contextSize: s.currentContextSize,
      toolCalls: [...s.currentToolCalls],
      timestamp: Date.now(),
    });

    // Oscillation detection — extract text content from assistant message
    if (msg.role === 'assistant') {
      const content = (msg as { content?: Array<{ type: string; text?: string }> }).content ?? [];
      const text = content.filter(c => c.type === 'text').map(c => c.text ?? '').join('\n');
      if (text && s.previousOutputTexts.includes(text)) {
        s.terminatedBy = 'oscillation';
        ctx.abort();
        return;
      }
      if (text) s.previousOutputTexts.push(text);
    }

    // Max-turns enforcement
    if (s.turns.length >= s.maxTurns && s.terminatedBy === null) {
      s.terminatedBy = 'max_turns';
      ctx.abort();
    }
  });

  // ── tool_execution_start / _end ───────────────────────────────────────────

  pi.on('tool_execution_start', (event, _ctx) => {
    pendingTool = { name: event.toolName, args: event.args, startTime: Date.now() };
  });

  pi.on('tool_execution_end', (event, _ctx) => {
    let linesReturned = 0;
    const result = event.result as { content?: Array<{ type: string; text?: string }> } | undefined;
    if (result?.content) {
      for (const c of result.content) {
        if (c.type === 'text' && c.text) linesReturned += c.text.split('\n').length;
      }
    }
    s.currentToolCalls.push({
      name: pendingTool?.name ?? event.toolName,
      args: pendingTool?.args,
      linesReturned,
      timestamp: pendingTool?.startTime ?? Date.now(),
    });
    pendingTool = null;
  });

  // ── agent_end ─────────────────────────────────────────────────────────────

  pi.on('agent_end', (_event, ctx) => {
    writeLog(ctx.model?.id ?? 'unknown');
  });

  // ── session_shutdown ──────────────────────────────────────────────────────

  pi.on('session_shutdown', (_event, ctx) => {
    if (s.benchPath && s.turns.length > 0) writeLog(ctx.model?.id ?? 'unknown');
  });

};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface PendingTool { name: string; args: unknown; startTime: number }
let pendingTool: PendingTool | null = null;

function writeLog(modelId: string): void {
  if (!s.benchPath) return;

  const totalLines = s.initialSliceLines +
    s.turns.reduce((sum, t) => sum + t.toolCalls.reduce((a, tc) => a + tc.linesReturned, 0), 0);
  const expansionRate = s.turns.reduce((sum, t) => sum + t.toolCalls.length, 0);
  const passCount = s.turns.length;
  const cost = s.initialSliceLines > 0 ? totalLines / s.initialSliceLines : 0;

  const log = {
    session: {
      model: modelId,
      ablation_level: s.ablationLevel,
      initial_slice_lines: s.initialSliceLines,
      terminated_by: s.terminatedBy,
    },
    turns: s.turns.map(t => ({
      turn_index: t.turnIndex,
      tokens_in: t.tokensIn,
      tokens_out: t.tokensOut,
      context_size: t.contextSize,
      tool_calls: t.toolCalls.map(tc => ({ name: tc.name, args: tc.args, lines_returned: tc.linesReturned })),
      timestamp: t.timestamp,
    })),
    derived: {
      total_context_inspected: totalLines,
      expansion_rate: expansionRate,
      pass_count: passCount,
      context_expansion_cost: cost,
    },
  };

  try {
    fs.writeFileSync(path.join(s.benchPath, 'pi-agent-log.json'), JSON.stringify(log, null, 2));
  } catch (err) {
    console.error('[canary] failed to write pi-agent-log.json:', err);
  }
}

export default extension;
