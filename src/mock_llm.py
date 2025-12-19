
class MockLLM:
    """
    A mock LLM that returns hardcoded, valid JSON responses for testing purposes.
    """

    def __init__(self):
        pass

    def generate(self, prompt: str, call_type: str) -> str:
        """
        Generate a mock response based on the call type.

        Args:
            prompt: The prompt text (ignored in mock).
            call_type: The type of agent calling (reviewer, manager, engineer).

        Returns:
            A JSON string representing a valid response for that agent.
        """
        if call_type == "reviewer":
            return """
{
  "dead_end": false,
  "reviewer_feedback": "Mock reviewer feedback: The function looks complex but might be vectorizable with some loop adjustments."
}
"""
        elif call_type == "manager":
            return """
{
  "i": 1,
  "explanation": "Mock manager choice: Draft 1 seems most promising based on heuristics."
}
"""
        elif call_type == "engineer":
            # Return a mock pragma action
            return """[
  {
    "action_type": "pragma",
    "line_number": 1,
    "pragma_type": "vectorize",
    "reasoning": "Mock pragma for testing"
  }
]"""
        
        else:
            return "{}"
