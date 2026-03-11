#!/bin/bash

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)
TSVC_DIR="${SCRIPT_DIR}/../benchmarks/TSVC_2"
ORCHESTRATOR_DIR="${SCRIPT_DIR}/../src/orchestration/orchestrator.sh"

"${ORCHESTRATOR_DIR}" \
 "${TSVC_DIR}" \
 --name "TSVC_2_qwen_3_coder_no_remarks" \
 --max-jobs 128 \
 --num-attempts 10 \
 --compiler clang_trunk \
 --vectorizer-compiler clang \
 --compiler-feedback off \
 --model-name "Qwen/Qwen3-Coder-30B-A3B-Instruct" \
 --model-url "http://localhost:8000/v1" \
 --temperature 1.5

"${ORCHESTRATOR_DIR}" \
 "${TSVC_DIR}" \
 --name "TSVC_2_qwen_3_coder_base_remarks" \
 --max-jobs 128 \
 --num-attempts 10 \
 --compiler clang \
 --vectorizer-compiler clang \
 --compiler-feedback on \
 --model-name "Qwen/Qwen3-Coder-30B-A3B-Instruct" \
 --model-url "http://localhost:8000/v1" \
 --temperature 1.5

"${ORCHESTRATOR_DIR}" \
 "${TSVC_DIR}" \
 --name "TSVC_2_qwen_3_coder_new_remarks" \
 --max-jobs 128 \
 --num-attempts 10 \
 --compiler clang_trunk \
 --vectorizer-compiler clang \
 --compiler-feedback on \
 --model-name "Qwen/Qwen3-Coder-30B-A3B-Instruct" \
 --model-url "http://localhost:8000/v1" \
 --temperature 1.5




