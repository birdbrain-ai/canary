import modal
from typing import TypedDict


# ------------------------------------------------------------------------------
# Modal LLM client
# ------------------------------------------------------------------------------
_llm_inference = None

def get_llm_response(prompt: str) -> str:
    """Get LLM response via Modal (deployed from modal_llm.py)."""
    global _llm_inference
    if _llm_inference is None:
        _llm_inference = modal.Cls.from_name("vectorizer-llm", "LLMInference")()
    return _llm_inference.generate.remote(prompt)


# ------------------------------------------------------------------------------
# Vectorization State
# ------------------------------------------------------------------------------
class SearchReplaceAction(TypedDict):
    search: str  # The exact text to search for
    replace: str  # The replacement text

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
    perf_feedback: str | None
    modified_function_text: FunctionInfo

    def __init__(self, function_info):
        self.compile_success = False
        self.run_success = False
        self.dead_end = False
        self.vectorization_success = False
        self.runtime_s = None
        self.perf_feedback = None
        self.modified_function_text = function_info

    def __init__(self):
        self.compile_success = False
        self.run_success = False
        self.dead_end = False
        self.vectorization_success = False
        self.runtime_s = None
        self.perf_feedback = None
        self.modified_function_text = {
            "name": "",
            "signature": "",
            "body": "",
            "full_text": "",
            "start_line": 0,
            "end_line": 0,
        }

        
    def to_dict(self):
        return {
            "compile_success": self.compile_success,
            "run_success": self.run_success,
            "dead_end": self.dead_end,
            "vectorization_success": self.vectorization_success,
            "runtime_s": self.runtime_s,
            "perf_feedback": self.perf_feedback,
            "modified_function_text": self.modified_function_text
        }


class VectorizationState(TypedDict):
    bench_path: str # const
    file_path: str # const
    make_command: str # const
    run_command: str # const
    use_compiler_feedback: bool # const
    use_clang_not_intel: bool # const

    program_slice: str # const
    compiler_feedback: str
    optimization_remarks: str

    original_draft: FunctionDraft
    new_draft: FunctionDraft

    
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
    bench_path = state["bench_path"]
    cur_working_dir = os.getcwd()
    make_command = state["make_command"]
    current_file = state["file_path"]
    use_clang_not_intel = state["use_clang_not_intel"]

    original_draft = state["original_draft"]
    original_draft_info = original_draft.modified_function_text
    cur_function_name = origina_draft_info["name"]

    os.chdir(bench_path)

    rm_result = subprocess.run(
        "find . -name '*.opt.yaml' -type f -delete",
        shell=True,
        capture_output=True,
        text=True,
    )
    
    result = subprocess.run(
        make_command,
        shell=True,
        capture_output=True,
        text=True,
    )

    # 1. Extract compilation feedback.
    # TODO(akash): obviously just replace this with a compiler option instead of filtering it manually. Just make the compiler only output warnings and errors instead of an insane quantity of notes.
    # Convert 0-indexed function line numbers to 1-indexed compiler line numbers
    func_start_line_1indexed = original_draft_info["start_line"] + 1
    func_end_line_1indexed = original_draft_info["end_line"] + 1
    compilation_feedback = extract_compilation_errors(
        result.stderr,
        line_range_start=func_start_line_1indexed,
        line_range_end=func_end_line_1indexed
    )
    original_draft_info.compile_success = result.returncode == 0

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
                                                           True,
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

    original_draft.vectorization_success = vectorization_success

    os.chdir(cur_working_dir)

    result_dict = {
        "compiler_feedback": compilation_feedback,
        "optimization_remarks": optimization_remarks,
        "original_draft": original_draft
    }
    
    return result_dict

# Node: run_code
def run_code(state: VectorizationState):
    '''
    Runs code
    This node is responsible for the following fields:

    In function_drafts[current_iteration],
    1. run_success
    2. runtime_s (parsed from RUNTIME_S: <value> in stdout)

    '''
    run_command = state['run_command']

    original_draft = state["original_draft"]
    
    # Early exit: if compile failed, skip running and mark run as failed
    if not cur_function_draft.compile_success:
        print("Something terribly wrong has happened because the base program failed to compile")
        
    # Early exit: No run command provided, so the run is presumed successful
    if not run_command:
        print("You didn't give me a run command")
        return {
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
            logger.print(f"Running the benchmark took too much time")
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


def engineer(state: VectorizationState):
    '''
    This function is responsible for applying suggestions to a code base.

    In function_drafts[current_iteration],
    1. modified_function_text

    And, responsible for writing to file
    '''

    logger = state["logger"]
    logger.log_state(state, "engineer", "before")

    program_slice = state["program_slice"]
    make_command = state["make_command"]
    file_path = state["file_path"]
    use_clang_not_intel = state["use_clang_not_intel"]
    current_iteration = state["current_iteration"]

    manager_chosen_i = state["manager_chosen_i"]
    function_drafts = state["function_drafts"]
    current_function_draft = function_drafts[manager_chosen_i]
    reviewer_feedback = current_function_draft.reviewer_feedback
    current_function_info = current_function_draft.modified_function_text

    # Determine what's currently in the file by finding the last written draft
    # The last written draft is the one from the previous iteration (current_iteration - 1)
    last_written_index = current_iteration - 1 if current_iteration > 0 else 0
    last_written_info = function_drafts[last_written_index].modified_function_text

    # Retry loop for syntax errors
    lint_errors = None
    previous_search_replace = None
    new_func_info = last_written_info  # Default to what's in the file if all attempts fail

    for attempt in range(MAX_LINT_RETRIES):
        if attempt > 0:
            logger.print(f"🔄 Retry attempt {attempt + 1}/{MAX_LINT_RETRIES} due to syntax errors")

        prompt = get_engineer_prompt(
            None,  # numbered_function_body no longer used
            current_function_info,
            program_slice,
            make_command,
            reviewer_feedback,
            previous_search_replace=previous_search_replace,
            lint_errors=lint_errors,
            use_clang_not_intel=use_clang_not_intel
        )

        # Use attempt number in call_type to avoid overwriting logs
        call_type = f"engineer_{attempt}" if attempt > 0 else "engineer"

        # Log prompt before API call (in case of failure)
        logger.log_llm_prompt(
            iteration=current_iteration,
            file_path=file_path,
            call_type=call_type,
            prompt=prompt,
            function_name=current_function_info["name"]
        )

        response: str = llm.invoke(prompt).content

        # Log complete call after success
        logger.log_llm_call(
            iteration=current_iteration,
            file_path=file_path,
            call_type=call_type,
            prompt=prompt,
            response=response,
            function_name=current_function_info["name"]
        )

        # Parse engineer agent's outputs into search-replace actions
        actions = parse_search_replace_output(response, logger)

        if actions is None:
            logger.print("⚠️  Failed to parse engineer output, retrying...")
            continue
        elif len(actions) == 0:
            logger.print("ℹ️  Engineer suggested no modifications")
            new_func_info = current_function_info
            # Write to file to keep tracking in sync with file contents
            write_function_to_file(
                file_path,
                new_func_info,
                replace_start=last_written_info["start_line"],
                replace_end=last_written_info["end_line"],
                logger=logger
            )
            break
        else:
            # Apply search-replace actions to create modified function
            new_func_info = apply_search_replace_actions(current_function_info, actions, logger)

        # Write the modified function to the file
        success = write_function_to_file(
            file_path,
            new_func_info,
            replace_start=last_written_info["start_line"],
            replace_end=last_written_info["end_line"],
            logger=logger
        )

        if not success:
            logger.print(f"⚠️  Failed to write function to file, falling back to previous")
            new_func_info = last_written_info  # Keep tracking in sync with file
            break

        # Check syntax
        syntax_ok, syntax_errors = check_syntax(file_path, use_clang_not_intel, logger)

        if syntax_ok:
            logger.print(f"✅ Wrote modified function to {file_path}")
            # Log the entire file content after writing
            logger.log_file_content(
                iteration=current_iteration,
                file_path=file_path,
                call_type=call_type,
                function_name=current_function_info["name"]
            )
            break  # Success! Exit the retry loop
        else:
            logger.print(f"⚠️  Syntax errors detected in generated code")
            logger.print(f"    {syntax_errors[:500]}...")

            # Log the broken file for debugging before restoring
            logger.log_file_content(
                iteration=current_iteration,
                file_path=file_path,
                call_type=call_type,
                function_name=current_function_info["name"]
            )

            # Store the failed attempt for the next iteration
            if actions and len(actions) > 0:
                previous_search_replace = {
                    "search": actions[0]["search"],
                    "replace": actions[0]["replace"]
                }
            lint_errors = syntax_errors

            # Restore the previous function text to the file
            restore_success = write_function_to_file(
                file_path,
                last_written_info,
                replace_start=last_written_info["start_line"],
                replace_end=new_func_info["end_line"],  # Use new end line since we wrote it
                logger=logger
            )
            if restore_success:
                logger.print(f"🔙 Restored previous function text")
            else:
                logger.print(f"⚠️  Failed to restore previous function, continuing anyway")
                break  # Can't continue safely if we can't restore

            # If this was the last attempt, use the original function
            if attempt == MAX_LINT_RETRIES - 1:
                logger.print(f"⚠️  Max retries ({MAX_LINT_RETRIES}) reached, using original function")
                new_func_info = current_function_info
                # Write the original function back
                write_function_to_file(
                    file_path,
                    current_function_info,
                    replace_start=last_written_info["start_line"],
                    replace_end=last_written_info["end_line"],
                    logger=logger
                )
                break
    # Create new function draft with modified function
    function_drafts[current_iteration] = FunctionDraft(new_func_info)

    result_dict = {
        "function_drafts": function_drafts
    }

    after_state = state.copy()
    after_state.update(result_dict)
    logger.log_state(after_state, "engineer", "after")

    return result_dict



def create_vectorization_graph():
    workflow = StateGraph(VectorizationState)

    workflow.add_node("compile_code", compile_code)
    workflow.add_node("run_code", run_code)
    workflow.add_node("engineer", engineer)
    workflow.add_node("finalize", finalize)

    workflow.set_entry_point("compile_code")
    workflow.add_edge("compile_code", "run_code")
    workflow.add_edge("run_code", "engineer")        
    workflow.add_edge("engineer", "finalize")
    workflow.add_edge("finalize", END)
    
    return workflow.compile()

def vectorize_benchmark(benchmark_dir: str,
                        make_command: str,
                        max_iterations: int,
                        run_command: str,
                        use_compiler_feedback: bool = True,
                        use_clang_not_intel: bool = True
                        ):

    abs_benchmark_dir = os.path.abspath(benchmark_dir)
    benchmark_name = os.path.basename(abs_benchmark_dir)
    parent_dir = os.path.dirname(abs_benchmark_dir)
    opt_dir = os.path.join(parent_dir, f"{benchmark_name}_opt")
    current_dir = os.getcwd()

    print(f"{'='*60}\n")
    print(f"Vectorizing {benchmark_dir} ")
    print(f"Make command: {make_command}")
    print(f"Max iterations: {max_iterations}")
    print(f"Absolute Benchmark: {abs_benchmark_dir}")
    print(f"Benchmark name: {benchmark_name}")
    print(f"Parent Dir: {parent_dir}")
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
    log_dir = os.path.join(current_dir, f"{benchmark_name}_logs")
    logger = LLMLogger(log_dir)

    target_files = find_target_files(opt_dir)
    for current_file in target_files:
        # Initial read to find out how many functions we have
        loader = TextLoader(current_file, encoding='utf-8')
        document = loader.load()
        initial_code: str = document[0].page_content
        initial_functions: List[FunctionInfo] = extract_functions(initial_code)
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
            
            if func_idx >= len(functions):
                logger.print(f"⚠️  Warning: Expected {num_functions} functions but found {len(functions)} in {current_file} at index {func_idx}")
                continue

            function = functions[func_idx]
            
            # Construct an initial state
            initial_function_draft: FunctionDraft = FunctionDraft(function)
            initial_state = VectorizationState(
                bench_path=opt_dir,
                file_path=current_file,
                make_command=make_command,
                run_command=run_command,
                use_compiler_feedback=use_compiler_feedback,
                use_clang_not_intel=use_clang_not_intel,

                program_slice=program_slice,
                compiler_feedback="",
                optimization_remarks="",

                original_draft=initial_function_draft,
                new_draft=FunctionDraft()
            )

            final_state = vectorization_graph.invoke(initial_state, config={"recursion_limit": 1000})

            # Print the Loop Table to stdout

        return {"success": True}
