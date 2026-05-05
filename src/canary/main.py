import subprocess
from typing import TypedDict, Optional

# ====---- Main ----====#
import argparse
from langchain_openai import ChatOpenAI
from canary.agent import Agent, RunConfig, RunResult


def main():
    # Parse arguments
    parser = argparse.ArgumentParser(description="Canary argument parser")

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "--model",
        help="Model name",
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8001/v1",
        help="Base URL for the LLM API",
    )
    parser.add_argument(
        "--api-key",
        default="hehefunnykey",
        help="Key for the LLM API",
    )
    parser.add_argument(
        "--temperature",
        default=0.8,
        help="Model temperature",
    )
    parser.add_argument(
        "--kernel",
        required=True,
        help="Original kernel C file",
    )
    parser.add_argument(
        "--bitcode",
        required=True,
        help="Original kernel bitcode file",
    )

    args = parser.parse_args()

    # Setup the LLM server
    llm = ChatOpenAI(
        model=args.model,
        api_key=args.api_key,
        base_url=args.api_url,
        temperature=args.temperature,
        request_timeout=86400,
    )

    # Initialize the agent.
    agent = Agent(args.bitcode, llm)

    # Read the kernel source into a string.
    with open(args.kernel, "r") as file:
        kernel_content = file.read()

    # Run the agent.
    result: RunResult = agent.run(
        RunConfig(
            run_id="test",
            kernel=kernel_content,
            temperature=args.temperature,
        )
    )


if __name__ == "__main__":
    main()
