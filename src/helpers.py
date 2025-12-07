import subprocess
import os
from pathlib import Path
from typing import List
import re
import fnmatch

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

def filter_remarks_by_function(yaml_file_path: str, func_name: str) -> str:
    """
    Filter YAML optimization remarks to only include entries for a specific function.
    Uses yq to properly parse YAML and match against both mangled and demangled function names.
    
    Args:
        yaml_file_path: Path to .opt.yaml file
        func_name: Function name to filter for (e.g., "vecAdd")
    
    Returns:
        Filtered YAML content as string containing complete YAML documents,
        or empty string if no matches or filtering fails
    """
    try:
        # First, filter for loop-vectorize pass
        result = subprocess.run(
            ["yq", "select(.Pass == \"loop-vectorize\")", yaml_file_path],
            capture_output=True,
            text=True,
        )
        
        if result.returncode != 0 or not result.stdout.strip():
            return ""
        
        # Now filter by function name
        # We need to check if func_name appears in the Function field
        # The Function field contains mangled names, so we need to:
        # 1. Try exact match with mangled name
        # 2. Try substring match (func_name in demangled version)
        
        # Use yq to select documents where Function field contains our function name
        # This works because demangled names typically contain the original function name
        yq_filter = f'select(.Function and (.Function | test("{re.escape(func_name)}")))'
        
        result = subprocess.run(
            ["yq", yq_filter],
            input=result.stdout,
            capture_output=True,
            text=True,
        )
        
        if result.returncode == 0:
            # If direct match didn't work, try demangling approach
            if not result.stdout.strip():
                # Fall back to manual demangling check
                return filter_remarks_by_function_with_demangle(result.stdout, func_name)
            return result.stdout
        else:
            print(f"⚠ Warning: yq function filter failed for {yaml_file_path}")
            return ""
            
    except Exception as e:
        print(f"⚠ Warning: Could not filter remarks by function for {yaml_file_path}: {e}")
        return ""

def filter_remarks_by_function_with_demangle(yaml_content: str, func_name: str) -> str:
    """
    Filter YAML remarks by demangling function names.
    Fallback when direct yq filtering doesn't work.
    
    Args:
        yaml_content: YAML content (already filtered by pass)
        func_name: Function name to match
    
    Returns:
        Filtered YAML documents as string
    """
    try:
        # Parse YAML documents
        import yaml
        
        documents = list(yaml.safe_load_all(yaml_content))
        matching_docs = []
        
        for doc in documents:
            if doc and 'Function' in doc:
                mangled = doc['Function']
                demangled = demangle_function_name(mangled)
                
                # Check if func_name appears in demangled name
                if func_name in demangled:
                    matching_docs.append(doc)
        
        if not matching_docs:
            return ""
        
        # Convert back to YAML
        result = ""
        for doc in matching_docs:
            result += "---\n"
            result += yaml.dump(doc, default_flow_style=False)
            result += "...\n"
        
        return result
        
    except Exception as e:
        print(f"⚠ Warning: Demangle-based filtering failed: {e}")
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

def extract_compilation_errors(stderr_output: str, target_file: str) -> str:
    """
    Extracts 'error:' and 'warning:' lines from stderr along with the following 10 lines,
    but ONLY if the error line contains the target filename.
    
    Args:
        stderr_output: Raw stderr from compiler
        target_file: Path to the file we want errors for
        
    Returns:
        Filtered error/warning text
    """
    if not stderr_output:
        return ""
        
    target_basename = os.path.basename(target_file)
    lines = stderr_output.splitlines()
    filtered_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Check for error/warning AND target filename on the same line
        if ("error:" in line or "warning:" in line):
            # Capture this line and up to 10 following lines
            end_idx = min(i + 11, len(lines))
            filtered_lines.extend(lines[i:end_idx])
            filtered_lines.append("-" * 20) # Separator
            i = end_idx
        else:
            i += 1
            
    if not filtered_lines:
        return ""
        
    return f"File: {target_file}\n" + "\n".join(filtered_lines) + "\n" + ("-" * 20)


