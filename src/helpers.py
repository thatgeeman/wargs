from concurrent.futures import ThreadPoolExecutor, TimeoutError

from .config import Config

cfg = Config()
logger = cfg.get_logger("HelpersLogger")


def run_with_timeout(func, timeout, *args, **kwargs):
    """Run func with a per-attempt timeout.

    max_retries (kwarg, default 1) is the total number of attempts.
    Raises TimeoutError if every attempt exceeds the timeout.

    Note: Python cannot kill a running thread, so a timed-out worker keeps
    running in the background — but the caller is released immediately.
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
