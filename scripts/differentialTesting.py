import argparse
import concurrent.futures
import csv
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import yaml

try:
    _YamlLoader = yaml.CSafeLoader
except AttributeError:
    _YamlLoader = yaml.SafeLoader

# clang's optimization records tag each document (e.g. !Passed, !Missed,
# !Analysis). SafeLoader rejects unknown tags, so map any !-tag to a plain
# mapping.
yaml.add_multi_constructor(
    "!",
    lambda loader, suffix, node: loader.construct_mapping(node, deep=True),
    Loader=_YamlLoader,
)

DEFAULT_CONFIG_REL = "configs/clang-default.json"


def check_vectorized(remarks_stdout):
    try:
        for d in yaml.load_all(remarks_stdout, Loader=_YamlLoader):
            if isinstance(d, dict) and d.get("Name") == "Vectorized":
                return True
    except yaml.YAMLError:
        return False
    return False


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


def run_mkexperiment(tsvc_dir, ntrials, config_rel):
    subprocess.run(
        ["scripts/mkexperiment.sh", "-c", config_rel, "-n", str(ntrials), "-y"],
        cwd=tsvc_dir,
        check=True,
    )


def latest_experiment(tsvc_dir, config_name):
    base = Path(tsvc_dir) / "experiments" / config_name
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


def run_trial(trial_dir, makefile, config_sh, timeout_s=300):
    # clang-remarks (tsvc/bin/clang-remarks) is a shell wrapper that reads
    # $CC and lives on $PATH only after config.sh is sourced.
    prelude = f"source {config_sh} && "
    try:
        r = subprocess.run(
            ["bash", "-c", prelude + f"make -f {makefile} remarks"],
            cwd=trial_dir,
            capture_output=True,
            timeout=timeout_s,
        )
        vectorized = r.returncode == 0 and check_vectorized(r.stdout)
    except subprocess.TimeoutExpired:
        vectorized = False

    try:
        r = subprocess.run(
            ["bash", "-c", prelude + f"make -f {makefile} run"],
            cwd=trial_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_s,
        )
        code = r.returncode
    except subprocess.TimeoutExpired:
        code = -1

    return code, vectorized


def run_all_trials(tsvc_dir, exp_dir, trials, workers=None):
    makefile = Path(tsvc_dir) / "Makefile.kernel"
    config_sh = Path(exp_dir) / "config.sh"
    workers = workers or 64
    total = len(trials)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(run_trial, t["trial_dir"], makefile, config_sh): t
            for t in trials
        }
        for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            results.append((futures[fut], *fut.result()))
            if i % 200 == 0 or i == total:
                print(f"  {i}/{total}", file=sys.stderr)
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument("run_dir", help="out/<run>/ directory containing steps.json")
    p.add_argument("total_trials", type=int)
    p.add_argument("tsvc_dir")
    p.add_argument(
        "--config",
        default=DEFAULT_CONFIG_REL,
        help="path to config json, relative to tsvc_dir "
        f"(default: {DEFAULT_CONFIG_REL})",
    )
    args = p.parse_args()

    steps_path = Path(args.run_dir) / "steps.json"
    total_trials = args.total_trials
    tsvc_dir = args.tsvc_dir
    config_name = json.loads((Path(tsvc_dir) / args.config).read_text())["name"]

    trials = parse_trials(steps_path)
    if not trials:
        print("no produced kernels found in steps.json", file=sys.stderr)
        sys.exit(1)

    ntrials = max(Counter(t["kernel"] for t in trials).values())
    run_mkexperiment(tsvc_dir, ntrials, args.config)
    exp_dir = latest_experiment(tsvc_dir, config_name)
    seed_trials(exp_dir, trials, ntrials)

    build_suite(tsvc_dir)
    results = run_all_trials(tsvc_dir, exp_dir, trials)

    total = len(results)
    success = sum(1 for _, code, vec in results if code == 0 and vec)
    print(f"\n{success}/{total} succeeded ({100*success/total:.1f}%)")

    bucket_success = Counter()
    buckets = set()
    for t, code, vec in results:
        key = (t["model"], t["kernel"], t["ablated"], t["temperature"])
        buckets.add(key)
        if code == 0 and vec:
            bucket_success[key] += 1

    csv_path = Path(args.run_dir) / f"results_{total_trials}trials.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        # success_count = trials that ran to exit 0 AND vectorized the kernel.
        w.writerow(["model", "kernel_id", "diagnostic", "temperature", "success_count"])
        for key in sorted(buckets):
            w.writerow([*key, bucket_success[key]])
    print(f"wrote {csv_path}")


if __name__ == "__main__":
    main()
