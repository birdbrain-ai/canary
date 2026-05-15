import argparse
import json
import sys
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable

from langchain_openai import ChatOpenAI
from rich.console import Group
from rich.live import Live
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn
from rich.text import Text

from canary.agent import Agent
from canary.remark import Remark
from canary.run import RunConfig, RunResult
from canary.console import console


# ====---- Command-line Arguments ----==== #
def parse_args():
    parser = argparse.ArgumentParser(description="Canary argument parser")

    parser.add_argument(
        "path",
        help="Path to kernel(s) to run. If given a directory, runs on all C source files.",
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=1,
        help="Trials to run of each configuration",
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
        type=float,
        nargs="+",
        default=[0.8],
        help="Model temperature(s) to sweep over",
    )
    parser.add_argument(
        "--filter",
        nargs="+",
        help="Base PASS:REMARK filters applied to every run. Example: <PASS>:<REMARK>",
    )
    parser.add_argument(
        "--ablate",
        nargs="+",
        help="PASS:REMARK remarks to ablate — one extra run per entry. Example: <PASS>:<REMARK>",
    )
    parser.add_argument(
        "--jobs",
        "-j",
        type=int,
        default=1,
        help="Number of parallel workers (default: 1)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    return parser.parse_args()


# ====---- Helpers ----==== #
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
                console.print(f"ERROR: Malformed filter {f}, expected PASS:REMARK")
                sys.exit(1)
        return False

    return remark_filter


_thread_local = threading.local()


def _get_agent(
    filters: list[str],
    temperature: float,
    model: str,
    api_key: str,
    api_url: str,
) -> Agent:
    """Return a cached Agent for this thread, keyed on (filters, temperature)."""
    key = (tuple(filters), temperature)
    if not hasattr(_thread_local, "agents"):
        _thread_local.agents = {}
    if key not in _thread_local.agents:
        llm = ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=api_url,
            temperature=temperature,
            request_timeout=86400,
        )
        _thread_local.agents[key] = Agent(
            llm,
            remark_filter=build_remark_filter(filters),
        )
    return _thread_local.agents[key]


def run_one(
    config: RunConfig,
    model: str,
    api_key: str,
    api_url: str,
    verbose: bool = False,
) -> tuple[RunConfig, RunResult]:

    agent = _get_agent(config.filters, config.temperature, model, api_key, api_url)
    result, steps = agent.run(config, verbose=verbose)
    return config, result, steps


# ====---- Main entry ----==== #
def main():
    # Parse command-line arguments.
    args = parse_args()

    # Find the kernel(s) to run on.
    path = Path(args.path)
    kernels = sorted(path.rglob("*.c")) if path.is_dir() else [path]
    if not kernels:
        console.print(f"ERROR: No C files found at {path}")
        sys.exit(1)

    # Construct the set of ablation configurations.
    base_filters = args.filter or []
    ablation_configs: list[str | None] = [None] + (args.ablate or [])

    # Construct the set of run configurations.
    configs = [
        RunConfig(
            kernel,
            temp,
            ablated,
            base_filters + ([ablated] if ablated else []),
        )
        for kernel in kernels
        for temp in args.temperature
        for ablated in ablation_configs
    ]

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%s")
    out_dir = Path("out") / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)
    result_json = out_dir / "result.json"
    steps_json = out_dir / "steps.json"

    nruns = len(configs) * args.trials
    console.print(
        f"Running {nruns} total run(s) ({len(kernels)} kernels x {len(args.temperature)} temperatures x {len(ablation_configs)} filters x {args.trials} trials)"
    )
    console.print(f"Results -> {result_json}\n")

    recent: deque[tuple[str, str]] = deque(maxlen=5)
    progress = Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn())

    def make_display() -> Group:
        log = Text()
        for ts, line in recent:
            log.append(f"[{ts}] ", style="dim green")
            log.append(line + "\n", style="dim")
        return Group(progress, log)

    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        with (
            open(result_json, "w") as rf,
            open(steps_json, "w") as sf,
            Live(make_display(), refresh_per_second=10) as live,
        ):
            task = progress.add_task("Running...", total=nruns)

            futures = (
                executor.submit(
                    run_one,
                    c,
                    args.model,
                    args.api_key,
                    args.api_url,
                    args.verbose,
                )
                for c in configs
                for _ in range(args.trials)
            )

            for future in as_completed(futures):
                config, result, steps = future.result()

                result_entry = {
                    "kernel": str(config.filepath),
                    "temperature": config.temperature,
                    "ablated": config.ablated,
                    "filters": config.filters,
                    "attempts": result.attempts,
                    "result": "success" if result.success else "failure",
                    "reason": result.reason,
                }
                steps_entry = {
                    "kernel": str(config.filepath),
                    "temperature": config.temperature,
                    "ablated": config.ablated,
                    "filters": config.filters,
                    "attempts": result.attempts,
                    "result": "success" if result.success else "failure",
                    "steps": steps,
                }
                rf.write(json.dumps(result_entry) + "\n")
                sf.write(json.dumps(steps_entry) + "\n")

                status = (
                    "nop"
                    if result.attempts == 0
                    else "success" if result.success else f"failure ({result.reason})"
                )
                recent.append((
                    datetime.now().strftime("%H:%M:%S"),
                    f"{config.filepath} temp={config.temperature} ablated={config.ablated or 'none'} → {status}",
                ))
                progress.advance(task)
                live.update(make_display())

    console.print(f"\nDone! Results in {result_json}, steps in {steps_json}")


if __name__ == "__main__":
    main()
