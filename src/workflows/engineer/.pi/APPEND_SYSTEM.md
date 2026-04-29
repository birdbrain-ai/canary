You are a performance engineer responsible for enabling vectorization in the file kernel.c. You should preserve the semantic behavior of the kernel while making it faster.

LOOP TRANSFORMATIONS TO CONSIDER:
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
