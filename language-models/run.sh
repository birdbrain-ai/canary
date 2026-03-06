#!/bin/bash
# run.sh — Execute a command inside the vLLM Apptainer container
# --nv passes NVIDIA drivers through for GPU access
# --bind ensures the HuggingFace cache is accessible inside the container
apptainer exec --nv \
    --bind /nyx-projects/jtm2066/.cache:/root/.cache \
    --env HF_HOME=/root/.cache/huggingface \
    vllm.sif $*
