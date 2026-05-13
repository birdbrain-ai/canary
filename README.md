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
```bash
uv run canary \
   --kernel /path/to/kernel.c \    # C file to optimize
   --model YOUR_FAVORITE_MODEL \   # LLM model
   --api-url http://llm-server.url # LLM API URL
```

Add filter(s) to disable specific remarks:
```bash
uv run canary \
   --filter PASS1:REMARK1 PASS2:REMARK2 \
   ...
```