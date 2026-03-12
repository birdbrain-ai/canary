#!/bin/bash

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)
TSVC_DIR="${SCRIPT_DIR}/../benchmarks/TSVC_2"
ORCHESTRATOR="${SCRIPT_DIR}/../src/orchestration/orchestrator.sh"

MODEL_NAME="Qwen/Qwen3-Coder-30B-A3B-Instruct"
MODEL_URL="http://localhost:8000/v1"
MAX_JOBS=128
NUM_ATTEMPTS=100

# Rerunning #4 Clang+NewRemarks at temp 0.2 (was contaminated by bug)
"${ORCHESTRATOR}" "${TSVC_DIR}" \
 --name "t0.2_clang_new_remarks" \
 --max-jobs "$MAX_JOBS" \
 --num-attempts "$NUM_ATTEMPTS" \
 --compiler clang_canary \
 --vectorizer-compiler clang \
 --compiler-feedback on \
 --oracle-remarks off \
 --filter-distribute-suggestion on \
 --model-name "$MODEL_NAME" \
 --model-url "$MODEL_URL" \
 --temperature 0.2

# Temp 0.8: only need to run #4-6 (1-3 already completed)
# 4. Clang+NewRemarks
"${ORCHESTRATOR}" "${TSVC_DIR}" \
 --name "t0.8_clang_new_remarks" \
 --max-jobs "$MAX_JOBS" \
 --num-attempts "$NUM_ATTEMPTS" \
 --compiler clang_canary \
 --vectorizer-compiler clang \
 --compiler-feedback on \
 --oracle-remarks off \
 --filter-distribute-suggestion on \
 --model-name "$MODEL_NAME" \
 --model-url "$MODEL_URL" \
 --temperature 0.8

# 5. Intel+NoRemarks
"${ORCHESTRATOR}" "${TSVC_DIR}" \
 --name "t0.8_intel_no_remarks" \
 --max-jobs "$MAX_JOBS" \
 --num-attempts "$NUM_ATTEMPTS" \
 --compiler intel \
 --vectorizer-compiler intel \
 --compiler-feedback off \
 --oracle-remarks off \
 --model-name "$MODEL_NAME" \
 --model-url "$MODEL_URL" \
 --temperature 0.8

# 6. Intel+Remarks
"${ORCHESTRATOR}" "${TSVC_DIR}" \
 --name "t0.8_intel_remarks" \
 --max-jobs "$MAX_JOBS" \
 --num-attempts "$NUM_ATTEMPTS" \
 --compiler intel \
 --vectorizer-compiler intel \
 --compiler-feedback on \
 --oracle-remarks off \
 --model-name "$MODEL_NAME" \
 --model-url "$MODEL_URL" \
 --temperature 0.8

# Remaining temperatures: all 6 experiments
TEMPERATURES=(1.2 1.6 2.0)

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

    # 5. Intel+NoRemarks
    "${ORCHESTRATOR}" "${TSVC_DIR}" \
     --name "t${temp}_intel_no_remarks" \
     --max-jobs "$MAX_JOBS" \
     --num-attempts "$NUM_ATTEMPTS" \
     --compiler intel \
     --vectorizer-compiler intel \
     --compiler-feedback off \
     --oracle-remarks off \
     --model-name "$MODEL_NAME" \
     --model-url "$MODEL_URL" \
     --temperature "$temp"

    # 6. Intel+Remarks
    "${ORCHESTRATOR}" "${TSVC_DIR}" \
     --name "t${temp}_intel_remarks" \
     --max-jobs "$MAX_JOBS" \
     --num-attempts "$NUM_ATTEMPTS" \
     --compiler intel \
     --vectorizer-compiler intel \
     --compiler-feedback on \
     --oracle-remarks off \
     --model-name "$MODEL_NAME" \
     --model-url "$MODEL_URL" \
     --temperature "$temp"

done
