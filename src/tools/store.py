import uuid
from abc import ABC, abstractmethod
from inspect import signature

from tavily import TavilyClient

from ..config import Config, SecretsManager

cfg = Config()
sm = SecretsManager()
logger = cfg.get_logger("ToolLogger")

REGISTERED_TOOLS = {}  # stable tool name -> tool class


class Tool(ABC):
    tool_name = None  # stable registry name, set by subclasses

    def __init__(self, name, session_id=None):
        self.instance_id = uuid.uuid4()
        self.name = f"{name}_" + str(self.instance_id)
        self.config = Config()
        self.state = "INIT"
        self.traces = []
        self.session_id = session_id if session_id else uuid.uuid4()
        self.trace_file = (
            self.config.config_dir / f"trace_{self.session_id}" / f"{self.name}.json"
        )

    def __init_subclass__(cls, **kwargs):
        """Register any Tool which is subclassed"""
        super().__init_subclass__(**kwargs)
        if cls.tool_name:
            REGISTERED_TOOLS[cls.tool_name] = cls

    @abstractmethod
    def run(self, **kwargs):
        raise NotImplementedError("Subclasses should implement this method.")

    @abstractmethod
    def schema(self):
        raise NotImplementedError("Subclasses should implement this method.")

    def state_transition(self, new_state):
        logger.info(
            f"Transitioning {self.name} from state '{self.state}' to '{new_state}'"
        )
        self.state = new_state

    def to_dict(self):
        """JSON-safe snapshot for state dumps. Never includes secrets or clients."""
        return {
            "tool_name": self.tool_name,
            "name": self.name,
            "state": self.state,
            "session_id": str(self.session_id),
            "trace_file": str(self.trace_file),
            "traces": self.traces,
        }

    def store_trace(self, trace_data: dict):
        if not isinstance(trace_data, dict):
            logger.error(
                f"Instance trace data must be a dictionary. Received type: {type(trace_data)}"
            )
            return
        self.traces.append(trace_data)

    def save_trace(self):
        import json
        import os

        if len(self.traces) == 0:
            logger.warning(f"No trace data to save for agent {self.name}.")
            return
        os.makedirs(os.path.dirname(self.trace_file), exist_ok=True)
        traces = self.traces
        if os.path.exists(self.trace_file):
            # read-modify-write: appending raw JSON would concatenate
            # documents ([...][...]) and produce an invalid file
            try:
                with open(self.trace_file) as f:
                    existing = json.load(f)
                traces = (
                    existing if isinstance(existing, list) else [existing]
                ) + traces
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(
                    f"Could not read existing trace file {self.trace_file} ({e}) — overwriting with current traces."
                )
        logger.debug(f"Saving trace for {self.name} to {self.trace_file}")
        with open(self.trace_file, "w") as f:
            json.dump(traces, f, indent=4)


class WebSearch(Tool):
    tool_name = "WebSearch"

    def __init__(self, session_id=None):
        super().__init__("WebSearch", session_id=session_id)
        self.secret = SecretsManager().get_secret("WG_TAVILY_API_KEY")
        self.client = TavilyClient(self.secret)

    def run(self, **kwargs) -> dict:
        self.state_transition("RUNNING")
        # Placeholder for web search logic
        logger.info(f"Running web search for query: {kwargs}")
        response = self.client.search(**kwargs)
        # Tavily specifics
        follow_up_questions = response.get("follow_up_questions", [])
        web_results = response.get("results", [])
        short_answer = response.get("answer", "")
        # cleaned
        result = {
            "web_results": web_results,
            "short_answer": short_answer,
            "follow_up_questions": follow_up_questions,
        }
        self.store_trace(result)
        self.state_transition("COMPLETED")
        self.save_trace()
        return result

    def schema(self):
        return signature(self.client.search)
