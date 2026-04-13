# Vectorizer
# i think it's basically going to replace the old 'vectorizer.py'
# function i had earlier
# this should closely model the vectorizer.py

# Stub implementation — real compile / run / iterate logic replaces run_trial later.

from trial.trial import TrialResult
from worker.worker import Worker


class VectorizeWorker(Worker):
    def run_trial(self) -> TrialResult:
        result = TrialResult(success=True, compile_ok=True, iterations_used=0)
        self.trial.result = result
        return result
