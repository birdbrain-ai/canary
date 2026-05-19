import csv
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

TEMPERATURES = [0.2, 0.8, 1.2]
COVERAGE_PATH = Path(__file__).resolve().parent.parent / "benchmarks" / "coverage.csv"
COVERAGE_COLUMN = "clang"


def load(csv_path):
    rows = []
    with open(csv_path) as f:
        for r in csv.DictReader(f):
            rows.append({
                "model": r["model"],
                "kernel_id": r["kernel_id"],
                "diagnostic": r["diagnostic"],
                "temperature": float(r["temperature"]),
                "success_count": int(r["success_count"]),
            })
    return rows


def load_coverage(path, column):
    coverage = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            names = r[column].split("|") if r[column] else []
            coverage[r["function"]] = set(names)
    return coverage


def kernels_emitting(coverage, diagnostic):
    name = diagnostic.split(":", 1)[1] if ":" in diagnostic else diagnostic
    return {k for k, names in coverage.items() if name in names}


def kernels_for_diagnostic(coverage, rows, diagnostic):
    emitters = kernels_emitting(coverage, diagnostic)
    has_baseline = {r["kernel_id"] for r in rows if r["diagnostic"] == ""}
    has_ablated = {r["kernel_id"] for r in rows if r["diagnostic"] == diagnostic}
    return emitters & has_baseline & has_ablated


def rate_over(rows, kernels, diagnostic, temperature, total_trials):
    if not kernels:
        return None
    successes = sum(
        r["success_count"] for r in rows
        if r["diagnostic"] == diagnostic
        and r["kernel_id"] in kernels
        and r["temperature"] == temperature
    )
    return successes / (len(kernels) * total_trials)


def plot_model(rows, model, coverage, total_trials, out_path):
    rows = [r for r in rows if r["model"] == model]
    diagnostics = sorted({r["diagnostic"] for r in rows if r["diagnostic"]})

    kernels_for = {d: kernels_for_diagnostic(coverage, rows, d) for d in diagnostics}
    missing = [d for d, ks in kernels_for.items() if not ks]
    if missing:
        sys.exit(f"error: no usable kernels for: {missing}")

    baseline = {d: {t: rate_over(rows, kernels_for[d], "", t, total_trials)
                    for t in TEMPERATURES}
                for d in diagnostics}
    rates = {d: {t: rate_over(rows, kernels_for[d], d, t, total_trials)
                 for t in TEMPERATURES}
             for d in diagnostics}

    x = np.arange(len(diagnostics))
    width = 0.27

    fig, ax = plt.subplots(figsize=(max(10, 1.2 * len(diagnostics)), 6))
    for i, t in enumerate(TEMPERATURES):
        deltas = [baseline[d][t] - rates[d][t] for d in diagnostics]
        ax.bar(x + (i - 1) * width, deltas, width, label=f"t={t}")

    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(
        [f"{d}\n(|K|={len(kernels_for[d])})" for d in diagnostics],
        rotation=45, ha="right",
    )
    ax.set_xlabel("diagnostic")
    ax.set_ylabel("success rate delta")
    ax.set_title(
        f"{model} — per-diagnostic baseline "
        f"(coverage={COVERAGE_COLUMN}, n={total_trials}/bucket)"
    )
    ax.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"wrote {out_path}")


def main():
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <results.csv> <total_trials>", file=sys.stderr)
        sys.exit(1)

    csv_path = Path(sys.argv[1])
    total_trials = int(sys.argv[2])
    rows = load(csv_path)
    coverage = load_coverage(COVERAGE_PATH, COVERAGE_COLUMN)

    for model in sorted({r["model"] for r in rows}):
        safe = model.replace("/", "_")
        out = csv_path.parent / f"{csv_path.stem}_{safe}.png"
        plot_model(rows, model, coverage, total_trials, out)


if __name__ == "__main__":
    main()
