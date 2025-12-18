import subprocess
from typing import List
import re
import os
import fnmatch
from my_types import FunctionInfo, FunctionDraft, VectorizationState


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
