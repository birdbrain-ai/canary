from langgraph.graph import StateGraph, END
from langchain_community.document_loaders import TextLoader
import os
import shutil
import argparse
from more_helpers import extract_functions, find_target_files
from typing import List
from my_types import FunctionInfo, VectorizationState


# Node: compile_code
def compile_code(state: VectorizationState):
    return {}


# Node: run_code
def run_code(state: VectorizationState):
    return {}


# Node: reviewer
def reviewer(state: VectorizationState):
    return {}


# Node: increment
def increment(state: VectorizationState):
    current_iteration = state["current_iteration"]
    return {
        "current_iteration": current_iteration + 1
    }


# Node: manager
def manager(state: VectorizationState):
    return {}


# Node: engineer
def engineer(state: VectorizationState):
    return {}


# Node: finalize
def finalize(state: VectorizationState):
    return {}


# Node: should_continue
def should_continue(state: VectorizationState):
    max_iterations = state["max_iterations"]
    current_iteration = state["current_iteration"]
    if current_iteration < max_iterations:
        return "continue"
    else:
        return "done"


# Compile -> Run -> Reviewer -> If cur_iter < n, i++, manager -> engineer -> Compiler, else, finalize
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
                        max_iterations: int = 3,
                        run_command: str = ""):

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
        functions: List[FunctionInfo] = extract_functions(code)

        for function in functions:
            # Construct an initial state
            initial_state = VectorizationState(
                raw_function=function,
                program_slice="",
                compiler_feedback="",
                optimization_remarks="",
                current_iteration=0,
                max_iterations=max_iterations,
                manager_chosen_i=0,
                function_drafts={},
            )

            # Pass it to LangGraph workflow: Compile -> Run -> Reviewer -> Manager -> Engineer
            final_state = vectorization_graph.invoke(initial_state)
            print(f"Final State is:\n{final_state}")


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
            run_command=args.run_command
        )
    else:
        print(f"✗ Error: Directory not found: {args.path}")
        exit(1)

    # Exit with appropriate code
    if result and result.get('success'):
        exit(0)
    else:
        exit(1)
