#!/bin/bash
# Delete all *_opt directories inside TSVC_2_vec/ for every experiment in results/

RESULTS_DIR="/pool/akash/canary/results"

if [[ -z "$1" ]]; then
    echo "Usage: $0 <experiment_name>"
    echo "  Cleans *_opt directories from results/<experiment_name>/TSVC_2_vec/"
    exit 1
fi

EXPERIMENT_DIR="$RESULTS_DIR/$1"
if [[ ! -d "$EXPERIMENT_DIR" ]]; then
    echo "Error: directory '$EXPERIMENT_DIR' does not exist"
    exit 1
fi

vec_dir="$EXPERIMENT_DIR/TSVC_2_vec"
if [[ ! -d "$vec_dir" ]]; then
    echo "Error: no TSVC_2_vec directory in '$EXPERIMENT_DIR'"
    exit 1
fi

echo "Cleaning $vec_dir ..."
dirs_to_delete=$(ls "$vec_dir" | grep '_opt$')

echo "$dirs_to_delete" | while read -r d; do
    rm -rf "$vec_dir/$d"
done
