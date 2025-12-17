from langgraph.graph import StateGraph, END
from langchain_community.document_loaders import TextLoader
from typing import TypedDict, List, Dict
import subprocess
import os
import shutil
import argparse
import fnmatch
import re
from logger import LLMLogger
from more_helpers import extract_functions, find_target_files


class ModifiedFunction(TypedDict):
    compile_success: bool
    dead_end: bool
    vectorization_success: bool
    reviewer_feedback: str
    modified_function_text: str


class VectorizationState(TypedDict):
    raw_function_text: str
    program_slice: str
    compiler_feedback: str
    optimization_remarks: str

    current_iteration: int
    max_iterations: int
    manager_chosen_i: int

    function_drafts: Dict[int, ModifiedFunction]

    final_function_text: str

    
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

    target_files = find_target_files(opt_dir)
    
    for current_file in target_files:
        loader = TextLoader(current_file, encoding='utf-8')
        document = loader.load()
        code = document[0].page_content
        functions = extract_functions(code)
        
        for function in functions:
            # Encapsulate all of it in a LangGraph workflow
            # Compile -> Run -> Reviewer -> Manager -> Engineer
            # Exit when we're done with iterations, then finalize

            # Construct an initial state
            initial_state = VectorizationState(
                raw_function_text=function,
                program_slice="",
                compiler_feedback="",
                optimization_remarks="",
                current_iteration=0,
                max_iterations=max_iterations,
                manager_chosen_i=0,
                function_drafts={}
                final_function_text=""
            )

            # Pass it to LangGraph workflow

            # Apply the final function_text


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
