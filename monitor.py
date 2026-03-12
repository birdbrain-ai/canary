#!/usr/bin/env python3
"""Live terminal monitor for vectorization experiments."""

import argparse
import curses
import glob
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path


def parse_timestamp(dirname):
    """Extract datetime from experiment folder name (YYYY-MM-DD_HH-MM-SS prefix)."""
    base = os.path.basename(dirname)
    # Format: YYYY-MM-DD_HH-MM-SS_... — first 19 chars
    ts_str = base[:19]
    return datetime.strptime(ts_str, "%Y-%m-%d_%H-%M-%S")


def format_elapsed(seconds):
    """Format seconds into human-readable elapsed time."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m}m {s:02d}s"


def gather_stats(experiment_dir, vec_dir):
    """Collect current experiment statistics."""
    # Count base function dirs (no _attempt_ in name)
    entries = os.listdir(vec_dir)
    num_functions = sum(
        1 for e in entries
        if "_attempt_" not in e
        and os.path.isdir(os.path.join(vec_dir, e))
    )

    # Read num_attempts from metadata
    with open(os.path.join(experiment_dir, "metadata.json")) as f:
        metadata = json.load(f)
    num_attempts = metadata["num_attempts"]
    name = metadata["name"]

    total = num_functions * num_attempts

    # Find finished attempts via completion marker
    pattern = os.path.join(
        vec_dir, "*_logs", "file_tsvc.c", "func_*", "iteration_*",
        "09_finalize", "state_after.json"
    )
    finished_paths = set(glob.glob(pattern))

    finished = len(finished_paths)

    # Elapsed time
    start_time = parse_timestamp(experiment_dir)
    elapsed = (datetime.now() - start_time).total_seconds()

    # Time per attempt
    time_per = elapsed / finished if finished > 0 else 0

    return {
        "name": name,
        "start_time": start_time,
        "elapsed": elapsed,
        "num_functions": num_functions,
        "num_attempts": num_attempts,
        "total": total,
        "finished": finished,
        "time_per": time_per,
        "finished_paths": finished_paths,
    }


def parse_completion(path):
    """Extract (func_name, attempt_number, finish_time) from a finished-attempt path.

    Path looks like: .../s2101_attempt_3_logs/file_tsvc.c/func_s2101/iteration_1/...
    The attempt number lives in the *_logs directory component.
    """
    parts = Path(path).parts
    func_name = None
    attempt = None
    for p in parts:
        if p.startswith("func_"):
            func_name = p[len("func_"):]
        m = re.search(r'_attempt_(\d+)_logs$', p)
        if m:
            attempt = m.group(1)
    finish_time = datetime.fromtimestamp(os.path.getmtime(path))
    return func_name, attempt, finish_time


def draw(stdscr, stats, recent_completions):
    """Draw the monitor display."""
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    w = min(width, 66)

    name = stats["name"]
    elapsed_str = format_elapsed(stats["elapsed"])
    finished = stats["finished"]
    total = stats["total"]
    pct = (finished / total * 100) if total > 0 else 0
    time_per = stats["time_per"]
    start_str = stats["start_time"].strftime("%Y-%m-%d %H:%M")

    # Colors
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_CYAN, -1)

    row = 0

    # Top border
    stdscr.addnstr(row, 0, "═" * w, w, curses.A_BOLD | curses.color_pair(2))
    row += 1

    # Header line
    header = " Experiment Monitor"
    elapsed_label = f"Elapsed: {elapsed_str} "
    pad = w - len(header) - len(elapsed_label)
    if pad < 1:
        pad = 1
    line = header + " " * pad + elapsed_label
    stdscr.addnstr(row, 0, line[:w], w, curses.A_BOLD)
    row += 1

    # Second border
    stdscr.addnstr(row, 0, "═" * w, w, curses.A_BOLD | curses.color_pair(2))
    row += 1

    # Experiment name + start time
    info_line = f" {name} ({start_str})"
    stdscr.addnstr(row, 0, info_line[:w], w)
    row += 1

    # Progress bar
    bar_label = "   Progress: ["
    bar_suffix = f"] {finished} / {total}  ({pct:.1f}%)"
    bar_width = w - len(bar_label) - len(bar_suffix)
    if bar_width < 5:
        bar_width = 5
    filled = int(bar_width * pct / 100)
    empty = bar_width - filled
    bar_str = bar_label + "█" * filled + "░" * empty + bar_suffix

    stdscr.addnstr(row, 0, bar_str[:w], w)
    # Color the filled portion green
    if filled > 0:
        start_col = len(bar_label)
        stdscr.chgat(row, start_col, filled, curses.color_pair(1) | curses.A_BOLD)
    row += 1

    # Time per attempt
    if time_per > 0:
        tpa_line = f"   Time/attempt: {time_per:.1f}s"
        stdscr.addnstr(row, 0, tpa_line[:w], w)
        row += 1

    # ETA
    if finished > 0 and finished < total:
        remaining = (total - finished) * time_per
        eta_str = format_elapsed(remaining)
        eta_line = f"   ETA: {eta_str}"
        stdscr.addnstr(row, 0, eta_line[:w], w)
        row += 1

    # Bottom border
    stdscr.addnstr(row, 0, "─" * w, w, curses.color_pair(2))
    row += 1

    # Recently finished section
    if recent_completions:
        row += 1
        if row < height:
            stdscr.addnstr(row, 0, " Recently finished:", w, curses.A_BOLD)
            row += 1
        max_show = min(len(recent_completions), height - row - 1)
        for func_name, attempt, finish_time in recent_completions[-max_show:]:
            if row >= height - 1:
                break
            ts = finish_time.strftime("%H:%M:%S")
            line = f"   {ts}  {func_name}  attempt #{attempt}"
            stdscr.addnstr(row, 0, line[:w], w, curses.color_pair(1))
            row += 1

    stdscr.refresh()


def main(stdscr, experiment_dir, vec_dir, interval):
    """Main curses loop."""
    curses.curs_set(0)
    stdscr.timeout(interval * 1000)

    prev_paths = set()
    recent_completions = []  # list of (func_name, attempt)
    max_recent = 50

    while True:
        stats = gather_stats(experiment_dir, vec_dir)
        current_paths = stats["finished_paths"]

        # Find newly completed attempts
        new_paths = current_paths - prev_paths
        for p in sorted(new_paths):
            func_name, attempt, finish_time = parse_completion(p)
            if func_name and attempt:
                recent_completions.append((func_name, attempt, finish_time))
        recent_completions = recent_completions[-max_recent:]
        prev_paths = current_paths

        draw(stdscr, stats, recent_completions)

        # Wait for key or timeout
        key = stdscr.getch()
        if key == ord("q"):
            break


def run():
    parser = argparse.ArgumentParser(description="Monitor a vectorization experiment")
    parser.add_argument("experiment_dir", help="Path to the experiment directory")
    parser.add_argument("-i", "--interval", type=int, default=10,
                        help="Refresh interval in seconds (default: 10)")
    args = parser.parse_args()

    experiment_dir = os.path.abspath(args.experiment_dir)
    if not os.path.isdir(experiment_dir):
        print(f"Error: {experiment_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    metadata_path = os.path.join(experiment_dir, "metadata.json")
    if not os.path.isfile(metadata_path):
        print(f"Error: {metadata_path} not found", file=sys.stderr)
        sys.exit(1)

    # Find *_vec/ directory
    vec_dirs = [
        d for d in glob.glob(os.path.join(experiment_dir, "*_vec"))
        if os.path.isdir(d)
    ]
    if not vec_dirs:
        print("Error: no *_vec/ directory found", file=sys.stderr)
        sys.exit(1)
    vec_dir = vec_dirs[0]

    try:
        curses.wrapper(main, experiment_dir, vec_dir, args.interval)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
