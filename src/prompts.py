"""
Prompt templates for the vectorization workflow.
"""

def get_reviewer_prompt(cur_function_info, make_command, program_slice,
                        compiler_feedback, optimization_remarks):
    """
    Generate the reviewer prompt for evaluating autovectorization opportunities.

    Args:
        cur_function_info: FunctionInfo dict with function details
        make_command: Compilation command string
        program_slice: Surrounding program context
        compiler_feedback: Compiler errors/warnings
        optimization_remarks: LLVM optimization remarks

    Returns:
        Formatted prompt string
    """
    return f"""You are reviewing THIS FUNCTION for opportunities to autovectorize it.

{cur_function_info["full_text"]}

        The function is compiled with Clang, using the following command: {make_command}

        You have access to some information to help.

First, the PROGRAM

{program_slice}

Second, COMPILER FEEDBACK:

{compiler_feedback}

Third, OPTIMIZATION REMARKS.

{optimization_remarks}

You MUST return a JSON object in this format:

```
{{
  "dead_end": bool
  "reviewer_feedback": str
}}
```

RULES:
- If the function was already autovectorized, you must set the dead_end field to false, and the vectorization_success field to true.
- You must set 'dead_end' to false is the function is a useful starting point for autovectorization.
- Fill out the reviewer_feedback field to include future directions to modify the function in order to autovectorize it.

EXAMPLE OUTPUTS:
{{
  "dead_end": false,
  "reviewer_feedback": "This function is already fully autovectorized. No further work is needed."
}}

{{
  "dead_end": true,
  "reviewer_feedback": ""
}}

{{
  "dead_end": true,
  "reviewer_feedback": "Optimization remarks for this function suggest that a non-reduction value in the loop body is used outside the loop. Compiler feedback indicates that this function could be autovectorized if we make a copy of the variable 'a'. Suggestion: Make a copy of the variable 'a'."
}}

YOUR OUTPUT:

        """


def get_manager_prompt(drafts_str, make_command, current_iteration):
    """
    Generate the manager prompt for choosing the best function draft.

    Args:
        drafts_str: Pretty-printed string of all function drafts
        make_command: Compilation command string
        current_iteration: Current iteration number

    Returns:
        Formatted prompt string
    """
    return f"""Given a few drafts of the same function, pick the function that is most likely to be autovectorized by the compiler.

The command that this function will be compiled with is:

{make_command}

The FUNCTION DRAFTS are below:

{drafts_str}

OUTPUT RULES:
- Your output MUST be a JSON object in the following format.
```
{{
  "i": int,
  "explanation": str,
}}
```
- Your output i must be in the valid range: 0 <= i < {current_iteration}. This means i can be between 0 and {current_iteration - 1} (inclusive). DO NOT output any value outside this range.


EXAMPLE OUTPUT:
```
{{
  "i": {current_iteration - 1},
  "explanation": "It was the only function draft that was successfully autovectorized. This is a good starting point for further autovectorization attempts."
}}
```

YOUR OUTPUT:

    """


def get_engineer_prompt(numbered_function_body, current_function_info,
                        program_slice, make_command, reviewer_feedback):
    """
    Generate the engineer prompt for modifying functions to improve vectorization.

    Args:
        numbered_function_body: Function body with line numbers
        current_function_info: FunctionInfo dict with function details
        program_slice: Surrounding program context
        make_command: Compilation command string
        reviewer_feedback: Feedback from the reviewer

    Returns:
        Formatted prompt string
    """
    return f"""Your task is to take a function and modify it to make it easier to autovectorize.

The FUNCTION is (with line numbers):

{numbered_function_body}

(This function starts at line {current_function_info["start_line"]} in the original file)

The surrounding context is:

{program_slice}

It is compiled with Clang, using the following command:

{make_command}

Please use SUGGESTIONS FROM A REVIEWER when modifying the function.

{reviewer_feedback}

You have two options:

1. PRAGMA ACTIONS: Suggest pragmas for FOR LOOPS where vectorization still failed
- You may suggest: "vectorize", "interleave", or "vectorize_width"
- Be conservative - only suggest if you're confident it will help

2. CODE REPLACE: Make targeted code changes:
- Fix specific issues identified in optimization remarks
- Add temporaries, hoist computations, break dependencies
- Avoid making changes that alter the meaning of the function

OPTION 1 - PRAGMA ACTIONS (for simple vectorization hints):
For each loop that needs a pragma, create a JSON object:
{{
  "action_type": "pragma",
  "line_number": <line number from the numbered function above>,
  "pragma_type": "vectorize" OR "interleave" OR "vectorize_width",
  "width": <number (only if pragma_type is vectorize_width), otherwise null>,
  "reasoning": "<brief explanation>"
}}

OPTION 2 - CODE REPLACE (for targeted code changes):
For each code change, create a JSON object:
{{
  "action_type": "code_replace",
  "start_line": <start line number from the numbered function above>,
  "end_line": <end line number from the numbered function above (inclusive)>,
  "new_code": "<replacement code (can be multi-line)>",
  "reasoning": "<brief explanation>"
}}

Examples:
- Add variable: {{"action_type": "code_replace", "start_line": 0, "end_line": 0, "new_code": "int temp = 0;", "reasoning": "Add local temporary"}}
- Replace line: {{"action_type": "code_replace", "start_line": 5, "end_line": 5, "new_code": "result[i] = a[i] * factor;", "reasoning": "Use hoisted variable"}}
- Multi-line: {{"action_type": "code_replace", "start_line": 3, "end_line": 5, "new_code": "for (int i = 0; i < n; i++) {{\\n    output[i] = input[i];\\n}}", "reasoning": "Simplify loop"}}

CRITICAL OUTPUT RULES:
- Output a JSON ARRAY: [{{...}}] or [{{...}}, {{...}}] for multiple actions
- You can mix pragma and code_replace actions in the same array
- If NO modifications needed, output an empty array: []
- DO NOT include any explanatory text, markdown, or code fences
- Output ONLY the JSON array, nothing else

    """
