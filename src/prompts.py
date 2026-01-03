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
- Set 'dead_end' to false if:
  1. The function is already fully autovectorized (success case), OR
  2. There are concrete suggestions that could improve autovectorization (actionable case)
- Set 'dead_end' to true if:
  1. The function cannot be further autovectorized, AND
  2. There are no actionable suggestions to try
- When dead_end is false, provide a NUMBERED LIST of CONCRETE SUGGESTIONS in the reviewer_feedback field
- When dead_end is true, you may leave reviewer_feedback empty or briefly explain why no progress can be made
- All suggestions must preserve the semantic behavior of the function - only suggest changes that improve vectorization without altering what the function computes

EXAMPLE OUTPUTS:
{{
  "dead_end": false,
  "reviewer_feedback": "1. Finished: This function is already fully autovectorized. No further work is needed."
}}

{{
  "dead_end": true,
  "reviewer_feedback": "This function cannot be autovectorized due to inherent scalar operations with complex control flow that cannot be parallelized."
}}

{{
  "dead_end": false,
  "reviewer_feedback": "1. Problem: Optimization remarks indicate that a non-reduction value in the loop body is used outside the loop. Compiler feedback suggests this function could be autovectorized by making a copy of the variable 'a'. Suggestion: Make a temporary copy of the variable 'a' before the for loop."
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
    return f"""Given a few drafts of the same function, pick the function draft most likely to achieve the fastest execution time, either because it's already autovectorized or because it's closest to being autovectorized. This will be used as the starting point for the next iteration of optimization.

The command that this function will be compiled with is:

{make_command}

The FUNCTION DRAFTS are below:

{drafts_str}

SELECTION CRITERIA:
1. Prioritize drafts with the greatest potential for fast execution
2. Drafts already autovectorized (vectorization_success = true) typically have the best performance
3. If no drafts are vectorized, choose the one closest to being vectorized based on reviewer feedback
4. If multiple drafts are equally promising, consider reviewer feedback about optimization potential

OUTPUT RULES:
- Your output MUST be a JSON object in the following format.
```
{{
  "i": int,
  "explanation": str
}}
```
- Your output i must be in the valid range: 0 <= i < {current_iteration}. DO NOT output any value outside this range.


EXAMPLE OUTPUTS:
```
{{
  "i": 0,
  "explanation": "Draft 0 was successfully autovectorized and will execute the fastest among all drafts."
}}
```
{f'''
```
{{
  "i": {current_iteration // 2},
  "explanation": "Draft {current_iteration // 2} has the most promising reviewer feedback with concrete suggestions for vectorization, making it the best candidate for further optimization."
}}
```
''' if current_iteration >= 2 else ''}

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

CRITICAL INSTRUCTIONS:
- Output EXACTLY ONE search-replace block. Do NOT output multiple blocks.
- Your SEARCH block must match code that actually exists in the function above
- If no change needed, output: NO_CHANGES

FORMAT:
<<<<<<< SEARCH
exact code to find
=======
replacement code
>>>>>>> REPLACE

EXAMPLES:

EXAMPLE 1 - Add pragma:
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

EXAMPLE 2 - Fix dependency:
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
