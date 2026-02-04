#!/usr/bin/env python3
"""
Creates per-function copies of TSVC benchmark directory.

For each loop function in TSVC:
1. Copies the entire TSVC directory to {base_dir}_{function_name}
2. Removes all benchmark functions except the target function
3. Comments out all time_function calls except the target
"""

import sys
import shutil
import re
import os
from pathlib import Path

# Mapping of benchmark functions to their helper functions
FUNCTION_HELPERS = {
    's151': ['s151s'],
    's152': ['s152s'],
    's471': ['s471s'],
    's31111': ['test'],
    's4121': ['f'],
}


def extract_loop_functions(tsvc_c_path: str) -> list[str]:
    """Parse time_function calls from main() to get the list of benchmark functions."""
    with open(tsvc_c_path, 'r') as f:
        content = f.read()

    # Find all time_function(&function_name, ...) calls
    pattern = r'time_function\s*\(\s*&(\w+)\s*,'
    functions = re.findall(pattern, content)

    return functions


def find_function_boundaries(content: str) -> dict[str, tuple[int, int]]:
    """
    Find start and end line numbers for each benchmark and helper function.
    Returns dict of {function_name: (start_line, end_line)} (1-indexed).
    """
    lines = content.split('\n')
    boundaries = {}

    # Pattern for benchmark function definitions: real_t/void func_name(struct args_t * func_args)
    func_pattern = re.compile(r'^(?:real_t|void)\s+(\w+)\s*\(\s*struct\s+args_t\s*\*')

    # All helper function names from the mapping
    all_helpers = set()
    for helpers in FUNCTION_HELPERS.values():
        all_helpers.update(helpers)

    # Pattern for helper functions (different signatures)
    helper_pattern = re.compile(r'^(?:real_t|void|int)\s+(' + '|'.join(re.escape(h) for h in all_helpers) + r')\s*\(')

    i = 0
    while i < len(lines):
        match = func_pattern.match(lines[i]) or helper_pattern.match(lines[i])
        if match:
            func_name = match.group(1)
            start_line = i + 1  # 1-indexed

            # Find the opening brace
            brace_count = 0
            found_open = False
            j = i
            while j < len(lines):
                for ch in lines[j]:
                    if ch == '{':
                        brace_count += 1
                        found_open = True
                    elif ch == '}':
                        brace_count -= 1

                if found_open and brace_count == 0:
                    end_line = j + 1  # 1-indexed
                    boundaries[func_name] = (start_line, end_line)
                    i = j
                    break
                j += 1
        i += 1

    return boundaries


def filter_tsvc_content(content: str, keep_function: str, all_functions: list[str]) -> str:
    """
    Remove all benchmark functions except keep_function and comment out
    time_function calls except for keep_function.
    """
    lines = content.split('\n')

    # Get boundaries for all functions
    boundaries = find_function_boundaries(content)

    # Functions to keep: the main function + its helpers (if any)
    functions_to_keep = [keep_function] + FUNCTION_HELPERS.get(keep_function, [])

    # Determine which lines to remove (all functions except those to keep)
    lines_to_remove = set()
    for func_name, (start, end) in boundaries.items():
        if func_name not in functions_to_keep:
            # Remove from start to end (inclusive), convert to 0-indexed
            for line_num in range(start - 1, end):
                lines_to_remove.add(line_num)

    # Build new content, skipping removed lines and commenting time_function calls
    new_lines = []
    time_func_pattern = re.compile(r'^(\s*)time_function\s*\(\s*&(\w+)\s*,')

    for i, line in enumerate(lines):
        if i in lines_to_remove:
            new_lines.append('')
            continue

        # Check if this is a time_function call
        match = time_func_pattern.match(line)
        if match:
            indent = match.group(1)
            func_name = match.group(2)
            if func_name != keep_function:
                # Comment out this line
                new_lines.append(f"{indent}// {line.lstrip()}")
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    return '\n'.join(new_lines)


def create_single_function_copy(src_dir: str, dst_dir: str, function_name: str, all_functions: list[str]):
    """Copy TSVC directory and modify tsvc.c for a single function."""
    # Copy the entire directory
    if os.path.exists(dst_dir):
        shutil.rmtree(dst_dir)

    shutil.copytree(src_dir, dst_dir)

    # Modify tsvc.c
    tsvc_c_path = os.path.join(dst_dir, 'src', 'tsvc.c')

    with open(tsvc_c_path, 'r') as f:
        content = f.read()

    new_content = filter_tsvc_content(content, function_name, all_functions)

    with open(tsvc_c_path, 'w') as f:
        f.write(new_content)


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <tsvc_directory>", file=sys.stderr)
        sys.exit(1)

    src_dir = sys.argv[1].rstrip('/')

    if not os.path.isdir(src_dir):
        print(f"Error: {src_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    tsvc_c_path = os.path.join(src_dir, 'src', 'tsvc.c')
    if not os.path.isfile(tsvc_c_path):
        print(f"Error: {tsvc_c_path} not found", file=sys.stderr)
        sys.exit(1)

    # Extract all benchmark function names
    all_functions = extract_loop_functions(tsvc_c_path)
    print(f"Found {len(all_functions)} benchmark functions")

    # Create output directory: {src_dir}_vec/
    output_dir = f"{src_dir}_vec"
    os.makedirs(output_dir, exist_ok=True)
    print(f"Output directory: {output_dir}")

    # Create a copy for each function inside the output directory
    for i, func_name in enumerate(all_functions):
        # Create {src_dir}_vec/{src_dir}_{func_name}/
        dst_dir = os.path.join(output_dir, f"{os.path.basename(src_dir)}_{func_name}")
        print(f"[{i+1}/{len(all_functions)}] Creating {dst_dir}")
        create_single_function_copy(src_dir, dst_dir, func_name, all_functions)

    print(f"Done. Created {len(all_functions)} directories in {output_dir}.")


if __name__ == '__main__':
    main()
