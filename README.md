# canary
Evaluating compiler diagnostics in the context of AI coding agents.

## Dependencies
Requires [uv](https://docs.astral.sh/uv/).

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Setup
```bash
uv sync
```

## Running
```bash
uv run canary \
   --kernel /path/to/kernel.c \    # C file to optimize
   --bitcode /path/to/kernel.bc \  # LLVM IR of kernel
   --model YOUR_FAVORITE_MODEL \   # LLM model
   --api-url http://llm-server.url # LLM API URL
```