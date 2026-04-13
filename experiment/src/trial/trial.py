# TODO: Pydantic for plumbing

class Trial:
    def __init__(self,
                 trial_number,
                 make_command,
                 run_command,
                 compiler,
                 compiler_diagnostics,
                 handwritten_diagnostics,
                 llm_name,
                 llm_url,
                 temperature,
                 iterations,
                 skip_files,
                 skip_funcs):
        self.trial_number = trial_number
        self.make_command = make_command
        self.run_command = run_command
        self.compiler = compiler
        self.compiler_diagnostics = compiler_diagnostics
        self.handwritten_diagnostics = handwritten_diagnostics
        self.llm_name = llm_name
        self.llm_url = llm_url
        self.temperature = temperature
        self.iterations = iterations
        self.skip_files = skip_files
        self.skip_funcs = skip_funcs
        self.result = None

    def finished(self):
        return self.result is not None

    def get_result(self):
        return self.result
