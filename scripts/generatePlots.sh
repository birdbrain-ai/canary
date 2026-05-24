#!/bin/bash

###
### PROJECT DIRECTORIES
###
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
OUT_DIR="$PROJECT_DIR/out"
TSVC_DIR="$PROJECT_DIR/benchmarks/canary-test-suite/tsvc/"

###
### PARAMETERS FOR SCRIPTS
###
OUT_DIRS=(
	# 10 trials
	2026-05-22_20-51-53_1779501113
	2026-05-22_23-14-07_1779509647
	2026-05-22_23-51-27_1779511887

	# 100 trials
	# 2026-05-23_09-01-53_1779544913
	# 2026-05-23_23-13-21_1779596001
)
TRIALS=10

for d in "${OUT_DIRS[@]}"; do
	python3 "$SCRIPT_DIR/differentialTesting.py" "$OUT_DIR/$d" "$TRIALS" "$TSVC_DIR"
	python3 "$SCRIPT_DIR/plotResults.py" "$OUT_DIR/$d/results_${TRIALS}trials.csv" "$TRIALS"
done
