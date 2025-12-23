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

Output your changes using SEARCH/REPLACE blocks. Each block shows exactly what text to find and what to replace it with.

FORMAT:
<<<<<<< SEARCH
exact code to find (must match original exactly, including whitespace)
=======
replacement code
>>>>>>> REPLACE

CRITICAL RULES:
1. The SEARCH block must match the original code EXACTLY (character-for-character, including all whitespace and indentation)
2. Include enough context in SEARCH to make the match unique (typically 3-5 lines)
3. The REPLACE block shows the new code (with same indentation as original)
4. You can have multiple SEARCH/REPLACE blocks for multiple changes
5. If no changes needed, output: NO_CHANGES_NEEDED

EXAMPLE 1 - Adding __restrict__ keyword:
<<<<<<< SEARCH
real_t* __restrict__ xx;
real_t* yy;
=======
real_t* __restrict__ xx;
real_t* __restrict__ yy;
>>>>>>> REPLACE

EXAMPLE 2 - Hoisting computation out of loop:
<<<<<<< SEARCH
    for (int nl = 0; nl < 2*iterations; nl++) {{
        for (int i = 0; i < LEN_1D; i++) {{
            a[i] = a[LEN_1D/2] + b[i];
        }}
=======
    for (int nl = 0; nl < 2*iterations; nl++) {{
        real_t temp = a[LEN_1D/2];
        for (int i = 0; i < LEN_1D; i++) {{
            a[i] = temp + b[i];
        }}
>>>>>>> REPLACE

EXAMPLE 3 - Multiple changes (use multiple blocks):
<<<<<<< SEARCH
real_t* yy;
=======
real_t* __restrict__ yy;
>>>>>>> REPLACE

<<<<<<< SEARCH
        a[i] = b[i] * 2.0f;
=======
        a[i] = b[i] * factor;
>>>>>>> REPLACE

COMMON MISTAKES TO AVOID:
- ❌ WRONG: Not matching indentation exactly in SEARCH block
- ❌ WRONG: Including line numbers in SEARCH block
- ❌ WRONG: Not including enough context (making SEARCH ambiguous)
- ✅ RIGHT: Match original exactly, include sufficient context

If no changes are needed, output only: NO_CHANGES_NEEDED
"""


def parse_search_replace_blocks(text: str) -> list[tuple[str, str]]:
    """
    Parse SEARCH/REPLACE blocks from LLM output.

    Returns:
        List of (search, replace) tuples
    """
    import re

    # Pattern to match SEARCH/REPLACE blocks
    pattern = r'<<<<<<< SEARCH\s*\n(.*?)\n=======\s*\n(.*?)\n>>>>>>> REPLACE'

    matches = re.findall(pattern, text, re.DOTALL)

    if not matches:
        print("⚠️  No SEARCH/REPLACE blocks found in output")
        return []

    print(f"📋 Found {len(matches)} SEARCH/REPLACE block(s)")
    return matches


def apply_search_replace(original_file: str, llm_output: str) -> str:
    """
    Apply search/replace blocks to a file.

    Args:
        original_file: Path to original file
        llm_output: LLM output containing SEARCH/REPLACE blocks

    Returns:
        Path to modified file, or None if failed
    """
    # Parse search/replace blocks
    blocks = parse_search_replace_blocks(llm_output)

    if not blocks:
        return None

    # Read original file
    with open(original_file, 'r') as f:
        content = f.read()

    # Apply each search/replace block
    modified_content = content
    for i, (search, replace) in enumerate(blocks, 1):
        print(f"\n📝 Applying block {i}/{len(blocks)}...")
        print(f"   Searching for: {search[:50]}..." if len(search) > 50 else f"   Searching for: {search}")

        # Check if search text exists in content
        if search not in modified_content:
            print(f"   ❌ Search text not found in file!")
            print(f"   Search block was:")
            print(f"   {repr(search)}")
            return None

        # Count occurrences
        count = modified_content.count(search)
        if count > 1:
            print(f"   ⚠️  Warning: Search text appears {count} times in file")
            print(f"   ⚠️  Will replace all occurrences")

        # Apply replacement
        modified_content = modified_content.replace(search, replace)
        print(f"   ✅ Replaced {count} occurrence(s)")

    # Create output filename with _opt suffix
    base_name = os.path.basename(original_file)
    dir_name = os.path.dirname(original_file)
    name, ext = os.path.splitext(base_name)
    modified_file = os.path.join(dir_name, f"{name}_opt{ext}")

    # Write modified content to new file
    with open(modified_file, 'w') as f:
        f.write(modified_content)

    print(f"\n✅ Written modified file to: {modified_file}")
    return modified_file


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

    # Strip thinking tokens
    output = strip_thinking_tokens(raw_output)
    print(f"\nLLM Output (without thinking):\n{output}\n")

    # Check if no changes needed
    if "NO_CHANGES_NEEDED" in output:
        print("ℹ️  No changes needed.")
        return

    # Apply search/replace blocks
    modified_file = apply_search_replace(file_path, output)

    if modified_file:
        print(f"\n✅ Success! Modified file saved to: {modified_file}")
    else:
        print(f"\n❌ Failed to apply changes")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python harness.py <file_path>")
        sys.exit(1)

    file_path = sys.argv[1]

    if not os.path.exists(file_path):
        print(f"Error: File not found: {file_path}")
        sys.exit(1)

    run_experiment(file_path)

