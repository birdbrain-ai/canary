#!/usr/bin/env python3
"""
Parse vectorization logs from *_logs directories and output a CSV
showing the before/after vectorization state for each function.
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Optional


def find_logs_directories(base_path: Path) -> list[Path]:
    """Find all directories ending with _logs."""
    logs_dirs = []
    for item in base_path.iterdir():
        if item.is_dir() and item.name.endswith('_logs'):
            logs_dirs.append(item)
    return sorted(logs_dirs)


def find_function_directories(logs_dir: Path) -> list[Path]:
    """Find all function directories within a logs directory."""
    func_dirs = []
    # Look for file_* directories first
    for file_dir in logs_dir.iterdir():
        if file_dir.is_dir() and file_dir.name.startswith('file_'):
            # Look for func_* directories within
            for func_dir in file_dir.iterdir():
                if func_dir.is_dir() and func_dir.name.startswith('func_'):
                    func_dirs.append(func_dir)
    return sorted(func_dirs)


def get_initial_state(func_dir: Path) -> Optional[dict]:
    """Get the initial state (after first compile of original code) for a function.

    We use state_after.json from the first compile because that tells us whether
    the ORIGINAL code was already vectorized by the compiler.
    """
    # The initial vectorization state is in iteration_0/03_compile_code/state_after.json
    # This shows if the original code was vectorized
    initial_state_path = func_dir / 'iteration_0' / '03_compile_code' / 'state_after.json'
    if initial_state_path.exists():
        try:
            with open(initial_state_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not read {initial_state_path}: {e}", file=sys.stderr)
    return None


def parse_vectorizer_output_log(logs_dir: Path) -> dict[str, dict]:
    """Parse the vectorizer_output.log file and extract final states for all functions.

    Returns a dict mapping function_name -> {
        'vectorization_success': bool,
        'source_file': str,
        'manager_chosen_i': int
    }
    """
    log_path = logs_dir / 'vectorizer_output.log'
    if not log_path.exists():
        return {}

    try:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except IOError:
        return {}

    results = {}

    # Pattern to find function workflow starts
    # 🚀 Starting vectorization workflow for function: <name> in <file>
    start_pattern = re.compile(
        r'🚀 Starting vectorization workflow for function: (\w+) in (\S+)'
    )

    # Pattern to find finalize blocks
    # VectorizationState at finalize (after)
    finalize_pattern = re.compile(
        r'VectorizationState at finalize \(after\)'
    )

    # Pattern to find manager_chosen_i
    manager_pattern = re.compile(
        r'manager_chosen_i\s+\|\s+(\d+)'
    )

    # Pattern to find draft entries with vectorization_success
    # [0] func_name
    #     vectorization_success    : True/False
    draft_header_pattern = re.compile(
        r'\[(\d+)\]\s+(\w+)'
    )
    vec_success_pattern = re.compile(
        r'vectorization_success\s+:\s+(True|False)'
    )

    # Split by function workflow starts
    parts = start_pattern.split(content)

    # parts[0] is before first match, then triples of (func_name, source_file, content)
    i = 1
    while i + 2 < len(parts):
        func_name = parts[i]
        source_file = parts[i + 1]
        func_content = parts[i + 2]
        i += 3

        # Find the last finalize block in this function's content
        finalize_matches = list(finalize_pattern.finditer(func_content))
        if not finalize_matches:
            continue

        # Get content after the last finalize marker
        last_finalize_pos = finalize_matches[-1].end()
        finalize_content = func_content[last_finalize_pos:]

        # Find next block boundary (next === line or end)
        next_block = finalize_content.find('\n===')
        if next_block != -1:
            finalize_content = finalize_content[:next_block]

        # Extract manager_chosen_i
        manager_match = manager_pattern.search(finalize_content)
        manager_chosen_i = int(manager_match.group(1)) if manager_match else 0

        # Parse drafts to find the vectorization_success of the chosen draft
        # Find all draft headers and their vectorization status
        drafts = {}
        lines = finalize_content.split('\n')
        current_draft_idx = None

        for line in lines:
            draft_match = draft_header_pattern.search(line)
            if draft_match:
                current_draft_idx = int(draft_match.group(1))
                drafts[current_draft_idx] = {'name': draft_match.group(2)}
            elif current_draft_idx is not None:
                vec_match = vec_success_pattern.search(line)
                if vec_match:
                    drafts[current_draft_idx]['vectorization_success'] = (
                        vec_match.group(1) == 'True'
                    )

        # Get vectorization_success for the chosen draft
        vectorization_success = None
        if manager_chosen_i in drafts:
            vectorization_success = drafts[manager_chosen_i].get('vectorization_success')

        results[func_name] = {
            'vectorization_success': vectorization_success,
            'source_file': source_file,
            'manager_chosen_i': manager_chosen_i,
        }

    return results


def extract_vectorization_info(state: dict) -> tuple[Optional[bool], Optional[str]]:
    """
    Extract vectorization success info from state.
    Returns (vectorization_success, function_name).
    """
    if not state or 'function_drafts' not in state:
        return None, None

    function_drafts = state.get('function_drafts', {})
    if not function_drafts:
        return None, None

    # Get the first draft to extract function name
    first_draft = function_drafts.get('0', {})
    func_text = first_draft.get('modified_function_text', {})
    func_name = func_text.get('name', None)

    # Check vectorization_success of the first draft (initial state)
    vectorization_success = first_draft.get('vectorization_success', None)

    return vectorization_success, func_name


def extract_final_vectorization_info(state: dict) -> tuple[Optional[bool], Optional[str], Optional[int]]:
    """
    Extract final vectorization success info from state.
    Returns (best_vectorization_success, function_name, manager_chosen_index).
    """
    if not state or 'function_drafts' not in state:
        return None, None, None

    function_drafts = state.get('function_drafts', {})
    if not function_drafts:
        return None, None, None

    # Get manager's chosen index
    manager_chosen_i = state.get('manager_chosen_i', 0)

    # Get the chosen draft
    chosen_draft = function_drafts.get(str(manager_chosen_i), {})
    func_text = chosen_draft.get('modified_function_text', {})
    func_name = func_text.get('name', None)

    # Check if the chosen draft is vectorized successfully
    vectorization_success = chosen_draft.get('vectorization_success', None)

    # Also check if any draft was successfully vectorized
    any_vectorized = any(
        draft.get('vectorization_success', False)
        for draft in function_drafts.values()
    )

    return vectorization_success, func_name, manager_chosen_i


def process_logs_directory(logs_dir: Path) -> list[dict]:
    """Process a single logs directory and return function data."""
    results = []

    # Get the benchmark name from the logs directory name (remove _logs suffix)
    benchmark_name = logs_dir.name.rsplit('_logs', 1)[0]

    # Parse the vectorizer_output.log file for final states
    final_states_from_log = parse_vectorizer_output_log(logs_dir)

    func_dirs = find_function_directories(logs_dir)

    for func_dir in func_dirs:
        # Extract function name from directory name
        func_dir_name = func_dir.name
        func_name = func_dir_name.replace('func_', '')
        source_file = func_dir.parent.name.replace('file_', '')  # e.g., "tsvc.c"

        # Get initial state from JSON (iteration_0/03_compile_code/state_after.json)
        initial_state = get_initial_state(func_dir)
        before_vec, func_name_from_json = extract_vectorization_info(initial_state)

        # Use function name from JSON if available
        if func_name_from_json:
            func_name = func_name_from_json

        # Get final state from vectorizer_output.log
        after_vec = None
        if func_name in final_states_from_log:
            after_vec = final_states_from_log[func_name].get('vectorization_success')

        results.append({
            'benchmark': benchmark_name,
            'source_file': source_file,
            'function_name': func_name,
            'vectorized_before': before_vec,
            'vectorized_after': after_vec,
            'logs_directory': str(logs_dir),
        })

    return results


def main():
    parser = argparse.ArgumentParser(
        description='Parse vectorization logs and output CSV with before/after vectorization states.'
    )
    parser.add_argument(
        'input_path',
        type=Path,
        help='Path to directory containing *_logs directories'
    )
    parser.add_argument(
        '-o', '--output',
        type=Path,
        default=Path('vectorization_results.csv'),
        help='Output CSV file path (default: vectorization_results.csv)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Print verbose progress information'
    )

    args = parser.parse_args()

    if not args.input_path.exists():
        print(f"Error: Input path does not exist: {args.input_path}", file=sys.stderr)
        sys.exit(1)

    if not args.input_path.is_dir():
        print(f"Error: Input path is not a directory: {args.input_path}", file=sys.stderr)
        sys.exit(1)

    # Find all logs directories
    logs_dirs = find_logs_directories(args.input_path)

    if not logs_dirs:
        print(f"Warning: No *_logs directories found in {args.input_path}", file=sys.stderr)
        sys.exit(0)

    if args.verbose:
        print(f"Found {len(logs_dirs)} logs directories", file=sys.stderr)

    # Process all logs directories
    all_results = []
    for logs_dir in logs_dirs:
        if args.verbose:
            print(f"Processing: {logs_dir.name}", file=sys.stderr)
        results = process_logs_directory(logs_dir)
        all_results.extend(results)

    if not all_results:
        print("Warning: No function data found", file=sys.stderr)
        sys.exit(0)

    # Write CSV output
    fieldnames = [
        'benchmark',
        'source_file',
        'function_name',
        'vectorized_before',
        'vectorized_after',
        'logs_directory',
    ]

    with open(args.output, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_results)

    if args.verbose:
        print(f"Wrote {len(all_results)} rows to {args.output}", file=sys.stderr)

    # Print summary
    before_true = sum(1 for r in all_results if r['vectorized_before'] is True)
    before_false = sum(1 for r in all_results if r['vectorized_before'] is False)
    after_true = sum(1 for r in all_results if r['vectorized_after'] is True)
    after_false = sum(1 for r in all_results if r['vectorized_after'] is False)

    newly_vectorized = sum(
        1 for r in all_results
        if r['vectorized_before'] is False and r['vectorized_after'] is True
    )

    print(f"\nSummary:")
    print(f"  Total functions: {len(all_results)}")
    print(f"  Vectorized before: {before_true} ({100*before_true/len(all_results):.1f}%)")
    print(f"  Vectorized after: {after_true} ({100*after_true/len(all_results):.1f}%)")
    print(f"  Newly vectorized: {newly_vectorized} ({100*newly_vectorized/len(all_results):.1f}%)")
    print(f"\nOutput written to: {args.output}")


if __name__ == '__main__':
    main()
