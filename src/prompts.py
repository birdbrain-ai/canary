"""
Prompt templates for the vectorization workflow.
"""

def get_reviewer_prompt(cur_function_info, make_command, program_slice,
                        compiler_feedback, optimization_remarks, vectorization_success,
                        use_compiler_feedback=True, runtime_s=None):
    """
    Generate the reviewer prompt for evaluating autovectorization opportunities.

    Args:
        cur_function_info: FunctionInfo dict with function details
        make_command: Compilation command string
        program_slice: Surrounding program context
        compiler_feedback: Compiler errors/warnings
        optimization_remarks: LLVM optimization remarks
        vectorization_success: Whether the function was successfully vectorized
        use_compiler_feedback: Whether to include compiler feedback and optimization remarks in the prompt
        runtime_s: Runtime of the function in seconds, or None if not measured

    Returns:
        Formatted prompt string
    """
    # Build the feedback sections conditionally
    # When disabled, keep structure but remove actual content for ablation study
    if use_compiler_feedback:
        compiler_fb_content = compiler_feedback
        opt_remarks_content = optimization_remarks
    else:
        compiler_fb_content = ""
        opt_remarks_content = ""

    feedback_sections = f"""Second, COMPILER FEEDBACK:

{compiler_fb_content}

Third, OPTIMIZATION REMARKS:

{opt_remarks_content}"""

    return f"""You are reviewing THIS FUNCTION for opportunities to autovectorize it. If there are further opportunities to autovectorize the function, you MUST provide a NUMBERED LIST of suggested changes.

{cur_function_info["full_text"]}

The function is compiled with Intel's ICX compiler, using the following command: {make_command}

You have access to the following information:

First, the PROGRAM:

{program_slice}

{feedback_sections}

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
- DO NOT MAKE SUGGESTIONS THAT TOUCH THE OUTERMOST LOOP. I CANNOT OVERSTATE HOW TERRIBLE IT WOULD BE IF YOU TOUCHED THE OUTERMOST LOOP. THAT MEANS THE FOLLOWING. DO NOT CHANGE THE NUMBER OF ITERATIONS THAT THE OUTER LOOP RUNS FOR. DO NOT CHANGE THE DUMMY CALL. DO NOT CHANGE THE NUMBER OF TIMES THAT THE DUMMY FUNCTION IS CALLED.

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
  "reviewer_feedback": "Problem: Optimization remarks indicate that there is a flow dependency between two variables. Compiler feedback suggests this function could be autovectorized by removing a data dependency on 'a'. Suggestions: 1. Make a temporary copy of 'a' before the for loop. 2. Reverse the iteration order to remove the data dependency on 'a'. 3. Split the loop to isolate the instruction with the data dependency in it. 3. Try rerolling the loop to simplify it so the compiler can automatically resolve the dependency."
}}

{{
  "dead_end": false,
  "reviewer_feedback": "Problem: Optimization remarks indicate that there are unsafe memory dependencies in the loop. Suggestions: 1. Split the loop to isolate the offending instruction. 2. Add a pragma directive to unroll the loop, to make the loop easier to SLP vectorize."
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
1. CRITICAL: Only consider drafts where ALL of the following are true:
   - compile_success = true (must compile without errors)
   - run_success = true (must pass validation/correctness checks)
   - dead_end = false (must have a viable path forward for optimization)
   Drafts failing ANY of these criteria are invalid and MUST be excluded from consideration.
2. Among valid drafts, prioritize those with the fastest runtime (lowest Runtime value)
3. Drafts already autovectorized (vectorization_success = true) typically have the best performance
4. If runtime values are available, prefer the draft with the lowest runtime
5. If no drafts are vectorized, choose the one closest to being vectorized based on reviewer feedback
6. If multiple drafts have similar runtimes, consider reviewer feedback about optimization potential

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

    # Credit for example: https://johnnysswlab.com/loop-optimizations-interpreting-the-compiler-optimization-report/
    
    return f"""Modify this function to enable autovectorization.

FUNCTION:
{current_function_info["full_text"]}

CONTEXT:
{program_slice}

COMPILED WITH: {make_command}

REVIEWER FEEDBACK:
{reviewer_feedback}

CRITICAL INSTRUCTIONS:
- Output EXACTLY ONE search-replace block. Do NOT output multiple blocks.
- Your SEARCH block must match code that actually exists in the FUNCTION section above.
- If the same code appears multiple times in the function, include enough surrounding lines in your SEARCH to make it unique - otherwise the replacement will FAIL
- Follow the reviewer feedback - implement the suggested changes
- Preserve the semantic behavior of the function - only make changes that improve vectorization without altering what the function computes
- DO NOT TOUCH THE OUTERMOST LOOP. I CANNOT OVERSTATE HOW TERRIBLE IT WOULD BE IF YOU TOUCHED THE OUTERMOST LOOP. THAT MEANS THE FOLLOWING. DO NOT CHANGE THE NUMBER OF ITERATIONS THAT THE OUTER LOOP RUNS FOR. DO NOT CHANGE THE DUMMY CALL. DO NOT CHANGE THE NUMBER OF TIMES THAT THE DUMMY FUNCTION IS CALLED.
- If no change needed, output: NO_CHANGES
- PRAGMA PLACEMENT: ALL pragmas MUST be placed ABOVE the loop header, NEVER below it
- DO NOT use memcpy() - it requires string.h which cannot be included in this context

FORMAT:
<<<<<<< SEARCH
exact code to find
=======
replacement code
>>>>>>> REPLACE

EXAMPLES:

EXAMPLE 1 - Fix dependency:
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

EXAMPLE 2 - Loop splitting:
<<<<<<< SEARCH
for (int i = 0; i < n; i++) {{
    a[i] = a[i - 1] * b[i];
    c[i] = a[i] + e[i];
}}
=======
for (int i = 0; i < n; i++) {{
    a[i] = a[i - 1] * b[i];
}}
for (int i = 0; i < n; i++) {{
    c[i] = a[i] + e[i];
}}
>>>>>>> REPLACE

EXAMPLE 3 - Loop rerolling:
<<<<<<< SEARCH
for (int i = 0; i < LEN_1D - 5; i += 5) {{
    a[i] = a[i + 1] * a[i];
    a[i + 1] = a[i + 2] * a[i + 1];
    a[i + 2] = a[i + 3] * a[i + 2];
    a[i + 3] = a[i + 4] * a[i + 3];
    a[i + 4] = a[i + 5] * a[i + 4];
}}
=======
for (int i = 0; i < LEN_1D - 1; i++) {{
    a[i] = a[i + 1] * a[i];
}}
>>>>>>> REPLACE


YOUR OUTPUT:
    """
