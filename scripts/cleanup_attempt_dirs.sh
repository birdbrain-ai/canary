#!/bin/bash
# Delete all *_opt and bare *_attempt_NN directories inside TSVC_2_vec/ for every experiment in results/

RESULTS_DIR="${1:-/pool/akash/canary/results}"

for experiment in "$RESULTS_DIR"/*/; do
    vec_dir="$experiment/TSVC_2_vec"
    [[ -d "$vec_dir" ]] || continue

    echo "Cleaning $vec_dir ..."
    # Use ls + grep to avoid slow recursive find
    dirs_to_delete=$(ls "$vec_dir" | grep -E '_opt$|_attempt_[0-9]+$')
    count=$(echo "$dirs_to_delete" | wc -l)
    # echo "  Found $count _opt dirs. Sample:"
    # echo "$dirs_to_delete" | head -5 | sed 's/^/    /'
    # echo "    ..."
    # echo "$dirs_to_delete" | tail -2 | sed 's/^/    /'

    # Uncomment to actually delete:
    echo "$dirs_to_delete" | while read -r d; do
        rm -rf "$vec_dir/$d"
    done
    # echo "  (dry run — uncomment to delete)"
done
