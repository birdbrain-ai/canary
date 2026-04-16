# CANARY Agent — Pi Extension Context

## Project Goal
Build a research instrumented coding agent using pi's SDK/extension system to evaluate compiler diagnostic quality in AI-assisted performance engineering. This is a separate repo that declares pi as an npm dependency — do not fork pi.

## Repo Structure
```
canary-agent/
  extensions/
    instrumentation.ts    # token/pass/context logging
    compiler-tools.ts     # context expansion tools
    diagnostic-context.ts # initial slice construction
  prompts/
    optimization.md       # task prompt templates
  experiments/
    run_ablation.sh
    corpus/
  README.md
```

## The Agent Loop
The agent's task is: given a C/C++ program, a missed optimization, and a compiler diagnostic at a specific ablation level, produce a source transformation that enables the optimization.

```
program + diagnostic (ablated) → agent → transformed program → compiler → validate
```

This is a controlled single-task loop, not open-ended agentic navigation. The agent is not browsing a codebase autonomously — it starts from a principled, compiler-derived initial context.

## Initial Context: Diagnostic-Guided Program Slicing
Before the agent runs, a program slice is constructed from the compiler diagnostic's source locations. This slice is the agent's starting context, not the full file or project.

The slice is constructed externally (in LLVM/Python infrastructure, not in pi) and passed into the agent as initial context. Pi extensions do not implement the slicing — they consume the pre-computed slice.

Slice construction priority order (for fixed context window):
1. The diagnostic (always)
2. The target function (always)
3. Type definitions referenced by target
4. Direct callees
5. Callers

## Context Expansion Tools
The agent has access to structured expansion tools that retrieve compiler-derived context slices on demand. These are pi extensions implemented as TypeScript tool definitions.

Tools to implement:
- `expand_caller(function_name)` — retrieves calling context
- `expand_callee(function_name)` — retrieves called function body
- `expand_type(type_name)` — retrieves struct/type definition
- `expand_slice(variable, location)` — backward slice from a variable use

Each tool returns a bounded, semantically meaningful slice — not raw file contents. Every tool call must be intercepted and logged by the instrumentation extension.

## Instrumentation Requirements
Every experiment run must log the following per turn and per session:

**Per session:**
- Model used
- Diagnostic ablation level (0-N)
- Initial slice size (lines)
- Oracle slice size (lines, computed from ground truth)
- Success/failure
- Failure mode classification (syntactic / semantic / behavioral hallucination, fixation, oscillation, diagnostic-agnostic)

**Per turn:**
- Token count (input and output separately)
- Tool calls made (name, arguments, lines returned)
- Total context size at turn start
- Compiler feedback received

**Derived metrics (computed post-hoc):**
- Total context inspected = initial slice + sum of expansion lines
- Expansion rate = number of tool calls beyond turn 0
- Pass count = number of turns to success or termination
- Context expansion cost = total context inspected / initial slice size

## Ablation Ladder
The diagnostic is ablated by stripping fields from the compiler's JSON output (`--error-format=json` for rustc, `-fsave-optimization-record` for LLVM). The ablation level is set externally before the agent runs — pi extensions do not manage ablation.

LLVM remark ablation levels (ascending information):
- Level 0: remark type only
- Level 1: + message string
- Level 2: + source location
- Level 3: + missed optimization name
- Level 4: + analysis details
- Level 5: full remark (current state of the art)

## Temperature Sweep
Experiments are run at T = {0.2, 0.8, 1.2} per ablation level. Temperature is set at the model call level. The instrumentation extension must log the temperature used per session. The purpose is to classify each diagnostic type as descriptive, prescriptive, both, or neither based on how success rate varies with temperature.

## Models
- Qwen2.5-Coder 14B (via Ollama)
- Qwen3.5 9B (via Ollama)

Both run locally. Pi's Ollama provider support handles this natively. Model is a configurable parameter per experiment run, not hardcoded.

## Validation
Validation is external to pi — the instrumentation extension triggers a validation script after each agent turn that:
1. Compiles the transformed program
2. Checks optimization records for target optimization firing
3. Runs differential testing for semantic equivalence

The validation result (pass/fail + failure type) is logged and returned to the agent as the next turn's feedback if the loop continues.

## Termination Conditions
The agent loop terminates when:
- The optimization fires and semantic equivalence is confirmed (success)
- Maximum turns reached (configurable, default 5)
- Syntactic error persists after 3 attempts to fix
- Agent produces identical output to previous turn (oscillation detected)

## Key Constraints
- Corpus is stratified to single-function and bounded interprocedural transformations only — no global memory layout changes
- Each corpus program produces exactly one compiler diagnostic at baseline (multi-error programs are excluded)
- The agent sees only the ablated diagnostic and the current slice — no implicit codebase knowledge beyond what tools return
- All tool calls return deterministic, compiler-derived content — no fuzzy retrieval

## What Pi Extensions Own
- Instrumentation and logging
- Tool definitions for context expansion
- Prompt template loading
- Turn management and termination logic
- Validation script invocation

## What Pi Extensions Do Not Own
- Program slicing (external LLVM infrastructure)
- Diagnostic ablation (external preprocessing)
- Corpus management
- Model selection (configured per run)
- Validation logic (external scripts)
