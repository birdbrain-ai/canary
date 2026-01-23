#!/bin/bash

base_dir="$(pwd)"
tsvc_dir="TSVC_2_without_comments"
# NOTE: REMEMBER INTEL IS HARDCODED IN RUN_VECTORIZER
compiler="intel"
outfile="$base_dir/tsvc_run_log.txt"

# NOTE: REMEMBER THAT INTEL IS HARDCODED HERE
run_vectorizer() {
	if [ "$compiler" == "intel" ]; then
		# source ~/tank/intel/oneapi/compiler/latest/env/vars.sh 
	   python3 "$base_dir"/ai-pragmas/src/vectorizer.py \
			--iterations 3 \
			--make-command "make COMPILER=$compiler" \
			--run-command "$base_dir/ai-pragmas/validate_function_behavior.py" \
			--use-intel \
			"$1"
	else
		python3 "$base_dir"/ai-pragmas/src/vectorizer.py \
			--iterations 3 \
			--make-command "make COMPILER=$compiler" \
			--run-command "$base_dir/ai-pragmas/validate_function_behavior.py" \
			"$1"
	fi
}


echo "Making copies of TSVC"

mkdir "$tsvc_dir"_vec

pushd "$tsvc_dir"_vec

source ~/tank/intel/oneapi/compiler/latest/env/vars.sh 

# Make copies of TSVC - inspect the validate script for inspiration here
python3 "$base_dir"/ai-pragmas/make_tsvc_per_function.py ../"$tsvc_dir"

# Get all the dirs I care about
tsvc_dirs=("${tsvc_dir}"_{s,v}*)

echo "Spawning vectorizers"

# Run the vectorizer on all subdirectories
for dir in "${tsvc_dirs[@]}"; do
	run_vectorizer "$dir" &
done

wait

echo "Finished vectorizing"

echo "Running all loop functions"

echo "Loop  Time_s  Checksum" >> "$outfile"

for dir in "${tsvc_dirs[@]}"; do
	pushd "$dir"
	make clean
	rm -r bin
	make COMPILER="$compiler"
	./bin/"$compiler"/tsvc_vec_relaxed | sed -n '2p' >> "$outfile"
	popd
done

popd
