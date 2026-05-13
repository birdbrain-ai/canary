# canary
Evaluating compiler diagnostics in the context of AI coding agents.

![An Inquisitive Canary](https://www.zooplus.co.uk/magazine/wp-content/uploads/2017/12/AdobeStock_127952455-1024x683.webp)

## Dependencies
Requires [uv](https://docs.astral.sh/uv/).

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

_Optional:_ Run developer recipes with [`just`](https://just.systems/man/en/installation.html)

## Setup
```bash
uv sync
```

## Running
Run the canary workflow to optimize your C source file.
```bash
uv run canary \
   /path/to/kernel.c \    # C file to optimize
   --model YOUR_FAVORITE_MODEL \   # LLM model
   --api-url http://llm-server.url # LLM API URL
```

You can also run over all C source files in a directory.
```bash
uv run canary /path/to/kernels/ ...
```

Add filter(s) to disable specific remarks:
```bash
uv run canary \
   --filter PASS1:REMARK1 PASS2:REMARK2 \
   ...
```

You can also set up an ablation for specific remark(s):
```bash
uv run canary ... \
   --ablate PASS1:REMARK1 PASS2:REMARK2
```
This will run three experiments:
1. No filters
2. Filter `PASS1:REMARK1`
3. Filter `PASS2:REMARK2`

Specify temperature(s) to sweep.
```bash
uv run canary ... \
   --temperature 0.2 0.8 1.2
```