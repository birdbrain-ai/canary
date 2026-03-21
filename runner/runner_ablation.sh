#!/bin/bash

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)
TSVC_DIR="${SCRIPT_DIR}/../benchmarks/TSVC_2"
ORCHESTRATOR="${SCRIPT_DIR}/../src/orchestration/orchestrator_ablation.sh"

MODEL_NAME="Qwen/Qwen2.5-Coder-7B-Instruct"
MODEL_URL="http://localhost:8000/v1"
MAX_JOBS=64
NUM_ATTEMPTS=100

TEMPERATURES=(0.2 0.8 1.2)
ABLATION_CONFIGS=(1 2 3 4 5 6)

for temp in "${TEMPERATURES[@]}"; do
    for config in "${ABLATION_CONFIGS[@]}"; do

        "${ORCHESTRATOR}" "${TSVC_DIR}" \
         --name "t${temp}_ablation_config_${config}" \
         --max-jobs "$MAX_JOBS" \
         --num-attempts "$NUM_ATTEMPTS" \
         --compiler clang \
         --vectorizer-compiler clang \
         --oracle-ablation-config "$config" \
         --filter-distribute-suggestion on \
         --model-name "$MODEL_NAME" \
         --model-url "$MODEL_URL" \
         --temperature "$temp"

    done
done
