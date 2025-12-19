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
        Log the full vectorization state to a file.
        
        Args:
            state: The VectorizationState dict
            node_name: Name of the node being executed
            stage: "before" or "after"
        """
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

