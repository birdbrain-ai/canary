#!/bin/bash
#
# orchestrateExperiment.sh - Sweep canary over (model x ablation x temperature).
#
# For each model in MODELS, spin up a vLLM server, run canary against the TSVC
# kernels with every (ablation, temperature) combination, then tear the server
# down. Env vars CC/CFLAGS/REMARKS/TV are sourced from the experiment config
# JSON so it remains the single source of truth.
#
# TODO: convert to Python.

# ---------------------------------------------------------------------------
# Experiment parameters (override via the environment)
# ---------------------------------------------------------------------------
TRIALS="${TRIALS:-100}"
EXPERIMENT_NAME="${EXPERIMENT_NAME:-clang-default}"

MODELS=(
   # google/gemma-3-1b-it
   # google/gemma-3-4b-it
   # google/gemma-3-12b-it
   # google/gemma-3-27b-it
   google/gemma-4-E2B-it
   google/gemma-4-E4B-it
   google/gemma-4-26B-A4B-it
   google/gemma-4-31B-it
)

# loop-vectorize remarks to ablate (canary adds an implicit baseline run).
ABLATE=(
   loop-vectorize:CantIdentifyArrayBounds
   loop-vectorize:CantVectorizeInstruction
   loop-vectorize:CantVectorizeLibcall
   loop-vectorize:MissedDetails
   loop-vectorize:NonReductionValueUsedOutsideLoop
   loop-vectorize:UnsafeDep
   loop-vectorize:UnsupportedUncountableLoop
   loop-vectorize:WritesInEarlyExitLoop
)

SLP_ABLATE=(
	slp-vectorizer:NotPossible
	slp-vectorizer:NotBeneficial
)


TEMPERATURES=(0.2 0.8 1.2)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR/.."
TSVC_DIR="$PROJECT_DIR/benchmarks/canary-test-suite/tsvc"
CONFIG="$TSVC_DIR/configs/${EXPERIMENT_NAME}.json"

# ---------------------------------------------------------------------------
# Environment for canary (sourced from the experiment config)
# ---------------------------------------------------------------------------
# PATH lets unqualified tool names in the config (e.g. "clang-remarks") resolve.
export PATH="${TSVC_DIR}/bin:$PATH"
# Translate config .env into export statements and apply them in this shell.
eval "$(jq -r '.env | to_entries[] | "export \(.key)=\"\(.value)\""' "$CONFIG")"
export INCLUDES="-I${TSVC_DIR}/include"

# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------
for MODEL in "${MODELS[@]}"; do
   echo "=== Running experiment for $MODEL ==="

   # Spawn a vLLM server.
   cd "$SCRIPT_DIR"
   "$PROJECT_DIR/language-models/tunnel.sh" "$MODEL"
   # Run a canary experiment.
   cd "$PROJECT_DIR"
   MAX_RETRIES=1 uv run canary \
      "$TSVC_DIR/kernels" \
      --model "$MODEL" \
      --api-url http://localhost:8000/v1 \
      --trials "$TRIALS" \
      --jobs 32 \
      --ablate "${ABLATE[@]}" \
	  --transform "loop-vectorize" \
      --temperature "${TEMPERATURES[@]}"

   MAX_RETRIES=1 uv run canary \
      "$TSVC_DIR/kernels" \
      --model "$MODEL" \
      --api-url http://localhost:8000/v1 \
      --trials "$TRIALS" \
      --jobs 32 \
      --ablate "${SLP_ABLATE[@]}" \
	  --transform "slp-vectorizer" \
      --temperature "${TEMPERATURES[@]}"
   
   # Tear down the vLLM server.
   cd "$SCRIPT_DIR"
   "$PROJECT_DIR/language-models/killall.sh"
done
