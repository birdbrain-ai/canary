#!/bin/bash

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)
TSVC_DIR="${SCRIPT_DIR}/../benchmarks/TSVC_2"
ORCHESTRATOR="${SCRIPT_DIR}/../src/orchestration/orchestrator.sh"

MODEL_NAME="Qwen/Qwen3.5-27B-FP8"
MODEL_URL="http://localhost:8000/v1"
MAX_JOBS=128
NUM_ATTEMPTS=50

# Remaining temperatures: all 6 experiments
TEMPERATURES=(0.2 0.8 1.2)
for temp in "${TEMPERATURES[@]}"; do

    # 1. Clang+BaseRemarks
    "${ORCHESTRATOR}" "${TSVC_DIR}" \
     --name "t${temp}_clang_base_remarks" \
     --max-jobs "$MAX_JOBS" \
     --num-attempts "$NUM_ATTEMPTS" \
     --compiler clang_trunk \
     --vectorizer-compiler clang \
     --compiler-feedback on \
     --oracle-remarks off \
     --model-name "$MODEL_NAME" \
     --model-url "$MODEL_URL" \
     --temperature "$temp"

    # 2. Clang+NoRemarks
    "${ORCHESTRATOR}" "${TSVC_DIR}" \
     --name "t${temp}_clang_no_remarks" \
     --max-jobs "$MAX_JOBS" \
     --num-attempts "$NUM_ATTEMPTS" \
     --compiler clang_trunk \
     --vectorizer-compiler clang \
     --compiler-feedback off \
     --oracle-remarks off \
     --model-name "$MODEL_NAME" \
     --model-url "$MODEL_URL" \
     --temperature "$temp"

    # 3. Clang+OracleRemarks
    "${ORCHESTRATOR}" "${TSVC_DIR}" \
     --name "t${temp}_clang_oracle_remarks" \
     --max-jobs "$MAX_JOBS" \
     --num-attempts "$NUM_ATTEMPTS" \
     --compiler clang_trunk \
     --vectorizer-compiler clang \
     --compiler-feedback on \
     --oracle-remarks on \
     --filter-distribute-suggestion on \
     --model-name "$MODEL_NAME" \
     --model-url "$MODEL_URL" \
     --temperature "$temp"

    # 4. Clang+NewRemarks
    "${ORCHESTRATOR}" "${TSVC_DIR}" \
     --name "t${temp}_clang_new_remarks" \
     --max-jobs "$MAX_JOBS" \
     --num-attempts "$NUM_ATTEMPTS" \
     --compiler clang_canary \
     --vectorizer-compiler clang \
     --compiler-feedback on \
     --oracle-remarks off \
     --filter-distribute-suggestion on \
     --model-name "$MODEL_NAME" \
     --model-url "$MODEL_URL" \
     --temperature "$temp"

    # # 5. Intel+NoRemarks
    # "${ORCHESTRATOR}" "${TSVC_DIR}" \
    #  --name "t${temp}_intel_no_remarks" \
    #  --max-jobs "$MAX_JOBS" \
    #  --num-attempts "$NUM_ATTEMPTS" \
    #  --compiler intel \
    #  --vectorizer-compiler intel \
    #  --compiler-feedback off \
    #  --oracle-remarks off \
    #  --model-name "$MODEL_NAME" \
    #  --model-url "$MODEL_URL" \
    #  --temperature "$temp"

    # # 6. Intel+Remarks
    # "${ORCHESTRATOR}" "${TSVC_DIR}" \
    #  --name "t${temp}_intel_remarks" \
    #  --max-jobs "$MAX_JOBS" \
    #  --num-attempts "$NUM_ATTEMPTS" \
    #  --compiler intel \
    #  --vectorizer-compiler intel \
    #  --compiler-feedback on \
    #  --oracle-remarks off \
    #  --model-name "$MODEL_NAME" \
    #  --model-url "$MODEL_URL" \
    #  --temperature "$temp"

done
