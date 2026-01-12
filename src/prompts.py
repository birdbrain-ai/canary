### I can give the reviewer a bit more context about what each remark means and how to interpret it now. I am a little concerned about the impulse to connect #pragma clang loop unroll(enable) to any specific remark, AND, I am concerned about whether this will ever enable further SLP vectorization. 
### To reviewer, add multiple suggestions to NonReductionValueUsedOutsideLoop remark example, AND add CantComputeNumberOfIterationsExample example, and use SLP vectorizer as a jumping off point. Modify an existing example (NonReductionValueUsedOutsideLoop), and add another example (SLP). 
### To engineer, add loop splitting, loop rerolling (s116 is a perfect example), AND loop unroll pragma.


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
    return f"""You are reviewing THIS FUNCTION for opportunities to autovectorize it. If there are further opportunities to autovectorize the function, you MUST provide a NUMBERED LIST of suggested changes.

{cur_function_info["full_text"]}

The function is compiled with Clang, using the following command: {make_command}

You have access to the following information:

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

EXTRA INFORMATION:
- Clang has two autovectorizers: The Loop Vectorizer and the Superword Level Parallelism (SLP) Vectorizer. The Loop Vectorizer takes loop iterations and executes them in parallel. The SLP Vectorizer packs instructions in straight-line code, and transforms them into vector instructions. One common pattern with the SLP Vectorizer: unroll a loop in order to transform it into straight line code, and then autovectorize it using the SLP Vectorizer. 
- The relevant remarks for the loop vectorizer have 'loop-vectorize' in them.
- The relevant remarks for the SLP vectorizer have either 'slp-vectorizer' or 'loop-unroll' in them.
- Your suggestions as a reviewer should target one or both of the loop and SLP vectorizers.

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
  "reviewer_feedback": "Problem: Optimization remarks indicate that a non-reduction value in the loop body is used outside the loop. Compiler feedback suggests this function could be autovectorized by making a copy of the variable 'a'. Suggestions: 1. Make a temporary copy of the variable 'a' before the for loop. 2. Reverse the iteration order and split the loop. Luckily, this would not break semantics, and it would resolve the data dependency over b. 3. Try rerolling the loop so the compiler can automatically resolve the RAW dependency."
}}

{{
  "dead_end": false,
  "reviewer_feedback": "Problem: ."
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
2. Among valid drafts, prioritize those with the greatest potential for fast execution
3. Drafts already autovectorized (vectorization_success = true) typically have the best performance
4. If no drafts are vectorized, choose the one closest to being vectorized based on reviewer feedback
5. If multiple drafts are equally promising, consider reviewer feedback about optimization potential

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
