# TODO: Pydantic for plumbing

import json
from queue import Queue

class Experiment:
    def __init__(self,
                 config_json):
        # clang: clang_canary_21.1.8, clang_trunk, clang_canary, clang
        # icx: icx-2025.3, icx...
        with open(config_json, 'r') as file:
            config = json.load(file)

        # get all the relevant things from config, and assign defaults
        # i don't know what the relevant fields in config should be
        self.experiment_name = ""
        self.compiler = ""
        self.compiler_for_makefile = ""
        self.compiler_diagnostics = ""
        self.handwritten_diagnostics = ""
        self.topic = "" # ["vectorization", "rust"]. I should put this in an enum or something
        self.llm_name = ""
        self.llm_url = ""
        self.temperature = ""
        self.iterations = ""
        self.num_trials = ""
        self.results_dir = ""
        self.data_dir = ""
        self.max_jobs: int = 8
        self.skip_files = []
        self.skip_funcs = []
        
        if self.topic == "vectorization":
            self.filter_distribute_suggestion = "off" # whatever
        if self.topic == "rust":
            pass

        # Make work queue: Trials go into the Queue
        self.queue = Queue()
