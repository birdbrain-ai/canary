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

The FUNCTION is:

{current_function_info["full_text"]}

The surrounding context is:

{program_slice}

It is compiled with Clang, using the following command:

{make_command}

Please use SUGGESTIONS FROM A REVIEWER when modifying the function.

{reviewer_feedback}

INSTRUCTIONS:
Use search-replace blocks to suggest modifications. Each block shows the exact code to find (SEARCH) and what to replace it with (REPLACE).

FORMAT:
For each change, use this exact format:

<<<<<<< SEARCH
exact code to find
(must match exactly including whitespace and indentation)
=======
replacement code
(this will replace the SEARCH block)
>>>>>>> REPLACE

RULES:
1. SEARCH block must match the original code EXACTLY (including indentation and whitespace)
2. You can make multiple changes - just use multiple search-replace blocks
3. To add a pragma before a loop, include the loop line in SEARCH and add the pragma in REPLACE
4. To modify code, include the lines you want to change in SEARCH and provide new code in REPLACE
5. Make targeted changes - don't include unnecessary surrounding code
6. If NO modifications are needed, output only: NO_CHANGES

EXAMPLES:

Example 1 - Adding a pragma before a loop:
<<<<<<< SEARCH
    for (int i = 0; i < n; i++) {{
        result[i] = a[i] + b[i];
    }}
=======
    #pragma clang loop vectorize(enable)
    for (int i = 0; i < n; i++) {{
        result[i] = a[i] + b[i];
    }}
>>>>>>> REPLACE

Example 2 - Modifying code to hoist a computation:
<<<<<<< SEARCH
    for (int i = 0; i < n; i++) {{
        result[i] = a[i] * factor * 2;
    }}
=======
    int hoisted = factor * 2;
    for (int i = 0; i < n; i++) {{
        result[i] = a[i] * hoisted;
    }}
>>>>>>> REPLACE

Example 3 - Multiple changes (just put multiple blocks one after another):
<<<<<<< SEARCH
    int x = compute();
=======
    int temp = compute();
    int x = temp;
>>>>>>> REPLACE

<<<<<<< SEARCH
    for (int i = 0; i < n; i++) {{
        data[i] = x;
    }}
=======
    #pragma clang loop vectorize(enable)
    for (int i = 0; i < n; i++) {{
        data[i] = x;
    }}
>>>>>>> REPLACE

YOUR OUTPUT:
(Provide search-replace blocks or NO_CHANGES)

    """
