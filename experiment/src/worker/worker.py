# this is a worker.
# this is the thing that's responsible for
# taking in a benchmark, processing it somehow, etc.
# it should have some functions like:
# start the trial in the docker image
# clean up everything in the docker image, etc.
# this is going to be the meat of the whole thing
# consider making this an abstract class, and making workers that
# inherit from it per experiment
# so, we would have a different worker for the rust experiments
# than the workers for the vectorization experiments

# TODO: Vectorize a small copy of TSVC with one function in it, using mini-swe-agent, Docker, and git diffs to track evolutions between turns.

from abc import ABC, abstractmethod
from pathlib import Path

from trial.trial import Trial, TrialResult


class Worker(ABC):
    def __init__(
        self,
        trial: Trial,
        bench_path: Path,
        worker_path: Path,
        results_dir: Path,
    ):
        self.trial = trial
        self.bench_path = bench_path
        self.worker_path = worker_path
        self.results_dir = results_dir

    def setup_worker(self):
        # Make a docker container
        # Copy the benchmark into it
        # Initialize a git repo
        pass

    def setup_trial(self):
        pass

    @abstractmethod
    def run_trial(self) -> TrialResult:
        # Compile Code -> Run Code -> Save Output ->
        # For Num Iterations / Max Turns { AI LLM Call + Execute What The AI Says And Save CLI Output + Git Diff } ->
        # Compile Code -> Run -> Verify Output
        pass

    def cleanup_trial(self):
        pass

    def cleanup_worker(self):
        pass

    def __compile_code(self):
        pass

    def __run_code(self):
        pass

    def __save_output(self):
        pass

    def __verify_output(self):
        pass
