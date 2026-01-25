#!/bin/bash

base_dir="$(pwd)"
tsvc_dir="TSVC_2_without_comments"
tsvc_dir_vec="$tsvc_dir"_vec
compiler="intel"
outfile="$base_dir/$tsvc_dir_vec/tsvc_run_log.txt"

source ~/tank/intel/oneapi/compiler/latest/env/vars.sh

# mkdir "$tsvc_dir"_vec
pushd "$tsvc_dir_vec"

echo "Loop  Time_s  Checksum" >> "$outfile"

opt_dirs="*_opt"


echo "HELLO GUYS"
echo "$opt_dirs"

for dir in $opt_dirs; do
	pushd "$dir"
	make clean
	rm -r bin
	make COMPILER="$compiler"
	./bin/"$compiler"/tsvc_vec_relaxed | sed -n '2p' >> "$outfile"
	popd
done

popd

