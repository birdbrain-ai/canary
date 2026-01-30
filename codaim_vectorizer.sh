#!/bin/bash

ai_pragmas_dir="$HOME/tank/ai-pragmas"
clang_no_remarks_dir="$HOME/tank/TSVC_2_clang_no_remarks"
clang_remarks_dir="$HOME/tank/TSVC_2_clang_remarks"
intel_no_remarks_dir="$HOME/tank/TSVC_2_intel_no_remarks"
intel_remarks_dir="$HOME/tank/TSVC_2_intel_remarks"
temperature="1.0"
num_attempts=10

# Help message
usage() {
	cat <<EOF
Usage: $(basename "$0") [options]

A tool to run the vectorizer engineer with configurable directories. This
will automatically vectorize each TSVC function in parallel.

Options:
	-a, --a-dir PATH	Path to ai-pragmas dir. This has necessary utilities like 'make_tsvc_per_function.py' and 'src/vectorizer-engineer.py'. Default: $HOME/tank/ai-pragmas-simple
	-cn, --clang-no PATH	Path to clang_no_remarks_dir. Default: $HOME/tank/TSVC_2_clang_no_remarks
	-cr, --clang-rem PATH	Path to clang_remarks_dir. Default: $HOME/tank/TSVC_2_clang_remarks
	-in, --intel-no PATH 	Path to intel_no_remarks_dir. Default: $HOME/tank/TSVC_2_intel_no_remarks
	-ir, --intel-rem PATH 	Path to intel_remarks_dir. Default: $HOME/tank/TSVC_2_intel_remarks
	-t, --temperature int   The temperature to set the model to. Default: 1.0.
	-n, --num-attempts int  Number of attempts per function. Default: 10.
	-h, --help		  Display this help message.
EOF
	exit 0
}

# Argument parsing
while [[ $# -gt 0 ]]; do
	case $1 in
		-a|--ai-dir)
			ai_pragmas_dir=$2
			shift 2
			;;
		-cn|--clang-no)
			clang_no_remarks_dir=$2
			shift 2
			;;
		-cr|--clang-rem)
			clang_remarks_dir=$2
			shift 2
			;;
		-in|--intel-no)
			intel_no_remarks_dir=$2
			shift 2
			;;
		-ir|--intel-rem)
			intel_remarks_dir=$2
			shift 2
			;;
		-t|--temperature)
			temperature=$2
			shift 2
			;;
		-n|--num-attempts)
			num_attempts=$2
			shift 2
			;;
		-h|--help)
			usage
			;;
	esac
done

vectorize_with_clang_no_remarks() {
	python3 "$ai_pragmas_dir/src/vectorizer-engineer.py" \
			--iterations 1 \
			--make-command "make COMPILER=clang" \
			--run-command "$ai_pragmas_dir/validate_function_behavior.py" \
			--disable-compiler-feedback \
			--temperature "$temperature" \
			"$1"
}

vectorize_with_clang_remarks() {
	python3 "$ai_pragmas_dir/src/vectorizer-engineer.py" \
			--iterations 1 \
			--make-command "make COMPILER=clang" \
			--run-command "$ai_pragmas_dir/validate_function_behavior.py" \
			--temperature "$temperature" \
			"$1"
}

vectorize_with_intel_no_remarks() {
	python3 "$ai_pragmas_dir/src/vectorizer-engineer.py" \
			--iterations 1 \
			--make-command "make COMPILER=intel" \
			--run-command "$ai_pragmas_dir/validate_function_behavior.py" \
			--disable-compiler-feedback \
			--use-intel \
			--temperature "$temperature" \
			"$1"
}

vectorize_with_intel_remarks() {
	python3 "$ai_pragmas_dir/src/vectorizer-engineer.py" \
			--iterations 1 \
			--make-command "make COMPILER=intel" \
			--run-command "$ai_pragmas_dir/validate_function_behavior.py" \
			--use-intel \
			--temperature "$temperature" \
			"$1"
}


# # --- Review Choices ---
# echo "------------------------------------------------"
# echo "CONFIGURATION SUMMARY:"
# echo "AI Pragmas Dir:    $ai_pragmas_dir"
# echo "Clang No Remarks:  $clang_no_remarks_dir"
# echo "Clang Remarks:     $clang_remarks_dir"
# echo "Intel No Remarks:  $intel_no_remarks_dir"
# echo "Intel Remarks:     $intel_remarks_dir"
# echo "Temperature:       $temperature"
# echo "Num Attempts:      $num_attempts"
# echo "------------------------------------------------"


# # Prompt for confirmation
# read -p "Do you want to proceed with these settings? (y/n): " confirm

# if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
#     echo "Operation cancelled by user."
#     exit 0
# fi

# echo "Proceeding..."

echo "Starting experiment for CoDAIM!"

NUM_ATTEMPTS=$num_attempts

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

				
