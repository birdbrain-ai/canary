#!/bin/bash

###
### PROJECT DIRECTORIES
###
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
OUT_DIR="$PROJECT_DIR/out"
TSVC_DIR="$PROJECT_DIR/benchmarks/canary-test-suite/tsvc/"
CONFIG="clang-canary"

###
### PARAMETERS FOR SCRIPTS
###
OUT_DIRS=(
	# 2026-05-26_14-52-57_1779825177
	# 2026-05-26_23-13-54_1779855234
	# 2026-05-27_08-20-11_1779888011
	2026-05-27_20-16-47_1779931007
)
TRIALS=100

for d in "${OUT_DIRS[@]}"; do
	python3 "$SCRIPT_DIR/differentialTesting.py" "$OUT_DIR/$d" "$TRIALS" "$TSVC_DIR" --config configs/"$CONFIG".json
	python3 "$SCRIPT_DIR/plotResults.py" "$OUT_DIR/$d/results_${TRIALS}trials.csv" "$TRIALS"
done
