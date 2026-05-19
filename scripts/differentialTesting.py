import concurrent.futures
import csv
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

CONFIG_REL = "configs/clang-default.json"
CONFIG_NAME = "clang-default"


def last_kernel(trial):
    for step in reversed(trial["steps"]):
        body = next(iter(step.values()))
        if isinstance(body, dict) and "kernel" in body:
            return body["kernel"]
    return None


def parse_trials(steps_path):
    trials = []
    with open(steps_path) as f:
        for line in f:
            t = json.loads(line)
            src = last_kernel(t)
            if src is None:
                continue
            trials.append({
                "model": t["model"],
                "kernel": Path(t["kernel"]).parent.name,
                "ablated": t["ablated"] or "",
                "temperature": t["temperature"],
                "source": src,
            })
    return trials


def run_mkexperiment(tsvc_dir, ntrials):
    subprocess.run(
        ["scripts/mkexperiment.sh", "-c", CONFIG_REL, "-n", str(ntrials), "-y"],
        cwd=tsvc_dir,
        check=True,
    )


def latest_experiment(tsvc_dir):
    base = Path(tsvc_dir) / "experiments" / CONFIG_NAME
    return max(base.iterdir(), key=lambda p: p.stat().st_mtime)


def seed_trials(exp_dir, trials, ntrials):
    width = len(str(ntrials))
    seen = Counter()
    for t in trials:
        seen[t["kernel"]] += 1
        t["trial_dir"] = exp_dir / t["kernel"] / f"{seen[t['kernel']]:0{width}d}"
        (t["trial_dir"] / "kernel.c").write_text(t["source"])
    print(f"wrote {len(trials)} kernel.c files into {exp_dir}")


def build_suite(tsvc_dir):
    subprocess.run(
        ["make"], cwd=tsvc_dir, check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def run_trial(trial_dir, makefile, timeout_s=300):
    try:
        r = subprocess.run(
            ["make", "-f", str(makefile), "run"],
            cwd=trial_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_s,
        )
        return r.returncode
    except subprocess.TimeoutExpired:
        return -1


def run_all_trials(tsvc_dir, trials, workers=None):
    makefile = Path(tsvc_dir) / "Makefile.kernel"
    workers = workers or 64
    total = len(trials)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(run_trial, t["trial_dir"], makefile): t for t in trials}
        for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            results.append((futures[fut], fut.result()))
            if i % 200 == 0 or i == total:
                print(f"  {i}/{total}", file=sys.stderr)
    return results


def main():
    if len(sys.argv) != 4:
        print(
            f"usage: {sys.argv[0]} <out/<run>/> <total_trials> <tsvc_dir>",
            file=sys.stderr,
        )
        sys.exit(1)

    steps_path = Path(sys.argv[1]) / "steps.json"
    total_trials = int(sys.argv[2])
    tsvc_dir = sys.argv[3]

    trials = parse_trials(steps_path)
    if not trials:
        print("no produced kernels found in steps.json", file=sys.stderr)
        sys.exit(1)

    ntrials = max(Counter(t["kernel"] for t in trials).values())
    run_mkexperiment(tsvc_dir, ntrials)
    exp_dir = latest_experiment(tsvc_dir)
    seed_trials(exp_dir, trials, ntrials)

    build_suite(tsvc_dir)
    results = run_all_trials(tsvc_dir, trials)

    total = len(results)
    success = sum(1 for _, code in results if code == 0)
    print(f"\n{success}/{total} succeeded ({100*success/total:.1f}%)")

    bucket_success = Counter()
    buckets = set()
    for t, code in results:
        key = (t["model"], t["kernel"], t["ablated"], t["temperature"])
        buckets.add(key)
        if code == 0:
            bucket_success[key] += 1

    csv_path = Path(sys.argv[1]) / f"results_{total_trials}trials.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "kernel_id", "diagnostic", "temperature", "success_count"])
        for key in sorted(buckets):
            w.writerow([*key, bucket_success[key]])
    print(f"wrote {csv_path}")


if __name__ == "__main__":
    main()
