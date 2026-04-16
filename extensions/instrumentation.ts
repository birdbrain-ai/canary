/**
 * instrumentation extension — per-session and per-turn logging for canary.
 *
 * Logs to {bench-path}/pi-agent-log.json after each agent run.
 * Also enforces termination conditions that are not owned by diagnostic-context:
 *   - Max turns reached
 *
 * Oscillation detection (identical outputs) is handled in diagnostic-context
 * because it needs access to the parsed assistant text before compilation.
 */

import type { ExtensionFactory } from '@mariozechner/pi-coding-agent';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { state } from './shared-state.js';

const extension: ExtensionFactory = (pi) => {

  pi.on('session_start', (_event, _ctx) => {
    // State is initialized by diagnostic-context's session_start handler.
    // Nothing extra needed here.
  });

  pi.on('turn_start', (_event, ctx) => {
    // Reset per-turn scratch state
    state.currentTurnToolCalls = [];
    state.currentTurnContextSize = ctx.getContextUsage()?.tokens ?? 0;
  });

  pi.on('turn_end', (event, _ctx) => {
    // Collect token usage from the assistant message
    let tokensIn = 0;
    let tokensOut = 0;
    const msg = event.message;
    if (msg.role === 'assistant') {
      // usage is typed on AssistantMessage from @mariozechner/pi-ai
      const usage = (msg as { usage?: { input?: number; output?: number } }).usage;
      tokensIn = usage?.input ?? 0;
      tokensOut = usage?.output ?? 0;
    }

    state.turns.push({
      turnIndex: event.turnIndex,
      tokensIn,
      tokensOut,
      contextSize: state.currentTurnContextSize,
      toolCalls: [...state.currentTurnToolCalls],
      compilerFeedback: state.lastCompilerFeedback,
      timestamp: Date.now(),
    });

    // Enforce max-turns termination
    if (!state.terminated && state.turns.length >= state.maxTurns) {
      state.terminated = true;
      state.failureMode = 'max_turns_reached';
    }
  });

  pi.on('tool_execution_start', (event, _ctx) => {
    // Capture args and start timestamp so they are available when the tool ends.
    pendingToolCall = {
      name: event.toolName,
      args: (event.args ?? {}) as Record<string, unknown>,
      startTime: Date.now(),
    };
  });

  pi.on('tool_execution_end', (event, _ctx) => {
    // Count lines returned by the tool
    let linesReturned = 0;
    const result = event.result as { content?: Array<{ type: string; text?: string }> } | undefined;
    if (result?.content) {
      for (const c of result.content) {
        if (c.type === 'text' && c.text) {
          linesReturned += c.text.split('\n').length;
        }
      }
    }

    state.currentTurnToolCalls.push({
      name: event.toolName,
      args: pendingToolCall?.name === event.toolName ? pendingToolCall.args : {},
      linesReturned,
      timestamp: pendingToolCall?.startTime ?? Date.now(),
    });
    pendingToolCall = null;
  });

  pi.on('agent_end', (_event, ctx) => {
    if (!state.benchPath) return;

    writeLog(ctx.model?.id ?? 'unknown');
  });

  pi.on('session_shutdown', (_event, ctx) => {
    // Write log on graceful shutdown in case agent_end didn't fire
    if (state.benchPath && state.turns.length > 0) {
      writeLog(ctx.model?.id ?? 'unknown');
    }
  });

};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface PendingToolCall {
  name: string;
  args: Record<string, unknown>;
  startTime: number;
}

let pendingToolCall: PendingToolCall | null = null;

function writeLog(modelId: string): void {
  const totalContextInspected =
    state.initialSliceLines +
    state.turns.reduce(
      (sum, t) => sum + t.toolCalls.reduce((s, tc) => s + tc.linesReturned, 0),
      0,
    );
  const expansionRate = state.turns.reduce((sum, t) => sum + t.toolCalls.length, 0);
  const passCount = state.turns.length;
  const contextExpansionCost =
    state.initialSliceLines > 0 ? totalContextInspected / state.initialSliceLines : 0;

  const log = {
    session: {
      model: modelId,
      ablation_level: state.ablationLevel,
      initial_slice_lines: state.initialSliceLines,
      success: state.success,
      failure_mode: state.failureMode,
    },
    turns: state.turns.map(t => ({
      turn_index: t.turnIndex,
      tokens_in: t.tokensIn,
      tokens_out: t.tokensOut,
      context_size: t.contextSize,
      tool_calls: t.toolCalls.map(tc => ({
        name: tc.name,
        args: tc.args,
        lines_returned: tc.linesReturned,
      })),
      compiler_feedback: t.compilerFeedback,
      timestamp: t.timestamp,
    })),
    derived: {
      total_context_inspected: totalContextInspected,
      expansion_rate: expansionRate,
      pass_count: passCount,
      context_expansion_cost: contextExpansionCost,
    },
  };

  const logPath = path.join(state.benchPath, 'pi-agent-log.json');
  try {
    fs.writeFileSync(logPath, JSON.stringify(log, null, 2), 'utf-8');
  } catch (err) {
    console.error('[canary] Failed to write pi-agent-log.json:', err);
  }
}

export default extension;
