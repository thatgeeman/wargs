import json
import uuid
from abc import ABC


class InvestigationState(ABC):
    def __init__(
        self,
        question: str,
        hypotheses: list,
        evidence: list,
        sources: list,
        contradictions: list,
        current_step: int,
    ):
        self.question = question
        self.hypotheses = hypotheses
        self.evidence = evidence
        self.sources = sources
        self.contradictions = contradictions
        self.current_step = current_step
        self.status = None
        self.budget = None

        self._session_id = str(uuid.uuid4())

    def to_json(self):
        data = {
            "question": self.question,
            "hypotheses": self.hypotheses,
            "evidence": self.evidence,
            "sources": self.sources,
            "contradictions": self.contradictions,
            "current_step": self.current_step,
            "status": self.status,
            "budget": self.budget,
        }
        return json.dumps(data)

    @classmethod
    def from_json(cls, json_str: str):
        data = json.loads(json_str)
        return cls(
            question=data["question"],
            hypotheses=data["hypotheses"],
            evidence=data["evidence"],
            sources=data["sources"],
            contradictions=data["contradictions"],
            current_step=data["current_step"],
        )

    @classmethod
    def from_path(cls, path: str):
        with open(path, "r") as f:
            json_str = f.read()
        return cls.from_json(json_str)

    def dump_trace(self, path: str = None):
        trace = {
            "session_id": self._session_id,
            "question": self.question,
            "hypotheses": self.hypotheses,
            "evidence": self.evidence,
            "sources": self.sources,
            "contradictions": self.contradictions,
            "current_step": self.current_step,
            "status": self.status,
            "budget": self.budget,
        }
        if path:
            with open(path, "w") as f:
                json.dump(trace, f, indent=4)
        return json.dumps(trace, indent=4)
