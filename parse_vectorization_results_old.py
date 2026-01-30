#!/usr/bin/env python3
"""
Parse vectorization state_after.json files and output results as CSV.
"""

import argparse
import json
import csv
import sys
import time
from pathlib import Path


def parse_state_file(json_path: Path) -> dict | None:
    """Parse a state_after.json file and extract draft information."""
    try:
        with open(json_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Warning: Could not parse {json_path}: {e}", file=sys.stderr)
        return None

    function_drafts = data.get("function_drafts", {})

    # Extract path components for identification
    # Path format: ~/tank/*_vec/*_attempt_*_logs/file_tsvc.c/func_*/iteration_1/09_finalize/state_after.json
    parts = json_path.parts

    # Find the _vec directory and logs directory
    vec_dir = None
    logs_dir = None
    func_name = None

    for i, part in enumerate(parts):
        if part.endswith("_vec"):
            vec_dir = part
        if part.endswith("_logs"):
            logs_dir = part
        if part.startswith("func_"):
            func_name = part.replace("func_", "")

    if not all([vec_dir, logs_dir, func_name]):
        print(f"Warning: Could not parse path components from {json_path}", file=sys.stderr)
        return None

    # Parse experiment info from vec_dir (e.g., TSVC_2_clang_no_remarks_vec)
    experiment = vec_dir.replace("_vec", "")

    # Parse attempt info from logs_dir (e.g., TSVC_2_clang_no_remarks_s222_attempt_02_logs)
    # Extract the attempt number and function from logs_dir
    logs_base = logs_dir.replace("_logs", "")
    # Find attempt number
    attempt_num = None
    if "_attempt_" in logs_base:
        attempt_part = logs_base.split("_attempt_")[-1]
        attempt_num = attempt_part.split("_")[0]

    result = {
        "experiment": experiment,
        "logs_dir": logs_base,
        "function": func_name,
        "attempt": attempt_num,
    }

    # Extract draft 0 info
    draft_0 = function_drafts.get("0", {})
    result["draft_0_compile_success"] = draft_0.get("compile_success", "")
    result["draft_0_run_success"] = draft_0.get("run_success", "")
    result["draft_0_vectorization_success"] = draft_0.get("vectorization_success", "")
    result["draft_0_runtime_s"] = draft_0.get("runtime_s", "")

    # Extract draft 1 info
    draft_1 = function_drafts.get("1", {})
    result["draft_1_compile_success"] = draft_1.get("compile_success", "")
    result["draft_1_run_success"] = draft_1.get("run_success", "")
    result["draft_1_vectorization_success"] = draft_1.get("vectorization_success", "")
    result["draft_1_runtime_s"] = draft_1.get("runtime_s", "")

    return result


def main():
    parser = argparse.ArgumentParser(description="Parse vectorization state_after.json files and output results as CSV.")
    parser.add_argument("vec_dir", help="Top-level *_vec directory pattern (e.g., 'temp_0.8_TSVC_2_*0128_afternoon_vec')")
    args = parser.parse_args()

    home = Path.home()
    tank_dir = home / "tank"

    # Find all state_after.json files matching the pattern
    pattern = f"{args.vec_dir}/*_logs/file_tsvc.c/func_[sv]*/iteration_1/09_finalize/state_after.json"
    # print(pattern)

    t0 = time.perf_counter()
    json_files_unsorted = list(tank_dir.glob(pattern))
    t1 = time.perf_counter()
    print(f"[TIMING] glob: {t1 - t0:.3f}s", file=sys.stderr)

    t2 = time.perf_counter()
    json_files = sorted(json_files_unsorted)
    t3 = time.perf_counter()
    print(f"[TIMING] sorting {len(json_files)} files: {t3 - t2:.3f}s", file=sys.stderr)

    # print("DEBUG INFO:")
    # print(json_files)

    if not json_files:
        print("No state_after.json files found matching the pattern.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(json_files)} state files to parse.", file=sys.stderr)

    t4 = time.perf_counter()
    results = []
    for json_path in json_files:
        result = parse_state_file(json_path)
        if result:
            results.append(result)
    t5 = time.perf_counter()
    print(f"[TIMING] parsing {len(json_files)} JSON files: {t5 - t4:.3f}s", file=sys.stderr)

    if not results:
        print("No valid results to output.", file=sys.stderr)
        sys.exit(1)

    # Output CSV
    fieldnames = [
        "experiment",
        "logs_dir",
        "function",
        "attempt",
        "draft_0_compile_success",
        "draft_0_run_success",
        "draft_0_vectorization_success",
        "draft_0_runtime_s",
        "draft_1_compile_success",
        "draft_1_run_success",
        "draft_1_vectorization_success",
        "draft_1_runtime_s",
    ]

    t6 = time.perf_counter()
    writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(results)
    t7 = time.perf_counter()
    print(f"[TIMING] CSV writing: {t7 - t6:.3f}s", file=sys.stderr)

    print(f"[TIMING] total: {t7 - t0:.3f}s", file=sys.stderr)
    print(f"Wrote {len(results)} rows.", file=sys.stderr)


if __name__ == "__main__":
    main()
