/**
 * Shared mutable state between canary extensions.
 * Since all extensions in the same Node.js process share module instances,
 * this singleton is safely readable by both diagnostic-context and instrumentation.
 */

export interface ToolCallLog {
  name: string;
  args: Record<string, unknown>;
  linesReturned: number;
  timestamp: number;
}

export interface TurnLog {
  turnIndex: number;
  tokensIn: number;
  tokensOut: number;
  contextSize: number;
  toolCalls: ToolCallLog[];
  compilerFeedback: string;
  timestamp: number;
}

export interface SessionState {
  // Config — populated from flags in session_start
  benchPath: string;
  targetFunction: string;
  ablationLevel: number;
  maxTurns: number;
  makeCommand: string;
  validatorPath: string;
  sourceFile: string;
  isClang: boolean;

  // Slice sizing
  initialSliceLines: number;

  // Turn tracking
  turns: TurnLog[];
  consecutiveCompileFailures: number;
  previousOutputs: string[];
  terminated: boolean;
  success: boolean;
  failureMode: string | null;

  // Per-turn scratch state (reset each turn_start)
  currentTurnContextSize: number;
  currentTurnToolCalls: ToolCallLog[];
  lastCompilerFeedback: string;

  // Initialization guard
  initialized: boolean;
}

export const state: SessionState = {
  benchPath: '',
  targetFunction: '',
  ablationLevel: 5,
  maxTurns: 5,
  makeCommand: 'make',
  validatorPath: '',
  sourceFile: '',
  isClang: true,

  initialSliceLines: 0,

  turns: [],
  consecutiveCompileFailures: 0,
  previousOutputs: [],
  terminated: false,
  success: false,
  failureMode: null,

  currentTurnContextSize: 0,
  currentTurnToolCalls: [],
  lastCompilerFeedback: '',

  initialized: false,
};
