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
    return f"""Modify this C++ code to make it easier for the clang compiler to autovectorize.

CODE:
{code}

Output a unified diff showing your changes. Use standard diff format:

--- original.cpp
+++ modified.cpp
@@ -line,count +line,count @@
 context line
-removed line
+added line
 context line

If no changes are needed, output: NO_CHANGES_NEEDED
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

