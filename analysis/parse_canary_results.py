#!/usr/bin/env python3
"""
Parse all canary result directories for a given temperature.

Finds matching directories in the results folder, locates their TSVC_2_vec
subdirectories, and outputs a separate CSV for each run into the run's directory.
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from tqdm import tqdm

RESULTS_DIR = Path("/pool/akash/canary/results")

FIELDNAMES = [
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


def parse_state_file(json_path_str: str) -> dict | None:
    json_path = Path(json_path_str)
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return None

    function_drafts = data.get("function_drafts", {})
    parts = json_path.parts

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

    for d in ["0", "1"]:
        draft = function_drafts.get(d, {})
        for key in ["compile_success", "run_success", "vectorization_success", "runtime_s"]:
            result[f"draft_{d}_{key}"] = draft.get(key, "")

    return result


def generate_paths(vec_dir: Path) -> list[str]:
    paths = []
    try:
        for entry in vec_dir.iterdir():
            if not entry.name.endswith("_logs"):
                continue
            file_tsvc_dir = entry / "file_tsvc.c"
            try:
                for func_entry in file_tsvc_dir.iterdir():
                    if not func_entry.name.startswith("func_"):
                        continue
                    func_name = func_entry.name[5:]
                    if not func_name or func_name[0] not in ('s', 'v'):
                        continue
                    state_path = func_entry / "iteration_1" / "09_finalize" / "state_after.json"
                    paths.append(str(state_path))
            except OSError:
                continue
    except OSError as e:
        print(f"Warning: Could not list {vec_dir}: {e}", file=sys.stderr)
    return paths


def find_runs(temperature: float) -> list[tuple[Path, Path, str]]:
    """Returns list of (run_dir, vec_dir, run_name) tuples."""
    runs = []
    for entry in sorted(RESULTS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        metadata_file = entry / "metadata.json"
        if not metadata_file.exists():
            continue
        try:
            with open(metadata_file) as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if meta.get("temperature") == temperature:
            vec_dir = entry / "TSVC_2_vec"
            if vec_dir.is_dir():
                runs.append((entry, vec_dir, meta.get("name", entry.name)))
    return runs


def parse_one_run(run_dir: Path, vec_dir: Path, run_name: str) -> None:
    """Parse a single run and write its CSV into the run directory."""
    paths = sorted(generate_paths(vec_dir))
    if not paths:
        print(f"  No state_after.json files found, skipping.", file=sys.stderr)
        return

    results = []
    with ProcessPoolExecutor() as executor:
        for r in tqdm(
            executor.map(parse_state_file, paths, chunksize=200),
            total=len(paths), desc=f"  {run_name}", unit="file", file=sys.stderr
        ):
            if r:
                results.append(r)

    if not results:
        print(f"  No valid results, skipping.", file=sys.stderr)
        return

    out_path = run_dir / "results.csv"
    with open(out_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(results)

    print(f"  Wrote {len(results)} rows -> {out_path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Parse canary results for a given temperature, outputting a CSV per run."
    )
    parser.add_argument("temperature", type=float, help="Temperature to filter by (e.g. 0.8)")
    args = parser.parse_args()

    t0 = time.perf_counter()

    runs = find_runs(args.temperature)
    if not runs:
        print(f"No result directories found for temperature={args.temperature}", file=sys.stderr)
        sys.exit(1)

    print(f"[*] Found {len(runs)} runs for temperature={args.temperature}:", file=sys.stderr)
    for _, _, name in runs:
        print(f"    - {name}", file=sys.stderr)

    for run_dir, vec_dir, run_name in runs:
        parse_one_run(run_dir, vec_dir, run_name)

    t1 = time.perf_counter()
    print(f"[TIMING] total: {t1 - t0:.3f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
