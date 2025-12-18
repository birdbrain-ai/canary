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
        dir_parts = [f"iteration_{iteration}"]
        
        # Add file component
        file_basename = Path(file_path).name
        dir_parts.append(f"file_{file_basename}")
        
        # Add function component if applicable
        if function_name:
            dir_parts.append(f"func_{function_name}")
        
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
    
    def _get_call_number(self, call_type: str, function_name: str | None) -> int:
        """Determine sequential number for call type"""
        # File-level calls
        if function_name is None:
            if call_type == "file_context":
                return 0
            elif call_type == "manager":
                return 4
        # Function-level calls
        else:
            if call_type == "summarize_context":
                return 0
            elif call_type == "analyze_loops":
                return 1
            elif call_type == "suggest_modifications":
                return 2
            elif call_type == "reviewer":
                return 3
            elif call_type == "engineer":
                return 5
        return 99  # Unknown
