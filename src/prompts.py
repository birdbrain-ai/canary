"""
Prompt templates for the vectorization workflow.
"""

def get_reviewer_prompt(cur_function_info, make_command, program_slice,
                        compiler_feedback, optimization_remarks, vectorization_success):
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
    return f"""You are reviewing THIS FUNCTION for opportunities to autovectorize it. If there are further opportunities to autovectorize the function, you MUST provide a NUMBERED LIST of suggested changes to the for loop. 

{cur_function_info["full_text"]}

        The function is compiled with Clang, using the following command: {make_command}

        You have access to some information to help.

First, the PROGRAM:

{program_slice}

Second, COMPILER FEEDBACK:

{compiler_feedback}

Third, OPTIMIZATION REMARKS:

{optimization_remarks}

You MUST return a JSON object in this format:

```
{{
  "dead_end": bool
  "reviewer_feedback": str
}}
```

The function's VECTORIZATION SUCCESS is: {vectorization_success}

RULES:
- If the function was already autovectorized, you must set the dead_end field to false, and the vectorization_success field to true.
- You must set 'dead_end' to false is the function is a useful starting point for autovectorization.
- Fill out the reviewer_feedback field to include a NUMBERED LIST of CONCRETE SUGGESTIONS to modify the function in order to autovectorize it.

EXAMPLE OUTPUTS:
{{
  "dead_end": false,
  "reviewer_feedback": "1. Finished: This function is already fully autovectorized. No further work is needed."
}}

{{
  "dead_end": true,
  "reviewer_feedback": ""
}}

{{
  "dead_end": true,
  "reviewer_feedback": "1. Problem: Optimization remarks for this function suggest that a non-reduction value in the loop body is used outside the loop. Compiler feedback indicates that this function could be autovectorized if we make a copy of the variable 'a'. Suggestion: Make a temporary copy of the variable 'a' before the for loop."
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
    return f"""Modify this function to enable autovectorization. Make ONE small, targeted change.

FUNCTION:
{current_function_info["full_text"]}

CONTEXT:
{program_slice}

COMPILED WITH: {make_command}

REVIEWER FEEDBACK:
{reviewer_feedback}

INSTRUCTIONS:
Make ONE change using this format:

<<<<<<< SEARCH
exact code to find
=======
replacement code
>>>>>>> REPLACE

- If no change needed, output: NO_CHANGES
- Keep changes minimal - only modify what's necessary
- Whitespace differences in SEARCH are OK

EXAMPLES:

Add pragma:
<<<<<<< SEARCH
for (int i = 0; i < n; i++) {{
    a[i] = b[i] + c[i];
}}
=======
#pragma clang loop vectorize(enable)
for (int i = 0; i < n; i++) {{
    a[i] = b[i] + c[i];
}}
>>>>>>> REPLACE

Fix dependency:
<<<<<<< SEARCH
for (int i = 1; i < n; i++) {{
    a[i] = a[i-1] + b[i];
}}
=======
float temp = a[0];
for (int i = 1; i < n; i++) {{
    temp = temp + b[i];
    a[i] = temp;
}}
>>>>>>> REPLACE

YOUR OUTPUT:
    """
