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
    # Extract function without line numbers for diff generation
    function_body = current_function_info["full_text"]

    return f"""Your task is to take a function and modify it to make it easier to autovectorize.

The FUNCTION is:

{function_body}

(This function starts at line {current_function_info["start_line"]} in the original file)

The surrounding context is:

{program_slice}

It is compiled with Clang, using the following command:

{make_command}

Please use THIS INFORMATION FROM A REVIEWER when modifying the function.

{reviewer_feedback}


OUTPUT FORMAT:

You must output a UNIFIED DIFF that shows the changes to make to the function. The unified diff should:
- Use standard unified diff format (--- / +++ headers, @@ hunk markers)
- Show context lines around changes (typically 3 lines)
- Use the filename "function.c" (exact name doesn't matter)
- Be applicable to the function code shown above

Example unified diff format:
```diff
--- function.c
+++ function.c
@@ -1,5 +1,6 @@
 void example(int *arr, int n) {{
+    int temp = 0;  // Added temporary variable
     for (int i = 0; i < n; i++) {{
-        arr[i] = arr[i] * 2;
+        arr[i] = arr[i] * temp;  // Use temp instead
     }}
 }}
```

RULES:
1. Output the unified diff in a code block with ```diff
2. If no changes are needed, output only the text "NO_CHANGES_NEEDED"
3. Make targeted changes to help with autovectorization:
   - Add #pragma clang loop directives where beneficial
   - Add temporary variables to break dependencies
   - Hoist invariant computations
   - Simplify pointer arithmetic
4. You MUST preserve the function's semantic meaning

YOUR OUTPUT (unified diff):

    """
