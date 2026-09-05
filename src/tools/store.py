import uuid
from abc import abstractmethod
from inspect import signature

from tavily import TavilyClient

from ..config import Config, SecretsManager

cfg = Config()
sm = SecretsManager()
logger = cfg.get_logger("ToolLogger")

REGISTERED_TOOLS = []  # should instantiate each tool in this module


class Tool:
    def __init__(self, name):
        self.name = name
        self.config = Config()
        self.state = "INIT"
        self.traces = []
        self.session_id = uuid.uuid4()
        self.trace_file = (
            self.config.config_dir / f"trace_{self.session_id}" / f"{self.name}.json"
        )
        self._register_tool()

    @abstractmethod
    def run(self, input):
        raise NotImplementedError("Subclasses should implement this method.")

    @abstractmethod
    def schema(self):
        raise NotImplementedError("Subclasses should implement this method.")

    def state_transition(self, new_state):
        logger.info(
            f"Transitioning {self.name} from state '{self.state}' to '{new_state}'"
        )
        self.state = new_state

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

        save_mode = "w"  # write mode by default
        os.makedirs(os.path.dirname(self.trace_file), exist_ok=True)
        if os.path.exists(self.trace_file):
            save_mode = "a"  # Append if trace file exists
            logger.warning(f"Trace file path is non existent for agent {self.name}.")
        if len(self.traces) == 0:
            logger.warning(f"No trace data to save for agent {self.name}.")
            return
        logger.debug(
            f"Saving trace for {self.name} to {self.trace_file} with mode '{save_mode}'"
        )
        with open(self.trace_file, save_mode) as f:
            json.dump(self.traces, f, indent=4)

    def _register_tool(self):
        REGISTERED_TOOLS.extend([self.name])


class WebSearch(Tool):
    def __init__(self):
        super().__init__("WebSearch")
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


# register tool Once
WebSearch()
