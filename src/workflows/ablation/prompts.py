"""
Prompt templates for the ablation experiment workflow.

Oracle remarks are decomposed into three components:
  - dependence: the dependence description (e.g., "assumed write-after-read dependence between a and a")
  - code_lines: the source code snippets with caret markers showing the relevant lines
  - suggestion: the actionable suggestion (e.g., "consider using a temporary to store a[i + 1]")

Six ablation configurations control which components are included:
  Config 1: suggestion + dependence + code_lines  (full remark)
  Config 2: suggestion + dependence               (no code lines)
  Config 3: suggestion only
  Config 4: dependence + code_lines               (no suggestion)
  Config 5: dependence only
  Config 6: none                                   (empty)
"""

# Structured oracle remark supplements for ablation.
# Each entry is either None (no remark for this function) or a dict with
# 'dependence', 'code_lines', and 'suggestion' keys (any may be absent).

ORACLE_REMARK_SUPPLEMENTS = {
    's1113': {
        'dependence': "assumed read-after-write dependence between a [tsvc.c:140:13] and a [tsvc.c:140:20]",
        'code_lines': """\
            a[i] = a[LEN_1D/2] + b[i];
            ^
and a [tsvc.c:140:20]
            a[i] = a[LEN_1D/2] + b[i];
                   ^""",
        'suggestion': "consider loop splitting. load a into a[LEN_1D/2] temporary before the loop, split the loop at iteration LEN_1D/2, and update the temporary for the second split.",
    },

    's114': None,  # NO_REMARK

    's116': {
        'dependence': "assumed write-after-read dependence between a [tsvc.c:225:24] and a [tsvc.c:221:31]",
        'code_lines': """\
           a[i + 4] = a[i + 5] * a[i + 4];
                      ^
and a [tsvc.c:221:31]
           a[i] = a[i + 1] * a[i];
                             ^""",
        'suggestion': "consider using a temporary to store a[i + 5].",
    },

    's141': None,  # NO_REMARK

    's161': None,  # NO_REMARK

    's212': {
        'dependence': "assumed write-after-read dependence between a [tsvc.c:838:21] and a [tsvc.c:837:13]",
        'code_lines': """\
            b[i] += a[i + 1] * d[i];
                    ^
and a [tsvc.c:837:13]
            a[i] *= c[i];
            ^""",
        'suggestion': "consider using a temporary to store a[i + 1].",
    },

    's1213': {
        'suggestion': "consider statement reordering for vectorization.",
    },

    's241': {
        'dependence': "assumed write-after-read dependence between a [tsvc.c:1065:27] and a [tsvc.c:1064:13]",
        'code_lines': """\
            b[i] = a[i] * a[i+1] * d[i];
                          ^
and a [tsvc.c:1064:13]
            a[i] = b[i] * c[i  ] * d[i];
            ^""",
        'suggestion': "consider using a temporary to store a[i + 1].",
    },

    's244': {
        'dependence': """\
assumed write-after-read dependence between a [tsvc.c:1130:29] and a [tsvc.c:1128:12]

assumed write-after-write dependence between a [tsvc.c:1130:29] and a [tsvc.c:1128:13]""",
        'code_lines': """\
           a[i+1] = b[i] + a[i+1] * d[i];
                           ^
and a [tsvc.c:1128:12]
           a[i] = b[i] + c[i] * d[i];
           ^

           a[i+1] = b[i] + a[i+1] * d[i];
                           ^
and a [tsvc.c:1128:13]
           a[i] = b[i] + c[i] * d[i];
           ^""",
        'suggestion': "consider statement reordering to break the data dependency on a.",
    },

    's1244': {
        'dependence': "assumed write-after-read dependence between a [tsvc.c:1148:13] and a [tsvc.c:1149:27]",
        'code_lines': """\
           a[i] = b[i] + c[i] * c[i] + b[i]*b[i] + c[i];
           ^
and a [tsvc.c:1149:27]

           d[i] = a[i] + a[i+1];
                         ^""",
        'suggestion': "consider using a temporary to store a[i+1].",
    },

    's277': None,  # NO_REMARK

    's281': {
        'suggestion': "consider restructuring the loop into multiple, simpler loops.",
    },
}


def get_oracle_remark(function_name, ablation_config):
    """
    Assemble the oracle remark for a function based on the ablation config.

    Args:
        function_name: Name of the function (e.g., 's1113')
        ablation_config: int 1-6 controlling which components to include:
            1: suggestion + dependence + code_lines
            2: suggestion + dependence (no code lines)
            3: suggestion only
            4: dependence + code_lines (no suggestion)
            5: dependence only
            6: none

    Returns:
        Assembled remark string, or empty string if no remark.
    """
    entry = ORACLE_REMARK_SUPPLEMENTS.get(function_name)
    if entry is None:
        return ""

    if ablation_config == 6:
        return ""

    include_suggestion = ablation_config in (1, 2, 3)
    include_dependence = ablation_config in (1, 2, 4, 5)
    include_code_lines = ablation_config in (1, 4)

    parts = []

    if include_dependence and 'dependence' in entry:
        parts.append(entry['dependence'])

    if include_code_lines and 'code_lines' in entry:
        parts.append(entry['code_lines'])

    if include_suggestion and 'suggestion' in entry:
        parts.append("suggestion: " + entry['suggestion'])

    return "\n\n".join(parts)


def get_engineer_prompt(numbered_function_body, current_function_info,
                        program_slice, make_command, reviewer_feedback,
                        compiler_feedback=None, optimization_remarks=None,
                        perf_data=None, previous_search_replace=None,
                        lint_errors=None, oracle_ablation_config=0,
                        use_clang_not_intel=True,
                        filter_distribute_suggestion=False):
    """
    Generate the engineer prompt for the ablation experiment.

    In this workflow, compiler_feedback and optimization_remarks are always
    discarded from the prompt. The only hint provided is the oracle remark
    assembled from the ablation config.

    Args:
        oracle_ablation_config: int 1-6 controlling which oracle remark
            components to include. 0 means no oracle remark.
    """

    extra_info=""

    # Assemble oracle remark based on ablation config
    function_name = current_function_info.get("name")
    oracle_remark = ""
    if oracle_ablation_config > 0 and function_name:
        oracle_remark = get_oracle_remark(function_name, oracle_ablation_config)

    # In ablation mode, discard compiler feedback and optimization remarks.
    # The oracle remark is the only hint.
    compiler_feedback = oracle_remark if oracle_remark else ""
    optimization_remarks = ""

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
