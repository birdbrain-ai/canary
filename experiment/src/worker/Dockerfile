# Dockerfile that defines the environment for the container executing LLM commands
# I must mount the directory to the compiler I want to give my experiment access to
# Mount clang so it's on path

FROM ubuntu:22.04

# Set ENV equal to compiler
ENV PATH="/mnt/llvm/bin:${PATH}"
# COPY: TSVC benchmark into the docker image


