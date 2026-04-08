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

from abc import ABC, abstractmethod

class Worker(ABC):
    def __init__(self):
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
        pass

    def setup_trial(self):
        pass

    @property
    @abstractmethod
    def run_trial(self):
        pass

    def cleanup_trial(self):
        pass

    def cleanup_worker(self):
        pass
    
