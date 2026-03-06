import subprocess
from typing import List, TypedDict
import re
import os
import fnmatch


class FunctionInfo(TypedDict):
    name: str
    signature: str
    body: str
    full_text: str
    start_line: int
    end_line: int


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

    functions = [function for function in functions if (function["name"] != "time_function" and function["name"] != "main")]
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
    all_files = find_files_with_ext(directory, [".h", ".c", ".cpp", ".hxx", ".hpp"])

    # TODO(akash): make this configurable - i hate hard coding tsvc here
    # For TSVC benchmarks, only process tsvc.c (skip dummy.c, common.c, etc.)
    if "TSVC" in directory:
        all_files = [f for f in all_files if f.endswith("tsvc.c")]

    return all_files


def match_remark_files(target_file: str, remark_files: List[str], use_clang_not_intel: bool) -> List[str]:
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
    if use_clang_not_intel:
        pattern = f"{target_prefix}*.opt.yaml"
    else:
        pattern = f"{target_prefix}*.optrpt"

    matching = []
    for remark_file in remark_files:
        yaml_basename = os.path.basename(remark_file)
        if fnmatch.fnmatch(yaml_basename, pattern):
            matching.append(remark_file)
    return matching


def filter_vectorize_remarks(yaml_file_path: str) -> str:
    """
    Filter YAML optimization remarks to only include vectorization entries
    (loop-vectorize, slp-vectorizer, and loop-unroll).
    This dramatically reduces the content sent to the LLM.

    Args:
        yaml_file_path: Path to .opt.yaml file

    Returns:
        Filtered YAML content as string, or empty string if filtering fails
    """
    try:
        result = subprocess.run(
            ["yq", "select(.Pass == \"loop-vectorize\" or .Pass == \"slp-vectorizer\" or .Pass == \"loop-unroll\")", yaml_file_path],
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


def deduplicate_yaml_remarks(yaml_content: str) -> str:
    """
    Deduplicate YAML optimization remarks by removing duplicate entries.
    Uses string-based comparison with whitespace normalization to avoid
    YAML parsing issues with custom tags (!Missed, !Passed, etc.).

    Args:
        yaml_content: YAML content containing optimization remarks

    Returns:
        Deduplicated YAML content
    """
    if not yaml_content.strip():
        return ""

    try:
        # Split by YAML document separator
        # Documents are separated by "---" lines
        documents = yaml_content.split('\n---\n')

        seen_docs = set()
        unique_docs = []

        for doc in documents:
            if not doc.strip():
                continue

            # Remove leading "---" if present (happens with first document)
            doc_cleaned = doc.strip()
            if doc_cleaned.startswith('---'):
                doc_cleaned = doc_cleaned[3:].lstrip('\n')

            if not doc_cleaned.strip():
                continue

            # Normalize whitespace for comparison
            normalized_doc = normalize_whitespace_for_matching(doc_cleaned)

            if normalized_doc not in seen_docs:
                seen_docs.add(normalized_doc)
                # Keep original formatting for output (without leading ---)
                unique_docs.append(doc_cleaned)

        # Reconstruct YAML with document separators
        if not unique_docs:
            return ""

        result = "---\n" + "\n---\n".join(unique_docs)
        if not result.endswith('\n'):
            result += '\n'

        return result

    except Exception as e:
        print(f"⚠ Warning: Could not deduplicate YAML remarks: {e}")
        return yaml_content  # Return original on error


def filter_remarks_by_function(yaml_file_path: str, func_name: str, include_loop_unroll: bool, use_clang_not_intel: bool) -> str:
    """
    Filter YAML optimization remarks to only include entries for a specific function.
    Includes loop-vectorize, slp-vectorizer, and loop-unroll remarks.
    Uses two yq queries: one for exact matches, one for all docs (which we demangle).
    Concatenates and deduplicates results.

    Args:
        yaml_file_path: Path to .opt.yaml file
        func_name: Function name to filter for (e.g., "vecAdd", "init")

    Returns:
        Filtered YAML content as string containing complete YAML documents,
        or empty string if no matches or filtering fails
    """
    ### Case: INTEL
    is_intel_opt_report = not use_clang_not_intel
    if is_intel_opt_report:
        with open(yaml_file_path, 'r') as f:
            file_content = f.read()
            regex = f"Begin optimization report for: {func_name}[\S\s]*?================================================================="
            match_obj = re.search(regex, file_content)
            return match_obj.group() if match_obj is not None else  ""

    ### Main Case: CLANG
    if include_loop_unroll:
        query_part = "(.Pass == \"loop-vectorize\" or .Pass == \"loop-unroll\")"
    else:
        query_part = "(.Pass == \"loop-vectorize\")"
    
    try:
        # Query 1: Get docs with exact function name match (handles unmangled names)
        yq_filter_exact = f'select({query_part} and .Function == "{func_name}")'
        result_exact = subprocess.run(
            ["yq", yq_filter_exact, yaml_file_path],
            capture_output=True,
            text=True,
        )

        exact_matches = result_exact.stdout if result_exact.returncode == 0 else ""

        # Query 2: Get all docs, then filter by demangling
        result_all = subprocess.run(
            ["yq", f"select({query_part})", yaml_file_path],
            capture_output=True,
            text=True,
        )

        mangled_matches = ""
        if result_all.returncode == 0 and result_all.stdout.strip():
            # Parse documents and filter by demangled name
            documents = result_all.stdout.split('\n---\n')
            matching_docs = []

            for doc in documents:
                if not doc.strip():
                    continue

                # Extract Function field
                for line in doc.splitlines():
                    if line.strip().startswith('Function:'):
                        function_field = line.split('Function:', 1)[1].strip()

                        # Demangle and compare
                        demangled = demangle_function_name(function_field)
                        if demangled.strip() == func_name.strip():
                            # Clean up the doc (remove leading --- if present)
                            doc_cleaned = doc.strip()
                            if doc_cleaned.startswith('---'):
                                doc_cleaned = doc_cleaned[3:].lstrip('\n')
                            matching_docs.append(doc_cleaned)
                            break

            if matching_docs:
                mangled_matches = "---\n" + "\n---\n".join(matching_docs)
                if not mangled_matches.endswith('\n'):
                    mangled_matches += '\n'

        # Concatenate both result sets
        combined = exact_matches + mangled_matches

        if not combined.strip():
            return ""

        # Deduplicate the combined results
        return deduplicate_yaml_remarks(combined)

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
                if func_name.strip() == demangled.strip():
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
            timeout=600
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


def normalize_whitespace_for_matching(text: str) -> str:
    """
    Normalize whitespace in text for flexible matching.
    Collapses all whitespace runs to single spaces.

    Args:
        text: Original text

    Returns:
        Text with normalized whitespace
    """
    import re
    return re.sub(r'\s+', ' ', text.strip())


def extract_line_number_from_diagnostic(line: str) -> int | None:
    """
    Extracts the line number from a compiler diagnostic line.

    Expected formats:
    - file.c:123:45: warning: message (with column)
    - file.c:123: warning: message (without column)

    Args:
        line: Compiler diagnostic line

    Returns:
        Line number if found, None otherwise
    """
    import re
    # Pattern: filename:line:column: or filename:line:
    # Look for :NUMBER: or :NUMBER:NUMBER: pattern
    match = re.search(r':(\d+)(?::\d+)?:', line)
    if match:
        return int(match.group(1))
    return None


def extract_compilation_errors(
    stderr_output: str,
    line_range_start: int | None = None,
    line_range_end: int | None = None
) -> str:
    """
    Extracts 'error:' and 'warning:' lines from stderr along with context lines,
    with deduplication to avoid repeating the same warning/error multiple times.

    Context capture stops at the next diagnostic line (note:/remark:/warning:/error:)
    or after 10 lines, whichever comes first.

    Args:
        stderr_output: Raw stderr from compiler
        line_range_start: Optional start line (inclusive) for filtering warnings/notes/remarks
        line_range_end: Optional end line (inclusive) for filtering warnings/notes/remarks

    Returns:
        Filtered error/warning text
    """
    if not stderr_output:
        return ""

    # Keywords that mark the start of a new diagnostic
    diagnostic_keywords = ["note:", "remark:", "warning:", "error:"]

    lines = stderr_output.splitlines()
    filtered_blocks = []
    seen_messages = set()  # Track unique warning/error messages (normalized)
    i = 0

    while i < len(lines):
        line = lines[i]

        # Check for error/warning/note/remark
        is_error = "error:" in line
        is_warning = "warning:" in line
        is_note = "note:" in line
        is_remark = "remark:" in line

        if is_error or is_warning or is_note or is_remark:
            # Extract line number from the diagnostic
            line_number = extract_line_number_from_diagnostic(line)

            # Apply line range filtering only to non-errors
            should_include = True
            if not is_error and line_range_start is not None and line_range_end is not None:
                # Filter warnings, notes, and remarks by line range
                if line_number is None:
                    # If we can't extract a line number, exclude it to be safe
                    should_include = False
                elif not (line_range_start <= line_number <= line_range_end):
                    # Line number is outside the function range
                    should_include = False

            if should_include:
                # Normalize the message for comparison (whitespace-insensitive)
                normalized_message = normalize_whitespace_for_matching(line)

                # Only include if we haven't seen this message before
                if normalized_message not in seen_messages:
                    seen_messages.add(normalized_message)

                    # Capture this line and up to 10 following lines,
                    # but stop before the next diagnostic line
                    block = [lines[i]]
                    j = i + 1
                    context_lines = 0

                    while j < len(lines) and context_lines < 10:
                        # Stop if we hit another diagnostic line
                        if any(keyword in lines[j] for keyword in diagnostic_keywords):
                            break
                        block.append(lines[j])
                        context_lines += 1
                        j += 1

                    block.append("-" * 20)  # Separator
                    filtered_blocks.append("\n".join(block))

            # Move to next line
            i += 1
        else:
            i += 1

    if not filtered_blocks:
        return ""

    return "\n".join(filtered_blocks) + "\n"
