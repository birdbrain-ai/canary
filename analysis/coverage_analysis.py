'''
This is a script that compiles TSVC 2 with a compiler, parses its compilation report, and outputs a mapping between TSVC loop and remark. TODO:
1. Output field
2. Add the 'remark_name' field to the csv
'''

import os
import csv
import subprocess
import glob
import argparse
import re
from pathlib import Path

COMPILERS = {
    "intel": {
        "make_command": "source ~/tank/intel/oneapi/compiler/latest/env/vars.sh && make COMPILER=intel",
        "remark_glob": "**/tsvc.optrpt",
    },
    "clang_trunk": {
        "make_command": "make COMPILER=clang_trunk",
        "remark_glob": "**/tsvc_vec.opt.yaml",
    },
    "clang_canary": {
        "make_command": "make COMPILER=clang_canary",
        "remark_glob": "**/tsvc_vec.opt.yaml",
    },
    "clang_21.1.8_canary": {
        "make_command": "make COMPILER=clang_21.1.8_canary",
        "remark_glob": "**/tsvc_vec.opt.yaml",
    },
}


def compile_tsvc(tsvc_dir: Path, compiler: str) -> tuple[str | None, str]:
    """
    Compile TSVC with the given compiler.
    Returns (remark_file_path, compiler_output) where compiler_output
    is the combined stdout+stderr from compilation.
    """
    info = COMPILERS[compiler]
    cwd = os.getcwd()
    os.chdir(tsvc_dir)

    # Clean old build artifacts and remark files
    subprocess.run("make clean", shell=True, capture_output=True, text=True)
    for pattern in ["*.opt.yaml", "*.optrpt"]:
        subprocess.run(
            f"find . -name '{pattern}' -type f -delete",
            shell=True,
            capture_output=True,
            text=True,
        )

    # Compile
    result = subprocess.run(
        info["make_command"],
        shell=True,
        executable="/bin/bash",
        capture_output=True,
        text=True,
    )

    compiler_output = result.stdout + result.stderr

    if result.returncode != 0:
        print(f"ERROR: Compilation failed for {compiler}")
        print(result.stderr)
        os.chdir(cwd)
        return None, compiler_output

    # Find the remark file and convert to absolute path
    remark_files = glob.glob(info["remark_glob"], recursive=True)
    os.chdir(cwd)

    if remark_files:
        return str((tsvc_dir / remark_files[0]).resolve()), compiler_output
    return None, compiler_output
    
def initialize_parser():
    parser = argparse.ArgumentParser(
        description="Compile TSVC with specified compilers and generate a CSV of optimization remarks."
    )
    parser.add_argument("--intel", action="store_true", help="Include Intel compiler")
    parser.add_argument("--clang-trunk", action="store_true", help="Include Clang trunk compiler")
    parser.add_argument("--clang-canary", action="store_true", help="Include Clang canary compiler")
    parser.add_argument("--clang-canary-21", action="store_true", help="Include Clang 21.1.8 canary compiler")
    parser.add_argument("-o", "--output", default="coverage.csv", help="Output CSV file path (default: coverage.csv)")
    return parser


def extract_loop_functions(tsvc_c_path: str) -> list[str]:
    """Parse time_function calls from main() to get the list of benchmark functions."""
    with open(tsvc_c_path, 'r') as f:
        content = f.read()

    # Find all time_function(&function_name, ...) calls
    pattern = r'time_function\s*\(\s*&(\w+)\s*,'
    functions = re.findall(pattern, content)

    return functions

INTEL_REMARK_CATEGORIES = [
    "output dependence",
    "anti dependence",
    "multiple exits",
    "flow dependence",
    "outer loop",
    "loop control var",
    "function call",
    "seems inefficient",
]


def parse_intel_remarks(remark_file: str, func_name: str) -> str:
    """
    Parse Intel .optrpt file and return pipe-separated remark categories for a function.
    """
    with open(remark_file, 'r') as f:
        file_content = f.read()

    regex = f"Begin optimization report for: {func_name}[\\S\\s]*?================================================================="
    match_obj = re.search(regex, file_content)
    if match_obj is None:
        return ""

    block = match_obj.group()
    found = []
    for category in INTEL_REMARK_CATEGORIES:
        if category in block:
            found.append(category.replace(" ", "_"))

    return "|".join(found)


def parse_clang_trunk_remarks(remark_file: str, func_name: str) -> str:
    """
    Parse Clang trunk .opt.yaml file and return pipe-separated remark Names for a function.
    """
    yq_filter = f'select(.Function == "{func_name}")'
    result = subprocess.run(
        ["yq", yq_filter, remark_file],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return ""

    result_names = subprocess.run(
        ["yq", ".Name"],
        input=result.stdout,
        capture_output=True,
        text=True,
    )
    if result_names.returncode != 0 or not result_names.stdout.strip():
        return ""

    names = dict.fromkeys(
        n for n in result_names.stdout.strip().split("\n") if n and n != "---"
    )
    return "|".join(names)


def parse_clang_canary_remarks(remark_file: str, compiler_output: str, func_name: str) -> str:
    """
    Parse Clang canary compiler output for dependence reports for a function.
    Extracts dependence types (e.g. 'Forward write-after-read dependence') from
    blocks matching 'Dependence report for loop in <func_name>'.
    Returns pipe-separated deduplicated dependence types.
    """
    # Find all dependence report blocks for this function.
    # Each block starts with "Dependence report for loop in  <func_name>"
    # and continues with indented lines until the next warning or end of output.
    dep_pattern = re.compile(
        rf'Dependence report for loop in\s+{re.escape(func_name)}\n(.*?)(?=\n\S|\Z)',
        re.DOTALL,
    )
    blocks = dep_pattern.findall(compiler_output)

    # This captures two non-whitespace blocks immediately after the indentation in the
    # dependence reports. Brittle, but correct for now. 
    dep_type_pattern = re.compile(r'^\s+(\S+\s+\S+\s+dependence)', re.MULTILINE)

    found = dict.fromkeys(
        m.replace(" ", "_") for block in blocks for m in dep_type_pattern.findall(block)
    )
    return "|".join(found)


PARSERS = {
    "intel": lambda remark_file, compiler_output, func_name: parse_intel_remarks(remark_file, func_name),
    "clang_trunk": lambda remark_file, compiler_output, func_name: parse_clang_trunk_remarks(remark_file, func_name),
    "clang_canary": lambda remark_file, compiler_output, func_name: parse_clang_canary_remarks(remark_file, compiler_output, func_name),
    "clang_21.1.8_canary": lambda remark_file, compiler_output, func_name: parse_clang_canary_remarks(remark_file, compiler_output, func_name),
}


def main():
    parser = initialize_parser()
    args = parser.parse_args()

    # Map CLI flags to compiler names
    selected = []
    if args.intel:
        selected.append("intel")
    if args.clang_trunk:
        selected.append("clang_trunk")
    if args.clang_canary:
        selected.append("clang_canary")
    if args.clang_canary_21:
        selected.append("clang_21.1.8_canary")

    if not selected:
        parser.error("At least one compiler must be specified (--intel, --clang-trunk, --clang-canary, --clang-canary-21)")

    tsvc_dir = Path(__file__).resolve().parent.parent / "benchmarks" / "TSVC_2"
    tsvc_c_path = tsvc_dir / "src" / "tsvc.c"
    functions = extract_loop_functions(str(tsvc_c_path))

    # For each compiler: compile, parse remarks for all functions, then clean.
    # This avoids remark files from one compiler being deleted by the next.
    compiler_results = {}  # compiler -> {func_name -> remarks_string}
    for compiler in selected:
        print(f"Compiling TSVC with {compiler}...")
        remark_file, compiler_output = compile_tsvc(tsvc_dir, compiler)
        if remark_file is None:
            print(f"WARNING: No remark file produced for {compiler}")

        print(f"  Remark file: {remark_file}")
        print(f"  Parsing remarks...")

        compiler_results[compiler] = {}
        for func_name in functions:
            compiler_results[compiler][func_name] = PARSERS[compiler](
                remark_file, compiler_output, func_name
            )

    # Build CSV rows
    rows = []
    for func_name in functions:
        row = {"function": func_name}
        for compiler in selected:
            row[compiler] = compiler_results[compiler][func_name]
        rows.append(row)

    # Write CSV: function,compiler_1_remarks,compiler_2_remarks,...
    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["function"] + selected)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()

