#!/usr/bin/env python3
"""
Validation script for TSVC function behavior equivalence.

This script receives a JSON file containing VectorizationState and validates
that the modified function produces the same checksum as the original.

Usage:
    python validate_function_behavior.py <state_json_path>

Exit codes:
    0: Checksums match (behavior preserved)
    1: Checksums differ (behavior changed)
    2: Build or execution failed
"""

import sys
import json
import os
import shutil
import subprocess
import re
from pathlib import Path


def load_state(json_path):
    """Load and parse VectorizationState from JSON file."""
    with open(json_path, 'r') as f:
        state = json.load(f)
    return state


def extract_function_name(state):
    """Extract the function name from VectorizationState."""
    # Get function name from the first draft (iteration 0)
    function_drafts = state['function_drafts']
    first_draft = function_drafts['0']
    function_name = first_draft['modified_function_text']['name']
    return function_name


def modify_main_function(tsvc_path, function_name):
    """
    Modify main() in tsvc.c to only call the target function.
    Comments out all other time_function() calls.

    Args:
        tsvc_path: Path to tsvc.c file
        function_name: Name of the function to keep (e.g., 's000')
    """
    with open(tsvc_path, 'r') as f:
        lines = f.readlines()

    # Find main() function
    main_start = None
    for i, line in enumerate(lines):
        if 'int main(' in line:
            main_start = i
            break

    if main_start is None:
        raise RuntimeError("Could not find main() function in tsvc.c")

    # Process lines from main() onwards
    modified_lines = lines[:main_start]
    in_main = False

    for i in range(main_start, len(lines)):
        line = lines[i]

        # Check if we're entering main
        if 'int main(' in line:
            in_main = True
            modified_lines.append(line)
            continue

        # Check if we're exiting main
        if in_main and line.strip().startswith('return EXIT_SUCCESS'):
            modified_lines.append(line)
            in_main = False
            continue

        # If we're in main and this is a time_function call
        if in_main and 'time_function(' in line:
            # Check if this line calls our target function
            # Pattern: time_function(&function_name, ...)
            if f'time_function(&{function_name},' in line or f'time_function(&{function_name}, ' in line:
                # Keep this line
                modified_lines.append(line)
            else:
                # Comment out this line
                modified_lines.append('    // ' + line.lstrip())
        else:
            modified_lines.append(line)

    # Write modified file
    with open(tsvc_path, 'w') as f:
        f.writelines(modified_lines)


def build_tsvc(directory, make_target=''):
    """
    Build TSVC in the given directory.

    Args:
        directory: Path to TSVC directory
        make_target: Optional make target (e.g., 'clean')

    Returns:
        True if build succeeded, False otherwise
    """
    cwd = os.getcwd()
    try:
        os.chdir(directory)

        # Run make clean first
        result = subprocess.run(
            ['make', 'clean'],
            capture_output=True,
            text=True
        )

        # Run make
        result = subprocess.run(
            ['make'],
            capture_output=True,
            text=True,
            timeout=120
        )

        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print("Build timed out", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Build failed: {e}", file=sys.stderr)
        return False
    finally:
        os.chdir(cwd)


def run_and_extract_checksum(executable_path, function_name):
    """
    Run TSVC executable and extract checksum for the target function.

    Args:
        executable_path: Path to tsvc executable
        function_name: Name of the function to extract checksum for

    Returns:
        Checksum value as float, or None if not found
    """
    try:
        result = subprocess.run(
            [executable_path],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            print(f"Execution failed with code {result.returncode}", file=sys.stderr)
            print(f"stderr: {result.stderr}", file=sys.stderr)
            return None

        # Parse output to find the checksum for our function
        # Format: "s000      1.150  512066944.000000"
        # We need to extract the checksum (last column) for the matching function
        for line in result.stdout.split('\n'):
            # Match lines that start with the function name (with possible whitespace)
            if line.strip().startswith(function_name):
                # Split by whitespace and get the last column (checksum)
                parts = line.split()
                if len(parts) >= 3:
                    try:
                        checksum = float(parts[-1])
                        return checksum
                    except ValueError:
                        continue

        print(f"Could not find checksum for function {function_name} in output", file=sys.stderr)
        print(f"Output:\n{result.stdout}", file=sys.stderr)
        return None

    except subprocess.TimeoutExpired:
        print("Execution timed out", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Execution failed: {e}", file=sys.stderr)
        return None


def compare_checksums(baseline, modified, tolerance=1e-6):
    """
    Compare two checksums with floating-point tolerance.

    Args:
        baseline: Baseline checksum
        modified: Modified checksum
        tolerance: Absolute tolerance for comparison

    Returns:
        True if checksums match within tolerance
    """
    if baseline is None or modified is None:
        return False

    diff = abs(baseline - modified)
    return diff <= tolerance


def main():
    if len(sys.argv) != 2:
        print("Usage: validate_function_behavior.py <state_json_path>", file=sys.stderr)
        sys.exit(2)

    json_path = sys.argv[1]

    # Load state
    try:
        state = load_state(json_path)
    except Exception as e:
        print(f"Failed to load state: {e}", file=sys.stderr)
        sys.exit(2)

    # Extract info from state
    current_iteration = state['current_iteration']
    bench_path = state['bench_path']
    file_path = state['file_path']
    function_name = extract_function_name(state)

    print(f"Validating function: {function_name} at iteration {current_iteration}")

    # Paths
    cwd = os.getcwd()
    baseline_dir = os.path.join(cwd, 'TSVC_2_baseline')
    test_dir = os.path.join(cwd, 'TSVC_2_test')

    # Determine which executable to use (prefer relaxed, fallback to default)
    exec_name = 'tsvc_vec_relaxed'

    # Step 1: Create baseline (only at iteration 0)
    if current_iteration == 0:
        print("Creating baseline (iteration 0)...")

        # Remove old baseline if it exists
        if os.path.exists(baseline_dir):
            shutil.rmtree(baseline_dir)

        # Copy original TSVC_2 to baseline
        # The bench_path is TSVC_2_opt, so we need to go back to TSVC_2
        original_tsvc = bench_path.replace('_opt', '')
        if not os.path.exists(original_tsvc):
            print(f"Original TSVC_2 not found at {original_tsvc}", file=sys.stderr)
            sys.exit(2)

        shutil.copytree(original_tsvc, baseline_dir)

        # Modify main() to only test our function
        baseline_tsvc_c = os.path.join(baseline_dir, 'src', 'tsvc.c')
        modify_main_function(baseline_tsvc_c, function_name)

        # Build baseline
        print("Building baseline...")
        if not build_tsvc(baseline_dir):
            print("Failed to build baseline", file=sys.stderr)
            sys.exit(2)

        # Run baseline to get checksum
        baseline_exec = os.path.join(baseline_dir, 'bin', 'GNU', exec_name)
        if not os.path.exists(baseline_exec):
            # Fallback to default
            exec_name = 'tsvc_vec_default'
            baseline_exec = os.path.join(baseline_dir, 'bin', 'GNU', exec_name)

        baseline_checksum = run_and_extract_checksum(baseline_exec, function_name)
        if baseline_checksum is None:
            print("Failed to get baseline checksum", file=sys.stderr)
            sys.exit(2)

        print(f"Baseline checksum: {baseline_checksum}")

        # Save baseline checksum to a file for future iterations
        with open(os.path.join(cwd, f'.baseline_checksum_{function_name}'), 'w') as f:
            f.write(str(baseline_checksum))
    else:
        # Load baseline checksum from file
        baseline_checksum_file = os.path.join(cwd, f'.baseline_checksum_{function_name}')
        if not os.path.exists(baseline_checksum_file):
            print(f"Baseline checksum file not found: {baseline_checksum_file}", file=sys.stderr)
            print("This should have been created at iteration 0", file=sys.stderr)
            sys.exit(2)

        with open(baseline_checksum_file, 'r') as f:
            baseline_checksum = float(f.read().strip())

        print(f"Loaded baseline checksum: {baseline_checksum}")

    # Step 2: Create test directory with modified code
    print("Creating test directory...")

    # Remove old test dir if it exists
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)

    # Copy baseline to test dir
    shutil.copytree(baseline_dir, test_dir)

    # Copy the modified tsvc.c from bench_path to test_dir
    modified_tsvc_c = file_path  # This is the path in bench_path
    test_tsvc_c = os.path.join(test_dir, 'src', 'tsvc.c')
    shutil.copy(modified_tsvc_c, test_tsvc_c)

    # Re-apply main() modification (in case the modified file changed main)
    modify_main_function(test_tsvc_c, function_name)

    # Build test
    print("Building test...")
    if not build_tsvc(test_dir):
        print("Failed to build test", file=sys.stderr)
        # Clean up before exit
        shutil.rmtree(test_dir)
        sys.exit(2)

    # Run test to get checksum
    test_exec = os.path.join(test_dir, 'bin', 'GNU', exec_name)
    modified_checksum = run_and_extract_checksum(test_exec, function_name)
    if modified_checksum is None:
        print("Failed to get modified checksum", file=sys.stderr)
        # Clean up before exit
        shutil.rmtree(test_dir)
        sys.exit(2)

    print(f"Modified checksum: {modified_checksum}")

    # Compare checksums
    if compare_checksums(baseline_checksum, modified_checksum, tolerance=1e-6):
        print(f"✓ Checksums match! (diff: {abs(baseline_checksum - modified_checksum):.2e})")
        result_code = 0
    else:
        print(f"✗ Checksums differ! (diff: {abs(baseline_checksum - modified_checksum):.2e})")
        print(f"  Baseline: {baseline_checksum}")
        print(f"  Modified: {modified_checksum}")
        result_code = 1

    # Clean up test directory
    print("Cleaning up test directory...")
    shutil.rmtree(test_dir)

    sys.exit(result_code)


if __name__ == '__main__':
    main()
