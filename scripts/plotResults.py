import csv
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from patsy import dmatrix
from scipy import stats

TEMPERATURES = [0.0, 0.2, 0.8, 1.2]
COVERAGE_PATH = Path(__file__).resolve().parent.parent / "benchmarks" / "coverage.csv"
COVERAGE_COLUMN = "clang"
STATS_DIAGNOSTIC = "loop-vectorize:MissedDetails"


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


def successes_over(rows, kernels, diagnostic, temperature):
    return sum(
        r["success_count"] for r in rows
        if r["diagnostic"] == diagnostic
        and r["kernel_id"] in kernels
        and r["temperature"] == temperature
    )


def rate_over(rows, kernels, diagnostic, temperature, total_trials):
    if not kernels:
        return None
    successes = successes_over(rows, kernels, diagnostic, temperature)
    return successes / (len(kernels) * total_trials)


def per_kernel_deltas(rows, kernels, diagnostic, temperature, total_trials):
    baseline = {}
    ablated = {}
    for r in rows:
        if r["kernel_id"] not in kernels or r["temperature"] != temperature:
            continue
        if r["diagnostic"] == "":
            baseline[r["kernel_id"]] = r["success_count"]
        elif r["diagnostic"] == diagnostic:
            ablated[r["kernel_id"]] = r["success_count"]

    common = baseline.keys() & ablated.keys()
    return {k: (baseline[k] - ablated[k]) / total_trials for k in common}


def paired_stats(deltas_a, deltas_b):
    kernels = sorted(deltas_a.keys() & deltas_b.keys())
    a = np.array([deltas_a[k] for k in kernels])
    b = np.array([deltas_b[k] for k in kernels])
    diff = a - b

    pos = int((diff > 0).sum())
    neg = int((diff < 0).sum())
    ties = int((diff == 0).sum())

    if len(kernels) >= 2 and np.any(diff != 0):
        t_pvalue = stats.ttest_rel(a, b).pvalue
    else:
        t_pvalue = float("nan")

    if pos + neg > 0:
        sign_pvalue = stats.binomtest(pos, pos + neg, 0.5).pvalue
    else:
        sign_pvalue = float("nan")

    return {
        "n": len(kernels),
        "pos": pos,
        "neg": neg,
        "ties": ties,
        "t_pvalue": t_pvalue,
        "sign_pvalue": sign_pvalue,
    }


def compare_temperatures(rows, model, coverage, diagnostic, total_trials):
    rows = [r for r in rows if r["model"] == model]
    kernels = kernels_for_diagnostic(coverage, rows, diagnostic)
    if not kernels:
        print(f"\n{model} — {diagnostic}: no usable kernels, skipping")
        return

    deltas = {
        t: per_kernel_deltas(rows, kernels, diagnostic, t, total_trials)
        for t in TEMPERATURES
    }

    print(
        f"\n{model} — {diagnostic} — pairwise temperature comparisons "
        f"(|K|={len(kernels)})"
    )
    print(f"  {'pair':<16}{'n':<5}{'t-test p':<12}{'sign p':<12}signs (+/-/=)")
    print("  " + "-" * 60)

    for i, ta in enumerate(TEMPERATURES):
        for tb in TEMPERATURES[i + 1:]:
            s = paired_stats(deltas[ta], deltas[tb])
            pair = f"t={ta} vs t={tb}"
            signs = f"+{s['pos']}/-{s['neg']}/={s['ties']}"
            print(
                f"  {pair:<16}{s['n']:<5}"
                f"{s['t_pvalue']:<12.4f}{s['sign_pvalue']:<12.4f}{signs}"
            )


def build_logit_frame(rows, kernels, diagnostic, total_trials):
    records = []
    for r in rows:
        if r["kernel_id"] not in kernels:
            continue
        if r["diagnostic"] == "":
            has_remark = 1
        elif r["diagnostic"] == diagnostic:
            has_remark = 0
        else:
            continue
        records.append({
            "kernel_id": r["kernel_id"],
            "has_remark": has_remark,
            "temperature": r["temperature"],
            "successes": r["success_count"],
            "failures": total_trials - r["success_count"],
        })
    return pd.DataFrame(records)


def fit_clustered_logit(rows, model, coverage, diagnostic, total_trials):
    rows = [r for r in rows if r["model"] == model]
    kernels = kernels_for_diagnostic(coverage, rows, diagnostic)
    if not kernels:
        print(f"\n{model} — {diagnostic}: no usable kernels, skipping logit")
        return

    df = build_logit_frame(rows, kernels, diagnostic, total_trials)
    X = dmatrix("has_remark * C(temperature)", df, return_type="dataframe")
    y = df[["successes", "failures"]].values

    fit = sm.GLM(y, X, family=sm.families.Binomial()).fit(
        cov_type="cluster",
        cov_kwds={"groups": df["kernel_id"].values},
    )

    print(
        f"\n{model} — {diagnostic} — clustered logit "
        f"(cluster=kernel_id, |K|={len(kernels)})"
    )
    print(fit.summary().tables[1])


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

    print(f"\n{model} — per-diagnostic impact (with - without remark)")
    cols = "  ".join(f"t={t:<3} (with/without/Δ)".rjust(25) for t in TEMPERATURES)
    header = f"  {'diagnostic':<48}{'|K|':<5}{'N':<6}{cols}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for d in diagnostics:
        ks = kernels_for[d]
        trials = len(ks) * total_trials
        cells = []
        for t in TEMPERATURES:
            with_rem = successes_over(rows, ks, "", t)
            without_rem = successes_over(rows, ks, d, t)
            delta = baseline[d][t] - rates[d][t]
            cells.append(f"{with_rem:>4}/{without_rem:<4}{delta:+7.3f}".rjust(25))
        print(f"  {d:<48}{len(ks):<5}{trials:<6}{'  '.join(cells)}")

    x = np.arange(len(diagnostics))
    n = len(TEMPERATURES)
    width = 0.8 / n

    fig, ax = plt.subplots(figsize=(max(10, 1.8 * len(diagnostics)), 6))
    for i, t in enumerate(TEMPERATURES):
        deltas = [baseline[d][t] - rates[d][t] for d in diagnostics]
        ax.bar(x + (i - (n - 1) / 2) * width, deltas, width, label=f"t={t}")

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
        compare_temperatures(rows, model, coverage, STATS_DIAGNOSTIC, total_trials)
        fit_clustered_logit(rows, model, coverage, STATS_DIAGNOSTIC, total_trials)


if __name__ == "__main__":
    main()
