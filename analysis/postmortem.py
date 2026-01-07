#!/usr/bin/env python3
"""
Generate a diff between two versions of a C benchmark and create a table
of changes made to each function.

Usage:
    python postmortem.py <file1.c> <file2.c> [--output output.csv]
"""

import argparse
import csv
import difflib
import os
import re
import sys
from typing import Dict, List, Tuple, Optional
from langchain_openai import ChatOpenAI


def extract_functions(c_code: str, filename: str) -> Dict[str, str]:
    """
    Extract function definitions from C code.
    Returns a dict mapping function names to their full source code.
    """
    functions = {}

    # Pattern to match function definitions
    # This is a simplified pattern that should work for most C functions
    # Matches: return_type function_name(...) { ... }
    pattern = r'(?:^|\n)([a-zA-Z_][a-zA-Z0-9_*\s]+\s+)([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^)]*\)\s*\{[^}]*\}'

    # Use a more robust approach: find all top-level function definitions
    # First, remove comments
    code_no_comments = remove_c_comments(c_code)

    # Split into lines for better parsing
    lines = code_no_comments.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Skip empty lines, preprocessor directives, and struct/enum/typedef
        if (not line or
            line.startswith('#') or
            line.startswith('typedef') or
            line.startswith('struct') or
            line.startswith('enum') or
            line.startswith('//') or
            line.startswith('/*')):
            i += 1
            continue

        # Check if this looks like a function definition
        # Look for pattern: type name(...) with opening brace
        if '(' in line and not line.endswith(';'):
            # Try to find the complete function signature
            func_start = i
            func_sig = line

            # Keep reading until we find the opening brace
            while i < len(lines) and '{' not in func_sig:
                i += 1
                if i < len(lines):
                    func_sig += ' ' + lines[i].strip()

            if '{' in func_sig:
                # Extract function name
                # Remove everything after the opening brace for name extraction
                sig_before_brace = func_sig.split('{')[0]

                # Find the function name (word before the first '(')
                match = re.search(r'([a-zA-Z_][a-zA-Z0-9_]*)\s*\(', sig_before_brace)
                if match:
                    func_name = match.group(1)

                    # Now extract the full function body
                    brace_count = 1
                    func_lines = [lines[j] for j in range(func_start, i + 1)]
                    i += 1

                    while i < len(lines) and brace_count > 0:
                        func_lines.append(lines[i])
                        brace_count += lines[i].count('{') - lines[i].count('}')
                        i += 1

                    func_code = '\n'.join(func_lines)
                    functions[func_name] = func_code
                    continue

        i += 1

    return functions


def remove_c_comments(code: str) -> str:
    """Remove C-style comments from code."""
    # Remove single-line comments
    code = re.sub(r'//.*?$', '', code, flags=re.MULTILINE)
    # Remove multi-line comments
    code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
    return code


def generate_function_diff(func1: Optional[str], func2: Optional[str], func_name: str) -> str:
    """Generate a unified diff for a function."""
    if func1 is None:
        return f"[NEW FUNCTION]\n{func2}"
    if func2 is None:
        return f"[DELETED FUNCTION]\n{func1}"

    diff = difflib.unified_diff(
        func1.splitlines(keepends=True),
        func2.splitlines(keepends=True),
        fromfile=f'{func_name} (version 1)',
        tofile=f'{func_name} (version 2)',
        lineterm=''
    )

    return ''.join(diff)


def analyze_changes_with_ai(func_name: str, diff: str, llm: ChatOpenAI) -> str:
    """
    Use local LLM to analyze the changes and provide a concise explanation.
    """
    prompt = f"""Analyze the following diff for the function '{func_name}' and provide a concise,
technical summary of what changed. Focus on the key modifications, not line-by-line details.
Keep your response to 1-2 sentences maximum.

Diff:
{diff}

Summary:"""

    try:
        response = llm.invoke(prompt)
        content = response.content.strip()

        # Remove thinking tags if present
        content = re.sub(r'<think>.*?</think>\s*', '', content, flags=re.DOTALL)

        return content.strip()
    except Exception as e:
        return f"Error analyzing: {str(e)}"


def main():
    parser = argparse.ArgumentParser(
        description='Generate diff and AI analysis of changes between two C benchmark versions'
    )
    parser.add_argument('file1', help='Path to first C file')
    parser.add_argument('file2', help='Path to second C file')
    parser.add_argument('--output', '-o', default='function_changes.csv',
                        help='Output CSV file path (default: function_changes.csv)')
    parser.add_argument('--model', default='Qwen/Qwen3-8B',
                        help='Model name (default: Qwen/Qwen3-8B)')
    parser.add_argument('--base-url', default='http://localhost:8000/v1',
                        help='Base URL for the LLM API (default: http://localhost:8000/v1)')

    args = parser.parse_args()

    # Initialize LLM
    llm = ChatOpenAI(
        model=args.model,
        api_key="",
        base_url=args.base_url,
    )

    # Read the C files
    try:
        with open(args.file1, 'r') as f:
            code1 = f.read()
    except Exception as e:
        print(f"Error reading {args.file1}: {e}", file=sys.stderr)
        return 1

    try:
        with open(args.file2, 'r') as f:
            code2 = f.read()
    except Exception as e:
        print(f"Error reading {args.file2}: {e}", file=sys.stderr)
        return 1

    print(f"Extracting functions from {args.file1}...")
    functions1 = extract_functions(code1, args.file1)
    print(f"Found {len(functions1)} functions in {args.file1}")

    print(f"Extracting functions from {args.file2}...")
    functions2 = extract_functions(code2, args.file2)
    print(f"Found {len(functions2)} functions in {args.file2}")

    # Find all unique function names
    all_functions = set(functions1.keys()) | set(functions2.keys())
    print(f"\nTotal unique functions: {len(all_functions)}")

    # Generate diffs and analyze changes
    results = []

    for func_name in sorted(all_functions):
        func1 = functions1.get(func_name)
        func2 = functions2.get(func_name)

        # Skip if function is identical
        if func1 == func2:
            print(f"  {func_name}: No changes")
            continue

        print(f"  {func_name}: Analyzing changes...")

        diff = generate_function_diff(func1, func2, func_name)

        if not diff.strip():
            continue

        # Analyze with AI
        explanation = analyze_changes_with_ai(func_name, diff, llm)

        results.append({
            'func_name': func_name,
            'explanation': explanation
        })

    # Write results to CSV
    print(f"\nWriting results to {args.output}...")
    with open(args.output, 'w', newline='') as csvfile:
        fieldnames = ['func_name', 'explanation']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        writer.writeheader()
        for result in results:
            writer.writerow(result)

    print(f"Done! Analyzed {len(results)} changed functions.")
    print(f"Results saved to {args.output}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
