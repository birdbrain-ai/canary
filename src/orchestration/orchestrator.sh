#!/bin/bash

# Use a tmp directory on /tank to avoid filling up /tmp
export TMPDIR="$HOME/tank/tmp"
mkdir -p "$TMPDIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AI_PRAGMAS_DIR="$(cd "$SCRIPT_DIR/../.." && pwd -P)"

# Defaults
name="TSVC_$(date +%Y-%m-%d_%H-%M-%S)"
compiler="clang"
vectorizer_compiler="clang"
compiler_feedback="on"
oracle_remarks="off"
model_name="Qwen/Qwen2.5-Coder-7B-Instruct"
model_url="http://localhost:8001/v1"
temperature="1.0"
iterations=1
results_dir="$AI_PRAGMAS_DIR/results"
max_jobs=8
num_attempts=10
skip_files="common.c,dummy.c,array_defs.h,common.h"
skip_functions="time_function,main"

usage() {
	cat <<EOF
Usage: $(basename "$0") <tsvc_dir> [options]

Split a TSVC benchmark into per-function benchmarks and run the vectorizer
on each one in parallel.

Arguments:
  tsvc_dir                       Path to the TSVC benchmark directory

Orchestration options:
  --name NAME                    Name for this experiment copy (default: TSVC_<timestamp>)
  --max-jobs N                   Max parallel vectorizer jobs (default: $max_jobs)
  --num-attempts N               Attempts per function (default: $num_attempts)

Vectorizer options (forwarded to vectorizer.py):
  --compiler NAME                Compiler for make COMPILER= (clang, clang_trunk, intel, etc.) (default: $compiler)
  --vectorizer-compiler NAME     Remark format for vectorizer (clang, intel) (default: $vectorizer_compiler)
  --compiler-feedback {on,off}   Compiler feedback in LLM prompts (default: $compiler_feedback)
  --oracle-remarks {on,off}      Oracle remark supplements in prompts (default: $oracle_remarks)
  --model-name NAME              LLM model name (default: $model_name)
  --model-url URL                LLM API base URL (default: $model_url)
  --temperature T                LLM temperature (default: $temperature)
  --iterations N                 Refinement iterations per function (default: $iterations)
  --results-dir DIR              Output directory (default: $results_dir)
  --skip-files LIST              Comma-separated filenames to skip (default: $skip_files)
  --skip-functions LIST          Comma-separated function names to skip (default: $skip_functions)
  -h, --help                     Display this help message
EOF
	exit 0
}

# --- Argument parsing ---

if [[ $# -eq 0 ]]; then
	usage
fi

tsvc_dir="$1"
shift

while [[ $# -gt 0 ]]; do
	case $1 in
		--compiler)          compiler=$2;              shift 2 ;;
		--vectorizer-compiler) vectorizer_compiler=$2; shift 2 ;;
		--compiler-feedback) compiler_feedback=$2;     shift 2 ;;
		--oracle-remarks)    oracle_remarks=$2;        shift 2 ;;
		--model-name)        model_name=$2;         shift 2 ;;
		--model-url)         model_url=$2;          shift 2 ;;
		--temperature)       temperature=$2;        shift 2 ;;
		--iterations)        iterations=$2;         shift 2 ;;
		--results-dir)       results_dir=$2;        shift 2 ;;
		--name)              name=$2;                shift 2 ;;
		--max-jobs)          max_jobs=$2;            shift 2 ;;
		--num-attempts)      num_attempts=$2;        shift 2 ;;
		--skip-files)        skip_files=$2;          shift 2 ;;
		--skip-functions)    skip_functions=$2;      shift 2 ;;
		-h|--help)           usage ;;
		*) echo "Unknown option: $1"; exit 1 ;;
	esac
done

if [[ ! -d "$tsvc_dir" ]]; then
	echo "Error: $tsvc_dir is not a directory"
	exit 1
fi

# --- Create timestamped experiment directory ---

timestamp=$(date +%Y-%m-%d_%H-%M-%S)
experiment_dir="$results_dir/${timestamp}_${name}"
mkdir -p "$experiment_dir"

# --- Save experiment metadata ---

cat > "$experiment_dir/metadata.json" <<EOF
{
  "name": "$name",
  "timestamp": "$timestamp",
  "tsvc_dir": "$(realpath "$tsvc_dir")",
  "compiler": "$compiler",
  "vectorizer_compiler": "$vectorizer_compiler",
  "compiler_feedback": "$compiler_feedback",
  "oracle_remarks": "$oracle_remarks",
  "model_name": "$model_name",
  "model_url": "$model_url",
  "temperature": $temperature,
  "iterations": $iterations,
  "num_attempts": $num_attempts,
  "max_jobs": $max_jobs,
  "skip_files": "$skip_files",
  "skip_functions": "$skip_functions",
  "results_dir": "$results_dir",
  "git_commit": "$(git -C "$AI_PRAGMAS_DIR" rev-parse HEAD 2>/dev/null || echo "unknown")",
  "hostname": "$(hostname)"
}
EOF

echo "Saved experiment metadata to $experiment_dir/metadata.json"

# --- Copy TSVC into experiment dir and split into per-function benchmarks ---

tsvc_copy="$experiment_dir/$(basename "$tsvc_dir")"

echo "Experiment dir: $experiment_dir"
echo "Copying $tsvc_dir to $tsvc_copy..."
cp -r "$tsvc_dir" "$tsvc_copy"

echo "Splitting $tsvc_copy into per-function benchmarks..."
python3 "$AI_PRAGMAS_DIR/src/orchestration/make_tsvc_per_function.py" "$tsvc_copy"

vec_dir="${tsvc_copy}_vec"
if [[ ! -d "$vec_dir" ]]; then
	echo "Error: expected split output at $vec_dir"
	exit 1
fi

# Collect per-function subdirs (skip any _attempt_ dirs from previous runs)
subdirs=()
for d in "$vec_dir"/*/; do
	[[ -d "$d" && "$d" != *_attempt_* ]] && subdirs+=("$d")
done

echo "Found ${#subdirs[@]} per-function benchmarks"
echo "Running $num_attempts attempts each, max $max_jobs parallel jobs"
echo "Compiler: $compiler | Feedback: $compiler_feedback | Oracle: $oracle_remarks | Model: $model_name | Temp: $temperature | Iters: $iterations"

# --- Set make command and source compiler environment ---

make_command="make COMPILER=$compiler"

# Source Intel environment if needed
if [[ "$compiler" == intel ]]; then
	if [[ -f ~/tank/intel/oneapi/compiler/latest/env/vars.sh ]]; then
		source ~/tank/intel/oneapi/compiler/latest/env/vars.sh
	fi
fi

# --- Run vectorizer on each function ---

for dir in "${subdirs[@]}"; do
	for attempt in $(seq -w 1 "$num_attempts"); do
		# Wait for a slot to open up
		while [[ $(jobs -rp | wc -l) -ge $max_jobs ]]; do
			sleep 0.5
		done

		attempt_dir="${dir%/}_attempt_${attempt}"
		cp -r "$dir" "$attempt_dir"

		log_file="$attempt_dir/output.log"

		python3 "$AI_PRAGMAS_DIR/src/workflows/engineer/vectorizer.py" \
			"$attempt_dir" \
			--make-command "$make_command" \
			--run-command "python3 $AI_PRAGMAS_DIR/src/tsvc/validate_function_behavior.py" \
			--compiler "$vectorizer_compiler" \
			--compiler-feedback "$compiler_feedback" \
			--oracle-remarks "$oracle_remarks" \
			--model-name "$model_name" \
			--model-url "$model_url" \
			--temperature "$temperature" \
			--iterations "$iterations" \
			--results-dir "$vec_dir" \
			${skip_files:+--skip-files "$skip_files"} \
			${skip_functions:+--skip-functions "$skip_functions"} \
			> "$log_file" 2>&1 &
	done
done

wait
echo "Done. All vectorization runs complete."
