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
        self.name = f"{name}_{self.session_id}"
        self.parameters = parameters
        self.result = None

        # automatically trigger
        self._trigger_run()

    def _trigger_run(self):
        tool_cls = REGISTERED_TOOLS[self.tool_name]
        tool_instance = tool_cls(session_id=self.session_id)
        logger.info(f"Running {self.name}.")
        self.result = tool_instance.run(**self.parameters)


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
