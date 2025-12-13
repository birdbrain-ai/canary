from langgraph.graph import StateGraph, END
from typing import TypedDict, List, Dict
import subprocess
import os
import shutil
import argparse
import fnmatch
import re
from logger import LLMLogger
from helpers import *
from modify_code import *
from analyze_loops import *
from extra_nodes import *
from vectorization_state import *


import json
import hashlib




# Build the workflow graph
def create_vectorization_workflow():
    """Create the multi-file, multi-iteration vectorization workflow"""
    workflow = StateGraph(VectorizationState)

    # Add all nodes
    workflow.add_node("setup_baseline", setup_baseline)
    workflow.add_node("compile_baseline_benchmark", compile_baseline_benchmark)
    workflow.add_node("run_baseline_benchmark", run_baseline_benchmark)
    workflow.add_node("initialize_benchmark_iteration", initialize_benchmark_iteration)
    workflow.add_node("initialize_file_processing", initialize_file_processing)
    workflow.add_node("summarize_file_context", summarize_file_context)
    workflow.add_node("initialize_function_processing", initialize_function_processing)
    workflow.add_node("analyze_loops", analyze_loops)
    workflow.add_node("suggest_modifications", suggest_modifications)
    workflow.add_node("apply_modifications", apply_modifications)
    workflow.add_node("replace_function_in_file", replace_function_in_file)
    workflow.add_node("write_file", write_file)
    workflow.add_node("compile_iteration_benchmark", compile_iteration_benchmark)
    workflow.add_node("run_iteration_benchmark", run_iteration_benchmark)
    workflow.add_node("increment_iteration", increment_iteration)
    workflow.add_node("finalize", finalize)
    workflow.add_node("handle_failure", handle_failure)

    # Set entry point
    workflow.set_entry_point("setup_baseline")

    # Phase 1: Setup and baseline compilation
    workflow.add_edge("setup_baseline", "compile_baseline_benchmark")
    workflow.add_edge("compile_baseline_benchmark", "run_baseline_benchmark")
    workflow.add_edge("run_baseline_benchmark", "initialize_benchmark_iteration")

    # Phase 2: Per-iteration loop starts here
    workflow.add_edge("initialize_benchmark_iteration", "initialize_file_processing")

    # Phase 3: Per-file loop (middle loop)
    workflow.add_edge("initialize_file_processing", "summarize_file_context")

    # Decision: Does this file have any functions?
    workflow.add_conditional_edges(
        "summarize_file_context",
        has_functions_to_process,
        {
            "process_functions": "initialize_function_processing",
            "write_file": "write_file"
        }
    )

    # Phase 4: Per-function loop (inner loop - NEW)
    workflow.add_edge("initialize_function_processing", "analyze_loops")
    workflow.add_edge("analyze_loops", "suggest_modifications")
    workflow.add_edge("suggest_modifications", "apply_modifications")
    workflow.add_edge("apply_modifications", "replace_function_in_file")

    # Decision: More functions to process in this file?
    workflow.add_conditional_edges(
        "replace_function_in_file",
        should_continue_functions,
        {
            "continue_functions": "initialize_function_processing",
            "write_file": "write_file"
        }
    )

    # Decision: More files to process?
    workflow.add_conditional_edges(
        "write_file",
        should_continue_files,
        {
            "continue_files": "initialize_file_processing",
            "compile_iteration": "compile_iteration_benchmark"
        }
    )

    # Phase 5: After all files processed, compile and run the iteration
    workflow.add_edge("compile_iteration_benchmark", "run_iteration_benchmark")
    workflow.add_edge("run_iteration_benchmark", "decide_next_iteration")

    # Add a dummy node for the iteration decision routing
    def decide_next_iteration(state: VectorizationState):
        """Dummy node to route iteration decision"""
        return state

    workflow.add_node("decide_next_iteration", decide_next_iteration)

    # Decision: Continue to next iteration?
    workflow.add_conditional_edges(
        "decide_next_iteration",
        should_continue_iteration,
        {
            "continue": "increment_iteration",
            "finalize": "finalize",
            "failed": "handle_failure"
        }
    )

    # Loop back: increment iteration then start new iteration
    workflow.add_edge("increment_iteration", "initialize_benchmark_iteration")

    # End nodes
    workflow.add_edge("finalize", END)
    workflow.add_edge("handle_failure", END)

    return workflow.compile()

# Main function for directory-based benchmarks
def vectorize_benchmark(benchmark_dir: str, make_command: str,
                       max_iterations: int = 3, run_command: str = ""):
    """
    Add vectorization pragmas to all C/C++ files in a benchmark directory
    with iterative refinement based on compiler optimization remarks.

    Args:
        benchmark_dir: Path to the benchmark directory to optimize
        make_command: Shell command to build the benchmark (e.g., "make")
        max_iterations: Number of iterative refinement passes (default: 3)
        run_command: Optional command to run the benchmark (not used yet)

    Returns:
        Final state dict with results
    """

    if not os.path.exists(benchmark_dir):
        print(f"✗ Error: Benchmark directory not found: {benchmark_dir}")
        return None

    if not os.path.isdir(benchmark_dir):
        print(f"✗ Error: Path is not a directory: {benchmark_dir}")
        return None

    # Get absolute path and derive names
    abs_benchmark_dir = os.path.abspath(benchmark_dir)
    benchmark_name = os.path.basename(abs_benchmark_dir)
    parent_dir = os.path.dirname(abs_benchmark_dir)
    opt_dir = os.path.join(parent_dir, f"{benchmark_name}_opt")
    current_dir = os.getcwd()

    print(f"{'='*60}\n")
    print(f"Vectorizing {benchmark_dir} ")
    print(f"Make command: {make_command}")
    print(f"Max iterations: {max_iterations}")
    print(f"{'='*60}\n")

    print(f"Copying {benchmark_dir}")
    shutil.copytree(abs_benchmark_dir, opt_dir)
    print(f"{'='*60}\n")

    # Update vectorization state
    for current_file in find_target_files(opt_dir):
        # Update vectorization state
        loader = TextLoader(current_file, encoding='utf-8')
        document = loader.load()
        code = document[0].page_content
        functions = extract_functions(code)
        
        for function in functions:
            # Encapsulate all of it in a LangGraph workflow
            # Compile -> Run -> Reviewer -> Manager -> Engineer
            # Exit when we're done with iterations, then finalize
            pass
            
        


    



# CLI entry point
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
