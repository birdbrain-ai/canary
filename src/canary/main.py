import sys
import argparse
from langchain_openai import ChatOpenAI

from canary.agent import Agent
from canary.run import RunConfig, RunResult
from canary.remark import Remark


def build_remark_filter(filters: list[str] | None) -> Callable[[Remark], bool]:
    def remark_filter(remark: Remark) -> bool:
        if filters is None:
            return False
        for f in filters:
            try:
                pass_name, remark_name = f.split(":")
                if remark.Pass == pass_name and remark.Name == remark_name:
                    return True
            except ValueError:
                print(f"ERROR: Malformed filter {f}, expected PASS:REMARK")
                sys.exit(1)
        return False

    return remark_filter


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
        "--filter",
        nargs="+",
        help="One or more remarks to filter. Example: <PASS>:<REMARK>",
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
    agent = Agent(
        llm,
        remark_filter=build_remark_filter(args.filter),
    )

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

    # Print summary
    if args.verbose:
        if result.success:
            print(f"{args.kernel},{result.attempts},success,")
        else:
            print(f"{args.kernel},{result.attempts},failure,{result.reason}")


if __name__ == "__main__":
    main()
