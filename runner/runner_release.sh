#!/bin/bash

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)
TSVC_DIR="${SCRIPT_DIR}/../benchmarks/TSVC_2"
ORCHESTRATOR="${SCRIPT_DIR}/../src/orchestration/orchestrator.sh"

MODEL_NAME="gemma4:31b"
# gemma3:
# google/gemma-3-1b-it
# google/gemma-3-4b-it
# google/gemma-3-12b-it
# google/gemma-3-27b-it
# 
# gemma4:
# google/gemma-4-E2B-it
# google/gemma-4-E4B-it
# google/gemma-4-26B-A4B-it
# google/gemma-4-31B-it

MODEL_URL="http://localhost:8000"
MAX_JOBS=64
NUM_ATTEMPTS=5

# Remaining temperatures: all 6 experiments
TEMPERATURES=(0.2 0.8 1.2)
for temp in "${TEMPERATURES[@]}"; do

    # # # 1. Clang+BaseRemarks
    "${ORCHESTRATOR}" "${TSVC_DIR}" \
     --name "t${temp}_clang_base_remarks" \
     --max-jobs "$MAX_JOBS" \
     --num-attempts "$NUM_ATTEMPTS" \
     --compiler clang \
     --vectorizer-compiler clang \
     --compiler-feedback on \
     --oracle-remarks off \
     --model-name "$MODEL_NAME" \
     --model-url "$MODEL_URL" \
     --temperature "$temp"

    # # # 1.5. Clang+BaseRemarks+FiltDist
    "${ORCHESTRATOR}" "${TSVC_DIR}" \
     --name "t${temp}_clang_base_remarks_filt_dist" \
     --max-jobs "$MAX_JOBS" \
     --num-attempts "$NUM_ATTEMPTS" \
     --compiler clang \
     --vectorizer-compiler clang \
     --compiler-feedback on \
     --oracle-remarks off \
	 --filter-distribute-suggestion on \
     --model-name "$MODEL_NAME" \
     --model-url "$MODEL_URL" \
     --temperature "$temp"

    # # # # 2. Clang+NoRemarks
    "${ORCHESTRATOR}" "${TSVC_DIR}" \
     --name "t${temp}_clang_no_remarks" \
     --max-jobs "$MAX_JOBS" \
     --num-attempts "$NUM_ATTEMPTS" \
     --compiler clang \
     --vectorizer-compiler clang \
     --compiler-feedback off \
     --oracle-remarks off \
     --model-name "$MODEL_NAME" \
     --model-url "$MODEL_URL" \
     --temperature "$temp"

	# # # 4. Clang+NewRemarks
    "${ORCHESTRATOR}" "${TSVC_DIR}" \
     --name "t${temp}_clang_new_remarks" \
     --max-jobs "$MAX_JOBS" \
     --num-attempts "$NUM_ATTEMPTS" \
     --compiler clang_21.1.8_canary \
     --vectorizer-compiler clang \
     --compiler-feedback on \
     --oracle-remarks off \
     --filter-distribute-suggestion off \
     --model-name "$MODEL_NAME" \
     --model-url "$MODEL_URL" \
     --temperature "$temp"

    # # # 4.5 Clang+NewRemarks+FilterDistribute
    "${ORCHESTRATOR}" "${TSVC_DIR}" \
     --name "t${temp}_clang_new_remarks_filt_dist" \
     --max-jobs "$MAX_JOBS" \
     --num-attempts "$NUM_ATTEMPTS" \
     --compiler clang_21.1.8_canary \
     --vectorizer-compiler clang \
     --compiler-feedback on \
     --oracle-remarks off \
     --filter-distribute-suggestion on \
     --model-name "$MODEL_NAME" \
     --model-url "$MODEL_URL" \
     --temperature "$temp"


    # 3. Clang+OracleRemarks+FilterDistribute
    "${ORCHESTRATOR}" "${TSVC_DIR}" \
     --name "t${temp}_clang_oracle_remarks_filt_dist" \
     --max-jobs "$MAX_JOBS" \
     --num-attempts "$NUM_ATTEMPTS" \
     --compiler clang \
     --vectorizer-compiler clang \
     --compiler-feedback on \
     --oracle-remarks on \
     --filter-distribute-suggestion on \
     --model-name "$MODEL_NAME" \
     --model-url "$MODEL_URL" \
     --temperature "$temp"

	# 3.5. Clang+OracleRemarks
    "${ORCHESTRATOR}" "${TSVC_DIR}" \
     --name "t${temp}_clang_oracle_remarks" \
     --max-jobs "$MAX_JOBS" \
     --num-attempts "$NUM_ATTEMPTS" \
     --compiler clang \
     --vectorizer-compiler clang \
     --compiler-feedback on \
     --oracle-remarks on \
     --filter-distribute-suggestion off \
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
