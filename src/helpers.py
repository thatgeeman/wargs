from concurrent.futures import ThreadPoolExecutor, TimeoutError
from .config import Config 

cfg = Config()
logger = cfg.get_logger('HelpersLogger')

def run_with_timeout(func, timeout, *args, **kwargs):
    func_name = func.__name__
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            logger.error(f"Execution of {func_name} exceeded the time limit.")
            return None