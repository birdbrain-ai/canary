# Vectorizer
from langgraph.graph import StateGraph, END
from langchain_community.document_loaders import TextLoader
import os
import subprocess
import shutil
import argparse
from more_helpers import extract_functions, find_files_with_ext, find_target_files, extract_file_context, match_remark_files, filter_remarks_by_function, extract_compilation_errors
from typing import List
from my_types import FunctionInfo, FunctionDraft, VectorizationState
from logger import LLMLogger
from mock_llm import MockLLM


# Node: compile_code
def compile_code(state: VectorizationState):
    logger = LLMLogger(state["log_dir"])
    logger.log_state(state, "compile_code", "before")
    
    bench_path = state["bench_path"]
    cur_working_dir = os.getcwd()
    make_command = state["make_command"]
    current_file = state["file_path"]

    current_iteration = state["current_iteration"]
    function_drafts = state["function_drafts"]
    cur_function_draft = function_drafts[current_iteration]
    cur_function_info = cur_function_draft.modified_function_text
    cur_function_name = cur_function_info["name"]

    os.chdir(bench_path)

    result = subprocess.run(
        make_command,
        shell=True,
        capture_output=True,
        text=True,
    )

    all_remark_files = find_files_with_ext(bench_path, [".yaml"])
    relevant_remark_files: List[str] = match_remark_files(current_file, all_remark_files)
    relevant_remarks: List[str] = []

    for remark_file in relevant_remark_files:
        relevant_remarks.append(filter_remarks_by_function(remark_file,
                                                           cur_function_name))

    # TODO(akash): obviously just replace this with a compiler option instead of filtering it manually
    # Just make the compiler only output warnings and errors instead of an insane quantity of notes...
    compilation_feedback = extract_compilation_errors(result.stderr)
        
    os.chdir(cur_working_dir)

    result_dict = {
        "compiler_feedback": compilation_feedback,
        "optimization_remarks": "\n".join(relevant_remarks)
    }
    
    after_state = state.copy()
    after_state.update(result_dict)
    logger.log_state(after_state, "compile_code", "after")
    
    return result_dict


# Node: run_code
def run_code(state: VectorizationState):
    logger = LLMLogger(state["log_dir"])
    logger.log_state(state, "run_code", "before")
    
    run_command = state['run_command']

    if not run_command:
        print("No run command provided")
        logger.log_state(state, "run_code", "after")
        return {}

    bench_path = state['bench_path']
    cur_working_dir = os.getcwd()

    os.chdir(bench_path)

    result = subprocess.run(
        run_command,
        shell=True,
        capture_output=False,
        text=True,
    )

    if result.returncode != 0:
        print(f"Running the benchmark threw an error: {result.returncode}")
    
    os.chdir(cur_working_dir)
    
    logger.log_state(state, "run_code", "after")
    return {}


# Node: reviewer
def reviewer(state: VectorizationState):
    logger = LLMLogger(state["log_dir"])
    logger.log_state(state, "reviewer", "before")
    
    function_drafts = state["function_drafts"]
    current_iteration = state["current_iteration"]
    cur_function_draft = function_drafts[current_iteration]
    cur_function_info = cur_function_draft.modified_function_text
    cur_function_name = cur_function_info["name"]
    reviewer_feedback = function_drafts[current_iteration].reviewer_feedback
    make_command = state["make_command"]
    program_slice = state["program_slice"]
    compiler_feedback = state["compiler_feedback"]
    optimization_remarks = state["optimization_remarks"]

    compile_success = "error:" not in compiler_feedback
    if compile_success:
        compile_success_str = "The function did successfully compile."
        cur_function_draft.compile_success = True
    else:
        logger.log_state(state, "reviewer", "after")
        return {}
        
        
    vectorization_success = "!Passed" in optimization_remarks
    cur_function_draft.vectorization_success = vectorization_success
    if vectorization_success:
        cur_function_draft.dead_end = False
    
    if reviewer_feedback == "":
        prompt = f"""You are reviewing THIS FUNCTION for opportunities to autovectorize it.

{cur_function_info["full_text"]}

        The function is compiled with Clang, using the following command: {make_command}

        You have access to some information to help.

First, the PROGRAM

{program_slice}

Second, COMPILER FEEDBACK:

{compiler_feedback}

{compile_success_str}
        
Third, OPTIMIZATION REMARKS.

{optimization_remarks}

You MUST return a JSON object in this format:

```
{{
  "dead_end": bool
  "reviewer_feedback": str
}}
```
        
RULES:
- If the function was already autovectorized, you must set the dead_end field to false, and the vectorization_success field to true.
- You must set 'dead_end' to false is the function is a useful starting point for autovectorization.
- Fill out the reviewer_feedback field to include future directions to modify the function in order to autovectorize it.

EXAMPLE OUTPUTS:
{{
  "dead_end": false,
  "reviewer_feedback": "This function is already fully autovectorized. No further work is needed." 
}}

{{
  "dead_end": true,
  "reviewer_feedback": "" 
}}

{{
  "dead_end": true,
  "reviewer_feedback": "Optimization remarks for this function suggest that a non-reduction value in the loop body is used outside the loop. Compiler feedback indicates that this function could be autovectorized if we make a copy of the variable 'a'. Suggestion: Make a copy of the variable 'a'."
}}

YOUR OUTPUT:

        """

        output = prompt
        
        if state.get("use_mock_llm", False):
            mock = MockLLM()
            output = mock.generate(prompt, "reviewer")

        logger.log_llm_call(
            iteration=current_iteration,
            file_path=state["file_path"],
            call_type="reviewer",
            prompt=prompt,
            response=output, # Replace with actual LLM output when available
            function_name=cur_function_name
        )

        # Parse reviewer agent's output
        parsed = parse_reviewer_output(output)
        
        if parsed:
            cur_function_draft.dead_end = parsed.get("dead_end", True)
            cur_function_draft.reviewer_feedback = parsed.get("reviewer_feedback", "")
        else:
            print("⚠️  Failed to parse reviewer output, using defaults")
            cur_function_draft.dead_end = True
            cur_function_draft.reviewer_feedback = ""
        
        function_drafts[current_iteration] = cur_function_draft
        
        result_dict = {
            "function_drafts": function_drafts
        }
        
        after_state = state.copy()
        after_state.update(result_dict)
        logger.log_state(after_state, "reviewer", "after")
        
        return result_dict

    logger.log_state(state, "reviewer", "after")
    return {}


# Generic JSON parser for LLM outputs
def parse_llm_json_output(
    output: str,
    required_fields: dict[str, type],
    agent_name: str = "LLM"
) -> dict | None:
    """
    Generic JSON parser for LLM outputs.
    
    Args:
        output: Raw LLM output string
        required_fields: Dict mapping field names to their expected types
                        e.g., {"dead_end": bool, "reviewer_feedback": str}
        agent_name: Name of the agent for error messages
    
    Returns:
        Parsed and validated dict, or None if parsing fails
    """
    import json
    import re
    
    # Try to extract JSON from the output
    # First, try to find JSON in code blocks
    json_match = re.search(r'```(?:json)?\s*({[^`]+})\s*```', output, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        # Try to find raw JSON object with any of the required fields
        # Build a pattern that looks for any required field
        field_names = '|'.join(re.escape(f'"{field}"') for field in required_fields.keys())
        pattern = rf'{{[^{{}}]*(?:{field_names})[^{{}}]*}}'
        json_match = re.search(pattern, output, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            # Last resort: assume the entire output is JSON
            json_str = output.strip()
    
    try:
        parsed = json.loads(json_str)
        
        # Validate required fields
        missing_fields = [field for field in required_fields if field not in parsed]
        if missing_fields:
            print(f"⚠️  Missing required fields in {agent_name} output: {missing_fields}")
            return None
        
        # Type-cast fields according to required_fields
        result = {}
        for field, expected_type in required_fields.items():
            try:
                result[field] = expected_type(parsed[field])
            except (ValueError, TypeError) as e:
                print(f"⚠️  Failed to convert {field} to {expected_type.__name__} in {agent_name} output: {e}")
                return None
        
        return result
            
    except json.JSONDecodeError as e:
        print(f"⚠️  Failed to parse {agent_name} JSON: {e}")
        print(f"    Output was: {output[:200]}...")
        return None


# Node: reviewer: parse output
def parse_reviewer_output(output: str) -> dict | None:
    """
    Parse the reviewer LLM output to extract JSON.
    
    Expected format:
    {
      "dead_end": bool,
      "reviewer_feedback": str
    }
    
    Returns:
        dict with 'dead_end' and 'reviewer_feedback' keys, or None if parsing fails
    """
    return parse_llm_json_output(
        output,
        required_fields={"dead_end": bool, "reviewer_feedback": str},
        agent_name="reviewer"
    )


# Node: increment
def increment(state: VectorizationState):
    logger = LLMLogger(state["log_dir"])
    logger.log_state(state, "increment", "before")
    
    current_iteration = state["current_iteration"]
    result_dict = {
        "current_iteration": current_iteration + 1
    }
    
    after_state = state.copy()
    after_state.update(result_dict)
    logger.log_state(after_state, "increment", "after")
    
    return result_dict


# Node: manager
def manager(state: VectorizationState):
    logger = LLMLogger(state["log_dir"])
    logger.log_state(state, "manager", "before")
    
    function_drafts = state["function_drafts"]
    make_command = state["make_command"]
    
    # Pretty print function_drafts
    drafts_str = ""
    for i, draft in function_drafts.items():
        drafts_str += f"""
## Draft {i}
- **Compile Success**: {draft.compile_success}
- **Vectorization Success**: {draft.vectorization_success}
- **Dead End**: {draft.dead_end}
- **Reviewer Feedback**: {draft.reviewer_feedback if draft.reviewer_feedback else "None"}

**Function Code:**
```c
{draft.modified_function_text.get("full_text", "")}
```

---
"""
    
    prompt = f"""Given a few drafts of the same function, pick the function that is most likely to be autovectorized by the compiler.

The command that this function will be compiled with is:

{make_command}

The FUNCTION DRAFTS are below:

{drafts_str}

OUTPUT RULES:
Your output MUST be a JSON object in the following format.
```
{{
  i: int,
  explanation: str,
}}
```

EXAMPLE OUTPUT:
```
{{
  i: 2,
  explanation: It was the only function draft that was successfully autovectorized. This is a good starting point for further autovectorization attempts.
}}
```

YOUR OUTPUT:
    
    """

    result = prompt
    
    if state.get("use_mock_llm", False):
        mock = MockLLM()
        result = mock.generate(prompt, "manager")

    current_iteration = state["current_iteration"]
    logger.log_llm_call(
        iteration=current_iteration,
        file_path=state["file_path"],
        call_type="manager",
        prompt=prompt,
        response=result,
        function_name=function_drafts[0].modified_function_text["name"]
    )

    # Parse manager agent's output and update vectorization state
    parsed = parse_manager_output(result)
    
    if parsed:
        chosen_index = parsed.get("i", 0)
        # print(f"✅ Manager chose draft {chosen_index}: {parsed.get('explanation', 'No explanation')}")
    else:
        print("⚠️  Failed to parse manager output, defaulting to draft 0")
        chosen_index = 0
    
    # Bounds checking: ensure chosen_index is valid
    current_iteration = state["current_iteration"]
    if chosen_index < 0 or chosen_index >= current_iteration:
        print(f"⚠️  Invalid draft index {chosen_index} (must be 0 <= i < {current_iteration}), defaulting to draft 0")
        chosen_index = 0
    
    result_dict = {
        "manager_chosen_i": chosen_index
    }
    
    after_state = state.copy()
    after_state.update(result_dict)
    logger.log_state(after_state, "manager", "after")
    
    return result_dict


# Node: manager: parse output
def parse_manager_output(output: str) -> dict | None:
    """
    Parse the manager LLM output to extract the chosen draft index.
    
    Expected format:
    {
      "i": int,
      "explanation": str
    }
    
    Returns:
        dict with 'i' and 'explanation' keys, or None if parsing fails
    """
    return parse_llm_json_output(
        output,
        required_fields={"i": int, "explanation": str},
        agent_name="manager"
    )


# Node: engineer
def engineer(state: VectorizationState):
    logger = LLMLogger(state["log_dir"])
    logger.log_state(state, "engineer", "before")
    
    program_slice = state["program_slice"]
    make_command = state["make_command"]

    manager_chosen_i = state["manager_chosen_i"]
    function_drafts = state["function_drafts"]
    current_function_draft = function_drafts[manager_chosen_i]
    reviewer_feedback = current_function_draft.reviewer_feedback
    current_function_info = current_function_draft.modified_function_text
    current_function_body = current_function_info["full_text"]

    prompt = f"""Your task is to take a function and modify it to make it easier to autovectorize.

The FUNCTION is:

{current_function_body}

It starts at {current_function_info["start_line"]} and ends at {current_function_info["end_line"]}

The surrounding context is:

{program_slice}

It is compiled with Clang, using the following command:

{make_command}

Please use SUGGESTIONS FROM A REVIEWER when modifying the function.

{reviewer_feedback}

You have two options:

1. PRAGMA ACTIONS: Suggest pragmas for FOR LOOPS where vectorization still failed
- You may suggest: "vectorize", "interleave", or "vectorize_width"
- Be conservative - only suggest if you're confident it will help

2. CODE REPLACE: Make targeted code changes:
- Fix specific issues identified in optimization remarks
- Add temporaries, hoist computations, break dependencies
- Avoid making changes that alter the meaning of the function

OPTION 1 - PRAGMA ACTIONS (for simple vectorization hints):
For each loop that needs a pragma, create a JSON object:
{{
  "action_type": "pragma",
  "line_number": <line number of the 'for' statement>,
  "pragma_type": "vectorize" OR "interleave" OR "vectorize_width",
  "width": <number (only if pragma_type is vectorize_width), otherwise null>,
  "reasoning": "<brief explanation>"
}}

OPTION 2 - CODE REPLACE (for targeted code changes):
For each code change, create a JSON object:
{{
  "action_type": "code_replace",
  "start_line": <start line number (0-indexed)>,
  "end_line": <end line number (0-indexed, inclusive)>,
  "new_code": "<replacement code (can be multi-line)>",
  "reasoning": "<brief explanation>"
}}

Examples:
- Add variable: {{"action_type": "code_replace", "start_line": 0, "end_line": 0, "new_code": "int temp = 0;", "reasoning": "Add local temporary"}}
- Replace line: {{"action_type": "code_replace", "start_line": 5, "end_line": 5, "new_code": "result[i] = a[i] * factor;", "reasoning": "Use hoisted variable"}}
- Multi-line: {{"action_type": "code_replace", "start_line": 3, "end_line": 5, "new_code": "for (int i = 0; i < n; i++) {{\\n    output[i] = input[i];\\n}}", "reasoning": "Simplify loop"}}

CRITICAL OUTPUT RULES:
- Output a JSON ARRAY: [{{...}}] or [{{...}}, {{...}}] for multiple actions
- You can mix pragma and code_replace actions in the same array
- If NO modifications needed, output an empty array: []
- DO NOT include any explanatory text, markdown, or code fences
- Output ONLY the JSON array, nothing else
    
    """
    response = prompt

    if state.get("use_mock_llm", False):
        mock = MockLLM()
        response = mock.generate(prompt, "engineer")

    current_iteration = state["current_iteration"]
    logger.log_llm_call(
        iteration=current_iteration,
        file_path=state["file_path"],
        call_type="engineer",
        prompt=prompt,
        response=response,
        function_name=current_function_info["name"]
    )

    # TODO(akash). Parse engineer agent's outputs into an array of CodeReplaceAction and PragmaAction objects
    # TODO(akash): Write the new function text to the file. 
    new_func_info = current_function_info
    current_iteration = state["current_iteration"]
    function_drafts[current_iteration] = FunctionDraft(new_func_info)
    
    result_dict = {
        "function_drafts": function_drafts
    }
    
    after_state = state.copy()
    after_state.update(result_dict)
    logger.log_state(after_state, "engineer", "after")
    
    return result_dict


# Node: finalize
def finalize(state: VectorizationState):
    logger = LLMLogger(state["log_dir"])
    logger.log_state(state, "finalize", "before")
    
    function_drafts = state["function_drafts"]

    final_draft = None
    
    for i in range(len(function_drafts)):
        if function_drafts[i].compile_success and function_drafts[i].vectorization_success:
            final_draft = function_drafts[i]
            break

    if final_draft is None:
        final_draft = function_drafts[0]

    # TODO(akash): Write the function draft to the function to the file

    logger.log_state(state, "finalize", "after")
    return {}


# Decision point: should_continue
def should_continue(state: VectorizationState):
    max_iterations = state["max_iterations"]
    current_iteration = state["current_iteration"]
    if current_iteration < max_iterations:
        return "continue"
    else:
        return "done"


def create_vectorization_graph():
    workflow = StateGraph(VectorizationState)

    workflow.add_node("compile_code", compile_code)
    workflow.add_node("run_code", run_code)
    workflow.add_node("reviewer", reviewer)
    workflow.add_node("increment", increment)
    workflow.add_node("manager", manager)
    workflow.add_node("engineer", engineer)
    workflow.add_node("finalize", finalize)

    workflow.set_entry_point("compile_code")
    workflow.add_edge("compile_code", "run_code")
    workflow.add_edge("run_code", "reviewer")        
    workflow.add_conditional_edges(
        "reviewer",
        should_continue,
        {
            "continue": "increment",
            "done": "finalize"
        }
    )
    workflow.add_edge("increment", "manager")
    workflow.add_edge("manager", "engineer")
    workflow.add_edge("engineer", "compile_code")

    workflow.add_edge("finalize", END)
    
    return workflow.compile()
    
    
def vectorize_benchmark(benchmark_dir: str,
                        make_command: str,
                        max_iterations: int,
                        run_command: str,
                        mock: bool = False):

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
    shutil.copytree(abs_benchmark_dir, opt_dir)
    print(f"{'='*60}\n")

    print("Creating vectorization workflow graph")
    vectorization_graph = create_vectorization_graph()
    
    target_files = find_target_files(opt_dir)
    for current_file in target_files:
        loader = TextLoader(current_file, encoding='utf-8')
        document = loader.load()
        code: str = document[0].page_content
        program_slice: str = extract_file_context(code)
        functions: List[FunctionInfo] = extract_functions(code)

        for function in functions:
            # Construct an initial state
            initial_function_draft: FunctionDraft = FunctionDraft(function)
            initial_state = VectorizationState(
                bench_path=opt_dir,
                file_path=current_file,
                make_command=make_command,
                run_command=run_command,
                
                program_slice=program_slice,
                compiler_feedback="",
                optimization_remarks="",
                
                current_iteration=0,
                max_iterations=max_iterations,
                manager_chosen_i=0,
                function_drafts={
                    0: initial_function_draft
                },
                log_dir=os.path.join(current_dir, f"{benchmark_name}_logs"),
                use_mock_llm=mock
            )

            # Pass it to LangGraph workflow: Compile -> Run -> Reviewer -> Manager -> Engineer
            final_state = vectorization_graph.invoke(initial_state)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Add vectorization pragmas to C/C++ code using iterative AI analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Benchmark directory mode (recommended):
  python vectorizer.py my_benchmark --make-command "make" --iterations 3

  # Legacy single-file mode:
  python vectorizer.py my_file.cpp --iterations 3
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
        help="Optional command to run benchmark (not used yet)"
    )

    parser.add_argument(
        "--iterations", "-n",
        type=int,
        default=3,
        help="Number of iterative refinement passes (default: 3)"
    )

    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock LLM responses for testing"
    )

    args = parser.parse_args()

    # Determine mode based on path type
    if os.path.isdir(args.path):
        # Directory mode (benchmark)
        if not args.make_command:
            print("✗ Error: --make-command is required for benchmark directory mode")
            print("Example: python vectorizer.py my_benchmark --make-command 'make'")
            exit(1)

        result = vectorize_benchmark(
            args.path,
            args.make_command,
            max_iterations=args.iterations,
            run_command=args.run_command,
            mock=args.mock
        )
    else:
        print(f"✗ Error: Directory not found: {args.path}")
        exit(1)

    # Exit with appropriate code
    if result and result.get('success'):
        exit(0)
    else:
        exit(1)
