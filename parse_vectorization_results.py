#!/usr/bin/env python3
"""
Parse vectorization state_after.json files and output results as CSV.
"""
import argparse
import json
import csv
import sys
import time
import subprocess
import os
import re
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from tqdm import tqdm


def parse_state_file(json_path_str: str) -> dict | None:
    """Worker function: Parses one JSON file.
    Accepts string path to reduce serialization overhead."""
    json_path = Path(json_path_str)
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Warning: Could not parse {json_path}: {e}", file=sys.stderr)
        return None

    function_drafts = data.get("function_drafts", {})
    parts = json_path.parts

    # Identification: Finding the key markers in the path
    vec_dir = next((p for p in parts if p.endswith("_vec")), "")
    logs_dir = next((p for p in parts if p.endswith("_logs")), "")
    func_name = next((p.replace("func_", "") for p in parts if p.startswith("func_")), "")

    if not all([vec_dir, logs_dir, func_name]):
        print(f"Warning: Could not parse path components from {json_path}", file=sys.stderr)
        return None

    logs_base = logs_dir.replace("_logs", "")
    attempt_num = logs_base.split("_attempt_")[-1].split("_")[0] if "_attempt_" in logs_base else ""

    result = {
        "experiment": vec_dir.replace("_vec", ""),
        "logs_dir": logs_base,
        "function": func_name,
        "attempt": attempt_num,
    }

    # Extract info for Draft 0 and Draft 1
    for d in ["0", "1"]:
        draft = function_drafts.get(d, {})
        for key in ["compile_success", "run_success", "vectorization_success", "runtime_s"]:
            result[f"draft_{d}_{key}"] = draft.get(key, "")

    return result

def main():
    parser = argparse.ArgumentParser(description="Parse vectorization state_after.json files and output results as CSV.")
    parser.add_argument("vec_dir", help="Top-level *_vec directory pattern (e.g., 'temp_0.8_TSVC_2_*0128_afternoon_vec')")
    args = parser.parse_args()

    tank_dir = Path.home() / "tank"
    fd_bin = os.path.expanduser("~/.cargo/bin/fd")

    # --- STEP 1: DISCOVERY (via FD) ---
    t0 = time.perf_counter()
    print(f"[*] Starting discovery in {tank_dir}...", file=sys.stderr)

    # Use fd for fast file discovery with high thread count for NFS latency
    fd_cmd = [
        fd_bin,
        "-j", "512",
        "-p", "-g", "**/iteration_1/09_finalize/state_after.json",
        str(tank_dir),
        "-g", f"**/{args.vec_dir}/**"
    ]

    try:
        proc = subprocess.run(fd_cmd, capture_output=True, text=True, check=True)
        json_files_raw = proc.stdout.splitlines()
    except subprocess.CalledProcessError as e:
        print(f"Error running fd: {e.stderr}", file=sys.stderr)
        sys.exit(1)

    t1 = time.perf_counter()
    print(f"[TIMING] fd discovery: {t1 - t0:.3f}s", file=sys.stderr)

    # Filter to match original glob pattern: *_logs/file_tsvc.c/func_[sv]*/iteration_1/09_finalize/state_after.json
    # This ensures we only process files under file_tsvc.c with func_s* or func_v* directories
    path_filter = re.compile(r'_logs/file_tsvc\.c/func_[sv][^/]*/iteration_1/09_finalize/state_after\.json$')
    json_files_unsorted = [f for f in json_files_raw if path_filter.search(f)]

    t2 = time.perf_counter()
    print(f"[TIMING] filtering {len(json_files_raw)} -> {len(json_files_unsorted)} files: {t2 - t1:.3f}s", file=sys.stderr)

    # Sort for consistent output ordering
    json_files = sorted(json_files_unsorted)
    t3 = time.perf_counter()
    print(f"[TIMING] sorting {len(json_files)} files: {t3 - t2:.3f}s", file=sys.stderr)

    if not json_files:
        print("No state_after.json files found matching the pattern.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(json_files)} state files to parse.", file=sys.stderr)

    # --- STEP 2: PARALLEL PARSING ---
    t4 = time.perf_counter()
    results = []
    # chunksize=200 is key for high-core machines to minimize inter-process communication
    with ProcessPoolExecutor() as executor:
        parsing_iterator = executor.map(parse_state_file, json_files, chunksize=200)

        for r in tqdm(parsing_iterator, total=len(json_files), desc="Parsing", unit="file", file=sys.stderr):
            if r:
                results.append(r)

    t5 = time.perf_counter()
    print(f"[TIMING] parsing {len(json_files)} JSON files: {t5 - t4:.3f}s", file=sys.stderr)

    if not results:
        print("No valid results to output.", file=sys.stderr)
        sys.exit(1)

    # --- STEP 3: OUTPUT ---
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
