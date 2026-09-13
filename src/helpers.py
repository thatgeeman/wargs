import json
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel

from .config import Config

cfg = Config()
logger = cfg.get_logger("HelpersLogger")


def run_with_timeout(func, timeout, *args, **kwargs):
    """Run func with a per-attempt timeout.

    max_retries (kwarg, default 1) is the total number of attempts.
    Raises TimeoutError if every attempt exceeds the timeout.

    Note: Python cannot kill a running thread, so a timed-out worker keeps
    running in the background, but the caller is released immediately.
    """
    func_name = func.__name__
    max_retries, kwargs = _get_and_pop("max_retries", kwargs, 1)
    for attempt in range(1, max_retries + 1):
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(func, *args, **kwargs)
            return future.result(timeout=timeout)
        except TimeoutError:
            logger.error(
                f"Execution of {func_name} exceeded the time limit "
                f"(attempt {attempt}/{max_retries}, timeout={timeout}s)."
            )
            future.cancel()
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    raise TimeoutError(
        f"{func_name} did not finish within {timeout}s after {max_retries} attempt(s)."
    )


def _get_and_pop(key, d: dict, default=None):
    """Take the value from the dict and return after removing from the dict."""
    val = d.get(key, default)
    d.pop(key, default)
    return val, d


def unwrap_json_strings(node):
    """Recursively replace strings that hold a full JSON document
    (object/array) with the parsed value.

    LLM structured-output responses arrive as a JSON *string*; storing them
    raw would double-encode the payload inside trace files.
    """
    if isinstance(node, dict):
        return {k: unwrap_json_strings(v) for k, v in node.items()}
    if isinstance(node, list):
        return [unwrap_json_strings(v) for v in node]
    if isinstance(node, str):
        stripped = node.strip()
        if stripped[:1] in "[{":
            try:
                # recurse: the parsed value may itself contain JSON strings
                # (models sometimes nest JSON-in-JSON)
                return unwrap_json_strings(json.loads(stripped))
            except json.JSONDecodeError:
                pass  # plain text that merely starts with [ or {
    return node


class WargsEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, BaseModel):
            return obj.model_dump(mode="json")
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, (uuid.UUID, Path)):
            return str(obj)
        # objects that know how to serialize themselves (e.g. Tool)
        to_dict = getattr(obj, "to_dict", None)
        if callable(to_dict):
            return to_dict()
        # last-resort for plain objects (Config, API clients, ...):
        # serialize their repr instead of raising TypeError
        return repr(obj)
