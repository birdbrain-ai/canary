from langgraph.graph import StateGraph, END
from langchain_community.document_loaders import TextLoader
import os
import subprocess
import shutil
import argparse
import json
import tempfile
import sys
from pathlib import Path

# Add src/ to path so we can import from utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.more_helpers import extract_functions, find_files_with_ext, find_target_files, extract_file_context, match_remark_files, filter_remarks_by_function, extract_compilation_errors
from typing import TypedDict, Dict, List

from utils.logger import LLMLogger
import re


class FunctionInfo(TypedDict):
    name: str
    signature: str
    body: str
    full_text: str
    start_line: int
    end_line: int


class FunctionDraft:
    compile_success: bool
    run_success: bool
    dead_end: bool
    vectorization_success: bool
    runtime_s: float | None
    reviewer_feedback: str
    modified_function_text: FunctionInfo

    def __init__(self, function_info):
        self.compile_success = False
        self.run_success = False
        self.dead_end = False
        self.vectorization_success = False
        self.runtime_s = None
        self.reviewer_feedback = ""
        self.modified_function_text = function_info

    def to_dict(self):
        return {
            "compile_success": self.compile_success,
            "run_success": self.run_success,
            "dead_end": self.dead_end,
            "vectorization_success": self.vectorization_success,
            "runtime_s": self.runtime_s,
            "reviewer_feedback": self.reviewer_feedback,
            "modified_function_text": self.modified_function_text
        }


class VectorizationState(TypedDict):
    bench_path: str # const
    file_path: str # const
    make_command: str # const
    run_command: str # const
    use_compiler_feedback: bool # const
    use_clang_not_intel: bool # const
    use_oracle_remarks: bool # const
    filter_distribute_suggestion: bool # const
    model_name: str # const

    program_slice: str # const
    compiler_feedback: str
    optimization_remarks: str

    current_iteration: int
    max_iterations: int # const
    manager_chosen_i: int

    function_drafts: Dict[int, FunctionDraft]
    logger: 'LLMLogger'


# Helper: Serialize VectorizationState to JSON
def serialize_state_to_json(state: VectorizationState) -> dict:
    """
    Convert VectorizationState to a JSON-serializable dictionary.

    Args:
        state: The VectorizationState to serialize

    Returns:
        A dictionary that can be JSON-serialized
    """
    # Convert function_drafts to serializable format
    serialized_drafts = {}
    for iteration, draft in state["function_drafts"].items():
        serialized_drafts[str(iteration)] = draft.to_dict()

    # Create serialized state, excluding non-serializable fields
    serialized_state = {
        "bench_path": state["bench_path"],
        "file_path": state["file_path"],
        "make_command": state["make_command"],
        "run_command": state["run_command"],
        "use_compiler_feedback": state["use_compiler_feedback"],
        "model_name": state["model_name"],
        "program_slice": state["program_slice"],
        "compiler_feedback": state["compiler_feedback"],
        "optimization_remarks": state["optimization_remarks"],
        "current_iteration": state["current_iteration"],
        "max_iterations": state["max_iterations"],
        "manager_chosen_i": state["manager_chosen_i"],
        "function_drafts": serialized_drafts,
    }

    return serialized_state


# Node: compile_code
def compile_code(state: VectorizationState):
    '''
    Compiles code base. 
    This node is responsible for updating the following fields in VectorizationState.
    
    In state:
    1. compiler_feedback
    2. optimization_remarks

    In function_drafts[current_iteration]:
    1. compile_success
    2. vectorization_success

    '''
    logger = state["logger"]
    logger.log_state(state, "compile_code", "before")
    
    bench_path = state["bench_path"]
    cur_working_dir = os.getcwd()
    make_command = state["make_command"]
    current_file = state["file_path"]
    use_clang_not_intel = state["use_clang_not_intel"]

    current_iteration = state["current_iteration"]
    function_drafts = state["function_drafts"]
    cur_function_draft = function_drafts[current_iteration]
    cur_function_info = cur_function_draft.modified_function_text
    cur_function_name = cur_function_info["name"]

    os.chdir(bench_path)

    if current_iteration == 1 and function_drafts[0].vectorization_success:
        return {}
    
    subprocess.run(
        "find . -name '*.opt.yaml' -type f -delete",
        shell=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        "find . -name '*.optrpt' -type f -delete",
        shell=True,
        capture_output=True,
        text=True,
    )
    
    try:
        result = subprocess.run(
            make_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        logger.print("⚠️  Compilation timed out after 600s")
        cur_function_draft.compile_success = False
        cur_function_draft.vectorization_success = False
        function_drafts[current_iteration] = cur_function_draft
        os.chdir(cur_working_dir)
        result_dict = {
            "compiler_feedback": "Compilation timed out after 600 seconds. The build process was killed. Consider simplifying the code to reduce compilation time.",
            "optimization_remarks": "",
            "function_drafts": function_drafts
        }
        after_state = state.copy()
        after_state.update(result_dict)
        logger.log_state(after_state, "compile_code", "after")
        return result_dict

    # 1. Extract compilation feedback.
    # TODO(akash): obviously just replace this with a compiler option instead of filtering it manually. Just make the compiler only output warnings and errors instead of an insane quantity of notes.
    # Convert 0-indexed function line numbers to 1-indexed compiler line numbers
    func_start_line_1indexed = cur_function_info["start_line"] + 1
    func_end_line_1indexed = cur_function_info["end_line"] + 1
    compilation_feedback = extract_compilation_errors(
        result.stderr,
        line_range_start=func_start_line_1indexed,
        line_range_end=func_end_line_1indexed,
        target_file=current_file
    )

    # print(result)
    cur_function_draft.compile_success = result.returncode == 0

    # 2. Extract optimization remarks
    if use_clang_not_intel:
        all_remark_files = find_files_with_ext(bench_path, [".yaml"])
    else:
        all_remark_files = find_files_with_ext(bench_path, [".optrpt"])
    relevant_remark_files: List[str] = match_remark_files(current_file, all_remark_files, use_clang_not_intel)
    relevant_remarks: List[str] = []
    only_vec_remarks: List[str] = []
    for remark_file in relevant_remark_files:
        relevant_remarks.append(filter_remarks_by_function(remark_file,
                                                           cur_function_name,
                                                           False,
                                                           use_clang_not_intel))
        only_vec_remarks.append(filter_remarks_by_function(remark_file,
                                                           cur_function_name,
                                                           False,
                                                           use_clang_not_intel))
    optimization_remarks = "\n".join(relevant_remarks)
    only_vec_remarks = "\n".join(only_vec_remarks)
    if use_clang_not_intel:
        vectorization_success = "!Passed" in only_vec_remarks
    else:
        vectorization_success = re.search(r"was vectorized", optimization_remarks, re.IGNORECASE) is not None

    cur_function_draft.vectorization_success = vectorization_success

    function_drafts[current_iteration] = cur_function_draft
    
    os.chdir(cur_working_dir)

    result_dict = {
        "compiler_feedback": compilation_feedback,
        "optimization_remarks": optimization_remarks,
        "function_drafts": function_drafts
    }
    
    after_state = state.copy()
    after_state.update(result_dict)
    logger.log_state(after_state, "compile_code", "after")
    
    return result_dict


# Helper: Parse runtime from validation script output
def parse_runtime_from_output(output: str) -> float | None:
    """
    Parse RUNTIME_S: <value> from validation script stdout.

    Args:
        output: stdout from the validation script

    Returns:
        Runtime in seconds as float, or None if not found/invalid
    """
    match = re.search(r'RUNTIME_S:\s*([\d.]+)', output)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


# Node: run_code
def run_code(state: VectorizationState):
    '''
    Runs code
    This node is responsible for the following fields:

    In function_drafts[current_iteration],
    1. run_success
    2. runtime_s (parsed from RUNTIME_S: <value> in stdout)

    '''
    logger = state["logger"]
    logger.log_state(state, "run_code", "before")

    run_command = state['run_command']

    function_drafts = state["function_drafts"]
    current_iteration = state["current_iteration"]
    cur_function_draft = function_drafts[current_iteration]

    # Early exit: if compile failed, skip running and mark run as failed
    if not cur_function_draft.compile_success:
        cur_function_draft.run_success = False
        function_drafts[current_iteration] = cur_function_draft
        logger.log_state(state, "run_code", "after")
        return {
            "function_drafts": function_drafts
        }

    if current_iteration == 0 and function_drafts[current_iteration].vectorization_success:
        cur_function_draft.run_success = True
        function_drafts[current_iteration] = cur_function_draft
        return {
            "function_drafts": function_drafts
        }

    # Early exit: No run command provided, so the run is presumed successful
    if not run_command:
        logger.print("No run command provided")
        cur_function_draft.run_success = True
        function_drafts[current_iteration] = cur_function_draft
        logger.log_state(state, "run_code", "after")
        return {
            "function_drafts": function_drafts
        }

    bench_path = state['bench_path']
    cur_working_dir = os.getcwd()

    # Serialize state to JSON and write to temporary file
    serialized_state = serialize_state_to_json(state)
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    temp_file_path = temp_file.name

    try:
        json.dump(serialized_state, temp_file, indent=2)
        temp_file.close()

        os.chdir(bench_path)

        # Append the temp file path to the run command

        # perf stat -e 'cache-misses,cache-references,instructions,cycles'

        full_command = f"{run_command} {temp_file_path}"

        try:
           result = subprocess.run(
               full_command,
               shell=True,
               capture_output=True,
               text=True,
               timeout=600
           )

           # Log stdout and stderr from validation script
           if result.stdout:
               logger.print(result.stdout, end='')
           if result.stderr:
               logger.print(result.stderr, end='')
        # Early exit: Timeout, so run failed
        except subprocess.TimeoutExpired:
            logger.print("Running the benchmark took too much time")
            cur_function_draft.run_success = False
            function_drafts[current_iteration] = cur_function_draft
            logger.log_state(state, "run_code", "after")
            os.chdir(cur_working_dir)
            return {
                "function_drafts": function_drafts
            }

        # Main case: either the run throws an error, or it succeeds
        if result.returncode != 0:
            logger.print(f"Running the benchmark threw an error: {result.returncode}")

        os.chdir(cur_working_dir)
        cur_function_draft.run_success = result.returncode == 0

        # reviewer_feedback now holds perf data!
        cur_function_draft.reviewer_feedback = result.stderr

        # Parse runtime from stdout if run succeeded
        if cur_function_draft.run_success and result.stdout:
            cur_function_draft.runtime_s = parse_runtime_from_output(result.stdout)
            if cur_function_draft.runtime_s is not None:
                logger.print(f"Runtime: {cur_function_draft.runtime_s:.6f}s")

        function_drafts[current_iteration] = cur_function_draft
        logger.log_state(state, "run_code", "after")
        return {
            "function_drafts": function_drafts
        }
    finally:
        # Clean up temporary file
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)


# Node: engineer
def engineer(state: VectorizationState):
    '''
    This function is responsible for applying suggestions to a code base.

    In function_drafts[current_iteration],
    1. modified_function_text

    And, responsible for writing to file
    '''

    logger = state["logger"]
    logger.log_state(state, "engineer", "before")

    current_iteration = state["current_iteration"]
    function_drafts = state["function_drafts"]

    if function_drafts[0].vectorization_success:
        logger.print("WE ARE SKIPPING THIS ITERATION BECAUSE THE FUNCTION WAS ALREADY VECTORIZED!")
        return {
            "current_iteration": current_iteration + 1
        }

    print("Starting trial")
    print(os.getcwd())

    # This code launches a docker image with pi as the primary executable.
    # It mounts a pi config dir, it mounts the benchmark directory,
    # And it passes CLI options to pi (--mode, --no-session, --provider,
    # --model, -p, etc.)

    # The command is:
    # pi --provider vllm_slurm --model google/gemma-4-31B-it -p "Transform functions in kernel.c so they are easier to vectorize. After every change, use the compile tool to ensure your changes compile."
    
    cmd = [
        "pi",
        "--provider", "vllm_slurm",
        "--model", state["model_name"],
        "-p", "try and transform functions in c_prog.cpp so they are easier to vectorize. after every change, use your bash tool to call clang, and ensure that your changes compile.",
    ]

    script_dir = Path(__file__).resolve().parent
    pi_coding_agent_dir : Path = script_dir / ".pi"
    env = {**os.environ, "PI_CODING_AGENT_DIR": str(pi_coding_agent_dir.resolve())}

    bench_path = state["bench_path"]
    log_path = os.path.join(bench_path, "pi_output.log")

    with subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    ) as proc, open(log_path, "w", encoding="utf-8") as f:
        for line in proc.stdout:
            # print(line, end="")
            f.write(line)
            f.flush()
        returncode = proc.wait()

    if returncode != 0:
        raise RuntimeError(f"pi exited with code {returncode}")

    result_dict = {
        "function_drafts": function_drafts,
        "current_iteration": current_iteration + 1
    }

    after_state = state.copy()
    after_state.update(result_dict)
    logger.log_state(after_state, "engineer", "after")

    return result_dict


# Node: finalize
def finalize(state: VectorizationState):
    logger = state["logger"]
    logger.log_state(state, "finalize", "before")

    function_drafts = state["function_drafts"]

    final_draft = None
    the_thing_i_want_to_return = 0

    # Find all valid drafts (compile_success, run_success, vectorization_success all true)
    valid_drafts = []
    for i, draft in function_drafts.items():
        if draft.compile_success and draft.run_success and draft.vectorization_success:
            valid_drafts.append((i, draft))

    if valid_drafts:
        # Among valid drafts, pick the one with the lowest runtime
        # If runtime is None, treat it as infinity (less preferred)
        drafts_with_runtime = [(i, d) for i, d in valid_drafts if d.runtime_s is not None]

        if drafts_with_runtime:
            # Pick the draft with the lowest runtime
            best_i, best_draft = min(drafts_with_runtime, key=lambda x: x[1].runtime_s)
            final_draft = best_draft
            the_thing_i_want_to_return = best_i
        else:
            # No runtime data available, fall back to most recent valid draft
            best_i, best_draft = max(valid_drafts, key=lambda x: x[0])
            final_draft = best_draft
            the_thing_i_want_to_return = best_i

    # Fall back to draft 0 if no valid drafts
    if final_draft is None:
        final_draft = function_drafts[0]
        the_thing_i_want_to_return = 0

    logger.log_state(state, "finalize", "after")
    return {
        "manager_chosen_i": the_thing_i_want_to_return
    }

# Decision point: should_continue
def should_continue(state: VectorizationState):
    if state["current_iteration"] < state["max_iterations"]:
        return "continue"
    else:
        return "done"

    
def create_vectorization_graph():
    workflow = StateGraph(VectorizationState)

    workflow.add_node("compile_code", compile_code)
    workflow.add_node("run_code", run_code)
    workflow.add_node("engineer", engineer)
    workflow.add_node("finalize", finalize)

    workflow.set_entry_point("compile_code")
    workflow.add_edge("compile_code", "run_code")
    workflow.add_conditional_edges(
        "run_code",
        should_continue,
        {
            "continue": "engineer",
            "done": "finalize"
        }
    )
    workflow.add_edge("engineer", "compile_code")
    # workflow.add_edge("run_code", "engineer")        
    # workflow.add_edge("engineer", "finalize")

    workflow.add_edge("finalize", END)
    
    return workflow.compile()
    
    
def vectorize_benchmark(benchmark_dir: str,
                        make_command: str,
                        max_iterations: int,
                        run_command: str,
                        model_name: str,
                        use_compiler_feedback: bool = True,
                        use_clang_not_intel: bool = True,
                        use_oracle_remarks: bool = False,
                        filter_distribute_suggestion: bool = False,
                        results_dir: str = "results",
                        skip_files: set = None,
                        skip_functions: set = None,
                        ):
    skip_files = skip_files or set()
    skip_functions = skip_functions or set()

    abs_benchmark_dir = os.path.realpath(benchmark_dir)
    benchmark_name = os.path.basename(abs_benchmark_dir)
    opt_dir = os.path.join(results_dir, f"{benchmark_name}_opt")
    current_dir = os.getcwd()

    print(f"{'='*60}\n")
    print(f"Vectorizing {benchmark_dir} ")
    print(f"Make command: {make_command}")
    print(f"Max iterations: {max_iterations}")
    print(f"Absolute Benchmark: {abs_benchmark_dir}")
    print(f"Benchmark name: {benchmark_name}")
    print(f"Results Dir: {results_dir}")
    print(f"Opt Dir: {opt_dir}")
    print(f"Current Dir: {current_dir}")
    print(f"{'='*60}\n")

    print(f"Copying {benchmark_dir}")
    if os.path.exists(opt_dir):
        shutil.rmtree(opt_dir)
    shutil.copytree(abs_benchmark_dir, opt_dir)
    print(f"{'='*60}\n")

    print("Creating vectorization workflow graph")
    vectorization_graph = create_vectorization_graph()

    # Initialize logger once for the entire benchmark
    log_dir = os.path.join(results_dir, f"{benchmark_name}_logs")
    logger = LLMLogger(log_dir)

    target_files = find_target_files(opt_dir)
    if skip_files:
        target_files = [f for f in target_files if os.path.basename(f) not in skip_files]
    for current_file in target_files:
        # Initial read to find out how many functions we have
        loader = TextLoader(current_file, encoding='utf-8')
        document = loader.load()
        initial_code: str = document[0].page_content
        initial_functions: List[FunctionInfo] = extract_functions(initial_code)
        if skip_functions:
            initial_functions = [f for f in initial_functions if f["name"] not in skip_functions]
        num_functions = len(initial_functions)

        print(f"Starting to vectorize {current_file}")
        print("function,base_compile,base_run,base_vec,base_runtime,opt_compile,opt_run,opt_vec,opt_runtime")

        for func_idx in range(num_functions):
            # Re-read the file every time to get updated line numbers if it was modified
            loader = TextLoader(current_file, encoding='utf-8')
            document = loader.load()
            code: str = document[0].page_content
            
            # Re-extract context and functions to handle line number shifts
            program_slice: str = extract_file_context(code)
            functions: List[FunctionInfo] = extract_functions(code)
            if skip_functions:
                functions = [f for f in functions if f["name"] not in skip_functions]

            if func_idx >= len(functions):
                logger.print(f"⚠️  Warning: Expected {num_functions} functions but found {len(functions)} in {current_file} at index {func_idx}")
                continue

            function = functions[func_idx]
            
            # Construct an initial state
            # initial_function_draft: FunctionDraft = FunctionDraft(function)
            initial_state = VectorizationState(
                bench_path=opt_dir,
                file_path=current_file,
                make_command=make_command,
                run_command=run_command,
                use_compiler_feedback=use_compiler_feedback,
                use_clang_not_intel=use_clang_not_intel,
                use_oracle_remarks=use_oracle_remarks,
                filter_distribute_suggestion=filter_distribute_suggestion,
                model_name=model_name,

                program_slice=program_slice,
                compiler_feedback="",
                optimization_remarks="",

                current_iteration=0,
                max_iterations=max_iterations,
                manager_chosen_i=0,
                function_drafts={
                    0: FunctionDraft(function),
                    1: FunctionDraft(function),
                },
                logger=logger,
            )

            # Pass it to LangGraph workflow: Compile -> Run -> Reviewer -> Manager -> Engineer
            logger.print(f"🚀 Starting vectorization workflow for function: {function['name']} in {os.path.basename(current_file)}")
            final_state = vectorization_graph.invoke(initial_state, config={"recursion_limit": 1000})

            # Print the Loop Table to stdout
            final_function_drafts = final_state["function_drafts"]
            finalized_i = final_state["manager_chosen_i"]
            base_function_draft = final_function_drafts[0]
            func_name = base_function_draft.modified_function_text["name"]
            base_compile = base_function_draft.compile_success
            base_run = base_function_draft.run_success
            base_vec = base_function_draft.vectorization_success
            base_runtime = base_function_draft.runtime_s if base_function_draft.runtime_s is not None else "N/A"
            final_function_draft = final_function_drafts[finalized_i]
            opt_compile = final_function_draft.compile_success
            opt_run = final_function_draft.run_success
            opt_vec = final_function_draft.vectorization_success
            opt_runtime = final_function_draft.runtime_s if final_function_draft.runtime_s is not None else "N/A"

            print(f"{func_name},{base_compile},{base_run},{base_vec},{base_runtime},{opt_compile},{opt_run},{opt_vec},{opt_runtime}")

    return {"success": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Add vectorization pragmas to C/C++ code using iterative AI analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Benchmark directory mode (recommended):
  python vectorizer.py my_benchmark --make-command "make" --iterations 3

  # With custom model and results directory:
  python vectorizer.py my_benchmark --make-command "make" --iterations 3 \\
    --model-name "meta-llama/Llama-3-8B" --model-url "http://localhost:8000/v1" \\
    --results-dir results
        """
    )

    parser.add_argument(
        "path",
        type=str,
        help="Path to C++ file (legacy mode) or benchmark directory (recommended)"
    )

    parser.add_argument(
        "--make-command", "-m",
        type=str,
        default=None,
        help="Build command for benchmark (e.g., 'make'). Required for directory mode."
    )

    parser.add_argument(
        "--run-command", "-r",
        type=str,
        default="",
        help="Optional command to validate function behavior. "
             "The script receives a JSON file path as its first argument containing the full VectorizationState. "
             "Exit code 0 indicates success, non-zero indicates failure."
    )

    parser.add_argument(
        "--iterations", "-n",
        type=int,
        default=3,
        help="Number of iterative refinement passes (default: 3)"
    )

    parser.add_argument(
        "--compiler-feedback",
        type=str,
        choices=["on", "off"],
        default="on",
        help="Whether to provide compiler feedback and optimization remarks in LLM prompts. "
             "When 'off', feedback is still collected for logging but not provided to the LLM. "
             "(default: on)"
    )

    parser.add_argument(
        "--compiler",
        type=str,
        choices=["clang", "intel"],
        default="clang",
        help="Compiler toolchain to use for optimization remarks formatting. "
             "(default: clang)"
    )

    parser.add_argument(
        "--temperature", "-t",
        type=float,
        default=1.0,
        help="Temperature for the LLM (default: 1.0)"
    )

    parser.add_argument(
        "--model-name",
        type=str,
        default="google/gemma-4-31B-it",
        help="Model name for the LLM (default: google/gemma-4-31B-it)"
    )

    parser.add_argument(
        "--model-url",
        type=str,
        default="http://localhost:8001/v1",
        help="Base URL for the LLM API (default: http://localhost:8001/v1)"
    )

    parser.add_argument(
        "--results-dir",
        type=str,
        default="results",
        help="Directory for output results (default: results)"
    )

    parser.add_argument(
        "--oracle-remarks",
        type=str,
        choices=["on", "off"],
        default="off",
        help="Whether to insert oracle remark supplements into the prompt. "
             "These provide additional hand-crafted hints beyond standard compiler remarks. "
             "(default: off)"
    )

    parser.add_argument(
        "--filter-distribute-suggestion",
        type=str,
        choices=["on", "off"],
        default="off",
        help="Whether to filter out the 'distribute(enable)' suggestion from optimization remarks. "
             "(default: off)"
    )

    parser.add_argument(
        "--skip-files",
        type=str,
        default="",
        help="Comma-separated filenames to skip (basename match, e.g. 'dummy.c,common.c')"
    )

    parser.add_argument(
        "--skip-functions",
        type=str,
        default="",
        help="Comma-separated function names to skip (e.g. 'main,time_function')"
    )

    args = parser.parse_args()

    assert not (args.oracle_remarks == "on" and args.compiler != "clang"), \
        "Oracle remark supplements are only available for clang. Use --compiler clang or disable --oracle-remarks."

    # Determine mode based on path type
    if os.path.isdir(args.path):
        # Directory mode (benchmark)
        if not args.make_command:
            print("✗ Error: --make-command is required for benchmark directory mode")
            print("Example: python vectorizer.py my_benchmark --make-command 'make'")
            exit(1)

        results_dir = os.path.realpath(args.results_dir)
        os.makedirs(results_dir, exist_ok=True)

        skip_files = set(f.strip() for f in args.skip_files.split(",") if f.strip())
        skip_functions = set(f.strip() for f in args.skip_functions.split(",") if f.strip())

        result = vectorize_benchmark(
            args.path,
            args.make_command,
            max_iterations=args.iterations,
            run_command=args.run_command,
            model_name=args.model_name,
            use_compiler_feedback=(args.compiler_feedback == "on"),
            use_clang_not_intel=("clang" in args.compiler),
            use_oracle_remarks=(args.oracle_remarks == "on"),
            filter_distribute_suggestion=(args.filter_distribute_suggestion == "on"),
            results_dir=results_dir,
            skip_files=skip_files,
            skip_functions=skip_functions,
        )
    else:
        print(f"✗ Error: Directory not found: {args.path}")
        exit(1)

    # Exit with appropriate code
    if result and result.get('success'):
        exit(0)
    else:
        exit(1)
