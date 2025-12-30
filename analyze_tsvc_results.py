#!/usr/bin/env python3
"""
Analyze TSVC_2 vectorization results by comparing original vs final states.
"""
import json
import os
from pathlib import Path

def get_original_state(func_dir):
    """Get vectorization_success from iteration_0 compile_code after state."""
    try:
        path = func_dir / "iteration_0" / "03_compile_code" / "state_after.json"
        with open(path) as f:
            data = json.load(f)
        return data['function_drafts']['0']['vectorization_success']
    except (FileNotFoundError, KeyError) as e:
        return None

def get_final_state(func_dir):
    """Get vectorization_success from iteration_3 finalize after state."""
    try:
        path = func_dir / "iteration_3" / "09_finalize" / "state_after.json"
        with open(path) as f:
            data = json.load(f)
        manager_idx = str(data['manager_chosen_i'])
        return data['function_drafts'][manager_idx]['vectorization_success']
    except (FileNotFoundError, KeyError) as e:
        return None

def analyze_tsvc_logs(logs_dir):
    """
    Analyze all function logs in TSVC_2_logs/file_tsvc.c/

    Returns:
        List of dicts with function name, original state, final state
    """
    tsvc_dir = Path(logs_dir) / "file_tsvc.c"
    results = []

    # Iterate through all func_* directories
    for func_dir in sorted(tsvc_dir.glob("func_*")):
        func_name = func_dir.name.replace("func_", "")

        original = get_original_state(func_dir)
        final = get_final_state(func_dir)

        # Skip if we couldn't read either state
        if original is None or final is None:
            continue

        results.append({
            'function': func_name,
            'original': original,
            'final': final,
            'improved': final and not original  # Was False, became True
        })

    return results

def print_table(results):
    """Print results as a formatted table."""
    print("\n" + "="*70)
    print("TSVC Vectorization Results")
    print("="*70)
    print(f"{'Function':<15} {'Original':<12} {'Final':<12} {'Status':<20}")
    print("-"*70)

    for r in results:
        orig_str = "✓ Vectorized" if r['original'] else "✗ Not vectorized"
        final_str = "✓ Vectorized" if r['final'] else "✗ Not vectorized"

        if r['improved']:
            status = "🎉 IMPROVED"
        elif r['original'] and r['final']:
            status = "Already vectorized"
        elif not r['original'] and not r['final']:
            status = "No improvement"
        else:
            status = "REGRESSED"

        print(f"{r['function']:<15} {orig_str:<12} {final_str:<12} {status:<20}")

    print("-"*70)

    # Print summary statistics
    total = len(results)
    improved = sum(1 for r in results if r['improved'])
    already_vec = sum(1 for r in results if r['original'] and r['final'])
    no_improvement = sum(1 for r in results if not r['original'] and not r['final'])
    regressed = sum(1 for r in results if r['original'] and not r['final'])

    print(f"\nSummary:")
    print(f"  Total functions: {total}")
    print(f"  Improved (0→1): {improved}")
    print(f"  Already vectorized: {already_vec}")
    print(f"  No improvement: {no_improvement}")
    print(f"  Regressed (1→0): {regressed}")
    print("="*70 + "\n")

if __name__ == "__main__":
    logs_dir = os.path.expanduser("~/tank/TSVC_2_logs")
    results = analyze_tsvc_logs(logs_dir)
    print_table(results)
