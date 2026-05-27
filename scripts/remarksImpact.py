import argparse
import sys
from pathlib import Path

import pandas as pd
from scipy import stats

TEMPERATURE = 0.8


def load(csv_path):
    df = pd.read_csv(csv_path, dtype={"diagnostic": str})
    df["diagnostic"] = df["diagnostic"].fillna("")
    return df


def main():
    parser = argparse.ArgumentParser(
        description="Compute the impact of compiler remarks on vectorization "
                    "success by comparing two experiment CSVs, paired by kernel."
    )
    parser.add_argument("yes_csv", type=Path,
                        help="results CSV from the with-remarks experiment")
    parser.add_argument("no_csv", type=Path,
                        help="results CSV from the no-remarks experiment "
                             "(all rows must have empty diagnostic)")
    parser.add_argument("--trials", type=int, default=100,
                        help="trials per (kernel, temperature) bucket")
    parser.add_argument("--out", type=Path, default=None,
                        help="where to write the per-kernel CSV "
                             "(default: alongside yes_csv as remarks_impact.csv)")
    args = parser.parse_args()

    yes_df = load(args.yes_csv)
    no_df = load(args.no_csv)

    if not (no_df["diagnostic"] == "").all():
        sys.exit(
            "error: no_csv must contain only rows with empty diagnostic; "
            "check the arg order."
        )

    yes_base = yes_df[(yes_df["diagnostic"] == "") & (yes_df["temperature"] == TEMPERATURE)]
    no_base = no_df[(no_df["diagnostic"] == "") & (no_df["temperature"] == TEMPERATURE)]

    paired = yes_base.merge(
        no_base, on="kernel_id", suffixes=("_yes_remarks", "_no_remarks"),
    )[["kernel_id", "success_count_yes_remarks", "success_count_no_remarks"]]
    paired["success_rate_yes_remarks"] = paired["success_count_yes_remarks"] / args.trials
    paired["success_rate_no_remarks"] = paired["success_count_no_remarks"] / args.trials

    if len(paired) != len(yes_base) or len(paired) != len(no_base):
        print(
            f"warning: paired {len(paired)} kernels but yes_csv has "
            f"{len(yes_base)} and no_csv has {len(no_base)} baseline rows at "
            f"t={TEMPERATURE}",
            file=sys.stderr,
        )

    yes_rate = paired["success_rate_yes_remarks"].mean()
    no_rate = paired["success_rate_no_remarks"].mean()
    print(f"vectorization success rate (t={TEMPERATURE}, trials={args.trials}, "
          f"n={len(paired)} kernels):")
    print(f"  yes_remarks: {yes_rate:.4f}")
    print(f"  no_remarks:  {no_rate:.4f}")
    print()

    out_path = args.out or (args.yes_csv.parent / "remarks_impact.csv")
    paired.to_csv(out_path, index=False)
    print(f"wrote {out_path}")
    print()

    result = stats.ttest_rel(
        paired["success_rate_yes_remarks"],
        paired["success_rate_no_remarks"],
    )
    mean_delta = (
        paired["success_rate_yes_remarks"] - paired["success_rate_no_remarks"]
    ).mean()
    print("paired t-test (yes_remarks vs no_remarks, per kernel):")
    print(f"  n          = {len(paired)}")
    print(f"  mean delta = {mean_delta:+.4f}")
    print(f"  t          = {result.statistic:.4f}")
    print(f"  p          = {result.pvalue:.4g}")
    print(f"  df         = {result.df:.0f}")
    print()

    deltas = paired["success_count_yes_remarks"] - paired["success_count_no_remarks"]
    n_pos = int((deltas > 0).sum())
    n_neg = int((deltas < 0).sum())
    n_tie = int((deltas == 0).sum())
    sign = stats.binomtest(n_pos, n_pos + n_neg, p=0.5) if n_pos + n_neg > 0 else None
    print("sign test (yes_remarks > no_remarks, per kernel):")
    print(f"  yes > no   = {n_pos}")
    print(f"  yes < no   = {n_neg}")
    print(f"  ties       = {n_tie}")
    if sign is not None:
        print(f"  p (two-sided) = {sign.pvalue:.4g}")
    else:
        print("  p (two-sided) = n/a (all pairs tied)")
    print()

    pos_kernels = paired.loc[deltas > 0, "kernel_id"].sort_values().tolist()
    neg_kernels = paired.loc[deltas < 0, "kernel_id"].sort_values().tolist()
    print(f"kernels where yes > no ({len(pos_kernels)}):")
    for k in pos_kernels:
        print(f"  {k}")
    print(f"kernels where yes < no ({len(neg_kernels)}):")
    for k in neg_kernels:
        print(f"  {k}")


if __name__ == "__main__":
    main()
