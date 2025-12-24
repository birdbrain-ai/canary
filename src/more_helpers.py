import subprocess
from typing import List
import re
import os
import fnmatch
from my_types import FunctionInfo


def extract_file_context(file_content: str) -> str:
    """
    Extract relevant context from file (structs, classes, globals, typedefs,
    enums, preprocessor directives, function declarations).
    These provide context for understanding what functions operate on.

    Args:
        file_content: Complete file content

    Returns:
        String containing extracted context declarations
    """
    lines = file_content.splitlines()
    context_lines = []

    i = 0
    in_multiline_comment = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Handle multi-line comments properly
        # Process comment markers in order they appear
        temp_line = stripped
        while '/*' in temp_line or '*/' in temp_line:
            start_idx = temp_line.find('/*')
            end_idx = temp_line.find('*/')

            # Determine which comes first
            if start_idx != -1 and (end_idx == -1 or start_idx < end_idx):
                # Found /* first
                if end_idx != -1:
                    # Both /* and */ on same line, /* comes first
                    # Remove the comment and continue
                    temp_line = temp_line[:start_idx] + temp_line[end_idx+2:]
                else:
                    # Only /* found - start of multi-line comment
                    in_multiline_comment = True
                    temp_line = temp_line[:start_idx]
                    break
            elif end_idx != -1:
                # Found */ first (or only */)
                in_multiline_comment = False
                temp_line = temp_line[end_idx+2:]
            else:
                break

        # If we're inside a multi-line comment, skip this line
        if in_multiline_comment:
            i += 1
            continue

        # Use temp_line (with comments removed) for further checks
        stripped = temp_line.strip()

        # Skip single-line comments and empty lines
        if not stripped or stripped.startswith('//'):
            i += 1
            continue

        # 1. Capture preprocessor directives (#define, #include, etc.)
        if line.lstrip().startswith('#'):
            context_lines.append(line)
            # Handle multi-line preprocessor directives (ending with \)
            while i < len(lines) - 1 and lines[i].rstrip().endswith('\\'):
                i += 1
                context_lines.append(lines[i])
            i += 1
            continue

        # 2. Capture typedef declarations (can be multi-line)
        if stripped.startswith('typedef'):
            typedef_lines = [line]
            # Capture until we find semicolon
            while i < len(lines) - 1 and ';' not in lines[i]:
                i += 1
                typedef_lines.append(lines[i])
            if i < len(lines) - 1 or ';' in lines[i]:
                # Found the semicolon
                if ';' not in lines[i]:
                    i += 1
                    typedef_lines.append(lines[i])
                context_lines.extend(typedef_lines)
            i += 1
            continue

        # 3. Capture struct/class/enum/union definitions (multi-line)
        if any(stripped.startswith(kw) for kw in ['struct', 'class', 'enum', 'union']):
            decl_lines = [line]

            # Check if this is a forward declaration (ends with ; and no {)
            if ';' in stripped and '{' not in stripped:
                context_lines.append(line)
                i += 1
                continue

            # It's a definition - find the opening brace and capture complete definition
            j = i
            # Look for opening brace (might be on same line or next few lines)
            while j < len(lines) and '{' not in lines[j]:
                j += 1
                if j < len(lines):
                    decl_lines.append(lines[j])
                if ';' in lines[j]:
                    # Found semicolon before brace - it's a forward declaration
                    context_lines.extend(decl_lines)
                    i = j + 1
                    break
            else:
                # Found opening brace, now find matching closing brace
                if j < len(lines):
                    brace_count = lines[j].count('{') - lines[j].count('}')
                    j += 1

                    while j < len(lines) and brace_count > 0:
                        decl_lines.append(lines[j])
                        brace_count += lines[j].count('{') - lines[j].count('}')
                        j += 1

                    context_lines.extend(decl_lines)
                    i = j
            continue

        # 4. Capture using declarations/directives
        if stripped.startswith('using'):
            context_lines.append(line)
            i += 1
            continue

        # 5. Capture namespace declarations (opening line only)
        if stripped.startswith('namespace'):
            context_lines.append(line)
            i += 1
            continue

        # 6. Detect and capture function declarations (prototypes), skip definitions
        # Look for function-like patterns: has parentheses
        if '(' in stripped and ')' in stripped and not any(stripped.startswith(kw) for kw in ['if', 'for', 'while', 'switch', 'sizeof']):
            # Gather complete signature (might span multiple lines)
            sig_lines = [line]
            j = i

            # Find where signature ends (either ; or {)
            paren_depth = 0
            found_end = False

            while j < len(lines) and not found_end:
                for char in lines[j]:
                    if char == '(':
                        paren_depth += 1
                    elif char == ')':
                        paren_depth -= 1
                    elif char in [';', '{'] and paren_depth == 0:
                        found_end = True
                        break

                if not found_end and j < len(lines) - 1:
                    j += 1
                    sig_lines.append(lines[j])
                else:
                    break

            # Check if it's a declaration (ends with ;) or definition (has {)
            combined = ' '.join(ln.strip() for ln in sig_lines)

            if ';' in combined and ('{' not in combined or combined.index(';') < combined.index('{')):
                # It's a function declaration - capture it
                context_lines.extend(sig_lines)
                i = j + 1
                continue
            elif '{' in combined:
                # It's a function definition - skip it entirely
                # Find and skip past the closing brace
                brace_count = 0
                for ln in sig_lines:
                    brace_count += ln.count('{') - ln.count('}')

                j += 1
                while j < len(lines) and brace_count > 0:
                    brace_count += lines[j].count('{') - lines[j].count('}')
                    j += 1

                i = j
                continue

        # 7. Capture potential global variable declarations
        # Heuristic: line with semicolon, has spaces (type + name), no braces, not a control statement
        if ';' in stripped and '{' not in stripped and '(' not in stripped:
            # Exclude control flow and other non-declarations
            if not any(stripped.startswith(kw) for kw in ['if', 'for', 'while', 'switch', 'return',
                                                          'break', 'continue', 'case', 'default',
                                                          'goto', 'delete', 'throw']):
                # Check if it looks like a declaration (has space, likely type and name)
                if ' ' in stripped:
                    # Additional check: should have identifier-like tokens
                    tokens = stripped.split()
                    if len(tokens) >= 2:  # At least type and name
                        context_lines.append(line)

        i += 1

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
        # Use word boundaries to ensure exact function name match (not substring)
        yq_filter = f'select(.Function and (.Function | test("\\\\b{re.escape(func_name)}\\\\b")))'
        
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

                # Check if func_name exactly matches demangled name
                if func_name == demangled:
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


def extract_compilation_errors(stderr_output: str) -> str:
    """
    Extracts 'error:' and 'warning:' lines from stderr along with the following 10 lines,
    
    Args:
        stderr_output: Raw stderr from compiler
        target_file: Path to the file we want errors for
        
    Returns:
        Filtered error/warning text
    """
    if not stderr_output:
        return ""
        
    # target_basename = os.path.basename(target_file)
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
        
    return "\n".join(filtered_lines) + "\n"
