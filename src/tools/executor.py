import json

from ..config import Config
from .store import *

cfg = Config()
logger = cfg.get_logger("ToolExecutorLogger")


class ToolExecutor:
    def __init__(self, name: str, parameters: dict, session_id=None):
        if name not in REGISTERED_TOOLS:
            raise KeyError(
                f"Tool not registered: '{name}'. Available: {list(REGISTERED_TOOLS)}"
            )
        self.session_id = session_id if session_id else uuid.uuid4()
        self.tool_name = name
        self.instance_id = uuid.uuid4()
        self.name = f"{name}_{self.instance_id}"
        self.parameters = parameters
        self.result = None
        self.config = Config()
        self.state = "INIT"
        # storage
        self.traces = []
        self.trace_file = (
            self.config.config_dir / f"trace_{self.session_id}" / f"{self.name}.json"
        )

        # automatically trigger
        self._trigger_run()

    def _trigger_run(self):
        tool_cls = REGISTERED_TOOLS[self.tool_name]
        tool_instance = tool_cls(session_id=self.session_id)
        logger.info(f"Running {self.name}.")
        self.result = tool_instance.run(**self.parameters)
        self.store_trace(self.result)
        self.done()

    def store_trace(self, trace_data: dict):
        if not isinstance(trace_data, dict):
            logger.error(
                f"Instance trace data must be a dictionary. Received type: {type(trace_data)}"
            )
            return
        self.traces.append(trace_data)

    def save_trace(self):
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
                    f"Could not read existing trace file {self.trace_file} ({e}), overwriting with current traces."
                )
        logger.debug(f"Saving trace for {self.name} to {self.trace_file}")
        with open(self.trace_file, "w") as f:
            json.dump(traces, f, indent=4)
            logger.info(f"Trace for {self.name} saved to {self.trace_file}")

    def state_transition(self, new_state):
        logger.info(
            f"Transitioning {self.name} from state '{self.state}' to '{new_state}'"
        )
        self.state = new_state

    def done(self):
        self.state_transition("DONE")
        self.save_trace()
        logger.info(f"{self.name} has completed its run and saved the trace.")


if __name__ == "__main__":
    toolname = "WebSearch"
    parameters = {
        "query": "NVIDIA revenue growth vs Infineon revenue growth latest quarter",
        "time_range": "year",
        "topic": "finance",
        "max_results": 3,
    }
    tool_exec = ToolExecutor(name=toolname, parameters=parameters)
    exec_result = tool_exec.result
    logger.info(f"""
    Tool: {toolname}\n
    Params: {parameters}\n
    Result: {exec_result}\n
    """)
