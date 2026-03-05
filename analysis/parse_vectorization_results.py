#!/usr/bin/env python3
"""
Parse vectorization state_after.json files and output results as CSV.

Uses deterministic path generation instead of filesystem walking for speed on NFS.
"""
import argparse
import json
import csv
import sys
import time
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
        # File doesn't exist or is invalid - this is expected for some paths
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


def generate_paths_from_vec_dir(vec_dir: Path) -> list[str]:
    """
    Generate all possible state_after.json paths for a vec directory.

    Instead of walking the filesystem, we:
    1. List the top-level of vec_dir to get logs directories
    2. List file_tsvc.c/ to get all func_* directories (includes helpers)
    3. Generate the full paths deterministically
    """
    paths = []

    try:
        # List logs directories at top level
        for entry in vec_dir.iterdir():
            if not entry.name.endswith("_logs"):
                continue

            # List func_* directories inside file_tsvc.c/
            file_tsvc_dir = entry / "file_tsvc.c"
            try:
                for func_entry in file_tsvc_dir.iterdir():
                    if not func_entry.name.startswith("func_"):
                        continue
                    # Only include functions starting with s or v
                    func_name = func_entry.name[5:]  # Remove "func_" prefix
                    if not func_name or func_name[0] not in ('s', 'v'):
                        continue

                    # Generate the deterministic path to state_after.json
                    state_path = func_entry / "iteration_1" / "09_finalize" / "state_after.json"
                    paths.append(str(state_path))
            except OSError:
                # file_tsvc.c doesn't exist for this logs dir
                continue

    except OSError as e:
        print(f"Warning: Could not list {vec_dir}: {e}", file=sys.stderr)

    return paths


def main():
    parser = argparse.ArgumentParser(description="Parse vectorization state_after.json files and output results as CSV.")
    parser.add_argument("vec_dir", help="Top-level *_vec directory pattern (e.g., 'TSVC_2_*_vec')")
    args = parser.parse_args()

    base_dir = Path("/pool/akash")

    # --- STEP 1: EXPAND GLOB TO FIND VEC DIRECTORIES ---
    t0 = time.perf_counter()
    print(f"[*] Finding vec directories matching '{args.vec_dir}'...", file=sys.stderr)

    vec_dirs = sorted(base_dir.glob(args.vec_dir))
    t1 = time.perf_counter()
    print(f"[TIMING] glob for vec dirs: {t1 - t0:.3f}s (found {len(vec_dirs)} directories)", file=sys.stderr)

    if not vec_dirs:
        print(f"No directories found matching pattern: {args.vec_dir}", file=sys.stderr)
        sys.exit(1)

    # --- STEP 2: GENERATE PATHS DETERMINISTICALLY ---
    print(f"[*] Generating paths from {len(vec_dirs)} vec directories...", file=sys.stderr)

    json_files_unsorted = []
    for vec_dir in vec_dirs:
        json_files_unsorted.extend(generate_paths_from_vec_dir(vec_dir))

    t2 = time.perf_counter()
    print(f"[TIMING] path generation: {t2 - t1:.3f}s (generated {len(json_files_unsorted)} paths)", file=sys.stderr)

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
