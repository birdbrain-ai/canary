import re
from vectorization_state import *
import json

# Node: Suggest modifications (per-function)
def suggest_modifications(state: VectorizationState):
    """Ask LLM to suggest modifications (pragmas or function diffs) as structured JSON actions"""

    current_file = state['current_file']
    current_func = state['current_function']
    func_name = current_func['name']
    func_body = current_func['full_text']
    iteration = state['current_iteration']

    # TODO(Akash): Polish this part
    # Get current iteration's loop analysis from analyze_loops
    function_analysis_history = state.get('function_analysis_history', {})
    current_analyses = function_analysis_history.get(current_file, {}).get(func_name, [])
    current_loop_analysis = current_analyses[-1] if current_analyses else ""

    # Annotate lines with numbers for LLM reference
    func_lines = func_body.splitlines()
    annotated_code = '\n'.join([
        f"{i:4d} | {line}" 
        for i, line in enumerate(func_lines)
    ])

    # TODO(Akash): Move 'compiler feedback' to the analysis stage
#     compiler_feedback_section = ""
#     if iteration > 0:
#         file_compilation_feedback = state.get('file_compilation_feedback', {})
#         feedback = file_compilation_feedback.get(current_file, "")
#         if feedback:
#             compiler_feedback_section = f"""
# COMPILER FEEDBACK (from previous iteration):
# {feedback}
# Please address these compilation issues in your modifications.
# """
    
    # Build loop analysis section
    loop_analysis_section = ""
    if current_loop_analysis:
        loop_analysis_section = f"""
LOOP ANALYSIS (from analyze_loops):
{current_loop_analysis}
"""

    # Build iteration guidance
    iteration_guidance = ""
    if iteration == 0:
        iteration_guidance = """
GUIDANCE:
This is the first iteration. You have two options:

1. PRAGMA ACTIONS: For simple cases, suggest `vectorize` pragmas for FOR LOOPS that:
   - Have simple, predictable iteration patterns
   - Perform array/vector operations
   - Don't have complex control flow or dependencies

2. CODE REPLACE: For targeted code changes:
   - Add variable declarations (e.g., create local temporaries)
   - Hoist loop-invariant computations
   - Replace specific lines to fix vectorization blockers
   - Make multiple independent changes in one pass
   - Avoid making changes that alter the meaning of the function
"""
    else:
        iteration_guidance = f"""
GUIDANCE:
This is iteration {iteration}. Based on optimization remarks, you have two options:

1. PRAGMA ACTIONS: Suggest pragmas for FOR LOOPS where vectorization still failed
   - You may suggest: "vectorize", "interleave", or "vectorize_width"
   - Be conservative - only suggest if you're confident it will help

2. CODE REPLACE: Make targeted code changes:
   - Fix specific issues identified in optimization remarks
   - Add temporaries, hoist computations, break dependencies
   - Avoid making changes that alter the meaning of the function
"""

    prompt = f"""Analyze this C++ function for vectorization opportunities.

FUNCTION WITH LINE NUMBERS:
{annotated_code}

{loop_analysis_section}

{iteration_guidance}

TASK:
Analyze this function and suggest modifications to enable vectorization.

OPTION 1 - PRAGMA ACTIONS (for simple vectorization hints):
For each loop that needs a pragma, create a JSON object:
{{
  "action_type": "pragma",
  "line_number": <line number of the 'for' statement>,
  "pragma_type": "vectorize" OR "interleave" OR "vectorize_width",
  "width": <number (only if pragma_type is vectorize_width), otherwise null>,
  "reasoning": "<brief explanation>"
}}

OPTION 2 - CODE REPLACE (for targeted code changes):
For each code change, create a JSON object:
{{
  "action_type": "code_replace",
  "start_line": <start line number (0-indexed)>,
  "end_line": <end line number (0-indexed, inclusive)>,
  "new_code": "<replacement code (can be multi-line)>",
  "reasoning": "<brief explanation>"
}}

Examples:
- Add variable: {{"action_type": "code_replace", "start_line": 0, "end_line": 0, "new_code": "int temp = 0;", "reasoning": "Add local temporary"}}
- Replace line: {{"action_type": "code_replace", "start_line": 5, "end_line": 5, "new_code": "result[i] = a[i] * factor;", "reasoning": "Use hoisted variable"}}
- Multi-line: {{"action_type": "code_replace", "start_line": 3, "end_line": 5, "new_code": "for (int i = 0; i < n; i++) {{\n    output[i] = input[i];\n}}", "reasoning": "Simplify loop"}}

CRITICAL OUTPUT RULES:
- Output a JSON ARRAY: [{{...}}] or [{{...}}, {{...}}] for multiple actions
- You can mix pragma and code_replace actions in the same array
- If NO modifications needed, output an empty array: []
- DO NOT include any explanatory text, markdown, or code fences
- Output ONLY the JSON array, nothing else

OUTPUT (valid JSON array only):"""

    raw_response = llm.invoke(prompt)
    
    # Handle ChatModel response (AIMessage) vs LLM response (str)
    if hasattr(raw_response, 'content'):
        response = raw_response.content
    else:
        response = str(raw_response)

    # Log LLM interaction
    llm_logger = state.get('llm_logger')
    if llm_logger:
        llm_logger.log_llm_call(
            iteration=iteration,
            file_path=current_file,
            call_type="suggest_modifications",
            prompt=prompt,
            response=response,
            function_name=func_name
        )

    # Parse JSON response (supports array format or fallback to JSONL)
    actions = []

    try:
        print(response)

        # Handle empty response
        if not response or not response.strip():
            actions = None
        else:
            # Clean up response (handle markdown blocks, extra text)
            cleaned_response = extract_json_from_response(response)
            
            # Try to parse as a single JSON object first (if wrapped in array)
            try:
                parsed = json.loads(cleaned_response)
                # If it's already a list, use it directly
                if isinstance(parsed, list):
                    actions = parsed
                # If it's a single object, wrap it in a list
                elif isinstance(parsed, dict):
                    actions = [parsed]
                else:
                    actions = None
            except json.JSONDecodeError:
                # Parse as JSONL (one JSON object per line)
                # Use cleaned response for JSONL parsing too
                for line in cleaned_response.split('\n'):
                    line = line.strip()
                    # Skip empty lines and lines that don't look like JSON
                    if not line or not (line.startswith('{') or line.startswith('[')):
                        continue
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            actions.append(obj)
                        elif isinstance(obj, list):
                            actions.extend(obj)
                    except json.JSONDecodeError as line_err:
                        print(f"⚠ Failed to parse line: {line}")
                        print(f"  Error: {line_err}")
                        continue

                # If no valid objects were parsed, set to None
                if not actions:
                    actions = None

        if actions:
            print(f"  Parsed {len(actions)} action(s): {actions}")
    except Exception as e:
        print(f"⚠ Failed to parse LLM output: {response}")
        print(f"  Error: {e}")
        actions = None

    if not actions:
        print(f"✓ No modification actions suggested for function '{func_name}'")
    else:
        print(f"✓ LLM suggested {len(actions)} modification action(s) for function '{func_name}'")

    return {
        "modification_actions": actions
    }


# Node: Apply modifications
def apply_modifications(state: VectorizationState):
    """Apply all suggested modification actions (pragmas and code_replace) to the function"""
    
    func_body = state['current_function']['full_text']
    func_name = state['current_function']['name']
    actions = state.get('modification_actions', [])
    
    if not actions:
        print(f"✓ No modifications to apply for function '{func_name}'")
        return {"transformed_function": func_body}
    
    # Separate pragma and code_replace actions
    pragma_actions = [a for a in actions if a.get('action_type', 'pragma') == 'pragma']
    code_replace_actions = [a for a in actions if a.get('action_type') == 'code_replace']
    
    modified = func_body
    
    # Apply code_replace actions first (in reverse order to preserve line numbers)
    if code_replace_actions:
        print(f"\n=== Applying {len(code_replace_actions)} Code Replacement(s) ===")
        actions_sorted = sorted(code_replace_actions, key=lambda a: a.get('start_line', 0), reverse=True)
        
        for action in actions_sorted:
            new_modified = apply_code_replace(modified, action)
            modified = new_modified
    
    # Then apply pragma actions (in reverse order to preserve line numbers)
    if pragma_actions:
        print(f"\n=== Applying {len(pragma_actions)} Pragma Action(s) ===")
        actions_sorted = sorted(pragma_actions, key=lambda a: a.get('line_number', 0), reverse=True)
        
        applied_count = 0
        for action in actions_sorted:
            print(f"  Attempting: {action.get('pragma_type', 'unknown')} at line {action.get('line_number', '?')}")
            new_modified = apply_pragma(modified, action)
            if new_modified != modified:
                applied_count += 1
            modified = new_modified
        
        print(f"✓ Applied {applied_count}/{len(pragma_actions)} pragma(s)")
    
    if code_replace_actions or pragma_actions:
        print(f"✓ Applied modifications to function '{func_name}'")
    
    return {"transformed_function": modified}


def apply_pragma(file_content: str, action: PragmaAction) -> str:
    """Apply a single pragma insertion to file content"""
    lines = file_content.splitlines()
    
    # Validate line number
    if action['line_number'] < 0 or action['line_number'] >= len(lines):
        print(f"⚠ Invalid line number {action['line_number']}")
        return file_content
    
    # Check if line is actually a for loop
    target_line = lines[action['line_number']].strip()
    if not target_line.startswith('for'):
        print(f"⚠ Line {action['line_number']} is not a for loop: {target_line[:50]}")
        return file_content
    
    # Build pragma string
    if action['pragma_type'] == 'vectorize':
        pragma = "#pragma clang loop vectorize(enable)"
    elif action['pragma_type'] == 'interleave':
        pragma = "#pragma clang loop interleave(enable)"
    elif action['pragma_type'] == 'vectorize_width':
        width = action.get('width', 4)
        pragma = f"#pragma clang loop vectorize_width({width})"
    else:
        print(f"⚠ Unknown pragma type: {action['pragma_type']}")
        return file_content
    
    # Insert pragma before the loop (preserve indentation)
    indent = len(lines[action['line_number']]) - len(lines[action['line_number']].lstrip())
    pragma_line = ' ' * indent + pragma
    
    lines.insert(action['line_number'], pragma_line)
    
    print(f"  ✓ Added {pragma} at line {action['line_number']}")
    
    return '\n'.join(lines)

def apply_code_replace(file_content: str, action: CodeReplaceAction) -> str:
    """
    Apply a code replacement action to function content.
    
    Replaces lines [start_line, end_line] with new_code, preserving indentation.
    
    Args:
        file_content: Function content as string
        action: CodeReplaceAction with line range and new code
        
    Returns:
        Modified function content
    """
    lines = file_content.splitlines()
    
    # Validate line numbers
    start = action.get('start_line', -1)
    end = action.get('end_line', -1)
    
    if start < 0 or end >= len(lines):
        print(f"⚠ Invalid line range [{start}, {end}] (function has {len(lines)} lines)")
        return file_content
    
    if start > end:
        print(f"⚠ Start line ({start}) must be <= end line ({end})")
        return file_content
    
    # Get indentation from first line being replaced
    if lines[start].strip():  # If line is not empty
        indent = len(lines[start]) - len(lines[start].lstrip())
    else:
        indent = 0
    
    # Split new code and apply indentation
    new_code = action.get('new_code', '').rstrip()
    if not new_code:
        print(f"⚠ Empty replacement code provided")
        return file_content
    
    new_lines = new_code.splitlines()
    
    # Apply indentation to each new line (preserve relative indentation)
    indented_new_lines = []
    for line in new_lines:
        if line.strip():  # Non-empty line
            # Preserve the line's own indentation relative to base
            indented_new_lines.append(' ' * indent + line.lstrip())
        else:  # Empty line
            indented_new_lines.append('')
    
    # Replace lines
    lines[start:end+1] = indented_new_lines
    
    reasoning = action.get('reasoning', 'No reason provided')
    print(f"  ✓ Replaced lines {start}-{end}: {reasoning[:60]}")
    
    return '\n'.join(lines)

def extract_json_from_response(response: str) -> str:
    """
    Extract JSON content from LLM response, handling markdown code blocks.
    
    Args:
        response: Raw LLM response string
        
    Returns:
        Extracted JSON string
    """
    response = response.strip()
    
    # 1. Try to find markdown code blocks
    json_block_pattern = re.compile(r'```(?:json)?\s*([\s\S]*?)\s*```')
    match = json_block_pattern.search(response)
    if match:
        return match.group(1).strip()
        
    # 2. If no code blocks, try to find the first '[' and last ']'
    # (Since we expect a JSON array)
    start_idx = response.find('[')
    end_idx = response.rfind(']')
    
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        return response[start_idx:end_idx+1]
        
    # 3. Return original response as fallback
    return response
