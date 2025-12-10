from vectorization_state import *
from typing import TypedDict, List, Dict
import re
from helpers import *

# Node: Analyze loops (per-function)
def analyze_loops(state: VectorizationState):
    """Analyze function and matching remark files for current function"""

    current_file = state['current_file']
    current_func = state['current_function']
    func_name = current_func['name']
    func_body = current_func['full_text']
    iteration = state['current_iteration']
    remark_files_baseline = state['remark_files_baseline']
    remark_files_current = state.get('remark_files_current')
    program_slice_for_file = state.get('program_slice_for_file')
    function_analysis_history = state['function_analysis_history']

    # Match remark files for this specific file
    matching_baseline = match_remark_files(current_file, remark_files_baseline)
    matching_current = match_remark_files(current_file, remark_files_current)
    all_matching = matching_baseline + matching_current

    # Build remark analysis section - filter by function name using yq
    remark_analysis = ""
    if all_matching:
        remark_analysis = f"\n\nOPTIMIZATION REMARKS FOR THIS FUNCTION:\n"

        # Filter remarks by function name using yq (robust YAML parsing)
        for remark_file in all_matching:
            # Use yq-based filtering to get complete YAML documents for this function
            filtered_content = filter_remarks_by_function(remark_file, func_name)

            if filtered_content and filtered_content.strip():
                remark_analysis += f"\n--- From {os.path.basename(remark_file)} ---\n"
                remark_analysis += "```yaml\n" + filtered_content + "```\n"

    if not remark_analysis or remark_analysis == "\n\nOPTIMIZATION REMARKS FOR THIS FUNCTION:\n":
        remark_analysis = "\n\nNo optimization remarks available for this function yet."

    # Use relative path for lookup to match keys from compile_baseline/iteration_benchmark
    # current_file is in the current iteration directory
    rel_path = os.path.relpath(current_file, state['current_iteration_dir'])
    compiler_feedback = state["file_compilation_feedback"].get(rel_path, "No compilation errors.")

    # Get prior analysis history
    function_analysis_history = state["function_analysis_history"]
    function_analysis_history_for_func = []
    if rel_path in function_analysis_history:
        function_analysis_history_for_file = function_analysis_history[rel_path]
        print(func_name)
        print(function_analysis_history_for_file.keys())
        if func_name in function_analysis_history_for_file:
            function_analysis_history_for_func = function_analysis_history_for_file[func_name]

    function_analysis_history_str = ""

    for analysis_str in function_analysis_history_for_func:
        function_analysis_history_str += analysis_str
        function_analysis_history_str += "\n\n"
        function_analysis_history_str += "-"*20

    if function_analysis_history_str == "":
        function_analysis_history_str = "There is no prior analysis history for this function"
    else:
        summarize_analysis_prompt = f"Summarize this. Note that each dashed line separates out 'iterations' or attempts at vectorizing the function. {function_analysis_history_str}  "
        raw_function_analysis_history_str = llm.invoke(summarize_analysis_prompt)
        if hasattr(raw_function_analysis_history_str, 'content'):
            function_analysis_history_str = raw_function_analysis_history_str.content
        else:
            function_analysis_history_str = str(raw_function_analysis_history_str)

        llm_logger = state.get('llm_logger')
        if llm_logger:
            llm_logger.log_llm_call(
                iteration=iteration,
                file_path=current_file,
                call_type="summarize_function_analysis_history",
                prompt=summarize_analysis_prompt,
                response=function_analysis_history_str,
                function_name=func_name
            )

    print("I am trying to get the previous attempt details, so I can feed it into my LLM, so it can effectively analyze my loop. This is just a debug log basically: I'm inspecting the contents of modification_actions in VectorizationState.")

    modification_actions = state["modification_actions"]
    
    print(modification_actions)

    previous_attempt_details = "this is useless for now."
            
    # TODO(Akash): Get function-specific history summary from the function_analysis_history_field in VectorizationState
    iteration_context = f"""
ITERATION CONTEXT:
This is iteration {iteration} of {state['max_iterations']} for function '{func_name}'. Here is analysis from previous iterations.
"""

    prompt = f"""You are analyzing a C++ function for vectorization opportunities.

FUNCTION TO ANALYZE:
```cpp
{func_body}
```

This is what we attempted previously
{previous_attempt_details}

COMPILER FEEDBACK:
{compiler_feedback}

PROGRAM SLICE FOR FILE (structs/globals used by this function):
{program_slice_for_file}

{iteration_context}
{function_analysis_history_str}

{remark_analysis}

TASK:
Analyze the FOR LOOPS in this function to identify vectorization opportunities:
1. Loops that could benefit from vectorization but aren't vectorized yet
2. Loops that failed to vectorize (check remarks for failures)
3. Loops with vectorization issues that could be fixed with pragmas

Provide a concise analysis of which FOR LOOPS in THIS FUNCTION need pragmas and why.
"""

    raw_analysis = llm.invoke(prompt)
    if hasattr(raw_analysis, 'content'):
        analysis = raw_analysis.content
    else:
        analysis = str(raw_analysis)

    # Log LLM interaction
    llm_logger = state.get('llm_logger')
    if llm_logger:
        llm_logger.log_llm_call(
            iteration=iteration,
            file_path=current_file,
            call_type="analyze_loops",
            prompt=prompt,
            response=analysis,
            function_name=func_name
        )

    print(f"\n=== Loop Analysis ===")
    print(analysis[:500] + "..." if len(analysis) > 500 else analysis)
    print("=" * 60)

    # Store analysis in per-function history
    if rel_path not in function_analysis_history:
        function_analysis_history[rel_path] = {}
    if func_name not in function_analysis_history[rel_path]:
        function_analysis_history[rel_path][func_name] = []
    function_analysis_history[rel_path][func_name].append(analysis)

    return {
        "function_analysis_history": function_analysis_history
    }


def extract_file_context(file_content: str) -> str:
    """
    Extract relevant context from file (structs, classes, globals, typedefs, enums).
    These provide context for understanding what functions operate on.

    Args:
        file_content: Complete file content

    Returns:
        String containing extracted context declarations
    """
    lines = file_content.splitlines()
    context_lines = []

    in_multiline_comment = False

    for line in lines:
        stripped = line.strip()

        # Handle multi-line comments
        if '/*' in stripped:
            in_multiline_comment = True
        if '*/' in stripped:
            in_multiline_comment = False
            continue
        if in_multiline_comment:
            continue

        # Skip single-line comments and empty lines
        if stripped.startswith('//') or not stripped:
            continue

        # Capture context: struct, class, typedef, enum, global variables
        if any(stripped.startswith(keyword) for keyword in ['struct', 'class', 'typedef', 'enum', 'using']):
            context_lines.append(line)
        # Capture global variable declarations (simple heuristic: type name = or type name;)
        elif ';' in stripped and not stripped.startswith('for') and not stripped.startswith('if') and not stripped.startswith('while'):
            # Rough heuristic for global vars
            if ' ' in stripped and not '{' in stripped and not stripped.startswith('return'):
                context_lines.append(line)

    return '\n'.join(context_lines)

def extract_functions(file_content: str) -> List[FunctionInfo]:
    """
    Extract all function definitions from C/C++ file using regex.

    Args:
        file_content: Complete file content

    Returns:
        List of FunctionInfo objects containing metadata for each function
    """
    functions = []
    lines = file_content.splitlines()

    # Regex pattern for C/C++ function signatures
    # Matches: [static/inline/etc] return_type function_name(params) [const] [{]
    # More permissive to handle various C/C++ styles
    func_sig_pattern = re.compile(
        r'^(?:static\s+|inline\s+|extern\s+|__attribute__\(\([^)]+\)\)\s+)*'  # Optional modifiers
        r'[\w\s:<>*&,]+\s+'  # Return type (can include templates, pointers, etc.)
        r'(\w+)\s*'  # Function name (captured)
        r'\([^)]*\)'  # Parameters
        r'(?:\s*const)?'  # Optional const
        r'(?:\s*\{|\s*$)',  # Either opening brace or end of line
        re.MULTILINE
    )

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Skip empty lines, preprocessor directives, and comments
        if not line or line.startswith('#') or line.startswith('//'):
            i += 1
            continue

        # Try to match function signature
        match = func_sig_pattern.match(line)
        if match:
            func_name = match.group(1)

            # Skip common non-function keywords that might match pattern
            if func_name in ['if', 'for', 'while', 'switch', 'return', 'sizeof']:
                i += 1
                continue

            start_line = i
            signature = lines[i]

            # Look for opening brace (might be on same line or next few lines)
            brace_line_idx = i
            found_brace = False

            # Check current line first
            if '{' in lines[i]:
                found_brace = True
            else:
                # Look ahead up to 3 lines for opening brace
                for j in range(i + 1, min(i + 4, len(lines))):
                    if '{' in lines[j]:
                        brace_line_idx = j
                        found_brace = True
                        break
                    # Stop if we hit something that's not whitespace or comment
                    stripped = lines[j].strip()
                    if stripped and not stripped.startswith('//') and stripped != '{':
                        break

            if not found_brace:
                # No opening brace found, not a function definition
                i += 1
                continue

            # Count braces starting from the brace line
            brace_count = lines[brace_line_idx].count('{') - lines[brace_line_idx].count('}')
            body_lines = []
            i = brace_line_idx + 1

            while i < len(lines) and brace_count > 0:
                current_line = lines[i]
                body_lines.append(current_line)
                brace_count += current_line.count('{') - current_line.count('}')
                i += 1

            end_line = i - 1
            body = '\n'.join(body_lines[:-1]) if body_lines else ""  # Exclude closing brace line
            full_text = '\n'.join(lines[start_line:end_line+1])

            functions.append({
                'name': func_name,
                'signature': signature.strip(),
                'body': body,
                'full_text': full_text,
                'start_line': start_line,
                'end_line': end_line
            })
        else:
            i += 1

    return functions

