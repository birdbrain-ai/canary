###
### Two ideas
### 1. I need to expose only specific tools to LLMs
### 2. I have to shrink my giant prompts
###

from langgraph.graph import StateGraph, END
# from langchain_ollama import OllamaLLM
# from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
from langchain_community.document_loaders import TextLoader
from typing import TypedDict, List, Dict
import subprocess
import os
import shutil
import argparse
import fnmatch
import re
from pathlib import Path

import json
import datetime
import hashlib

class FunctionInfo(TypedDict):
    """Metadata about an extracted function"""
    name: str              # Function name (e.g., "vecAdd")
    signature: str         # Full signature line
    body: str              # Function body only
    full_text: str         # Complete function (signature + body)
    start_line: int        # Starting line number in file (0-indexed)
    end_line: int          # Ending line number in file (0-indexed)

class PragmaAction(TypedDict):
    """Action to insert a pragma at a specific line"""
    action_type: str  # Must be "pragma"
    line_number: int  # Line number in the function (0-indexed)
    pragma_type: str  # "vectorize", "interleave", or "vectorize_width"
    width: int | None  # For vectorize_width(N), otherwise None
    reasoning: str  # Brief explanation from LLM

class CodeReplaceAction(TypedDict):
    """Action to replace specific lines within a function"""
    action_type: str  # Must be "code_replace"
    start_line: int  # Start line (0-indexed, relative to function)
    end_line: int  # End line (0-indexed, inclusive)
    new_code: str  # Replacement code (can be multi-line)
    reasoning: str  # Explanation of change

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

    # Function tracking (NEW - for function-level processing)
    functions_in_file: List[FunctionInfo]  # All functions extracted from current file
    current_function_index: int            # Index of function being processed
    current_function: FunctionInfo         # Currently processing function
    modified_file_content: str             # File content being built up with modified functions
    summarized_file_context: str           # Summarized file context (structs/globals) - created ONCE per file
    transformed_function: str              # Temporary field for transformed function from LLM
    modification_actions: List[PragmaAction | CodeReplaceAction]  # Actions to apply

    # Iteration tracking
    current_iteration: int
    max_iterations: int

    # Remark files (per-directory)
    remark_files_baseline: List[str]     # Remark files from baseline compilation
    remark_files_current: List[str]      # Remark files from current iteration

    # Per-function context (CHANGED - now nested: file -> function -> context)
    function_analysis_history: Dict[str, Dict[str, List[str]]]  # file_path -> function_name -> [analyses]
    function_summarized_context: Dict[str, Dict[str, str]]      # file_path -> function_name -> summary

    # Compiler feedback (NEW)
    file_compilation_feedback: Dict[str, str]  # file_path -> formatted error/warning text

    # Status
    compiler_errors: List[str]
    success: bool

# llm = OllamaLLM(model="codellama:34b", base_url="http://localhost:11434")
# llm = ChatDeepSeek(
#     model="deepseek-reasoner",
#     api_key=os.getenv("DEEPSEEK_API_KEY")
#     # max_tokens=,  # Allow long function outputs without truncation
# )
llm = ChatOpenAI(
    model="codellama:34b",
    openai_api_key="EMPTY",
    openai_api_base="http://localhost:8000",
    max_tokens=,
    temperature=0.5
)


# AI Logging Configuration
AI_LOG_DIR = "ai_logs"
AI_LOG_FILE = os.path.join(AI_LOG_DIR, "ai_interactions.log")

def setup_ai_logging():
    """Create logging directory if it doesn't exist"""
    os.makedirs(AI_LOG_DIR, exist_ok=True)

    # Write header if file is new
    if not os.path.exists(AI_LOG_FILE):
        with open(AI_LOG_FILE, 'w', encoding='utf-8') as f:
            f.write("="*80 + "\n")
            f.write("AI INTERACTIONS LOG\n")
            f.write(f"Started: {datetime.datetime.now().isoformat()}\n")
            f.write("="*80 + "\n\n")
    else:
        with open(AI_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write("="*80 + "\n")
            f.write(f"NEW LOG STARTED: {datetime.datetime.now().isoformat()}\n")
            f.write("="*80 + "\n")

def log_ai_call(function_name: str, prompt: str, response: str, metadata: dict = None):
    """
    Log AI input/output to file

    Args:
        function_name: Name of the function making the AI call
        prompt: Input prompt sent to AI
        response: Output received from AI
        metadata: Optional dict with additional context (iteration, file, function, etc.)
    """
    timestamp = datetime.datetime.now().isoformat()
    prompt_hash = hashlib.md5(prompt.encode()).hexdigest()[:8]

    # Build log entry
    log_entry = f"\n{'='*80}\n"
    log_entry += f"TIMESTAMP: {timestamp}\n"
    log_entry += f"FUNCTION: {function_name}\n"
    log_entry += f"PROMPT_HASH: {prompt_hash}\n"

    if metadata:
        log_entry += "METADATA:\n"
        for key, value in metadata.items():
            log_entry += f"  {key}: {value}\n"

    log_entry += f"\n{'-'*80}\n"
    log_entry += "PROMPT (INPUT TO AI):\n"
    log_entry += f"{'-'*80}\n"
    log_entry += f"{prompt}\n"

    log_entry += f"\n{'-'*80}\n"
    log_entry += "RESPONSE (OUTPUT FROM AI):\n"
    log_entry += f"{'-'*80}\n"
    log_entry += f"{response}\n"
    log_entry += f"{'='*80}\n\n"

    # Write to log file
    with open(AI_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_entry)

    # Also write individual files for easier inspection
    log_filename = f"{timestamp.replace(':', '-')}_{function_name}_{prompt_hash}.txt"
    individual_log_path = os.path.join(AI_LOG_DIR, log_filename)

    with open(individual_log_path, 'w', encoding='utf-8') as f:
        f.write(log_entry)

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

def demangle_function_name(mangled: str) -> str:
    """
    Demangle a C++ function name using c++filt.

    Args:
        mangled: Mangled function name (e.g., _Z6vecAddPKfS0_Pfm)

    Returns:
        Demangled function name (e.g., vecAdd(float const*, float const*, float*, unsigned long))
        or original if demangling fails
    """
    try:
        result = subprocess.run(
            ["c++filt", mangled],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            demangled = result.stdout.strip()
            # Extract just the function name (before opening paren)
            if '(' in demangled:
                return demangled.split('(')[0]
            return demangled
        return mangled
    except Exception:
        return mangled

def extract_file_context(file_content: str) -> str:
    """
    Extract relevant context from file (structs, classes, globals, typedefs, enums).
    These provide context for understanding what functions operate on.

    Args:
        file_content: Complete file content

    Returns:
        String containing extracted context declarations
    """
    lines = file_content.splitlines()
    context_lines = []

    in_multiline_comment = False

    for line in lines:
        stripped = line.strip()

        # Handle multi-line comments
        if '/*' in stripped:
            in_multiline_comment = True
        if '*/' in stripped:
            in_multiline_comment = False
            continue
        if in_multiline_comment:
            continue

        # Skip single-line comments and empty lines
        if stripped.startswith('//') or not stripped:
            continue

        # Capture context: struct, class, typedef, enum, global variables
        if any(stripped.startswith(keyword) for keyword in ['struct', 'class', 'typedef', 'enum', 'using']):
            context_lines.append(line)
        # Capture global variable declarations (simple heuristic: type name = or type name;)
        elif ';' in stripped and not stripped.startswith('for') and not stripped.startswith('if') and not stripped.startswith('while'):
            # Rough heuristic for global vars
            if ' ' in stripped and not '{' in stripped and not stripped.startswith('return'):
                context_lines.append(line)

    return '\n'.join(context_lines)

def extract_functions(file_content: str) -> List[FunctionInfo]:
    """
    Extract all function definitions from C/C++ file using regex.

    Args:
        file_content: Complete file content

    Returns:
        List of FunctionInfo objects containing metadata for each function
    """
    functions = []
    lines = file_content.splitlines()

    # Regex pattern for C/C++ function signatures
    # Matches: [static/inline/etc] return_type function_name(params) [const] [{]
    # More permissive to handle various C/C++ styles
    func_sig_pattern = re.compile(
        r'^(?:static\s+|inline\s+|extern\s+|__attribute__\(\([^)]+\)\)\s+)*'  # Optional modifiers
        r'[\w\s:<>*&,]+\s+'  # Return type (can include templates, pointers, etc.)
        r'(\w+)\s*'  # Function name (captured)
        r'\([^)]*\)'  # Parameters
        r'(?:\s*const)?'  # Optional const
        r'(?:\s*\{|\s*$)',  # Either opening brace or end of line
        re.MULTILINE
    )

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Skip empty lines, preprocessor directives, and comments
        if not line or line.startswith('#') or line.startswith('//'):
            i += 1
            continue

        # Try to match function signature
        match = func_sig_pattern.match(line)
        if match:
            func_name = match.group(1)

            # Skip common non-function keywords that might match pattern
            if func_name in ['if', 'for', 'while', 'switch', 'return', 'sizeof']:
                i += 1
                continue

            start_line = i
            signature = lines[i]

            # Look for opening brace (might be on same line or next few lines)
            brace_line_idx = i
            found_brace = False

            # Check current line first
            if '{' in lines[i]:
                found_brace = True
            else:
                # Look ahead up to 3 lines for opening brace
                for j in range(i + 1, min(i + 4, len(lines))):
                    if '{' in lines[j]:
                        brace_line_idx = j
                        found_brace = True
                        break
                    # Stop if we hit something that's not whitespace or comment
                    stripped = lines[j].strip()
                    if stripped and not stripped.startswith('//') and stripped != '{':
                        break

            if not found_brace:
                # No opening brace found, not a function definition
                i += 1
                continue

            # Count braces starting from the brace line
            brace_count = lines[brace_line_idx].count('{') - lines[brace_line_idx].count('}')
            body_lines = []
            i = brace_line_idx + 1

            while i < len(lines) and brace_count > 0:
                current_line = lines[i]
                body_lines.append(current_line)
                brace_count += current_line.count('{') - current_line.count('}')
                i += 1

            end_line = i - 1
            body = '\n'.join(body_lines[:-1]) if body_lines else ""  # Exclude closing brace line
            full_text = '\n'.join(lines[start_line:end_line+1])

            functions.append({
                'name': func_name,
                'signature': signature.strip(),
                'body': body,
                'full_text': full_text,
                'start_line': start_line,
                'end_line': end_line
            })
        else:
            i += 1

    return functions

def apply_pragma(file_content: str, action: PragmaAction) -> str:
    """Apply a single pragma insertion to file content"""
    lines = file_content.splitlines()
    
    # Validate line number
    if action['line_number'] < 0 or action['line_number'] >= len(lines):
        print(f"⚠ Invalid line number {action['line_number']}")
        return file_content
    
    # Check if line is actually a for loop
    target_line = lines[action['line_number']].strip()
    if not target_line.startswith('for'):
        print(f"⚠ Line {action['line_number']} is not a for loop: {target_line[:50]}")
        return file_content
    
    # Build pragma string
    if action['pragma_type'] == 'vectorize':
        pragma = "#pragma clang loop vectorize(enable)"
    elif action['pragma_type'] == 'interleave':
        pragma = "#pragma clang loop interleave(enable)"
    elif action['pragma_type'] == 'vectorize_width':
        width = action.get('width', 4)
        pragma = f"#pragma clang loop vectorize_width({width})"
    else:
        print(f"⚠ Unknown pragma type: {action['pragma_type']}")
        return file_content
    
    # Insert pragma before the loop (preserve indentation)
    indent = len(lines[action['line_number']]) - len(lines[action['line_number']].lstrip())
    pragma_line = ' ' * indent + pragma
    
    lines.insert(action['line_number'], pragma_line)
    
    print(f"  ✓ Added {pragma} at line {action['line_number']}")
    
    return '\n'.join(lines)

def apply_code_replace(file_content: str, action: CodeReplaceAction) -> str:
    """
    Apply a code replacement action to function content.
    
    Replaces lines [start_line, end_line] with new_code, preserving indentation.
    
    Args:
        file_content: Function content as string
        action: CodeReplaceAction with line range and new code
        
    Returns:
        Modified function content
    """
    lines = file_content.splitlines()
    
    # Validate line numbers
    start = action.get('start_line', -1)
    end = action.get('end_line', -1)
    
    if start < 0 or end >= len(lines):
        print(f"⚠ Invalid line range [{start}, {end}] (function has {len(lines)} lines)")
        return file_content
    
    if start > end:
        print(f"⚠ Start line ({start}) must be <= end line ({end})")
        return file_content
    
    # Get indentation from first line being replaced
    if lines[start].strip():  # If line is not empty
        indent = len(lines[start]) - len(lines[start].lstrip())
    else:
        indent = 0
    
    # Split new code and apply indentation
    new_code = action.get('new_code', '').rstrip()
    if not new_code:
        print(f"⚠ Empty replacement code provided")
        return file_content
    
    new_lines = new_code.splitlines()
    
    # Apply indentation to each new line (preserve relative indentation)
    indented_new_lines = []
    for line in new_lines:
        if line.strip():  # Non-empty line
            # Preserve the line's own indentation relative to base
            indented_new_lines.append(' ' * indent + line.lstrip())
        else:  # Empty line
            indented_new_lines.append('')
    
    # Replace lines
    lines[start:end+1] = indented_new_lines
    
    reasoning = action.get('reasoning', 'No reason provided')
    print(f"  ✓ Replaced lines {start}-{end}: {reasoning[:60]}")
    
    return '\n'.join(lines)

def format_compilation_feedback(stderr_output: str, current_file: str) -> str:
    """
    Parse compiler stderr and format errors/warnings for LLM consumption.
    
    Filters to only errors related to current_file and formats them
    in a clear, actionable way.
    
    Args:
        stderr_output: Raw stderr from compiler
        current_file: Path to current file being processed
        
    Returns:
        Formatted error/warning text for LLM, or empty string if no relevant errors
    """
    if not stderr_output or not stderr_output.strip():
        return ""
    
    # Get basename for matching (errors might use relative or absolute paths)
    current_basename = os.path.basename(current_file)
    
    # Parse errors: <file>:<line>:<col>: <type>: <message>
    error_pattern = re.compile(r'^(.+?):(\d+):(\d+):\s+(error|warning):\s+(.+)$')
    
    relevant_errors = []
    for line in stderr_output.splitlines():
        match = error_pattern.match(line.strip())
        if match:
            file_path, line_num, col, err_type, message = match.groups()
            # Check if this error is for the current file
            if os.path.basename(file_path) == current_basename:
                relevant_errors.append({
                    'line': int(line_num),
                    'type': err_type,
                    'message': message.strip()
                })
    
    if not relevant_errors:
        return ""
    
    # Sort by line number
    relevant_errors.sort(key=lambda e: e['line'])
    
    # Limit to first 10 errors to avoid overwhelming the LLM
    if len(relevant_errors) > 10:
        relevant_errors = relevant_errors[:10]
        truncated = True
    else:
        truncated = False
    
    # Format for LLM
    formatted = "The compiler reported the following issues in this file:\n\n"
    for err in relevant_errors:
        formatted += f"Line {err['line']}: {err['type']}: {err['message']}\n"
    
    if truncated:
        formatted += f"\n(Showing first 10 of {len(relevant_errors)} errors)\n"
    
    return formatted


# Node: Setups baseline
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
    """Select next file to process, load its code, and extract functions"""
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

    # Extract all functions from file
    functions = extract_functions(code)
    print(f"✓ Extracted {len(functions)} functions")

    # CRITICAL: Reverse function order to process from bottom to top
    # This prevents line number shifts when replacing earlier functions
    functions_reversed = list(reversed(functions))
    print(f"✓ Functions will be processed in reverse order (bottom-to-top)")

    return {
        "current_file": current_file,
        "current_file_code": code,
        "functions_in_file": functions_reversed,
        "current_function_index": 0,
        "modified_file_content": code  # Start with original content
    }

# Node: Summarize file context (structs/globals)
def summarize_file_context(state: VectorizationState):
    """
    Summarize file-level context (structs, globals, types) ONCE per file.
    This summary is reused for all functions in the file.
    """
    file_content = state['current_file_code']

    print(f"\n=== Summarizing File Context ===")

    # Extract raw context
    raw_context = extract_file_context(file_content)

    # If context is empty or small, no need to summarize
    if len(raw_context) < 500:
        print(f"✓ Context is small ({len(raw_context)} chars), using as-is")
        return {"summarized_file_context": raw_context}

    # Summarize using LLM
    prompt = f"""Summarize the following C++ declarations (structs, classes, globals, typedefs, enums).
Focus on: data structure names, key fields, purpose, and how they might be used in loops.

Context:
```cpp
{raw_context}
```

Provide a concise summary (max 300 words) that gives context for understanding
what data structures and globals are available for vectorization analysis."""

    print(f"Summarizing {len(raw_context)} characters of context...")
    summary = llm.invoke(prompt)

    # Log AI interaction
    log_ai_call(
        function_name="summarize_file_context",
        prompt=prompt,
        response=summary,
        metadata={
            "file": state.get('current_file', 'unknown'),
            "iteration": state.get('current_iteration', 0),
            "raw_context_length": len(raw_context)
        }
    )

    print(f"✓ Context summarized ({len(summary)} characters)")

    return {"summarized_file_context": summary}

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

# Node: Summarize context (per-function)
def summarize_context(state: VectorizationState):
    """Compress previous iteration analyses for current FUNCTION"""

    iteration = state['current_iteration']
    current_file = state['current_file']
    current_func = state['current_function']
    func_name = current_func['name']

    function_analysis_history = state['function_analysis_history']
    function_summarized_context = state['function_summarized_context'].copy()

    # No summarization needed for first iteration
    if iteration == 0:
        print(f"✓ No previous context to summarize (iteration 0)")
        return {}

    # Get previous analyses for THIS FUNCTION
    if current_file not in function_analysis_history:
        print(f"✓ No previous analyses for this function")
        return {}

    func_analyses = function_analysis_history[current_file].get(func_name, [])

    if not func_analyses:
        print(f"✓ No previous analyses for function '{func_name}'")
        return {}

    print(f"Summarizing context for function '{func_name}' from {len(func_analyses)} previous iteration(s)")

    # Build summarization prompt
    analyses_text = ""
    for i, analysis in enumerate(func_analyses):
        analyses_text += f"\n--- Iteration {i} Analysis ---\n{analysis}\n"

    prompt = f"""Summarize the key vectorization insights from these previous analyses for function '{func_name}'.

Previous iteration analyses:
{analyses_text}

Create a CONCISE summary (max 300 words) covering:
1. Which loops in this function were identified as vectorization candidates
2. What pragmas were recommended and why
3. Any recurring issues or patterns observed
4. What should be tried next

Focus on actionable insights for the next iteration of THIS FUNCTION.
Output ONLY the summary, no preamble."""

    summary = llm.invoke(prompt)

    # Log AI interaction
    log_ai_call(
        function_name="summarize_context",
        prompt=prompt,
        response=summary,
        metadata={
            "file": current_file,
            "function": func_name,
            "iteration": iteration,
            "num_previous_analyses": len(func_analyses),
            "analyses_text_length": len(analyses_text)
        }
    )

    print(f"✓ Compressed {len(analyses_text)} chars to {len(summary)} chars")

    # Store summary for this function
    if current_file not in function_summarized_context:
        function_summarized_context[current_file] = {}
    function_summarized_context[current_file][func_name] = summary

    return {"function_summarized_context": function_summarized_context}

# Node: Analyze loops (per-function)
def analyze_loops(state: VectorizationState):
    """Analyze function and matching remark files for current function"""

    current_file = state['current_file']
    current_func = state['current_function']
    func_name = current_func['name']
    func_body = current_func['full_text']
    iteration = state['current_iteration']
    remark_files_baseline = state['remark_files_baseline']
    remark_files_current = state.get('remark_files_current', [])
    summarized_file_context = state.get('summarized_file_context', '')
    function_summarized_context = state['function_summarized_context']
    function_analysis_history = state['function_analysis_history'].copy()

    # Match remark files for this specific file
    matching_baseline = match_remark_files(current_file, remark_files_baseline)
    matching_current = match_remark_files(current_file, remark_files_current)
    all_matching = matching_baseline + matching_current

    # Build remark analysis section - filter by function name
    remark_analysis = ""
    if all_matching:
        remark_analysis = f"\n\nOPTIMIZATION REMARKS FOR THIS FUNCTION:\n"

        # Filter remarks by function name using demangling
        for remark_file in all_matching:
            filtered_content = filter_vectorize_remarks(remark_file)

            if filtered_content:
                # Further filter by demangled function name
                relevant_remarks = []
                for line in filtered_content.splitlines():
                    if 'Function:' in line:
                        # Extract mangled name and demangle
                        mangled = line.split('Function:')[1].strip()
                        demangled = demangle_function_name(mangled)
                        # Check if this remark is for our function
                        if func_name in demangled:
                            relevant_remarks.append(line)
                        else:
                            relevant_remarks = []  # Reset if not our function
                    elif relevant_remarks:  # We're in a relevant block
                        relevant_remarks.append(line)

                if relevant_remarks:
                    remark_analysis += f"\n--- From {os.path.basename(remark_file)} ---\n"
                    remark_analysis += "```yaml\n" + '\n'.join(relevant_remarks) + "\n```\n"

    if not remark_analysis or remark_analysis == "\n\nOPTIMIZATION REMARKS FOR THIS FUNCTION:\n":
        remark_analysis = "\n\nNo optimization remarks available for this function yet."

    # Get function-specific history summary
    func_history = function_summarized_context.get(current_file, {}).get(func_name, "")
    iteration_context = ""
    if iteration > 0 and func_history:
        iteration_context = f"""
PREVIOUS ITERATIONS SUMMARY FOR THIS FUNCTION:
{func_history}
"""
    elif iteration > 0:
        iteration_context = f"""
ITERATION CONTEXT:
This is iteration {iteration} of {state['max_iterations']} for function '{func_name}'.
"""

    prompt = f"""You are analyzing a C++ function for vectorization opportunities.

FUNCTION TO ANALYZE:
```cpp
{func_body}
```

PROGRAM CONTEXT (structs/globals used by this function):
{summarized_file_context}

{iteration_context}

{remark_analysis}

TASK:
Analyze the FOR LOOPS in this function to identify vectorization opportunities:
1. Loops that could benefit from vectorization but aren't vectorized yet
2. Loops that failed to vectorize (check remarks for failures)
3. Loops with vectorization issues that could be fixed with pragmas

Focus ONLY on FOR LOOPS with:
- Simple iteration patterns (i++, i+=1, etc.)
- Array/vector operations in the loop body
- No complex control flow

IMPORTANT: Only analyze FOR LOOPS. Do NOT suggest pragmas for while/do-while loops.

Provide a concise analysis of which FOR LOOPS in THIS FUNCTION need pragmas and why.
"""

    analysis = llm.invoke(prompt)

    # Log AI interaction
    log_ai_call(
        function_name="analyze_loops",
        prompt=prompt,
        response=analysis,
        metadata={
            "file": current_file,
            "function": func_name,
            "iteration": iteration,
            "num_matching_remarks": len(all_matching),
            "has_remark_analysis": bool(remark_analysis and remark_analysis != "\n\nNo optimization remarks available for this function yet.")
        }
    )

    print(f"\n=== Loop Analysis ===")
    print(analysis[:500] + "..." if len(analysis) > 500 else analysis)
    print("=" * 60)

    # Store analysis in per-function history
    if current_file not in function_analysis_history:
        function_analysis_history[current_file] = {}
    if func_name not in function_analysis_history[current_file]:
        function_analysis_history[current_file][func_name] = []
    function_analysis_history[current_file][func_name].append(analysis)

    return {
        "function_analysis_history": function_analysis_history
    }

# Node: Suggest modifications (per-function)
def suggest_modifications(state: VectorizationState):
    """Ask LLM to suggest modifications (pragmas or function diffs) as structured JSON actions"""

    current_file = state['current_file']
    current_func = state['current_function']
    func_name = current_func['name']
    func_body = current_func['full_text']
    iteration = state['current_iteration']
    summarized_file_context = state.get('summarized_file_context', '')
    function_summarized_context = state['function_summarized_context']

    # Get function-specific history summary
    func_history = function_summarized_context.get(current_file, {}).get(func_name, "")

    # Annotate lines with numbers for LLM reference
    func_lines = func_body.splitlines()
    annotated_code = '\n'.join([
        f"{i:4d} | {line}" 
        for i, line in enumerate(func_lines)
    ])

    # Build context sections
    context_section = ""
    if summarized_file_context:
        context_section = f"""
PROGRAM CONTEXT (structs/globals):
{summarized_file_context}
"""

    history_section = ""
    if iteration > 0 and func_history:
        history_section = f"""
PREVIOUS ITERATIONS SUMMARY FOR THIS FUNCTION:
{func_history}
"""

    # Build compiler feedback section (NEW)
    compiler_feedback_section = ""
    if iteration > 0:
        file_compilation_feedback = state.get('file_compilation_feedback', {})
        feedback = file_compilation_feedback.get(current_file, "")
        if feedback:
            compiler_feedback_section = f"""
COMPILER FEEDBACK (from previous iteration):
{feedback}
Please address these compilation issues in your modifications.
"""

    # Build iteration guidance
    iteration_guidance = ""
    if iteration == 0:
        iteration_guidance = """
GUIDANCE:
This is the first iteration. You have two options:

1. PRAGMA ACTIONS: For simple cases, suggest `vectorize` pragmas for FOR LOOPS that:
   - Have simple, predictable iteration patterns
   - Perform array/vector operations
   - Don't have complex control flow or dependencies

2. CODE REPLACE: For targeted code changes:
   - Add variable declarations (e.g., create local temporaries)
   - Hoist loop-invariant computations
   - Replace specific lines to fix vectorization blockers
   - Make multiple independent changes in one pass
   - Can replace entire function if needed (start_line=0, end_line=last_line)
"""
    else:
        iteration_guidance = f"""
GUIDANCE:
This is iteration {iteration}. Based on optimization remarks, you have two options:

1. PRAGMA ACTIONS: Suggest pragmas for FOR LOOPS where vectorization still failed
   - You may suggest: "vectorize", "interleave", or "vectorize_width"
   - Be conservative - only suggest if you're confident it will help

2. CODE REPLACE: Make targeted code changes:
   - Fix specific issues identified in optimization remarks
   - Add temporaries, hoist computations, break dependencies
   - Can replace entire function if needed (start_line=0, end_line=last_line)
"""

    prompt = f"""Analyze this C++ function for vectorization opportunities.

FUNCTION WITH LINE NUMBERS:
{annotated_code}

{context_section}

{history_section}

{compiler_feedback_section}

{iteration_guidance}

TASK:
Analyze this function and suggest modifications to enable vectorization.

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
- Multi-line: {{"action_type": "code_replace", "start_line": 3, "end_line": 5, "new_code": "for (int i = 0; i < n; i++) {{\n    output[i] = input[i];\n}}", "reasoning": "Simplify loop"}}
- Entire function: {{"action_type": "code_replace", "start_line": 0, "end_line": <last_line>, "new_code": "<entire function>", "reasoning": "Complete rewrite"}}

CRITICAL OUTPUT RULES:
- Output a JSON ARRAY: [{{...}}] or [{{...}}, {{...}}] for multiple actions
- You can mix pragma and code_replace actions in the same array
- If NO modifications needed, output an empty array: []
- DO NOT include any explanatory text, markdown, or code fences
- Output ONLY the JSON array, nothing else

IMPORTANT:
- Use pragmas for simple hints, code_replace for targeted changes
- code_replace can handle everything from single lines to entire functions
- When in doubt, don't suggest any modifications

OUTPUT (valid JSON array only):"""

    response = llm.invoke(prompt)

    # Log AI interaction
    log_ai_call(
        function_name="suggest_modifications",
        prompt=prompt,
        response=response,
        metadata={
            "file": current_file,
            "function": func_name,
            "iteration": iteration,
            "function_start_line": current_func['start_line'],
            "function_end_line": current_func['end_line'],
            "has_history": bool(func_history)
        }
    )

    # Parse JSON response (supports array format or fallback to JSONL)
    actions = []

    try:
        print(response)

        # Handle empty response
        if not response or not response.strip():
            actions = None
        else:
            # Try to parse as a single JSON object first (if wrapped in array)
            try:
                parsed = json.loads(response)
                # If it's already a list, use it directly
                if isinstance(parsed, list):
                    actions = parsed
                # If it's a single object, wrap it in a list
                elif isinstance(parsed, dict):
                    actions = [parsed]
                else:
                    actions = None
            except json.JSONDecodeError:
                # Parse as JSONL (one JSON object per line)
                for line in response.strip().split('\n'):
                    line = line.strip()
                    # Skip empty lines and lines that don't look like JSON
                    if not line or not (line.startswith('{') or line.startswith('[')):
                        continue
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            actions.append(obj)
                        elif isinstance(obj, list):
                            actions.extend(obj)
                    except json.JSONDecodeError as line_err:
                        print(f"⚠ Failed to parse line: {line}")
                        print(f"  Error: {line_err}")
                        continue

                # If no valid objects were parsed, set to None
                if not actions:
                    actions = None

        if actions:
            print(f"  Parsed {len(actions)} action(s): {actions}")
    except Exception as e:
        print(f"⚠ Failed to parse LLM output: {response}")
        print(f"  Error: {e}")
        actions = None

    if not actions:
        print(f"✓ No modification actions suggested for function '{func_name}'")
    else:
        print(f"✓ LLM suggested {len(actions)} modification action(s) for function '{func_name}'")

    return {
        "modification_actions": actions
    }

# Node: Apply modifications
def apply_modifications(state: VectorizationState):
    """Apply all suggested modification actions (pragmas and code_replace) to the function"""
    
    func_body = state['current_function']['full_text']
    func_name = state['current_function']['name']
    actions = state.get('modification_actions', [])
    
    if not actions:
        print(f"✓ No modifications to apply for function '{func_name}'")
        return {"transformed_function": func_body}
    
    # Separate pragma and code_replace actions
    pragma_actions = [a for a in actions if a.get('action_type', 'pragma') == 'pragma']
    code_replace_actions = [a for a in actions if a.get('action_type') == 'code_replace']
    
    modified = func_body
    
    # Apply code_replace actions first (in reverse order to preserve line numbers)
    if code_replace_actions:
        print(f"\n=== Applying {len(code_replace_actions)} Code Replacement(s) ===")
        actions_sorted = sorted(code_replace_actions, key=lambda a: a.get('start_line', 0), reverse=True)
        
        for action in actions_sorted:
            new_modified = apply_code_replace(modified, action)
            modified = new_modified
    
    # Then apply pragma actions (in reverse order to preserve line numbers)
    if pragma_actions:
        print(f"\n=== Applying {len(pragma_actions)} Pragma Action(s) ===")
        actions_sorted = sorted(pragma_actions, key=lambda a: a.get('line_number', 0), reverse=True)
        
        applied_count = 0
        for action in actions_sorted:
            print(f"  Attempting: {action.get('pragma_type', 'unknown')} at line {action.get('line_number', '?')}")
            new_modified = apply_pragma(modified, action)
            if new_modified != modified:
                applied_count += 1
            modified = new_modified
        
        print(f"✓ Applied {applied_count}/{len(pragma_actions)} pragma(s)")
    
    if code_replace_actions or pragma_actions:
        print(f"✓ Applied modifications to function '{func_name}'")
    
    return {"transformed_function": modified}




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
    
    # Generate per-file compilation feedback
    file_compilation_feedback = {}
    if result.returncode != 0:
        # Parse stderr and create feedback for each target file
        target_files = state['target_files']
        for target_file in target_files:
            feedback = format_compilation_feedback(result.stderr, target_file)
            if feedback:
                file_compilation_feedback[target_file] = feedback
        
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
    workflow.add_node("summarize_file_context", summarize_file_context)  # NEW
    workflow.add_node("initialize_function_processing", initialize_function_processing)  # NEW
    workflow.add_node("summarize_context", summarize_context)  # Now per-function
    workflow.add_node("analyze_loops", analyze_loops)  # Now per-function
    workflow.add_node("suggest_modifications", suggest_modifications)  # Renamed from add_pragmas
    workflow.add_node("apply_modifications", apply_modifications)  # Renamed from apply_pragma_actions
    workflow.add_node("replace_function_in_file", replace_function_in_file)  # NEW
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

    # Phase 3: Per-file loop (middle loop)
    workflow.add_edge("initialize_file_processing", "summarize_file_context")

    # Decision: Does this file have any functions?
    workflow.add_conditional_edges(
        "summarize_file_context",
        has_functions_to_process,
        {
            "process_functions": "initialize_function_processing",  # Enter function loop
            "write_file": "write_file"  # Skip to next file if no functions
        }
    )

    # Phase 4: Per-function loop (inner loop - NEW)
    workflow.add_edge("initialize_function_processing", "summarize_context")
    workflow.add_edge("summarize_context", "analyze_loops")
    workflow.add_edge("analyze_loops", "suggest_modifications")
    workflow.add_edge("suggest_modifications", "apply_modifications")
    workflow.add_edge("apply_modifications", "replace_function_in_file")

    # Decision: More functions to process in this file?
    workflow.add_conditional_edges(
        "replace_function_in_file",
        should_continue_functions,
        {
            "continue_functions": "initialize_function_processing",  # Loop back to next function
            "write_file": "write_file"  # All functions done, write file
        }
    )

    # Decision: More files to process?
    workflow.add_conditional_edges(
        "write_file",
        should_continue_files,
        {
            "continue_files": "initialize_file_processing",  # Loop back to next file
            "compile_iteration": "compile_iteration_benchmark"  # All files done, compile
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

    # Setup AI logging
    setup_ai_logging()
    print(f"✓ AI logging initialized: {AI_LOG_FILE}")

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

        # Function tracking (NEW)
        "functions_in_file": [],
        "current_function_index": 0,
        "current_function": {},
        "modified_file_content": "",
        "summarized_file_context": "",
        "transformed_function": "",  # Temporary field for function transformation
        "modification_actions": [],

        # Iteration tracking
        "current_iteration": 0,
        "max_iterations": max_iterations,

        # Remark files
        "remark_files_baseline": [],
        "remark_files_current": [],

        # Per-function context (CHANGED from per-file)
        "function_analysis_history": {},
        "function_summarized_context": {},

        # Compiler feedback
        "file_compilation_feedback": {},

        # Status
        "compiler_errors": [],
        "success": False
    }

    # Run workflow with increased recursion limit for multi-iteration/multi-file processing
    # Each iteration processes all files through multiple nodes, so we need a high limit
    result = app.invoke(initial_state, config={"recursion_limit": 20000})
    return result

# Legacy function (kept for backwards compatibility)
def vectorize_file(filepath: str, max_iterations: int = 3):
    """Add vectorization pragmas to a C++ file with iterative refinement"""

    if not os.path.exists(filepath):
        print(f"✗ Error: File not found: {filepath}")
        return None

    # Setup AI logging
    setup_ai_logging()
    print(f"✓ AI logging initialized: {AI_LOG_FILE}")

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
