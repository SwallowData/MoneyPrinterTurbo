import time
from contextlib import contextmanager

from loguru import logger


@contextmanager
def log_elapsed(step_name: str, level: str = "INFO"):
    """计时上下文管理器，记录代码块的执行耗时。"""
    t0 = time.perf_counter()
    logger.log(level, f"[{step_name}] 开始")
    try:
        yield
    finally:
        elapsed = time.perf_counter() - t0
        logger.log(level, f"[{step_name}] 完成, 耗时 {elapsed:.2f}s")
