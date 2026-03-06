#!/bin/bash
# build.sh — Build the vLLM Apptainer image on a compute node
# This can take 10-20 minutes depending on network speed

echo "Building vLLM Apptainer image..."
srun \
    --mem 16G \
    --cpus-per-task 4 \
    apptainer build \
    --force \
    vllm.sif \
    vllm.def

echo "Build complete. Image saved as vllm.sif"
