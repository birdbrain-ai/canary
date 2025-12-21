import datetime
import json
from pathlib import Path


class LLMLogger:
    """Handles logging of all LLM interactions with full transparency"""
    
    def __init__(self, log_base_dir: str):
        """
        Initialize LLM logger.

        Args:
            log_base_dir: Base directory for all LLM logs (e.g., "my_bench_llm_logs")
        """
        self.log_base_dir = Path(log_base_dir)
        self.log_base_dir.mkdir(exist_ok=True)
        self.previous_state = {}  # Track previous state for change detection
        print(f"📝 LLM logging enabled: {self.log_base_dir}")
        
    def log_llm_call(
        self,
        iteration: int,
        file_path: str,
        call_type: str,
        prompt: str,
        response: str,
        function_name: str | None = None,
        metadata: dict | None = None
    ):
        """
        Log a single LLM call with prompt and response in separate files.
        
        Args:
            iteration: Current iteration number
            file_path: Path to source file being processed
            call_type: Type of LLM call (e.g., "file_context", "analyze_loops")
            prompt: The prompt sent to LLM
            response: The response from LLM
            function_name: Optional function name (for function-level calls)
            metadata: Optional metadata dict (model, tokens, timestamp, etc.)
        """
        # Build directory path
        # Add file component first
        file_basename = Path(file_path).name
        dir_parts = [f"file_{file_basename}"]
        
        # Add function component if applicable
        if function_name:
            dir_parts.append(f"func_{function_name}")
        
        # Add iteration last
        dir_parts.append(f"iteration_{iteration}")
        
        # Add call type with numbering
        call_number = self._get_call_number(call_type, function_name)
        dir_parts.append(f"{call_number:02d}_{call_type}")
        
        # Create full directory path
        log_dir = self.log_base_dir.joinpath(*dir_parts)
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # Write prompt
        prompt_file = log_dir / "prompt.txt"
        prompt_file.write_text(prompt, encoding='utf-8')
        
        # Write response
        response_file = log_dir / "response.txt"
        response_file.write_text(response, encoding='utf-8')
        
        # Write metadata
        if metadata is None:
            metadata = {}
        
        metadata.update({
            'timestamp': datetime.datetime.now().isoformat(),
            'iteration': iteration,
            'file': file_path,
            'function': function_name,
            'call_type': call_type,
            'prompt_length': len(prompt),
            'response_length': len(response)
        })
        
        metadata_file = log_dir / "metadata.json"
        metadata_file.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
        
        print(f"  📝 Logged: {'/'.join(dir_parts[-2:])}")

    def log_state(self, state: dict, node_name: str, stage: str):
        """
        Log the full vectorization state to a file and print changes to stdout.

        Args:
            state: The VectorizationState dict
            node_name: Name of the node being executed
            stage: "before" or "after"
        """
        # Print state table to stdout
        self._print_state_table(state, node_name, stage)

        # Detect and print changes to stdout
        self._detect_and_print_changes(state, node_name, stage)

        # Build directory path similar to log_llm_call
        iteration = state.get("current_iteration", 0)
        file_path = state.get("file_path", "unknown")

        # Add file component first
        from pathlib import Path
        file_basename = Path(file_path).name
        dir_parts = [f"file_{file_basename}"]

        # Get function name from function_drafts if available
        function_drafts = state.get("function_drafts", {})
        function_name = None
        if function_drafts:
            # Get the first draft to extract function name
            first_draft = list(function_drafts.values())[0]
            if hasattr(first_draft, 'modified_function_text'):
                function_name = first_draft.modified_function_text.get("name", "unknown")

        if function_name:
            dir_parts.append(f"func_{function_name}")

        # Add iteration last
        dir_parts.append(f"iteration_{iteration}")

        # Add node name with numbering based on call type
        call_number = self._get_call_number(node_name, function_name)
        dir_parts.append(f"{call_number:02d}_{node_name}")

        # Create full directory path
        log_dir = self.log_base_dir.joinpath(*dir_parts)
        log_dir.mkdir(parents=True, exist_ok=True)

        # Write state file
        state_file = log_dir / f"state_{stage}.json"

        # Helper to serialize objects
        def json_serial(obj):
            if hasattr(obj, 'to_dict'):
                return obj.to_dict()
            return str(obj)

        try:
            state_file.write_text(
                json.dumps(state, default=json_serial, indent=2),
                encoding='utf-8'
            )
        except Exception as e:
            print(f"  ⚠️  Failed to log state: {e}")

    def _get_call_number(self, call_type: str, function_name: str | None) -> int:
        """Determine sequential number for call type"""
        # File-level calls
        if function_name is None:
            if call_type == "file_context":
                return 0
            elif call_type == "compile_code":
                return 1
            elif call_type == "run_code":
                return 2
        # Function-level calls
        else:
            if call_type == "summarize_context":
                return 0
            elif call_type == "analyze_loops":
                return 1
            elif call_type == "suggest_modifications":
                return 2
            elif call_type == "compile_code":
                return 3
            elif call_type == "run_code":
                return 4
            elif call_type == "reviewer":
                return 5
            elif call_type == "increment":
                return 6
            elif call_type == "manager":
                return 7
            elif call_type == "engineer":
                return 8
            elif call_type == "finalize":
                return 9
        return 99  # Unknown

    def _print_state_table(self, state: dict, node_name: str, stage: str):
        """
        Print a formatted table of VectorizationState fields to stdout.

        Args:
            state: The VectorizationState dict
            node_name: Name of the node being executed
            stage: "before" or "after"
        """
        print("\n" + "="*80)
        print(f"VectorizationState at {node_name} ({stage})")
        print("="*80)

        # Print basic fields
        print(f"{'Field':<25} | {'Value'}")
        print("-"*80)
        print(f"{'current_iteration':<25} | {state.get('current_iteration', 'N/A')}")
        print(f"{'max_iterations':<25} | {state.get('max_iterations', 'N/A')}")
        print(f"{'manager_chosen_i':<25} | {state.get('manager_chosen_i', 'N/A')}")
        print(f"{'file_path':<25} | {state.get('file_path', 'N/A')}")

        # Print function drafts summary
        function_drafts = state.get('function_drafts', {})
        print(f"{'function_drafts':<25} | {len(function_drafts)} draft(s)")

        for draft_id, draft in function_drafts.items():
            draft_dict = draft.to_dict() if hasattr(draft, 'to_dict') else draft
            func_name = draft_dict.get('modified_function_text', {}).get('name', 'unknown')
            compile_ok = draft_dict.get('compile_success', False)
            run_ok = draft_dict.get('run_success', False)
            vec_ok = draft_dict.get('vectorization_success', False)
            dead_end = draft_dict.get('dead_end', False)

            status = []
            if compile_ok:
                status.append("✓ compile")
            if run_ok:
                status.append("✓ run")
            if vec_ok:
                status.append("✓ vectorized")
            if dead_end:
                status.append("✗ dead_end")

            status_str = ", ".join(status) if status else "no status"
            print(f"  [{draft_id}] {func_name:<20} | {status_str}")

        # Print feedback fields (truncated)
        compiler_feedback = state.get('compiler_feedback', '')
        opt_remarks = state.get('optimization_remarks', '')

        if compiler_feedback:
            cf_preview = compiler_feedback[:60].replace('\n', ' ')
            if len(compiler_feedback) > 60:
                cf_preview += "..."
            print(f"{'compiler_feedback':<25} | {cf_preview}")

        if opt_remarks:
            or_preview = opt_remarks[:60].replace('\n', ' ')
            if len(opt_remarks) > 60:
                or_preview += "..."
            print(f"{'optimization_remarks':<25} | {or_preview}")

        print("="*80 + "\n")

    def _detect_and_print_changes(self, state: dict, node_name: str, stage: str):
        """
        Detect changes in VectorizationState compared to previous state and print them.

        Args:
            state: The current VectorizationState dict
            node_name: Name of the node being executed
            stage: "before" or "after"
        """
        if not self.previous_state:
            # First time, no comparison
            self.previous_state = self._copy_state(state)
            return

        changes = []

        # Check simple fields
        simple_fields = [
            'current_iteration', 'max_iterations', 'manager_chosen_i',
            'compiler_feedback', 'optimization_remarks'
        ]

        for field in simple_fields:
            old_val = self.previous_state.get(field)
            new_val = state.get(field)

            if old_val != new_val:
                # Truncate long strings for display
                old_display = str(old_val)
                new_display = str(new_val)

                if len(old_display) > 100:
                    old_display = old_display[:100] + "..."
                if len(new_display) > 100:
                    new_display = new_display[:100] + "..."

                changes.append((field, old_display, new_display))

        # Check function_drafts changes
        old_drafts = self.previous_state.get('function_drafts', {})
        new_drafts = state.get('function_drafts', {})

        # Check for new drafts
        for draft_id in new_drafts:
            if draft_id not in old_drafts:
                changes.append(('function_drafts', f'added draft {draft_id}', ''))

        # Check for removed drafts
        for draft_id in old_drafts:
            if draft_id not in new_drafts:
                changes.append(('function_drafts', f'removed draft {draft_id}', ''))

        # Check for changed drafts
        for draft_id in set(old_drafts.keys()) & set(new_drafts.keys()):
            old_draft = old_drafts[draft_id]
            new_draft = new_drafts[draft_id]

            old_dict = old_draft.to_dict() if hasattr(old_draft, 'to_dict') else old_draft
            new_dict = new_draft.to_dict() if hasattr(new_draft, 'to_dict') else new_draft

            draft_changes = []
            for key in ['compile_success', 'run_success', 'vectorization_success', 'dead_end']:
                if old_dict.get(key) != new_dict.get(key):
                    draft_changes.append(f"{key}: {old_dict.get(key)} → {new_dict.get(key)}")

            if draft_changes:
                changes.append(('function_drafts', f'draft {draft_id}', ', '.join(draft_changes)))

        # Print changes if any
        if changes:
            print("\n" + "~"*80)
            print(f"CHANGES detected at {node_name} ({stage})")
            print("~"*80)

            for field, old, new in changes:
                if new:  # Three-part change (field, old, new)
                    print(f"{field}:")
                    print(f"  OLD: {old}")
                    print(f"  NEW: {new}")
                else:  # Two-part change (field, description)
                    print(f"{field}: {old}")

            print("~"*80 + "\n")

        # Update previous state
        self.previous_state = self._copy_state(state)

    def _copy_state(self, state: dict) -> dict:
        """
        Create a deep copy of the state for comparison purposes.

        Args:
            state: The VectorizationState dict to copy

        Returns:
            A copy of the state
        """
        import copy

        # Make a copy, handling FunctionDraft objects
        copied = {}
        for key, value in state.items():
            if key == 'function_drafts':
                # Deep copy function drafts
                copied[key] = {}
                for draft_id, draft in value.items():
                    if hasattr(draft, 'to_dict'):
                        copied[key][draft_id] = copy.deepcopy(draft.to_dict())
                    else:
                        copied[key][draft_id] = copy.deepcopy(draft)
            elif key == 'logger':
                # Skip logger to avoid circular references
                continue
            else:
                try:
                    copied[key] = copy.deepcopy(value)
                except:
                    # Fallback for non-copyable objects
                    copied[key] = value

        return copied

