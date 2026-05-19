import concurrent.futures
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

TSVC_DEFAULT = "/pool/akash/canary/benchmarks/canary-test-suite/tsvc"
CONFIG_REL = "configs/clang-default.json"
CONFIG_NAME = "clang-default"


def last_kernel(trial):
    for step in reversed(trial["steps"]):
        body = next(iter(step.values()))
        if isinstance(body, dict) and "kernel" in body:
            return body["kernel"]
    return None


def group_by_kernel(steps_path):
    groups = defaultdict(list)
    with open(steps_path) as f:
        for line in f:
            trial = json.loads(line)
            src = last_kernel(trial)
            if src is None:
                continue
            name = Path(trial["kernel"]).parent.name
            groups[name].append(src)
    return groups


def run_mkexperiment(tsvc_dir, ntrials):
    subprocess.run(
        ["scripts/mkexperiment.sh", "-c", CONFIG_REL, "-n", str(ntrials), "-y"],
        cwd=tsvc_dir,
        check=True,
    )


def latest_experiment(tsvc_dir):
    base = Path(tsvc_dir) / "experiments" / CONFIG_NAME
    return max(base.iterdir(), key=lambda p: p.stat().st_mtime)


def seed_trials(exp_dir, groups, ntrials):
    width = len(str(ntrials))
    written = []
    for name, sources in groups.items():
        for i, src in enumerate(sources, start=1):
            trial_dir = exp_dir / name / f"{i:0{width}d}"
            (trial_dir / "kernel.c").write_text(src)
            written.append(trial_dir)
    print(f"wrote {len(written)} kernel.c files into {exp_dir}")
    return written


def build_suite(tsvc_dir):
    subprocess.run(
        ["make"], cwd=tsvc_dir, check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def run_trial(trial_dir, makefile):
    r = subprocess.run(
        ["make", "-f", str(makefile), "run"],
        cwd=trial_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return r.returncode


def run_all_trials(tsvc_dir, trial_dirs, workers=None):
    makefile = Path(tsvc_dir) / "Makefile.kernel"
    workers = workers or os.cpu_count()
    counts = Counter()
    total = len(trial_dirs)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(run_trial, d, makefile): d for d in trial_dirs}
        for i, done in enumerate(concurrent.futures.as_completed(futures), 1):
            counts[done.result()] += 1
            if i % 200 == 0 or i == total:
                print(f"  {i}/{total}", file=sys.stderr)
    return counts


def main():
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <out/<run>/>", file=sys.stderr)
        sys.exit(1)

    tsvc_dir = os.environ.get("CANARY_TSVC", TSVC_DEFAULT)
    steps_path = Path(sys.argv[1]) / "steps.json"

    groups = group_by_kernel(steps_path)
    if not groups:
        print("no produced kernels found in steps.json", file=sys.stderr)
        sys.exit(1)

    ntrials = max(len(v) for v in groups.values())
    run_mkexperiment(tsvc_dir, ntrials)
    exp_dir = latest_experiment(tsvc_dir)
    trial_dirs = seed_trials(exp_dir, groups, ntrials)

    build_suite(tsvc_dir)
    counts = run_all_trials(tsvc_dir, trial_dirs)

    total = sum(counts.values())
    success = counts.get(0, 0)
    print(f"\n{success}/{total} succeeded ({100*success/total:.1f}%)")
    for code, n in sorted(counts.items()):
        print(f"  exit {code}: {n}")


if __name__ == "__main__":
    main()
