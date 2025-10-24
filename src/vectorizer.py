from langgraph.graph import StateGraph, END
from langchain_ollama import OllamaLLM
from langchain_community.document_loaders import TextLoader
from typing import TypedDict, List, Dict
import subprocess
import os
import shutil
import argparse
import fnmatch
from pathlib import Path

class VectorizationState(TypedDict):
    # Directory-level fields
    original_benchmark_dir: str          # Original benchmark directory (untouched)
    benchmark_base_dir: str              # benchmark_base copy (for baseline)
    current_iteration_dir: str           # benchmark_AI_i directory

    # Build/run commands
    make_command: str                    # Command to build benchmark
    run_command: str                     # Optional: command to run benchmark

    # File tracking
    target_files: List[str]              # All .cpp/.hpp files found in benchmark
    current_file_index: int              # Index of file being processed
    current_file: str                    # Path to file being processed
    current_file_code: str               # Code of current file

    # Iteration tracking
    current_iteration: int
    max_iterations: int

    # Remark files (per-directory)
    remark_files_baseline: List[str]     # Remark files from baseline compilation
    remark_files_current: List[str]      # Remark files from current iteration

    # Per-file context (for separate sessions)
    file_analysis_history: Dict[str, List[str]]  # file_path -> [analyses]
    file_summarized_context: Dict[str, str]      # file_path -> summary

    # Status
    compiler_errors: List[str]
    success: bool

llm = OllamaLLM(model="gpt-oss:latest", base_url="http://localhost:11434")

def get_base_filename(filepath: str) -> str:
    """Get base filename without extension (e.g., 'test.cpp' -> 'test')"""
    return Path(filepath).stem

def get_iteration_filename(filepath: str, iteration: int) -> str:
    """Generate iteration filename (e.g., 'test.cpp' -> 'test_AI_0.cpp')"""
    base = get_base_filename(filepath)
    ext = Path(filepath).suffix
    dir_path = Path(filepath).parent
    return str(dir_path / f"{base}_AI_{iteration}{ext}")

def get_remark_filename(cpp_file: str) -> str:
    """Get remark filename for a cpp file (e.g., 'test.cpp' -> 'test.opt.yaml')"""
    return str(Path(cpp_file).with_suffix('.opt.yaml'))

def get_object_filename(cpp_file: str) -> str:
    """Get object filename for a cpp file (e.g., 'test.cpp' -> 'test.o')"""
    return str(Path(cpp_file).with_suffix('.o'))

def find_files_with_ext(directory: str, file_exts: List[str]) -> List[str]:
    """
    Recursively find all files with given extensions in directory.

    Args:
        directory: Root directory to search
        file_exts: List of extensions to match (e.g., ['.cpp', '.h'])

    Returns:
        List of absolute file paths
    """
    files_with_ext = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            _, file_extension = os.path.splitext(file)
            if file_extension in file_exts:
                files_with_ext.append(os.path.join(root, file))
    return files_with_ext

def find_target_files(directory: str) -> List[str]:
    """
    Find all C/C++ source and header files in directory.

    Args:
        directory: Root directory to search

    Returns:
        List of absolute paths to .h, .c, .cpp, .hxx, .hpp files
    """
    return find_files_with_ext(directory, [".h", ".c", ".cpp", ".hxx", ".hpp"])

def match_remark_files(target_file: str, remark_files: List[str]) -> List[str]:
    """
    Find remark files corresponding to a target source file.

    Matches pattern: kernel.cpp -> kernel*.opt.yaml
    This handles cases like kernel.opt.yaml, kernel.opt.yaml.1, etc.

    Args:
        target_file: Path to source file
        remark_files: List of all available remark files

    Returns:
        List of matching remark file paths
    """
    target_prefix = os.path.splitext(os.path.basename(target_file))[0]
    pattern = f"{target_prefix}*.opt.yaml"

    matching = []
    for remark_file in remark_files:
        yaml_basename = os.path.basename(remark_file)
        if fnmatch.fnmatch(yaml_basename, pattern):
            matching.append(remark_file)
    return matching

def filter_vectorize_remarks(yaml_file_path: str) -> str:
    """
    Filter YAML optimization remarks to only include loop-vectorize entries.
    This dramatically reduces the content sent to the LLM.

    Args:
        yaml_file_path: Path to .opt.yaml file

    Returns:
        Filtered YAML content as string, or empty string if filtering fails
    """
    try:
        result = subprocess.run(
            ["yq", "select(.Pass == \"loop-vectorize\")", yaml_file_path],
            capture_output=True,
            text=True,
#             timeout=10
        )

        if result.returncode == 0:
            return result.stdout
        else:
            # If yq fails, return empty (don't fail the entire process)
            print(f"⚠ Warning: yq filter failed for {yaml_file_path}")
            return ""
    except Exception as e:
        print(f"⚠ Warning: Could not filter remarks for {yaml_file_path}: {e}")
        return ""

# Node: Setup baseline
def setup_baseline(state: VectorizationState):
    """Copy benchmark to baseline directory and find target files"""
    original_dir = state['original_benchmark_dir']
    base_dir = state['benchmark_base_dir']

    print(f"\n{'='*60}")
    print(f"ITERATIVE VECTORIZATION PRAGMA TOOL (Multi-File)")
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

# Node: Compile benchmark (baseline or iteration)
def compile_benchmark(state: VectorizationState):
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
#        timeout=300
    )

    # Change back
    os.chdir(current_dir)

    if result.returncode != 0:
        print(f"⚠ Warning: Baseline compilation had issues")
        print(f"  Output: {result.stderr[:300]}")
    else:
        print(f"✓ Baseline compiled successfully")

    # Find all generated .opt.yaml files
    remark_files = find_files_with_ext(base_dir, [".yaml"])
    print(f"✓ Found {len(remark_files)} remark files")

    return {
        "remark_files_baseline": remark_files
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
        # timeout=600  # 10 minute timeout
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

# Node: Initialize file processing
def initialize_file_processing(state: VectorizationState):
    """Select next file to process and load its code"""
    target_files = state['target_files']
    file_index = state['current_file_index']
    current_file = target_files[file_index]

    print(f"\n=== Processing File {file_index + 1}/{len(target_files)} ===")
    print(f"File: {current_file}")

    # Load file code
    loader = TextLoader(current_file, encoding='utf-8')
    document = loader.load()
    code = document[0].page_content

    print(f"✓ Loaded file ({len(code)} characters)")

    return {
        "current_file": current_file,
        "current_file_code": code
    }

# Node: Summarize context (per-file)
def summarize_context(state: VectorizationState):
    """Compress previous iteration analyses for current file"""

    iteration = state['current_iteration']
    current_file = state['current_file']
    file_analysis_history = state['file_analysis_history']
    file_summarized_context = state['file_summarized_context'].copy()

    # No summarization needed for first iteration
    if iteration == 0:
        print(f"✓ No previous context to summarize (iteration 0)")
        file_summarized_context[current_file] = ""
        return {"file_summarized_context": file_summarized_context}

    # Get previous analyses for THIS file
    analyses = file_analysis_history.get(current_file, [])

    if not analyses:
        print(f"✓ No previous analyses for this file")
        file_summarized_context[current_file] = ""
        return {"file_summarized_context": file_summarized_context}

    print(f"\n=== Summarizing Context for {os.path.basename(current_file)} ===")
    print(f"From {len(analyses)} previous iterations")

    # Build summarization prompt
    analyses_text = ""
    for i, analysis in enumerate(analyses):
        analyses_text += f"\n--- Iteration {i} Analysis ---\n{analysis}\n"

    prompt = f"""Summarize the key vectorization insights from these previous analyses for this file.

Previous iteration analyses:
{analyses_text}

Create a CONCISE summary (max 300 words) covering:
1. Which loops were identified as vectorization candidates
2. What pragmas were recommended and why
3. Any recurring issues or patterns observed
4. Any compilation issues encountered

Focus on actionable insights for the next iteration.
Output ONLY the summary, no preamble."""

    summary = llm.invoke(prompt)

    print(f"✓ Compressed {len(analyses_text)} chars to {len(summary)} chars")
    print(f"Summary preview: {summary[:200]}...")

    # Store summary for this file
    file_summarized_context[current_file] = summary

    return {"file_summarized_context": file_summarized_context}

# Node: Analyze loops (per-file)
def analyze_loops(state: VectorizationState):
    """Analyze code and matching remark files for current file"""

    current_file = state['current_file']
    current_code = state['current_file_code']
    iteration = state['current_iteration']
    remark_files_baseline = state['remark_files_baseline']
    remark_files_current = state.get('remark_files_current', [])
    file_summarized_context = state['file_summarized_context']
    file_analysis_history = state['file_analysis_history'].copy()

    # Match remark files for this specific file
    matching_baseline = match_remark_files(current_file, remark_files_baseline)
    matching_current = match_remark_files(current_file, remark_files_current)
    all_matching = matching_baseline + matching_current

    # Build remark analysis section
    remark_analysis = ""
    if all_matching:
        remark_analysis = f"\n\nOPTIMIZATION REMARKS FOR THIS FILE ({len(all_matching)} files):\n"

        # Include filtered content from ALL matching remark files
        # Since we're filtering for loop-vectorize only, they're much smaller now
        for remark_file in all_matching:
            remark_analysis += f"\n--- Remark file: {os.path.basename(remark_file)} ---\n"

            # Use yq to filter for loop-vectorize remarks only
            filtered_content = filter_vectorize_remarks(remark_file)

            if filtered_content:
                remark_analysis += f"```yaml\n{filtered_content}```\n"
            else:
                remark_analysis += "(No loop-vectorize remarks found)\n"
    else:
        remark_analysis = "\n\nNo optimization remarks available for this file yet."

    # Build iteration context with file-specific summary
    summarized_context = file_summarized_context.get(current_file, "")
    iteration_context = ""
    if iteration > 0 and summarized_context:
        iteration_context = f"""
ITERATION CONTEXT:
This is iteration {iteration} of {state['max_iterations']}.

Summary of previous iterations' findings for this file:
{summarized_context}

Build upon these previous optimizations and look for additional opportunities.
"""
    elif iteration > 0:
        iteration_context = f"""
ITERATION CONTEXT:
This is iteration {iteration} of {state['max_iterations']}.
Look for vectorization opportunities in this file.
"""

    prompt = f"""You are analyzing C++ code for vectorization opportunities.

FILE: {os.path.basename(current_file)}
CURRENT CODE (Iteration {iteration}):
```cpp
{current_code}
```

{remark_analysis}

{iteration_context}

TASK:
Analyze the code and optimization remarks to identify FOR LOOPS that:
1. Could benefit from vectorization but aren't vectorized yet
2. Failed to vectorize (check remarks for "LV" or "loop-vectorize" messages)
3. Have vectorization issues that could be fixed with pragmas

Focus ONLY on FOR LOOPS with these characteristics:
- Simple iteration patterns (i++, i+=1, etc.)
- Array/vector operations in the loop body
- No complex control flow (minimal breaks, continues, early returns)
- The compiler identified as vectorization candidates but failed

IMPORTANT: Only analyze FOR LOOPS. Do NOT suggest pragmas for while loops or do-while loops.

Provide a concise analysis of which FOR LOOPS to add pragmas to and why.
"""

    analysis = llm.invoke(prompt)
    print(f"\n=== Loop Analysis ===")
    print(analysis)
    print("=" * 60)

    # Store analysis in per-file history
    if current_file not in file_analysis_history:
        file_analysis_history[current_file] = []
    file_analysis_history[current_file].append(analysis)

    return {
        "file_analysis_history": file_analysis_history
    }

# Node: Add pragmas
def add_pragmas(state: VectorizationState):
    """Add or refine vectorization pragmas based on analysis"""

    current_file = state['current_file']
    current_code = state['current_file_code']
    iteration = state['current_iteration']
    file_summarized_context = state['file_summarized_context']

    # Get context for this specific file
    summarized_context = file_summarized_context.get(current_file, "")

    # Build context from summary (not full remark files)
    context_section = ""
    if iteration > 0 and summarized_context:
        context_section = f"""

PREVIOUS ITERATIONS SUMMARY:
{summarized_context}
"""

    # Build iteration guidance
    iteration_guidance = ""
    if iteration == 0:
        iteration_guidance = """
GUIDANCE:
This is the first iteration. Add `#pragma clang loop vectorize(enable)` pragmas before FOR LOOPS that:
- Have simple, predictable iteration patterns
- Perform array/vector operations
- Don't have complex control flow or dependencies
"""
    else:
        iteration_guidance = f"""
GUIDANCE:
This is iteration {iteration}. The code already has pragmas from previous iterations.
Based on the optimization remarks:
- Add NEW pragmas before FOR LOOPS where vectorization still failed
- You may add additional pragma directives like:
  - #pragma clang loop interleave(enable)
  - #pragma clang loop vectorize_width(N)
- DO NOT remove existing pragmas
- Build upon previous optimizations
"""

    prompt = f"""Add or refine vectorization pragmas in this C++ code.

CURRENT CODE (Iteration {iteration}):
```cpp
{current_code}
```

{context_section}

{iteration_guidance}

CRITICAL RULES FOR PRAGMA PLACEMENT:
1. ONLY add pragmas before FOR LOOPS (for, while loops are NOT supported)
2. Pragmas MUST be placed on the line IMMEDIATELY BEFORE the "for" keyword
3. Pragmas MUST be OUTSIDE the loop, NEVER inside the loop body

CORRECT PLACEMENT EXAMPLES:
✓ CORRECT:
    #pragma clang loop vectorize(enable)
    for (int i = 0; i < n; i++) {{
        arr[i] = 0;
    }}

✓ CORRECT (multiple pragmas):
    #pragma clang loop vectorize(enable)
    #pragma clang loop interleave(enable)
    for (size_t i = 0; i < size; i++) {{
        data[i] *= factor;
    }}

✗ WRONG (pragma after opening brace):
    for (int i = 0; i < n; i++) {{
        #pragma clang loop vectorize(enable)  // WRONG - inside loop body!
        arr[i] = 0;
    }}

✗ WRONG (pragma after for keyword):
    for (int i = 0; i < n; i++)
    #pragma clang loop vectorize(enable)  // WRONG - after the for statement!
    {{
        arr[i] = 0;
    }}

ALLOWED PRAGMAS:
- #pragma clang loop vectorize(enable)
- #pragma clang loop vectorize(disable)
- #pragma clang loop interleave(enable)
- #pragma clang loop interleave(disable)
- #pragma clang loop vectorize_width(N) where N is a power of 2 (e.g., 2, 4, 8, 16)
- #pragma clang loop interleave_count(N) where N is a positive integer

OTHER RULES:
- For nested loops, prefer pragmas on innermost loops where computation happens
- DO NOT modify any other code - preserve exact formatting, comments, logic
- DO NOT add explanations or comments about the pragmas
- DO NOT add pragmas to while loops or do-while loops, ONLY for loops

Generate ONLY the complete C++ code with pragmas added/refined.
Output WITHOUT any markdown formatting or explanations.
"""

    transformed = llm.invoke(prompt)

    # Clean up markdown
    transformed = transformed.strip()
    if transformed.startswith("```cpp"):
        transformed = transformed[6:]
    if transformed.startswith("```"):
        transformed = transformed[3:]
    if transformed.endswith("```"):
        transformed = transformed[:-3]
    transformed = transformed.strip()

    print(f"\n✓ Pragmas added/refined for {os.path.basename(current_file)} in iteration {iteration}")

    return {
        "current_file_code": transformed
    }

# Node: Write file
def write_file(state: VectorizationState):
    """Write the modified code back to the current file"""
    filepath = state['current_file']
    code = state['current_file_code']

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

# Node: Compile and verify
def compile_code(state: VectorizationState):
    """Compile iteration file with optimization remarks for verification"""
    filepath = state['current_iteration_file']
    iteration = state['current_iteration']
    remark_file = get_remark_filename(filepath)
    object_file = get_object_filename(filepath)

    print(f"\n=== Compiling Iteration {iteration} ===")

    result = subprocess.run(
        ["clang++", "-std=c++17", "-Wall", "-fsave-optimization-record",
         "-c", filepath, "-o", object_file],
        capture_output=True,
        text=True,
        # timeout=60
    )

    errors = []
    if result.returncode != 0:
        errors = [line for line in result.stderr.split("\n") if line.strip()]
        print(f"✗ Compilation failed with {len(errors)} errors:")
        for err in errors[:5]:
            print(f"  {err}")
    else:
        print("✓ Compilation successful!")

    # Check for new remark file
    if os.path.exists(remark_file):
        print(f"✓ Generated remark file: {remark_file}")
        # Add to remark files list
        remark_files = state['remark_files'].copy()
        if remark_file not in remark_files:
            remark_files.append(remark_file)
        return {
            "compiler_errors": errors,
            "remark_files": remark_files
        }
    else:
        print(f"⚠ No remark file generated")
        return {
            "compiler_errors": errors
        }

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
#         timeout=300  # 5 minute timeout for build
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

    return {
        "remark_files_current": remark_files,
        "compiler_errors": errors
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

    # Check for compilation errors
    if state['compiler_errors']:
        print(f"\n⚠ Compilation failed for iteration {state['current_iteration']}")
        return "failed"

    # Check if we've reached max iterations
    if state['current_iteration'] >= state['max_iterations'] - 1:
        print(f"\n✓ Reached maximum iterations ({state['max_iterations']})")
        return "finalize"

    # Continue to next iteration
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

# Build the workflow graph
def create_vectorization_workflow():
    """Create the multi-file, multi-iteration vectorization workflow"""
    workflow = StateGraph(VectorizationState)

    # Add all nodes
    workflow.add_node("setup_baseline", setup_baseline)
    workflow.add_node("compile_benchmark", compile_benchmark)
    workflow.add_node("run_baseline_benchmark", run_baseline_benchmark)
    workflow.add_node("initialize_benchmark_iteration", initialize_benchmark_iteration)
    workflow.add_node("initialize_file_processing", initialize_file_processing)
    workflow.add_node("summarize_context", summarize_context)
    workflow.add_node("analyze_loops", analyze_loops)
    workflow.add_node("add_pragmas", add_pragmas)
    workflow.add_node("write_file", write_file)
    workflow.add_node("compile_iteration_benchmark", compile_iteration_benchmark)
    workflow.add_node("run_iteration_benchmark", run_iteration_benchmark)
    workflow.add_node("increment_iteration", increment_iteration)
    workflow.add_node("finalize", finalize)
    workflow.add_node("handle_failure", handle_failure)

    # Set entry point
    workflow.set_entry_point("setup_baseline")

    # Phase 1: Setup and baseline compilation
    workflow.add_edge("setup_baseline", "compile_benchmark")
    workflow.add_edge("compile_benchmark", "run_baseline_benchmark")
    workflow.add_edge("run_baseline_benchmark", "initialize_benchmark_iteration")

    # Phase 2: Per-iteration loop starts here
    workflow.add_edge("initialize_benchmark_iteration", "initialize_file_processing")

    # Phase 3: Per-file loop (inner loop)
    workflow.add_edge("initialize_file_processing", "summarize_context")
    workflow.add_edge("summarize_context", "analyze_loops")
    workflow.add_edge("analyze_loops", "add_pragmas")
    workflow.add_edge("add_pragmas", "write_file")

    # Decision: More files to process?
    workflow.add_conditional_edges(
        "write_file",
        should_continue_files,
        {
            "continue_files": "initialize_file_processing",  # Loop back to next file
            "compile_iteration": "compile_iteration_benchmark"  # All files done, compile
        }
    )

    # Phase 4: After all files processed, compile and run the iteration
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
    base_dir = os.path.join(parent_dir, f"{benchmark_name}_base")

    print(f"{'='*60}")
    print(f"VECTORIZATION WORKFLOW")
    print(f"{'='*60}")
    print(f"Benchmark: {benchmark_name}")
    print(f"Original: {abs_benchmark_dir}")
    print(f"Baseline: {base_dir}")
    print(f"Make command: {make_command}")
    print(f"Max iterations: {max_iterations}")
    print(f"{'='*60}\n")

    # Create workflow
    app = create_vectorization_workflow()

    # Initialize state
    initial_state = {
        # Directory-level fields
        "original_benchmark_dir": abs_benchmark_dir,
        "benchmark_base_dir": base_dir,
        "current_iteration_dir": "",

        # Build/run commands
        "make_command": make_command,
        "run_command": run_command,

        # File tracking
        "target_files": [],
        "current_file_index": 0,
        "current_file": "",
        "current_file_code": "",

        # Iteration tracking
        "current_iteration": 0,
        "max_iterations": max_iterations,

        # Remark files
        "remark_files_baseline": [],
        "remark_files_current": [],

        # Per-file context
        "file_analysis_history": {},
        "file_summarized_context": {},

        # Status
        "compiler_errors": [],
        "success": False
    }

    # Run workflow with increased recursion limit for multi-iteration/multi-file processing
    # Each iteration processes all files through multiple nodes, so we need a high limit
    result = app.invoke(initial_state, config={"recursion_limit": 100})
    return result

# Legacy function (kept for backwards compatibility)
def vectorize_file(filepath: str, max_iterations: int = 3):
    """Add vectorization pragmas to a C++ file with iterative refinement"""

    if not os.path.exists(filepath):
        print(f"✗ Error: File not found: {filepath}")
        return None

    app = create_vectorization_workflow()

    initial_state = {
        "original_filepath": filepath,
        "original_code": "",
        "current_iteration": 0,
        "max_iterations": max_iterations,
        "remark_files": [],
        "iteration_files": [],
        "current_iteration_file": "",
        "current_code": "",
        "compiler_errors": [],
        "success": False,
        "analysis_history": [],
        "summarized_context": ""
    }

    result = app.invoke(initial_state, config={"recursion_limit": 100})
    return result

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
    elif os.path.isfile(args.path):
        # Legacy file mode
        print("⚠ Running in legacy single-file mode")
        print("⚠ Consider using benchmark directory mode for better results\n")
        result = vectorize_file(args.path, args.iterations)
    else:
        print(f"✗ Error: Path not found: {args.path}")
        exit(1)

    # Exit with appropriate code
    if result and result.get('success'):
        exit(0)
    else:
        exit(1)
