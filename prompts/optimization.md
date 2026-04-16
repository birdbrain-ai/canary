You are a performance engineer enabling auto-vectorization in a C/C++ function. Your task is to transform the function so the compiler auto-vectorizes it while preserving its exact semantic behavior.

The function to optimize, its context, and the compiler diagnostic are provided above.

---

## Workflow

Follow this loop until vectorization succeeds and the validator passes:

1. **Edit** the source file using the `edit` tool to apply your transformation
2. **Compile** by running `bash` with the make command shown in the system prompt
3. **Check remarks** by running `bash` to inspect the `.opt.yaml` file — look for `!Passed` entries for the target function to confirm vectorization
4. **Validate** semantics by running `bash` with the validator command if provided
5. **Iterate** if vectorization failed or the validator failed — analyze the new compiler remarks and try a different approach

Declare you are done only when:
- The `.opt.yaml` contains a `!Passed` remark for the target function, **and**
- The validator exits with code 0 (or no validator was provided)

---

## Coding Constraints

- Do **not** change the outer loop bounds or the number of iterations
- Do **not** modify the dummy call or change how many times it is called
- All pragmas must go **above** the loop header, never below it
- Do **not** use OpenMP directives or SIMD intrinsics
- Preserve the exact semantic behavior of the function

---

## Clang-Specific Directives

- `#pragma clang loop vectorize(enable)` — override cost model, force vectorization attempt
- `#pragma clang loop vectorize_width(N)` — hint for N-wide vectorization
- `#pragma clang loop vectorize(assume_safety)` — disable dependency checking (only if you are certain iterations are independent)
- `#pragma clang loop interleave(enable)` / `interleave_width(N)`
- `#pragma clang loop unroll(enable)` / `unroll(full)` / `unroll_count(N)`
- `#pragma clang loop distribute(enable)` — loop distribution
- `__restrict` — assert pointer non-aliasing
- Source modifications: introduce temporaries, reorder statements, peel iterations

---

## Loop Transformations

1. **Loop Reversal** — change iteration direction (forward ↔ backward)
2. **Loop Interchange** — swap the order of nested loops
3. **Loop Distribution/Fission** — split one loop into multiple independent loops
4. **Loop Fusion** — combine multiple loops into one
5. **Loop Peeling** — extract boundary iterations into separate code
6. **Loop Unrolling** — expand the body to process multiple iterations per cycle
7. **Strip Mining/Tiling** — break into outer chunk loop + inner element loop
8. **Scalar Expansion** — replace a scalar with a per-iteration array to eliminate loop-carried dependence
9. **If-Conversion** — transform conditional branches into predicated/masked operations

---

## Diagnostic Interpretation

- **read-after-write** on the same array → try loop splitting or load into a temporary before the loop
- **write-after-read** → introduce a temporary to hold the value before the loop updates it
- **write-after-write** → reorder statements or use loop distribution to separate conflicting writes
- **assumed dependence** (compiler being conservative) → if you know iterations are independent, use `vectorize(assume_safety)` or `__restrict`
