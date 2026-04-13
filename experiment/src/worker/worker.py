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
import os
import shutil
import docker

class Worker(ABC):
    def __init__(self):
        self.bench_path = ""
        self.worker_path = ""
        self.trial_number = ""
        self.make_command = ""
        self.run_command = ""
        self.compiler = ""
        self.compiler_diagnostics = ""
        self.handwritten_diagnostics = ""
        self.llm_name = ""
        self.llm_url = ""
        self.temperature = ""
        self.iterations = ""
        self.results_dir = ""
        self.skip_files = []
        self.skip_funcs = []
        self.result = None

    def setup_worker(self):
        client = docker.from_env()
        client.containers.run('alpine', 'echo hello world')

        # Make a docker container
        # Copy the benchmark into it
        # Initialize a git repo
        pass

    def setup_trial(self):
        pass

    @property
    @abstractmethod
    def run_trial(self):
        # This will usually look like
        # Compile Code -> Run Code -> Save Output -> For Num Iterations / Max Turns { AI LLM Call + Execute What The AI Says And Save CLI Output + Git Diff } -> Compile Code -> Run -> Verify Output
        pass

    def cleanup_trial(self):
        pass

    def cleanup_worker(self):
        pass

    # Consider implementing some common utilities that we can call from the run_trial
    def __compile_code(self):
        pass

    def __run_code(self):
        pass

    def __save_output(self):
        pass

    def __verify_output(self):
        pass
