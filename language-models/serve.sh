#!/bin/bash
# serve.sh — Serve a model via vLLM
#
# Usage: sbatch serve.sh [PORT]
#   PORT defaults to 8000 if not provided

#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:a40:2
#SBATCH --mem=64G
#SBATCH --cpus-per-task=8
#SBATCH --output=%j-%x.out

PORT=${1:-8000}

echo "Starting vLLM server on port $PORT ..."
echo "Hostname: $(hostname)"

./run.sh python3 -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-Coder-7B-Instruct \
    --host 0.0.0.0 \
    --port $PORT \
    --trust-remote-code \
    --dtype auto \
	--tensor-parallel-size 2

