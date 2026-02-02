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

# Compile TSVC_2
def compile_tsvc(tsvc_dir, make_command_clang: str, make_command_intel):
    '''
    - Compile TSVC
    - Return optimization remarks for tsvc.c:
    - Intel: "tsvc.optrpt"
    '''
    cwd = os.getcwd()
    os.chdir(tsvc_dir)
    
    # Clean old output
    rm_result = subprocess.run(
        "find . -name '*.opt.yaml' -type f -delete",
        shell=True,
        capture_output=True,
        text=True,
    )

    rm_result = subprocess.run(
        "find . -name '*.optrpt' -type f -delete",
        shell=True,
        capture_output=True,
        text=True,
    )
    
    result = subprocess.run(
        make_command_clang,
        shell=True,
        executable='/bin/bash',
        capture_output=True,
        text=True,
    )

    result = subprocess.run(
        make_command_intel,
        shell=True,
        executable='/bin/bash',
        capture_output=True,
        text=True,
    )
    
    if result.returncode != 0:
        print("ERROR: Compilation failed")
        exit(1)

    # Extract compilation feedback
    clang_remark_file = glob.glob('**/tsvc_vec.opt.yaml', recursive=True)
    intel_remark_file = glob.glob('**/tsvc.optrpt', recursive=True)

    os.chdir(cwd)
    
    return [clang_remark_file[0] if len(clang_remark_file) > 0 else None, intel_remark_file[0] if len(intel_remark_file) > 0 else None]
    
def initialize_parser():
    # 1. Initialize the parser
    parser = argparse.ArgumentParser(description="This is a script that compiles TSVC 2 with a compiler, parses its compilation report, and outputs a mapping between TSVC loop and remark.")

    # 2. Add arguments
    parser.add_argument("tsvc_dir", help="The directory of TSVC")
    parser.add_argument("-i", "--intel", action="store_true", help="Use intel instead of Clang (the default)")
    parser.add_argument("-o", "--output", default="functions_to_remarks.csv", help="Output CSV file path (default: functions_to_remarks.csv)")
    return parser


def extract_loop_functions(tsvc_c_path: str) -> list[str]:
    """Parse time_function calls from main() to get the list of benchmark functions."""
    with open(tsvc_c_path, 'r') as f:
        content = f.read()

    # Find all time_function(&function_name, ...) calls
    pattern = r'time_function\s*\(\s*&(\w+)\s*,'
    functions = re.findall(pattern, content)

    return functions

def filter_remarks_by_function(yaml_file_path: str, func_name: str, include_loop_unroll: bool, use_clang_not_intel: bool) -> tuple[str, list[str]]:
    """
    Filter YAML optimization remarks to only include entries for a specific function.
    Includes loop-vectorize, slp-vectorizer, and loop-unroll remarks.
    Uses two yq queries: one for exact matches, one for all docs (which we demangle).
    Concatenates and deduplicates results.

    Args:
        yaml_file_path: Path to .opt.yaml file
        func_name: Function name to filter for (e.g., "vecAdd", "init")

    Returns:
        Tuple of (filtered YAML content as string, list of remark Names)
    """

    ### Case: INTEL
    is_intel_opt_report = not use_clang_not_intel
    if is_intel_opt_report:
        with open(yaml_file_path, 'r') as f:
            file_content = f.read()
            regex = f"Begin optimization report for: {func_name}[\S\s]*?================================================================="
            match_obj = re.search(regex, file_content)
            return (match_obj.group() if match_obj is not None else "", [])

    ### Case: CLANG
    if include_loop_unroll:
        query_part = "(.Pass == \"loop-vectorize\" or .Pass == \"loop-unroll\")"
    else:
        query_part = "(.Pass == \"loop-vectorize\")"

    # Query: Get docs with exact function name match (handles unmangled names)
    yq_filter_exact = f'select({query_part} and .Function == "{func_name}")'
    result_exact = subprocess.run(
        ["yq", yq_filter_exact, yaml_file_path],
        capture_output=True,
        text=True,
    )

    # print(yq_filter_exact)
    # print(yaml_file_path)



    exact_matches = result_exact.stdout if result_exact.returncode == 0 else ""

    # Extract the Name field from each YAML document using yq
    remark_names = []
    if exact_matches:
        result_names = subprocess.run(
            ["yq", ".Name"],
            input=exact_matches,
            capture_output=True,
            text=True,
        )
        if result_names.returncode == 0 and result_names.stdout.strip():
            remark_names = [name for name in result_names.stdout.strip().split("\n") if name]

    return (exact_matches, remark_names)



    
def main():
    # Parse arguments
    parser = initialize_parser()
    args = parser.parse_args()
    make_command_intel = "source ~/tank/intel/oneapi/compiler/latest/env/vars.sh && make COMPILER=intel"
    make_command_clang = "make COMPILER=clang"

    # Convert to absolute path before compile_tsvc changes directory
    tsvc_dir = Path(args.tsvc_dir).resolve()

    # Compile TSVC_2
    clang_remark_file, intel_remark_file = compile_tsvc(args.tsvc_dir, make_command_intel, make_command_clang)

    remark_file = tsvc_dir / (intel_remark_file if args.intel else clang_remark_file)
    # print(remark_file)

    # Get a list of all functions in TSVC
    functions = extract_loop_functions(tsvc_dir / "src" / "tsvc.c")

    mapping = []
    
    for function in functions:
        # Extract optimization remarks
        function_remark_clang, clang_remark_names = filter_remarks_by_function(tsvc_dir / clang_remark_file, function, False, True)
        # function_remark_intel = ""
        function_remark_intel, intel_remark_names = filter_remarks_by_function(tsvc_dir / intel_remark_file, function, False, False)
        # Add to dictionary
        mapping.append([function, clang_remark_names, function_remark_clang, intel_remark_names, function_remark_intel])

    with open(args.output, 'w', newline='') as csvfile:
        csvwriter = csv.writer(csvfile)
        fields = ['function', 'clang_remark_names', 'clang_remark_text', 'intel_remark_names', 'intel_remark_text']
        csvwriter.writerow(fields)
        csvwriter.writerows(mapping)

if __name__ == "__main__":
    main()
