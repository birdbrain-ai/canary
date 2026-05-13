import sys
import argparse
from pathlib import Path
from typing import Callable

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
        "path",
        help="Path to kernel(s) to run."
        "If given a directory, runs on all C source files.",
    )
    parser.add_argument(
        "--model",
        required=True,
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
        "--filter",
        nargs="+",
        help="One or more remarks to filter. Example: <PASS>:<REMARK>",
    )
    parser.add_argument(
        "--ablate",
        nargs="+",
        help="One or more remarks to ablate. Example: <PASS>:<REMARK>",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    args = parser.parse_args()

    # Collect the kernels to evaluate.
    path = Path(args.path)
    if path.is_dir():
        kernels = sorted(list(path.rglob("*.c")))
    else:
        kernels = [str(path)]

    # Determine the set of ablation configurations.
    ablation_configs: list[str | None] = [None] + (args.ablate or [])

    # Run on each kernel.
    for kernel in kernels:
        # Read the kernel source into a string.
        with open(kernel, "r") as file:
            kernel_content = file.read()

        # Run with each ablation configuration.
        for ablated in ablation_configs:
            filters = (args.filter or []) + ([ablated] if ablated else [])

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

            # Run the agent.
            result: RunResult = agent.run(
                RunConfig(
                    run_id=f"{kernel}_{ablated or 'base'}",
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
