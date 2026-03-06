#!/bin/bash
# test_query.sh — Send a test query to the vLLM server
#
# Usage: ./test_query.sh PORT
#   PORT is the allocated port shown in the portforward output file

PORT=${1:-8000}

echo "Testing vLLM server on localhost:$PORT ..."
echo ""

curl -s http://localhost:$PORT/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{
        "model": "Qwen/Qwen2.5-Coder-7B",
        "messages": [
            {"role": "user", "content": "Write a Python function that computes the fibonacci sequence."}
        ],
        "max_tokens": 256,
        "temperature": 0.7
    }' | python3 -m json.tool

echo ""
echo "If you see a JSON response with a 'choices' field, the server is working."
