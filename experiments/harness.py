# Harness for experiments to determine two things
# 1. Is Qwen3 better than Qwen2.5Coder?
# 2. Which output strategy should I use?

# No need for LangGraph workflow. Too complicated. Just do a simple prompt, extract the output, and apply the diff.

# In experiments, there is a file called harness.py. Prop up a small experiment that is comprised of a few parts. 1) An llm object - Qwen3 coder. 2) A prompt - to edit a C/C++ file in order to make it easier to autovectorize. It should output a diff 3) A mechanism to apply the generated diff back to a file. Make this workflow usable with the s*.cpp files in ./experiments/TSVC_2/src/

import sys
import os
import shutil
import subprocess
import tempfile
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="none"
)

def engineer_prompt(code: str) -> str:
    # Add line numbers to the code to help LLM generate correct diffs
    numbered_lines = '\n'.join(f"{i+1:4d}: {line}" for i, line in enumerate(code.splitlines()))

    return f"""Modify this C++ code to make it easier for the clang compiler to autovectorize.

CODE WITH LINE NUMBERS:
{numbered_lines}

Output a unified diff showing your changes in STANDARD UNIFIED DIFF FORMAT.

IMPORTANT: Use the line numbers shown above in your diff. Do NOT count lines yourself.

CRITICAL RULES FOR UNIFIED DIFF FORMAT:
1. Context lines (unchanged) have a SPACE prefix and must EXACTLY match the original code
2. Removed lines have a MINUS (-) prefix showing the OLD content
3. Added lines have a PLUS (+) prefix showing the NEW content
4. To CHANGE a line: show it as BOTH removal (-old) AND addition (+new)
5. Hunks MUST be ordered by ascending line number (line 10 before line 20)
6. Context lines appear before/after changes to help locate where to apply the patch
7. Hunk header format: @@ -oldstart,oldcount +newstart,newcount @@

CORRECT EXAMPLE - Adding __restrict__ and changing a line:

Given code with line numbers:
   8: #include <stdio.h>
   9:
  10: real_t* __restrict__ xx;
  11: real_t* yy;
  12:
  13: void vectorize_me(float *a, float *b, int n) {{
  14:     for (int i = 0; i < n; i++) {{
  15:         a[i] = b[i] * 2.0f;
  16:     }}
  17: }}

Correct diff output:
--- original.cpp
+++ original.cpp
@@ -10,8 +10,9 @@
 real_t* __restrict__ xx;
-real_t* yy;
+real_t* __restrict__ yy;

 void vectorize_me(float *a, float *b, int n) {{
+    float factor = 2.0f;
     for (int i = 0; i < n; i++) {{
-        a[i] = b[i] * 2.0f;
+        a[i] = b[i] * factor;
     }}
 }}

EXPLANATION OF ABOVE:
- The hunk starts at line 10 (where "real_t* __restrict__ xx;" is)
- Lines with space prefix are unchanged context (they MUST match original exactly, WITHOUT line numbers)
- Line "real_t* yy;" is REMOVED (shown with -)
- Line "real_t* __restrict__ yy;" is ADDED (shown with +)
- Line "a[i] = b[i] * 2.0f;" is REMOVED
- Line "a[i] = b[i] * factor;" is ADDED
- Line "float factor = 2.0f;" is INSERTED (only + line, no corresponding -)
- CRITICAL: In the diff output, DO NOT include the line numbers - only the actual code text

WRONG EXAMPLE 1 - Showing modified content as context:
@@ -10,8 +10,8 @@
 real_t* __restrict__ xx;
 real_t* __restrict__ yy;  // WRONG! This shows NEW content as context (no prefix)

WRONG EXAMPLE 2 - Not showing both - and + for a change:
@@ -10,8 +10,8 @@
 real_t* __restrict__ xx;
+real_t* __restrict__ yy;  // WRONG! Missing the - line showing what was removed

WRONG EXAMPLE 3 - Context not matching original:
@@ -10,8 +10,8 @@
 real_t*  __restrict__  xx;  // WRONG! Extra spaces don't match original
-real_t* yy;
+real_t* __restrict__ yy;

WRONG EXAMPLE 4 - Hunks out of order:
@@ -20,3 +20,3 @@   // WRONG! Line 20 should come AFTER line 10
...
@@ -10,3 +10,3 @@
...

WRONG EXAMPLE 5 - Including line numbers in diff output:
@@ -10,2 +10,2 @@
  10: real_t* __restrict__ xx;  // WRONG! Do not include "10:" in the diff
- 11: real_t* yy;                // WRONG! Do not include "11:" in the diff
+ 11: real_t* __restrict__ yy;  // WRONG! Do not include "11:" in the diff

REMINDER:
- Use the provided line numbers to determine the correct @@ hunk header line numbers
- DO NOT include the line number prefixes (like "10: ") in the diff content itself
- Only include the actual source code text in the diff lines

If no changes are needed, output only: NO_CHANGES_NEEDED
"""


def apply_diff(original_file: str, diff: str) -> str:
    """Apply a diff to a file copy and return the path to the modified file."""

    # Create output filename with _opt suffix
    base_name = os.path.basename(original_file)
    dir_name = os.path.dirname(original_file)
    name, ext = os.path.splitext(base_name)
    modified_file = os.path.join(dir_name, f"{name}_opt{ext}")

    # Copy original to modified
    shutil.copy(original_file, modified_file)

    # Write diff to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.diff', delete=False) as f:
        diff_file = f.name
        f.write(diff)

    try:
        # Apply diff using git apply (stricter than patch)
        result = subprocess.run(
            ['git', 'apply', '--verbose', diff_file],
            cwd=dir_name if dir_name else '.',
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            print(f"⚠️  Git apply failed: {result.stderr}")
            return None

        print(f"✅ Applied diff to {modified_file}")
        return modified_file

    finally:
        os.unlink(diff_file)


def strip_thinking_tokens(text: str) -> str:
    """Remove <think>...</think> blocks from output."""
    import re
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()


def run_experiment(file_path: str):
    """Run the vectorization experiment on a file."""

    # Read the file
    with open(file_path, 'r') as f:
        code = f.read()

    # Generate prompt
    prompt = engineer_prompt(code)

    # Call LLM
    print(f"Calling Qwen3 on {file_path}...")
    response = client.chat.completions.create(
        model="Qwen/Qwen3-8B",
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    # Get raw output
    raw_output = response.choices[0].message.content

    # Log full output (with thinking tokens)
    log_file = f"{os.path.basename(file_path)}_llm_output.log"
    with open(log_file, 'w') as f:
        f.write(raw_output)
    print(f"📝 Logged full output to: {log_file}")

    # Strip thinking tokens to get just the diff
    diff = strip_thinking_tokens(raw_output)
    print(f"\nDiff:\n{diff}\n")

    # Check if no changes needed
    if "NO_CHANGES_NEEDED" in diff:
        print("No changes needed.")
        return

    # Apply diff to copy
    modified_file = apply_diff(file_path, diff)

    if modified_file:
        print(f"✅ Modified file saved to: {modified_file}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python harness.py <file_path>")
        sys.exit(1)

    file_path = sys.argv[1]

    if not os.path.exists(file_path):
        print(f"Error: File not found: {file_path}")
        sys.exit(1)

    run_experiment(file_path)

