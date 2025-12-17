from typing import List
import re
import os
from my_types import FunctionInfo, FunctionDraft, VectorizationState, 


def extract_functions(file_content: str) -> List[FunctionInfo]:
    """
    Extract all function definitions from C/C++ file using regex.

    Args:
        file_content: Complete file content

    Returns:
        List of strings, each containing the full text of a function
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
