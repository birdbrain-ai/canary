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

    # Clean old remark files
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

    # Find the remark file
    remark_files = glob.glob(info["remark_glob"], recursive=True)
    os.chdir(cwd)

    return (remark_files[0] if remark_files else None, compiler_output)
    
def initialize_parser():
    parser = argparse.ArgumentParser(
        description="Compile TSVC with specified compilers and generate a CSV of optimization remarks."
    )
    parser.add_argument("--intel", action="store_true", help="Include Intel compiler")
    parser.add_argument("--clang-trunk", action="store_true", help="Include Clang trunk compiler")
    parser.add_argument("--clang-canary", action="store_true", help="Include Clang canary compiler")
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

def parse_intel_remarks(remark_file: str, func_name: str) -> str:
    """
    Parse Intel .optrpt file and return pipe-separated remark categories for a function.
    """
    # TODO: implement
    return ""


def parse_clang_trunk_remarks(remark_file: str, func_name: str) -> str:
    """
    Parse Clang trunk .opt.yaml file and return pipe-separated remark categories for a function.
    """
    # TODO: implement
    return ""


def parse_clang_canary_remarks(remark_file: str, compiler_output: str, func_name: str) -> str:
    """
    Parse Clang canary .opt.yaml file and compiler output (dependency warnings)
    and return pipe-separated remark categories for a function.
    """
    # TODO: implement
    return ""


PARSERS = {
    "intel": lambda remark_file, compiler_output, func_name: parse_intel_remarks(remark_file, func_name),
    "clang_trunk": lambda remark_file, compiler_output, func_name: parse_clang_trunk_remarks(remark_file, func_name),
    "clang_canary": lambda remark_file, compiler_output, func_name: parse_clang_canary_remarks(remark_file, compiler_output, func_name),
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

    if not selected:
        parser.error("At least one compiler must be specified (--intel, --clang-trunk, --clang-canary)")

    tsvc_dir = Path(__file__).resolve().parent.parent / "benchmarks" / "TSVC_2"

    # Compile with each selected compiler and collect remark files + compiler output
    remark_files = {}
    compiler_outputs = {}
    for compiler in selected:
        print(f"Compiling TSVC with {compiler}...")
        remark_file, compiler_output = compile_tsvc(tsvc_dir, compiler)
        if remark_file is None:
            print(f"WARNING: No remark file produced for {compiler}")
        remark_files[compiler] = remark_file
        compiler_outputs[compiler] = compiler_output

    print(f"\nRemark files: {remark_files}")

    # Extract function list from TSVC source
    tsvc_c_path = tsvc_dir / "src" / "tsvc.c"
    functions = extract_loop_functions(str(tsvc_c_path))

    # Parse remarks for each function and build CSV rows
    rows = []
    for func_name in functions:
        row = {"function": func_name}
        for compiler in selected:
            row[compiler] = PARSERS[compiler](
                remark_files[compiler], compiler_outputs[compiler], func_name
            )
        rows.append(row)

    # Write CSV: function,compiler_1_remarks,compiler_2_remarks,...
    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["function"] + selected)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()

