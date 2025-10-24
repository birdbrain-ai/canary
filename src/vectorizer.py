from langgraph.graph import StateGraph, END
from langchain_ollama import OllamaLLM
from langchain_community.document_loaders import TextLoader
from typing import TypedDict, List
import subprocess
import os
import shutil
import argparse
from pathlib import Path

class VectorizationState(TypedDict):
    original_filepath: str
    original_code: str
    current_iteration: int
    max_iterations: int
    remark_files: List[str]
    iteration_files: List[str]
    current_iteration_file: str
    current_code: str
    compiler_errors: List[str]
    success: bool
    analysis_history: List[str]
    summarized_context: str

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

# Node: Load original file
def load_original(state: VectorizationState):
    """Read the original C++ file and create backup"""
    filepath = state['original_filepath']

    loader = TextLoader(filepath, encoding='utf-8')
    document = loader.load()
    code = document[0].page_content

    # Create backup
    backup_path = filepath + '.backup'
    shutil.copy2(filepath, backup_path)

    print(f"\n{'='*60}")
    print(f"ITERATIVE VECTORIZATION PRAGMA TOOL")
    print(f"Target: {filepath}")
    print(f"Iterations: {state['max_iterations']}")
    print('='*60)
    print(f"\n✓ Loaded original file: {filepath}")
    print(f"✓ Created backup: {backup_path}")

    return {
        "original_code": code,
        "current_code": code
    }

# Node: Compile original for baseline
def compile_for_baseline(state: VectorizationState):
    """Compile original file to generate baseline optimization remarks"""
    filepath = state['original_filepath']
    remark_file = get_remark_filename(filepath)
    object_file = get_object_filename(filepath)

    print(f"\n=== Generating Baseline Optimization Remarks ===")

    result = subprocess.run(
        ["clang++", "-std=c++17", "-fsave-optimization-record",
         "-c", filepath, "-o", object_file],
        capture_output=True,
        text=True,
        timeout=60
    )

    if result.returncode != 0:
        print(f"⚠ Warning: Baseline compilation had issues (this is OK)")
        print(f"  Compiler output: {result.stderr[:200]}")
    else:
        print(f"✓ Baseline compiled successfully")

    if os.path.exists(remark_file):
        print(f"✓ Generated baseline remarks: {remark_file}")
        return {
            "remark_files": [remark_file]
        }
    else:
        print(f"⚠ No remark file generated (compiler may not support -fsave-optimization-record)")
        return {
            "remark_files": []
        }

# Node: Initialize iteration
def initialize_iteration(state: VectorizationState):
    """Set up new iteration - copy file from previous iteration"""
    iteration = state['current_iteration']
    original_filepath = state['original_filepath']

    # Determine source file
    if iteration == 0:
        source_file = original_filepath
        print(f"\n{'='*60}")
        print(f"ITERATION {iteration}")
        print('='*60)
        print(f"Copying from original: {source_file}")
    else:
        source_file = get_iteration_filename(original_filepath, iteration - 1)
        print(f"\n{'='*60}")
        print(f"ITERATION {iteration}")
        print('='*60)
        print(f"Copying from previous iteration: {source_file}")

    # Generate target filename
    target_file = get_iteration_filename(original_filepath, iteration)

    # Copy file
    shutil.copy2(source_file, target_file)
    print(f"✓ Created: {target_file}")

    # Load code from target file
    loader = TextLoader(target_file, encoding='utf-8')
    document = loader.load()
    code = document[0].page_content

    # Update iteration files list
    iteration_files = state['iteration_files'].copy()
    iteration_files.append(target_file)

    return {
        "current_iteration_file": target_file,
        "current_code": code,
        "iteration_files": iteration_files
    }

# Node: Summarize context
def summarize_context(state: VectorizationState):
    """Compress previous iteration analyses into concise summary"""

    iteration = state['current_iteration']

    # No summarization needed for first iteration
    if iteration == 0:
        print(f"✓ No previous context to summarize (iteration 0)")
        return {"summarized_context": ""}

    # Get all previous analyses
    analyses = state['analysis_history']

    if not analyses:
        print(f"✓ No previous analyses to summarize")
        return {"summarized_context": ""}

    print(f"\n=== Summarizing Context from {len(analyses)} Previous Iterations ===")

    # Build summarization prompt
    analyses_text = ""
    for i, analysis in enumerate(analyses):
        analyses_text += f"\n--- Iteration {i} Analysis ---\n{analysis}\n"

    prompt = f"""Summarize the key vectorization insights from these previous analyses.

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

    return {"summarized_context": summary}

# Node: Analyze loops
def analyze_loops(state: VectorizationState):
    """Analyze code and all remark files to identify vectorization opportunities"""

    remark_files = state['remark_files']
    current_code = state['current_code']
    iteration = state['current_iteration']
    summarized_context = state['summarized_context']

    # Build remark analysis section (just list files, content is in summarized_context)
    remark_analysis = ""
    if remark_files:
        remark_analysis = f"\n\nOPTIMIZATION REMARKS AVAILABLE ({len(remark_files)} files):\n"
        for remark_file in remark_files:
            remark_analysis += f"- {remark_file}\n"

        # Include latest remark file content (not all)
        if remark_files:
            latest_remark = remark_files[-1]
            if os.path.exists(latest_remark):
                try:
                    with open(latest_remark, 'r') as f:
                        content = f.read()
                        remark_analysis += f"\nLatest remark file ({latest_remark}):\n```yaml\n{content[:2000]}\n```\n"
                except Exception as e:
                    remark_analysis += f"  (Could not read file: {e})\n"
    else:
        remark_analysis = "\n\nNo optimization remarks available yet."

    # Build iteration context with summarized history
    iteration_context = ""
    if iteration > 0 and summarized_context:
        iteration_context = f"""
ITERATION CONTEXT:
This is iteration {iteration} of {state['max_iterations']}.

Summary of previous iterations' findings:
{summarized_context}

Build upon these previous optimizations and look for additional opportunities.
"""
    elif iteration > 0:
        iteration_context = f"""
ITERATION CONTEXT:
This is iteration {iteration} of {state['max_iterations']}.
The code has been previously optimized in iteration {iteration - 1}.
You should build upon previous optimizations and look for additional opportunities.
"""

    prompt = f"""You are analyzing C++ code for vectorization opportunities.

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
    print(f"\n=== Loop Analysis (Iteration {iteration}) ===")
    print(analysis)
    print("=" * 60)

    # Store analysis in history
    analysis_history = state['analysis_history'].copy()
    analysis_history.append(analysis)

    return {
        "analysis_history": analysis_history
    }

# Node: Add pragmas
def add_pragmas(state: VectorizationState):
    """Add or refine vectorization pragmas based on analysis"""

    current_code = state['current_code']
    iteration = state['current_iteration']
    summarized_context = state['summarized_context']

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

    print(f"\n✓ Pragmas added/refined for iteration {iteration}")

    return {
        "current_code": transformed
    }

# Node: Write iteration file
def write_iteration_file(state: VectorizationState):
    """Write the modified code to the iteration file"""
    filepath = state['current_iteration_file']
    code = state['current_code']

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(code)

    print(f"✓ Wrote iteration file: {filepath}")

    return state

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
        timeout=60
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
    print(f"✓ Original file: {state['original_filepath']}")
    print(f"✓ Backup: {state['original_filepath']}.backup")
    print(f"✓ Iterations completed: {state['current_iteration'] + 1}")
    print(f"\nGenerated files:")
    for i, file in enumerate(state['iteration_files']):
        print(f"  Iteration {i}: {file}")
        remark_file = get_remark_filename(file)
        if os.path.exists(remark_file):
            print(f"              {remark_file}")

    # Clean up object files
    original_obj = get_object_filename(state['original_filepath'])
    if os.path.exists(original_obj):
        os.remove(original_obj)

    for file in state['iteration_files']:
        obj_file = get_object_filename(file)
        if os.path.exists(obj_file):
            os.remove(obj_file)

    print('='*60)

    return {"success": True}

# Node: Handle failure
def handle_failure(state: VectorizationState):
    """Handle compilation failure"""
    print(f"\n{'='*60}")
    print(f"✗ COMPILATION FAILED at iteration {state['current_iteration']}")
    print(f"✓ Original file unchanged: {state['original_filepath']}")
    print(f"✓ Backup available: {state['original_filepath']}.backup")
    print(f"✓ Partial results available in iteration files")
    print('='*60)

    # Clean up object files
    original_obj = get_object_filename(state['original_filepath'])
    if os.path.exists(original_obj):
        os.remove(original_obj)

    for file in state['iteration_files']:
        obj_file = get_object_filename(file)
        if os.path.exists(obj_file):
            os.remove(obj_file)

    return {"success": False}

# Build the workflow graph
def create_vectorization_workflow():
    workflow = StateGraph(VectorizationState)

    # Add nodes
    workflow.add_node("load_original", load_original)
    workflow.add_node("compile_baseline", compile_for_baseline)
    workflow.add_node("initialize_iteration", initialize_iteration)
    workflow.add_node("summarize_context", summarize_context)
    workflow.add_node("analyze_loops", analyze_loops)
    workflow.add_node("add_pragmas", add_pragmas)
    workflow.add_node("write_iteration_file", write_iteration_file)
    workflow.add_node("compile", compile_code)
    workflow.add_node("increment_iteration", increment_iteration)
    workflow.add_node("finalize", finalize)
    workflow.add_node("handle_failure", handle_failure)

    # Set entry point
    workflow.set_entry_point("load_original")

    # Build workflow
    workflow.add_edge("load_original", "compile_baseline")
    workflow.add_edge("compile_baseline", "initialize_iteration")
    workflow.add_edge("initialize_iteration", "summarize_context")
    workflow.add_edge("summarize_context", "analyze_loops")
    workflow.add_edge("analyze_loops", "add_pragmas")
    workflow.add_edge("add_pragmas", "write_iteration_file")
    workflow.add_edge("write_iteration_file", "compile")

    # Conditional: should continue iteration?
    workflow.add_conditional_edges(
        "compile",
        should_continue_iteration,
        {
            "continue": "increment_iteration",
            "finalize": "finalize",
            "failed": "handle_failure"
        }
    )

    # Loop back: increment then initialize next iteration
    workflow.add_edge("increment_iteration", "initialize_iteration")

    # End nodes
    workflow.add_edge("finalize", END)
    workflow.add_edge("handle_failure", END)

    return workflow.compile()

# Main function
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

    result = app.invoke(initial_state)
    return result

# CLI entry point
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Add vectorization pragmas to C++ code using iterative AI analysis"
    )

    parser.add_argument(
        "file",
        type=str,
        help="Path to the C++ file to optimize"
    )

    parser.add_argument(
        "--iterations", "-n",
        type=int,
        default=3,
        help="Number of iterative refinement passes (default: 3)"
    )

    args = parser.parse_args()

    result = vectorize_file(args.file, args.iterations)

    # Exit with appropriate code
    if result and result.get('success'):
        exit(0)
    else:
        exit(1)
