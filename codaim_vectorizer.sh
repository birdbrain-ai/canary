#!/bin/bash

ai_pragmas_dir="$HOME/tank/ai-pragmas-simple"
clang_no_remarks_dir="$HOME/tank/temp_0.2_TSVC_2_clang_no_remarks"
clang_remarks_dir="$HOME/tank/temp_0.2_TSVC_2_clang_remarks"
intel_no_remarks_dir="$HOME/tank/temp_0.2_TSVC_2_intel_no_remarks"
intel_remarks_dir="$HOME/tank/temp_0.2_TSVC_2_intel_remarks"

vectorize_with_clang_no_remarks() {
	python3 "$ai_pragmas_dir/src/vectorizer-engineer.py" \
			--iterations 1 \
			--make-command "make COMPILER=clang" \
			--run-command "$ai_pragmas_dir/validate_function_behavior.py" \
			--disable-compiler-feedback \
			"$1"
}

vectorize_with_clang_remarks() {
	python3 "$ai_pragmas_dir/src/vectorizer-engineer.py" \
			--iterations 1 \
			--make-command "make COMPILER=clang" \
			--run-command "$ai_pragmas_dir/validate_function_behavior.py" \
			"$1"
}

vectorize_with_intel_no_remarks() {
	python3 "$ai_pragmas_dir/src/vectorizer-engineer.py" \
			--iterations 1 \
			--make-command "make COMPILER=intel" \
			--run-command "$ai_pragmas_dir/validate_function_behavior.py" \
			--disable-compiler-feedback \
			--use-intel \
			"$1"
}

vectorize_with_intel_remarks() {
	python3 "$ai_pragmas_dir/src/vectorizer-engineer.py" \
			--iterations 1 \
			--make-command "make COMPILER=intel" \
			--run-command "$ai_pragmas_dir/validate_function_behavior.py" \
			--use-intel \
			"$1"
}

echo "Starting experiment for CoDAIM!"

NUM_ATTEMPTS=10

for compiler in clang intel; do
	for remarks in no yes; do
		echo "VECTORIZING WITH $compiler WITH $remarks REMARKS"

		# Set target directory
		if [[ "$compiler" == "clang" && "$remarks" == "no" ]]; then
			target_dir="$clang_no_remarks_dir"
		elif [[ "$compiler" == "clang" && "$remarks" == "yes" ]]; then
			target_dir="$clang_remarks_dir"
		elif [[ "$compiler" == "intel" && "$remarks" == "no" ]]; then
			target_dir="$intel_no_remarks_dir"
		elif [[ "$compiler" == "intel" && "$remarks" == "yes" ]]; then
			target_dir="$intel_remarks_dir"
		fi

		# Make vectorization directory for the target benchmark
		vec_dir="$target_dir"_vec
		mkdir "$vec_dir"
		pushd "$vec_dir"

		# Only source Intel's environment variables if we're using ICX
		if [[ "$compiler" == "intel" ]]; then
			source ~/tank/intel/oneapi/compiler/latest/env/vars.sh
		fi

		python3 "$ai_pragmas_dir"/make_tsvc_per_function.py "$target_dir"

		vec_subdirs=("${vec_dir}/$(basename "${target_dir}")"_{s,v}*)

		echo "Spawning vectorizers ($NUM_ATTEMPTS attempts per function)"

		for dir in "${vec_subdirs[@]}"; do
			for attempt in $(seq -w 1 $NUM_ATTEMPTS); do
				attempt_dir="${dir}_attempt_${attempt}"
				cp -r "$dir" "$attempt_dir"

				log_file="$attempt_dir/output.log"
				if [[ "$compiler" == "clang" && "$remarks" == "no" ]]; then
					vectorize_with_clang_no_remarks "$attempt_dir" > "$log_file" 2>&1 &
				elif [[ "$compiler" == "clang" && "$remarks" == "yes" ]]; then
					vectorize_with_clang_remarks "$attempt_dir" > "$log_file" 2>&1 &
				elif [[ "$compiler" == "intel" && "$remarks" == "no" ]]; then
					vectorize_with_intel_no_remarks "$attempt_dir" > "$log_file" 2>&1 &
				elif [[ "$compiler" == "intel" && "$remarks" == "yes" ]]; then
					vectorize_with_intel_remarks "$attempt_dir" > "$log_file" 2>&1 &
				fi
			done
		done

		wait

		popd
	done
done

				
