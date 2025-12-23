#!/usr/bin/env python3
"""
Batch test script for vectorization experiments.

Tests all s*.cpp files in TSVC_2/src/:
1. Runs harness.py to generate optimized version
2. Compiles the optimized version
3. Reports statistics on success/failure
"""

import os
import sys
import subprocess
import glob
from pathlib import Path

# Import from harness
sys.path.insert(0, os.path.dirname(__file__))
import harness


class TestResult:
    def __init__(self, file_name):
        self.file_name = file_name
        self.llm_success = False
        self.compile_success = False
        self.llm_error = None
        self.compile_error = None


def compile_file(cpp_file: str) -> tuple[bool, str]:
    """
    Compile a C++ file using the TSVC_2 Makefile.

    Args:
        cpp_file: Path to _opt.cpp file (in src/ directory)

    Returns:
        (success, error_message)
    """
    # Extract base name and create .o target name
    # e.g., src/s1113_opt.cpp -> s1113_opt.o
    base_name = os.path.basename(cpp_file)
    name_no_ext = os.path.splitext(base_name)[0]
    obj_target = f"{name_no_ext}.o"

    # Change to TSVC_2 directory and run make
    tsvc_dir = "TSVC_2"

    try:
        result = subprocess.run(
            ["make", "-f", "Makefile.loops", obj_target],
            cwd=tsvc_dir,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            return True, None
        else:
            return False, result.stderr

    except subprocess.TimeoutExpired:
        return False, "Compilation timeout (30s)"
    except Exception as e:
        return False, str(e)


def run_single_test(cpp_file: str) -> TestResult:
    """
    Run test on a single file.

    Args:
        cpp_file: Path to source file

    Returns:
        TestResult object
    """
    file_name = os.path.basename(cpp_file)
    result = TestResult(file_name)

    print(f"\n{'='*70}")
    print(f"Testing: {file_name}")
    print(f"{'='*70}")

    # Step 1: Run harness to generate optimized version
    print(f"[1/2] Running LLM optimization...")
    try:
        harness.run_experiment(cpp_file)

        # Check if opt file was created
        base_name = os.path.basename(cpp_file)
        dir_name = os.path.dirname(cpp_file)
        name, ext = os.path.splitext(base_name)
        opt_file = os.path.join(dir_name, f"{name}_opt{ext}")

        if os.path.exists(opt_file):
            result.llm_success = True
            print(f"      ✅ LLM optimization succeeded")
        else:
            result.llm_success = False
            result.llm_error = "No output file generated"
            print(f"      ❌ LLM optimization failed: No output file generated")
            return result

    except Exception as e:
        result.llm_success = False
        result.llm_error = str(e)
        print(f"      ❌ LLM optimization failed: {e}")
        return result

    # Step 2: Compile the optimized version
    print(f"[2/2] Compiling optimized version...")
    success, error = compile_file(opt_file)

    if success:
        result.compile_success = True
        print(f"      ✅ Compilation succeeded")
    else:
        result.compile_success = False
        result.compile_error = error
        print(f"      ❌ Compilation failed")
        if error:
            print(f"      Error: {error[:200]}")

    return result


def print_summary(results: list[TestResult]):
    """Print summary statistics."""

    total = len(results)
    llm_success = sum(1 for r in results if r.llm_success)
    llm_failed = total - llm_success

    compile_success = sum(1 for r in results if r.llm_success and r.compile_success)
    compile_failed = sum(1 for r in results if r.llm_success and not r.compile_success)

    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"Total files tested: {total}")
    print(f"\nLLM Output:")
    print(f"  ✅ Valid output:   {llm_success:3d} ({llm_success*100//total if total > 0 else 0}%)")
    print(f"  ❌ Invalid output: {llm_failed:3d} ({llm_failed*100//total if total > 0 else 0}%)")

    if llm_success > 0:
        print(f"\nCompilation (of valid LLM outputs):")
        print(f"  ✅ Compiled:       {compile_success:3d} ({compile_success*100//llm_success}%)")
        print(f"  ❌ Failed:         {compile_failed:3d} ({compile_failed*100//llm_success}%)")

    print(f"\nOverall Success Rate:")
    overall_success = compile_success
    print(f"  {overall_success}/{total} files ({overall_success*100//total if total > 0 else 0}%) fully succeeded (valid LLM + compiled)")

    # Show failures
    if llm_failed > 0:
        print(f"\n{'='*70}")
        print("LLM FAILURES:")
        print(f"{'='*70}")
        for r in results:
            if not r.llm_success:
                print(f"  ❌ {r.file_name}")
                if r.llm_error:
                    print(f"     {r.llm_error[:100]}")

    if compile_failed > 0:
        print(f"\n{'='*70}")
        print("COMPILATION FAILURES:")
        print(f"{'='*70}")
        for r in results:
            if r.llm_success and not r.compile_success:
                print(f"  ❌ {r.file_name}")
                if r.compile_error:
                    print(f"     {r.compile_error[:100]}")


def main():
    """Main entry point."""

    # Find all s*.cpp files (but exclude _opt.cpp files)
    src_dir = "TSVC_2/src"
    pattern = os.path.join(src_dir, "s*.cpp")
    all_files = sorted(glob.glob(pattern))

    # Filter out _opt.cpp files to avoid reprocessing optimized versions
    cpp_files = [f for f in all_files if not f.endswith("_opt.cpp")]

    if not cpp_files:
        print(f"Error: No s*.cpp files found in {src_dir}")
        sys.exit(1)

    print(f"Found {len(cpp_files)} files to test")

    # Optional: limit to first N files for quick testing
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
            cpp_files = cpp_files[:limit]
            print(f"Limiting to first {limit} files")
        except ValueError:
            pass

    # Run tests
    results = []
    for cpp_file in cpp_files:
        result = run_single_test(cpp_file)
        results.append(result)

    # Print summary
    print_summary(results)


if __name__ == "__main__":
    main()
