/**
 * compiler-tools extension — context expansion tools for the canary agent.
 *
 * These four tools let the agent request compiler-derived context slices on demand.
 * All implementations are currently stubbed. The tool structure, parameter schema,
 * and return interface are final; only the backend retrieval logic is missing.
 *
 * Backend contract (to be implemented):
 *   Each tool calls external infrastructure that returns a bounded, semantically
 *   meaningful code slice. The backend can be a script, HTTP API, or pre-computed
 *   file — wiring it up requires no changes to this file, only to the execute()
 *   bodies below.
 */

import type { ExtensionFactory } from '@mariozechner/pi-coding-agent';
import { defineTool } from '@mariozechner/pi-coding-agent';
import { Type } from '@sinclair/typebox';

const extension: ExtensionFactory = (pi) => {

  pi.registerTool(defineTool({
    name: 'expand_caller',
    label: 'Expand Caller',
    description:
      'Retrieve the calling context for a function — code that calls it, ' +
      'including call sites and surrounding logic. Useful for understanding ' +
      'how the function is invoked and what invariants callers establish.',
    parameters: Type.Object({
      function_name: Type.String({
        description: 'Name of the function whose callers to retrieve',
      }),
    }),
    async execute(_id, params, _signal, onUpdate) {
      onUpdate?.({ content: [{ type: 'text', text: `Looking up callers of ${params.function_name}...` }], details: {} });
      const text = `// [stub] calling context for '${params.function_name}'\n// Backend not yet implemented.`;
      return { content: [{ type: 'text', text }], details: {} };
    },
  }));

  pi.registerTool(defineTool({
    name: 'expand_callee',
    label: 'Expand Callee',
    description:
      'Retrieve the body of a function called by the target — useful for ' +
      'understanding what side effects callees have and whether they can be ' +
      'safely vectorized across or moved outside the loop.',
    parameters: Type.Object({
      function_name: Type.String({
        description: 'Name of the callee function to retrieve',
      }),
    }),
    async execute(_id, params, _signal, onUpdate) {
      onUpdate?.({ content: [{ type: 'text', text: `Looking up body of ${params.function_name}...` }], details: {} });
      const text = `// [stub] body of '${params.function_name}'\n// Backend not yet implemented.`;
      return { content: [{ type: 'text', text }], details: {} };
    },
  }));

  pi.registerTool(defineTool({
    name: 'expand_type',
    label: 'Expand Type',
    description:
      'Retrieve the definition of a struct, typedef, or other named type. ' +
      'Useful when a type\'s memory layout affects vectorizability ' +
      '(e.g., struct of arrays vs array of structs).',
    parameters: Type.Object({
      type_name: Type.String({
        description: 'Name of the type (struct, typedef, enum, etc.) to retrieve',
      }),
    }),
    async execute(_id, params, _signal, onUpdate) {
      onUpdate?.({ content: [{ type: 'text', text: `Looking up type '${params.type_name}'...` }], details: {} });
      const text = `// [stub] definition of '${params.type_name}'\n// Backend not yet implemented.`;
      return { content: [{ type: 'text', text }], details: {} };
    },
  }));

  pi.registerTool(defineTool({
    name: 'expand_slice',
    label: 'Expand Slice',
    description:
      'Compute a backward data-flow slice from a variable use at a source location. ' +
      'Traces which definitions reach a given variable, helping identify the source ' +
      'of potential dependencies flagged by the compiler.',
    parameters: Type.Object({
      variable: Type.String({
        description: 'Variable name to slice from',
      }),
      location: Type.String({
        description: 'Source location to slice from, in file:line format (e.g. "tsvc.c:140")',
      }),
    }),
    async execute(_id, params, _signal, onUpdate) {
      onUpdate?.({ content: [{ type: 'text', text: `Computing slice for ${params.variable} at ${params.location}...` }], details: {} });
      const text = `// [stub] backward slice from '${params.variable}' at ${params.location}\n// Backend not yet implemented.`;
      return { content: [{ type: 'text', text }], details: {} };
    },
  }));

};

export default extension;
