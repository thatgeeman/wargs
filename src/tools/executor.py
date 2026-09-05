from ..config import Config
from .store import *

cfg = Config()
logger = cfg.get_logger("ToolExecutorLogger")


class ToolExecutor:
    def __init__(self, name: str, parameters: dict):
        assert name in REGISTERED_TOOLS, (
            f"Tool not registered: {name} not in  {REGISTERED_TOOLS}"
        )
        self.name = name
        self.parameters = parameters
        self.result = None

        # automatically trigger
        self._trigger_run()

    def _trigger_run(self):
        tool_ref = None
        tool_instance = None
        try:
            tool_ref = eval(self.name)
            tool_instance = tool_ref()
        except (ImportError, AttributeError) as e:
            logger.error(f"Failed Import of Tool: {e}")
        except Exception as e:
            logger.error(f"Exception: {e}")
        finally:
            if tool_instance is not None:
                logger.info(f"Running {self.name}.")
                result = tool_instance.run(**self.parameters)
                self.result = result
            else:
                self.result = None


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
