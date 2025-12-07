import os
from vectorization_state import *
from analyze_loops import *
import shutil
from helpers import *
from langchain_community.document_loaders import TextLoader


# Node: Setups baseline
def setup_baseline(state: VectorizationState):
    """Copy benchmark to baseline directory and find target files"""
    original_dir = state['original_benchmark_dir']
    base_dir = state['benchmark_base_dir']

    print(f"\n{'='*60}")
    print(f"COMPILER-ASSISTED AI VECTORIZER")
    print(f"Benchmark: {original_dir}")
    print(f"Iterations: {state['max_iterations']}")
    print('='*60)

    # Copy original benchmark to baseline
    print(f"\n=== Setting Up Baseline ===")
    print(f"Copying {original_dir} → {base_dir}")
    shutil.copytree(original_dir, base_dir)
    print(f"✓ Created baseline directory")

    # Find all target files in baseline
    target_files = find_target_files(base_dir)
    print(f"✓ Found {len(target_files)} target files")

    return {
        "target_files": target_files
    }

# Node: Compile baseline benchmark
def compile_baseline_benchmark(state: VectorizationState):
    """Compile benchmark to generate optimization remarks"""
    base_dir = state['benchmark_base_dir']
    make_command = state['make_command']
    current_dir = os.getcwd()

    print(f"\n=== Compiling Baseline Benchmark ===")
    print(f"Command: {make_command}")

    # Change to baseline directory
    os.chdir(base_dir)

    # Run make command
    result = subprocess.run(
        make_command,
        shell=True,
        capture_output=True,
        text=True,
    )

    # Change back
    os.chdir(current_dir)

    # Check compilation result
    errors = []
    file_compilation_feedback = {}

    if result.returncode != 0:
        errors = [line for line in result.stderr.split("\n") if line.strip()]
        print(f"✗ Baseline compilation failed")
        print(f"Exit code: {result.returncode}")
        if errors:
            print("First few errors:")
            for err in errors[:10]:
                print(f"  {err}")
        
        # Generate per-file compilation feedback
        target_files = state['target_files']
        for target_file in target_files:
            feedback = extract_compilation_errors(result.stderr, target_file)
            
            if feedback:
                rel_path = os.path.relpath(target_file, state['benchmark_base_dir'])
                file_compilation_feedback[rel_path] = feedback
        
        if file_compilation_feedback:
            print(f"✓ Generated compilation feedback for {len(file_compilation_feedback)} file(s)")
    else:
        print(f"✓ Baseline compiled successfully")

    # Find all generated .opt.yaml files
    remark_files = find_files_with_ext(base_dir, [".yaml"])
    print(f"✓ Found {len(remark_files)} remark files")

    return {
        "remark_files_baseline": remark_files,
        "compiler_errors": errors,
        "file_compilation_feedback": file_compilation_feedback
    }

# Node: Run baseline benchmark
def run_baseline_benchmark(state: VectorizationState):
    """Execute the baseline benchmark if run_command is provided"""
    run_command = state['run_command']

    if not run_command:
        print("⊘ No run command provided, skipping baseline execution")
        return {}

    base_dir = state['benchmark_base_dir']
    current_dir = os.getcwd()

    print(f"\n=== Running Baseline Benchmark ===")
    print(f"Directory: {base_dir}")
    print(f"Command: {run_command}")

    # Change to baseline directory
    os.chdir(base_dir)

    # Run benchmark command
    result = subprocess.run(
        run_command,
        shell=True,
        capture_output=False,  # Let output go to stdout/stderr
        text=True,
    )

    # Change back
    os.chdir(current_dir)

    if result.returncode != 0:
        print(f"⚠ Warning: Baseline benchmark exited with code {result.returncode}")
    else:
        print(f"✓ Baseline benchmark completed")

    return {}

# Node: Initialize benchmark iteration
def initialize_benchmark_iteration(state: VectorizationState):
    """Set up new iteration - copy entire benchmark from original"""
    iteration = state['current_iteration']
    original_dir = state['original_benchmark_dir']
    bench_name = os.path.basename(original_dir.rstrip('/'))
    parent_dir = os.path.dirname(os.path.abspath(original_dir))

    # Generate iteration directory name
    iteration_dir = os.path.join(parent_dir, f"{bench_name}_AI_{iteration}")

    print(f"\n{'='*60}")
    print(f"ITERATION {iteration}")
    print('='*60)
    print(f"Copying benchmark: {original_dir} → {iteration_dir}")

    # Copy entire benchmark directory
    shutil.copytree(original_dir, iteration_dir)
    print(f"✓ Created iteration directory")

    # Find target files in iteration directory
    target_files = find_target_files(iteration_dir)
    print(f"✓ Found {len(target_files)} target files in iteration")

    return {
        "current_iteration_dir": iteration_dir,
        "target_files": target_files,
        "current_file_index": 0  # Reset file index for this iteration
    }

# Node: Initialize function processing
def initialize_function_processing(state: VectorizationState):
    """Select next function to process"""
    functions = state['functions_in_file']
    func_idx = state['current_function_index']
    current_func = functions[func_idx]

    print(f"\n=== Processing Function {func_idx + 1}/{len(functions)} ===")
    print(f"Function: {current_func['name']} (lines {current_func['start_line']}-{current_func['end_line']})")

    return {
        "current_function": current_func
    }


# Node: Replace function in file
def replace_function_in_file(state: VectorizationState):
    """Replace the modified function in the file content"""

    transformed_func = state['transformed_function']
    func_info = state['current_function']
    file_content = state['modified_file_content']

    # Replace function at line range
    lines = file_content.splitlines()
    new_func_lines = transformed_func.splitlines()

    # Replace lines from start_line to end_line (inclusive)
    lines[func_info['start_line']:func_info['end_line']+1] = new_func_lines

    new_content = '\n'.join(lines)

    print(f"✓ Replaced function '{func_info['name']}' in file content")

    return {
        "modified_file_content": new_content,
        "current_function_index": state['current_function_index'] + 1
    }

# Decision: Check if file has any functions
def has_functions_to_process(state: VectorizationState) -> str:
    """Check if the file has any functions to process"""
    functions = state['functions_in_file']

    if len(functions) == 0:
        print(f"⊘ No functions found in file, skipping to next file")
        return "write_file"  # Skip function processing, go straight to next file
    else:
        return "process_functions"  # Enter function processing loop

# Decision: Should continue processing functions?
def should_continue_functions(state: VectorizationState) -> str:
    """Decide whether to process more functions or write file"""

    current_idx = state['current_function_index']
    total_funcs = len(state['functions_in_file'])

    if current_idx < total_funcs:
        remaining = total_funcs - current_idx
        print(f"\n→ {remaining} function(s) remaining in this file")
        return "continue_functions"
    else:
        print(f"\n✓ All {total_funcs} function(s) processed in this file")
        return "write_file"

# Node: Write file
def write_file(state: VectorizationState):
    """Write the modified code back to the current file"""
    filepath = state['current_file']
    code = state['modified_file_content']  # Changed from current_file_code

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(code)

    print(f"✓ Wrote modified file: {os.path.basename(filepath)}")

    # Increment file index for next file
    return {
        "current_file_index": state['current_file_index'] + 1
    }

# Decision: Should continue processing files?
def should_continue_files(state: VectorizationState) -> str:
    """Decide whether to process more files or compile the benchmark"""

    current_index = state['current_file_index']
    total_files = len(state['target_files'])

    if current_index < total_files:
        remaining = total_files - current_index
        print(f"\n→ {remaining} file(s) remaining in this iteration")
        return "continue_files"
    else:
        print(f"\n✓ All {total_files} files processed in iteration {state['current_iteration']}")
        return "compile_iteration"

# Node: Compile entire iteration benchmark
def compile_iteration_benchmark(state: VectorizationState):
    """Compile the AI-modified benchmark to generate new optimization remarks"""

    current_dir = os.getcwd()
    iteration_dir = state['current_iteration_dir']
    make_command = state['make_command']
    iteration = state['current_iteration']

    print(f"\n{'='*60}")
    print(f"COMPILING BENCHMARK AI_{iteration}")
    print(f"{'='*60}")
    print(f"Directory: {iteration_dir}")
    print(f"Command: {make_command}")

    # Change to iteration directory
    os.chdir(iteration_dir)

    # Run make command
    result = subprocess.run(
        make_command,
        shell=True,
        capture_output=True,
        text=True,
    )

    # Return to original directory
    os.chdir(current_dir)

    # Check compilation result
    errors = []
    if result.returncode != 0:
        errors = [line for line in result.stderr.split("\n") if line.strip()]
        print(f"✗ Benchmark compilation failed")
        print(f"Exit code: {result.returncode}")
        if errors:
            print("First few errors:")
            for err in errors[:10]:
                print(f"  {err}")
    else:
        print(f"✓ Benchmark compiled successfully!")

    # Find all new remark files in iteration directory
    remark_files = find_files_with_ext(iteration_dir, [".yaml"])
    print(f"✓ Found {len(remark_files)} remark files")
    
    # Generate per-file compilation feedback
    file_compilation_feedback = {}
    if result.returncode != 0:
        # Parse stderr and create feedback for each target file
        target_files = state['target_files']
        for target_file in target_files:
            feedback = extract_compilation_errors(result.stderr, target_file)

            if feedback:
                rel_path = os.path.relpath(target_file, state['current_iteration_dir'])
                file_compilation_feedback[rel_path] = feedback
        
        if file_compilation_feedback:
            print(f"✓ Generated compilation feedback for {len(file_compilation_feedback)} file(s)")

    return {
        "remark_files_current": remark_files,
        "compiler_errors": errors,
        "file_compilation_feedback": file_compilation_feedback
    }

# Node: Run iteration benchmark
def run_iteration_benchmark(state: VectorizationState):
    """Execute the AI-modified benchmark if run_command is provided"""
    run_command = state['run_command']

    if not run_command:
        print("⊘ No run command provided, skipping benchmark execution")
        return {}

    iteration_dir = state['current_iteration_dir']
    iteration = state['current_iteration']
    current_dir = os.getcwd()

    print(f"\n{'='*60}")
    print(f"RUNNING BENCHMARK AI_{iteration}")
    print(f"{'='*60}")
    print(f"Directory: {iteration_dir}")
    print(f"Command: {run_command}")

    # Change to iteration directory
    os.chdir(iteration_dir)

    # Run benchmark command
    result = subprocess.run(
        run_command,
        shell=True,
        capture_output=False,  # Let output go to stdout/stderr
        text=True,
#        timeout=600  # 10 minute timeout
    )

    # Return to original directory
    os.chdir(current_dir)

    if result.returncode != 0:
        print(f"⚠ Warning: Benchmark AI_{iteration} exited with code {result.returncode}")
    else:
        print(f"✓ Benchmark AI_{iteration} completed")

    print(f"{'='*60}")

    return {}

# Decision: Should continue iteration?
def should_continue_iteration(state: VectorizationState):
    """Decide whether to continue with another iteration"""

    # Check if we've reached max iterations
    if state['current_iteration'] >= state['max_iterations'] - 1:
        print(f"\n✓ Reached maximum iterations ({state['max_iterations']})")
        return "finalize"
    
    # Continue to next iteration (even if there were compilation errors)
    # The LLM will see the errors in the next iteration and can fix them
    if state['compiler_errors']:
        print(f"\n→ Compilation had errors, but continuing to next iteration for LLM to fix them...")
    else:
        print(f"\n→ Proceeding to next iteration...")
    
    return "continue"

# Node: Increment iteration
def increment_iteration(state: VectorizationState):
    """Increment iteration counter"""
    return {
        "current_iteration": state['current_iteration'] + 1
    }

# Node: Finalize
def finalize(state: VectorizationState):
    """Finalize and summarize all iterations"""
    print(f"\n{'='*60}")
    print(f"VECTORIZATION COMPLETE")
    print('='*60)
    print(f"✓ Original benchmark: {state['original_benchmark_dir']}")
    print(f"✓ Baseline directory: {state['benchmark_base_dir']}")
    print(f"✓ Iterations completed: {state['current_iteration'] + 1}")
    print(f"✓ Files processed: {len(state['target_files'])}")

    # List generated iteration directories
    print(f"\nGenerated iteration directories:")
    benchmark_name = os.path.basename(state['original_benchmark_dir'])
    parent_dir = os.path.dirname(state['original_benchmark_dir'])
    for i in range(state['current_iteration'] + 1):
        iter_dir = os.path.join(parent_dir, f"{benchmark_name}_AI_{i}")
        if os.path.exists(iter_dir):
            print(f"  AI_{i}: {iter_dir}")
            # Count remark files
            remark_files = find_files_with_ext(iter_dir, [".yaml"])
            print(f"        ({len(remark_files)} optimization remark files)")

    print('='*60)

    return {"success": True}

# Node: Handle failure
def handle_failure(state: VectorizationState):
    """Handle compilation failure"""
    print(f"\n{'='*60}")
    print(f"✗ COMPILATION FAILED at iteration {state['current_iteration']}")
    print(f"✓ Original benchmark unchanged: {state['original_benchmark_dir']}")
    print(f"✓ Baseline available: {state['benchmark_base_dir']}")
    print(f"✓ Partial results available in iteration directories")

    # Show which iteration failed
    if state['current_iteration_dir']:
        print(f"✗ Failed directory: {state['current_iteration_dir']}")

    if state['compiler_errors']:
        print(f"\nFirst few compiler errors:")
        for err in state['compiler_errors'][:5]:
            print(f"  {err}")

    print('='*60)

    return {"success": False}
