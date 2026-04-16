#!/usr/bin/env python3
"""
Harness for canary experiments — orchestrates context building and pi invocation.

Responsibilities:
  1. Extract target function + file context from benchmark directory
  2. Ablate the compiler diagnostic to the requested level
  3. Build the system prompt (context + instructions)
  4. Invoke pi with the extension and system prompt
  5. Check vectorization success and patch the log

Invocation:
  python3 src/harness/run_experiment.py \\
    --bench-path /path/to/s1113 \\
    --function s1113 \\
    --ablation-level 3 \\
    --model Qwen/Qwen2.5-Coder-14B-Instruct \\
    --temperature 0.8 \\
    --max-turns 5 \\
    --make-command "make CC=clang CFLAGS='...'" \\
    --validator "python3 validate_function_behavior.py"
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional


def find_source_file(bench_path: str) -> Optional[str]:
    """Find a C/C++ source file in the benchmark directory."""
    for ext in ['.c', '.cpp', '.cxx', '.cc']:
        files = list(Path(bench_path).glob(f'*{ext}'))
        if len(files) == 1:
            return str(files[0])
        if len(files) > 1:
            # Prefer files without 'test'/'main' in the name
            preferred = [f for f in files if 'test' not in f.name and 'main' not in f.name]
            if preferred:
                return str(preferred[0])
            return str(files[0])
    return None


def extract_function_and_context(source_file: str, func_name: str) -> tuple[Optional[str], Optional[str]]:
    """Extract function body and file context. Reuses more_helpers logic."""
    sys.path.insert(0, str(Path(__file__).parent.parent / 'utils'))
    try:
        from more_helpers import extract_functions, extract_file_context
    except ImportError:
        print('[canary] ERROR: could not import more_helpers', file=sys.stderr)
        return None, None

    try:
        source = Path(source_file).read_text()
        functions = extract_functions(source)
        func_info = next((f for f in functions if f['name'] == func_name), None)
        if not func_info:
            print(f'[canary] ERROR: function {func_name} not found in {source_file}', file=sys.stderr)
            return None, None
        context = extract_file_context(source)
        return func_info['full_text'], context
    except Exception as e:
        print(f'[canary] ERROR: could not extract function: {e}', file=sys.stderr)
        return None, None


def ablate_remarks(raw_yaml: str, func_name: str, level: int, is_clang: bool) -> str:
    """
    Ablate remarks by stripping fields based on level (0-5).

    Levels:
      0 → remark type only
      1 → + message string
      2 → + source location
      3 → + optimization name
      4 → + analysis details
      5 → full remark
    """
    if level >= 5 or not raw_yaml.strip():
        return raw_yaml

    docs = [d.strip() for d in raw_yaml.split('---') if d.strip()]
    ablated = []

    for doc in docs:
        lines = doc.split('\n')
        type_match = re.match(r'^!(\w+)', lines[0] if lines else '')
        remark_type = type_match.group(1) if type_match else 'Remark'
        parts = [f'{remark_type} remark']

        # Extract fields from YAML-like format (line: value pairs)
        full_text = '\n'.join(lines)
        message_match = re.search(r"String:\s+['\"]?([^'\"\\n]+)['\"]?", full_text)
        location_match = re.search(r"File:\s+([^,}]+).*Line:\s+(\d+).*Column:\s+(\d+)", full_text)
        name_match = re.search(r"Name:\s+(\S+)", full_text)

        if level >= 1 and message_match:
            parts.append(f"Message: {message_match.group(1).strip()}")
        if level >= 2 and location_match:
            parts.append(f"Location: {location_match.group(1).strip()}:{location_match.group(2)}:{location_match.group(3)}")
        if level >= 3 and name_match:
            parts.append(f"Optimization: {name_match.group(1)}")
        if level >= 4:
            # Include all details lines
            detail_lines = [l.strip() for l in lines if re.match(r'^\s*-\s+String:', l)]
            if detail_lines:
                parts.append("Details: " + "; ".join(detail_lines))

        ablated.append('\n'.join(parts))

    return '\n\n'.join(ablated)


def get_remarks_for_function(bench_path: str, func_name: str, is_clang: bool) -> str:
    """Read and filter remarks for the target function from .opt.yaml or .optrpt."""
    sys.path.insert(0, str(Path(__file__).parent.parent / 'utils'))
    try:
        from more_helpers import filter_remarks_by_function, find_files_with_ext
    except ImportError:
        return ""

    exts = ['.yaml'] if is_clang else ['.optrpt']
    remark_files = find_files_with_ext(bench_path, exts)
    if not remark_files:
        return ""

    results = []
    for rfile in remark_files:
        try:
            filtered = filter_remarks_by_function(rfile, func_name, include_loop_unroll=False, use_clang_not_intel=is_clang)
            if filtered:
                results.append(filtered)
        except Exception:
            pass

    return '\n'.join(results)


def run_make(bench_path: str, make_command: str) -> bool:
    """Run compilation to produce baseline remarks."""
    try:
        result = subprocess.run(make_command, shell=True, cwd=bench_path, capture_output=True, timeout=60, text=True)
        return result.returncode == 0
    except Exception as e:
        print(f'[canary] WARNING: make failed: {e}', file=sys.stderr)
        return False


def check_vectorization_success(bench_path: str, func_name: str, is_clang: bool) -> bool:
    """Check if target function was vectorized by reading remarks."""
    remarks = get_remarks_for_function(bench_path, func_name, is_clang)
    if is_clang:
        return '!Passed' in remarks
    else:
        return bool(re.search(r'was vectorized', remarks, re.IGNORECASE))


def run_validator(validator_cmd: str, bench_path: str) -> bool:
    """Run validator (if provided). Returns True if validation passes."""
    if not validator_cmd:
        return False  # No validator provided

    try:
        result = subprocess.run(validator_cmd, shell=True, cwd=bench_path, capture_output=True, timeout=120, text=True)
        return result.returncode == 0
    except Exception as e:
        print(f'[canary] WARNING: validator failed: {e}', file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description='Canary harness for vectorization experiments')
    parser.add_argument('--bench-path', required=True, help='Benchmark directory')
    parser.add_argument('--function', required=True, help='Target function name')
    parser.add_argument('--ablation-level', type=int, default=5, choices=range(6), help='Ablation level 0-5')
    parser.add_argument('--model', default='Qwen/Qwen2.5-Coder-14B-Instruct', help='Model ID')
    parser.add_argument('--temperature', type=float, default=0.8, help='Sampling temperature')
    parser.add_argument('--max-turns', type=int, default=5, help='Max agent turns')
    parser.add_argument('--compiler', choices=['clang', 'intel'], default='clang', help='Compiler family')
    parser.add_argument('--make-command', default='make', help='Compilation command')
    parser.add_argument('--validator', default='', help='Validator command (optional)')

    args = parser.parse_args()

    bench_path = os.path.abspath(args.bench_path)
    is_clang = args.compiler == 'clang'

    # Step 1: Run make to get baseline remarks
    print(f'[canary] Running make in {bench_path}...', file=sys.stderr)
    if not run_make(bench_path, args.make_command):
        print('[canary] WARNING: compilation may have failed; continuing anyway', file=sys.stderr)

    # Step 2: Find source file
    source_file = find_source_file(bench_path)
    if not source_file:
        print(f'[canary] ERROR: no C/C++ source file found in {bench_path}', file=sys.stderr)
        sys.exit(1)

    # Step 3: Extract function and context
    func_body, file_context = extract_function_and_context(source_file, args.function)
    if not func_body:
        sys.exit(1)

    initial_slice_lines = len(func_body.split('\n'))

    # Step 4: Read and ablate remarks
    raw_remarks = get_remarks_for_function(bench_path, args.function, is_clang)
    ablated_remarks = ablate_remarks(raw_remarks, args.function, args.ablation_level, is_clang)

    # Step 5: Build system prompt
    dynamic_context = f"""## Target Function

```c
{func_body}
```

## Program Context

```c
{file_context}
```

## Compiler Diagnostic (ablation level {args.ablation_level})

{ablated_remarks or '*(no optimization remarks available)*'}
"""

    prompt_template = Path(__file__).parent.parent.parent / 'prompts' / 'optimization.md'
    if prompt_template.exists():
        instructions = prompt_template.read_text()
    else:
        instructions = "Vectorize the function using the techniques and pragmas described."

    system_prompt = dynamic_context + '\n\n' + instructions

    # Step 6: Write system prompt to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write(system_prompt)
        prompt_file = f.name

    try:
        # Step 7: Invoke pi
        canary_ext = Path(__file__).parent.parent.parent / 'dist' / 'extensions' / 'canary.js'
        if not canary_ext.exists():
            print(f'[canary] ERROR: extension not found at {canary_ext}', file=sys.stderr)
            sys.exit(1)

        pi_cmd = [
            'node_modules/.bin/pi',
            '--extension', str(canary_ext),
            '--system-prompt', f'@{prompt_file}',
            '--model', f'local-llm/{args.model}',
            '--temperature', str(args.temperature),
            '--bench-path', bench_path,
            '--target-function', args.function,
            '--ablation-level', str(args.ablation_level),
            '--max-turns', str(args.max_turns),
            '--initial-slice-lines', str(initial_slice_lines),
            '--print',
            'Vectorize the function.',
        ]

        print(f'[canary] Invoking pi with {args.max_turns} max turns...', file=sys.stderr)
        result = subprocess.run(pi_cmd, cwd=bench_path)

        # Step 8: Check vectorization success
        vectorized = check_vectorization_success(bench_path, args.function, is_clang)
        validated = run_validator(args.validator, bench_path) if args.validator else True

        # Step 9: Patch pi-agent-log.json with success/failure_mode
        log_file = Path(bench_path) / 'pi-agent-log.json'
        if log_file.exists():
            try:
                log = json.loads(log_file.read_text())
                log['success'] = vectorized and validated
                if vectorized and validated:
                    log['failure_mode'] = None
                elif not vectorized:
                    log['failure_mode'] = 'vectorization_not_achieved'
                elif not validated:
                    log['failure_mode'] = 'semantic_divergence'
                log_file.write_text(json.dumps(log, indent=2))
            except Exception as e:
                print(f'[canary] WARNING: could not patch log: {e}', file=sys.stderr)

        # Print result
        status = 'SUCCESS' if (vectorized and validated) else 'FAILURE'
        print(f'[canary] {status}: vectorized={vectorized}, validated={validated}', file=sys.stderr)
        sys.exit(0 if (vectorized and validated) else 1)

    finally:
        # Cleanup
        Path(prompt_file).unlink(missing_ok=True)


if __name__ == '__main__':
    main()
