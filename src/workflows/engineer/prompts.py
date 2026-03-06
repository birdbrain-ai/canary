"""
Prompt templates for the vectorization workflow.
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
    # oracle_supplement = ORACLE_REMARK_SUPPLEMENTS.get(function_name) if function_name else None
    oracle_supplement = False

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
