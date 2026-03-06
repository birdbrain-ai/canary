"""
Prompt templates for the vectorization workflow.
"""

# Oracle experiment: remark supplements for specific functions
# These provide additional hints to the model beyond standard compiler remarks
# None means no additional remark (also implies removing loop distribution suggestion)
ORACLE_REMARK_SUPPLEMENTS = {
    's1113': """assumed read-after-write dependence between a [tsvc.c:140:13]
            a[i] = a[LEN_1D/2] + b[i];
            ^
and a [tsvc.c:140:20]
            a[i] = a[LEN_1D/2] + b[i];
                   ^

suggestion: consider loop splitting. load a into a[LEN_1D/2] temporary before the loop, split the loop at iteration LEN_1D/2, and update the temporary for the second split.
""",

    's114': None,  # NO_REMARK (remove loop distribution suggestion)

    's116': """assumed write-after-read dependence between a [tsvc.c:225:24]
           a[i + 4] = a[i + 5] * a[i + 4];
                      ^
and a [tsvc.c:221:31]
           a[i] = a[i + 1] * a[i];
                             ^

suggestion: consider using a temporary to store a[i + 5].
    """,

    's141': None,  # NO_REMARK (remove loop distribution suggestion)

    's161': None,  # NO_REMARK (remove loop distribution suggestion)

    's212': """assumed write-after-read dependence between a [tsvc.c:838:21]
            b[i] += a[i + 1] * d[i];
                    ^
and a [tsvc.c:837:13]
            a[i] *= c[i];
            ^

suggestion: consider using a temporary to store a[i + 1].
    """,

    's1213': """consider statement reordering for vectorization.""",

    's241': """assumed write-after-read dependence between a [tsvc.c:1065:27]
            b[i] = a[i] * a[i+1] * d[i];
                          ^
and a [tsvc.c:1064:13]
            a[i] = b[i] * c[i  ] * d[i];
            ^

suggestion: consider using a temporary to store a[i + 1].
""",

    's244': """assumed write-after-read dependence between a [tsvc.c:1130:29]
           a[i+1] = b[i] + a[i+1] * d[i];
                           ^
and a [tsvc.c:1128:12]
           a[i] = b[i] + c[i] * d[i];
           ^

assumed write-after-write dependence between a [tsvc.c:1130:29]
           a[i+1] = b[i] + a[i+1] * d[i];
                           ^
and a [tsvc.c:1128:13]
           a[i] = b[i] + c[i] * d[i];
           ^

suggestion: consider statement reordering to break the data dependency on a. 
    """,

    's1244': """assumed write-after-read dependence between a [tsvc.c:1148:13]

           a[i] = b[i] + c[i] * c[i] + b[i]*b[i] + c[i];
           ^
and a [tsvc.c:1149:27]

           d[i] = a[i] + a[i+1];
                         ^

suggestion: consider using a temporary to store a[i+1].
""",

    's277': None,  # NO_REMARK (remove loop distribution suggestion)

    's281': """consider restructuring the loop into multiple, simpler loops.""",
}

def get_reviewer_prompt(cur_function_info, make_command, program_slice,
                        compiler_feedback, optimization_remarks, vectorization_success,
                        use_compiler_feedback=True, runtime_s=None, use_clang_not_intel=True):
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

The function is compiled with {"the Clang compiler" if use_clang_not_intel else "Intel's ICX compiler"}, using the following command: {make_command}

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
                        program_slice, make_command, reviewer_feedback,
                        compiler_feedback=None, optimization_remarks=None,
                        perf_data=None, previous_search_replace=None,
                        lint_errors=None, use_clang_not_intel=True):
    """
    Generate the engineer prompt for modifying functions to improve vectorization.

    Args:
        numbered_function_body: Function body with line numbers
        current_function_info: FunctionInfo dict with function details
        program_slice: Surrounding program context
        make_command: Compilation command string
        reviewer_feedback: Feedback from the reviewer
        previous_search_replace: Optional dict with 'search' and 'replace' from failed attempt
        lint_errors: Optional string with syntax errors from the failed attempt

    Returns:
        Formatted prompt string
    """

    extra_info=""

    # The distribute pragma suggestion to filter/replace
    distribute_suggestion = "Use #pragma clang loop distribute(enable) to allow loop distribution to attempt to isolate the offending operations into a separate loop"

    # Handle oracle experiment remark supplements
    function_name = current_function_info.get("name")
    oracle_supplement = ORACLE_REMARK_SUPPLEMENTS.get(function_name) if function_name else None

    if function_name in ('s281', 's1213') and oracle_supplement:
        # For s281 and s1213: replace the distribute suggestion with the oracle supplement
        if optimization_remarks and use_clang_not_intel:
            optimization_remarks = optimization_remarks.replace(distribute_suggestion, oracle_supplement)
    else:
        # For all other functions: filter out the distribute suggestion
        if optimization_remarks and use_clang_not_intel:
            optimization_remarks = optimization_remarks.replace(distribute_suggestion, "")
        # Add oracle supplement to compiler_feedback if present
        if oracle_supplement:
            if compiler_feedback:
                compiler_feedback = compiler_feedback + "\n\n" + oracle_supplement
            else:
                compiler_feedback = oracle_supplement

    if use_clang_not_intel:
        prompt_examples="""
<<<<<<< SEARCH
for (int i = 0; i < n; i++) {
    a[i] = b[i] + c[i];
}
=======
// Brief comment explaining why this change enables vectorization
#pragma clang loop [DIRECTIVES]
for (int i = 0; i < n; i++) {
    a[i] = b[i] + c[i];
}
>>>>>>> REPLACE
"""
        extra_info="""
You must ONLY use Clang-specific pragmas or source code modifications that preserve semantics to enable auto-vectorization. DO NOT use OpenMP or SIMD intrinsics.
Key Directives:
- Use `#pragma clang loop vectorize(enable)` to override the compiler's internal cost model.
- Use `#pragma clang loop vectorize_width(__count__)` where __count__ is a positive integer to give Clang a hint that executing __count__ iterations in parallel might be optimal. Example: `#pragma clang loop vectorize_width(4)`.
- Use `#pragma clang loop vectorize(assume_safety)` to ignore potential dependencies. DO NOT USE THIS PRAGMA UNLESS YOU ARE CERTAIN THAT LOOP ITERATIONS ARE INDEPENDENT.
- Use `#pragma clang loop interleave(enable)` to give Clang a hint that interleaving loop iterations might improve performance.
- Use `#pragma clang loop interleave_width(__count__)` where __count__ is a positive integer to give Clang a hint that interleaving __count__ iterations of the loop might improve performance (for instance, it might take advantage of advanced hardware features). Example: `#pragma clang loop interleave_width(4)`.
- Use `#pragma clang loop unroll(enable)` to unroll the loop.
- Use `#pragma clang loop unroll(full)` to fully unroll the loop if possible.
- Use `#pragma clang loop unroll_count(__count__)` to unroll the loop __count__ times. 
- Use `#pragma clang loop distribute(enable)` to give Clang a hint that loop distribution would be beneficial.
- Use `__restrict`, and source code modifications that preserve semantics like introducing temporaries for source-level fixes.
"""
    else:
        prompt_examples="""
<<<<<<< SEARCH
for (int i = 0; i < n; i++) {
    c[i] = b[i] * a[i];
}
=======
// Brief comment explaining why this change enables vectorization
#pragma [DIRECTIVES]
for (int i = 0; i < n; i++) {
    c[i] = b[i] * a[i];
}
>>>>>>> REPLACE
"""

        extra_info="""
You must ONLY use Intel-specific pragmas or source code modifications that preserve semantics to enable auto-vectorization. DO NOT use OpenMP or SIMD intrinsics.
Key Directives:
- Use `#pragma vector always` to override the compiler's internal cost model.
- Use `#pragma unroll` to unroll the loop.
- Use `#pragma ivdep` to ignore potential dependencies. DO NOT USE THIS PRAGMA UNLESS YOU ARE CERTAIN THAT LOOP ITERATIONS ARE INDEPENDENT.
- Use `__restrict`, `__attribute__((aligned(64)))` for pointer/data optimization, and source code modifications that preserve semantics like introducing temporaries for source-level fixes."""
        
    # Credit for example: https://johnnysswlab.com/loop-optimizations-interpreting-the-compiler-optimization-report/
    # Build the lint error section if there was a previous failed attempt
    lint_section = ""
    if previous_search_replace and lint_errors:
        lint_section = f"""
PREVIOUS ATTEMPT FAILED - FIX THE SYNTAX ERRORS:

Your previous search-replace produced syntax errors. Here is what you tried:

<<<<<<< SEARCH
{previous_search_replace['search']}
=======
{previous_search_replace['replace']}
>>>>>>> REPLACE

SYNTAX ERRORS:
{lint_errors}

You MUST fix these syntax errors in your new attempt. Output a corrected search-replace block.

"""
    return f"""You are a performance engineer responsible for enabling vectorization in a function. You should preserve the semantic behavior of the function while making it faster.


VECTORIZE THIS FUNCTION (starts on line {current_function_info["start_line"]}):
{current_function_info["full_text"]}


PROGRAM CONTEXT:
{program_slice}

{lint_section}


COMPILER FEEDBACK:
{compiler_feedback}


OPTIMIZATION REMARKS:
{optimization_remarks}


FORMATTING RULES:
- Output EXACTLY ONE search-replace block in this format:
<<<<<<< SEARCH
exact code to find
=======
replacement code
>>>>>>> REPLACE

- Your SEARCH BLOCK must match code that actually exists in the FUNCTION section below.
- Your SEARCH BLOCK should only occur ONCE in the function. Otherwise the replacement will fail.

FORMATTING EXAMPLE:
{prompt_examples}


CODING INSTRUCTIONS:
- DO NOT CHANGE THE OUTER LOOP. DO NOT CHANGE THE NUMBER OF ITERATIONS THE OUTER LOOP RUNS FOR. DO NOT MODIFY THE DUMMY CALL. DO NOT CHANGE THE NUMBER OF TIMES THAT THE DUMMY FUNCTION IS CALLED.
- PRAGMA PLACEMENT: ALL pragmas MUST be placed ABOVE the loop header, NEVER below it.
- Add a brief comment explaining why your change enables vectorization in your REPLACE BLOCK.


{"CLANG" if use_clang_not_intel else "ICX"}-SPECIFIC RULES:
{extra_info}


LOOP TRANSFORMATIONS YOU MAY APPLY:
1. Loop Reversal - Change iteration direction from forward to backward or vice versa
2. Loop Interchange - Swap the order of nested loops
3. Loop Distribution/Fission - Split one loop into multiple separate loops
4. Loop Fusion/Collapsing - Combine multiple loops into a single loop
5. Loop Peeling - Extract boundary iterations into separate code
6. Loop Unrolling - Expand loop body to process multiple iterations per cycle
7. Loop Rerolling - Convert manually unrolled code back into a compact loop
8. Strip Mining/Tiling - Break loop into outer loop over chunks and inner loop within each chunk
9. Scalar Expansion - Replace scalar variable with array to give each iteration its own storage
10. If-Conversion - Transform conditional branches into predicated/masked operations


YOUR OUTPUT:
"""
