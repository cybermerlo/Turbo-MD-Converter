"""Retry with exponential backoff for API calls."""

import random
import time
from typing import Any, Callable


def retry_with_backoff(
    func: Callable,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable_exceptions: tuple = (Exception,),
    on_retry: Callable[[int, Exception], None] | None = None,
) -> Any:
    """Execute a function with exponential backoff retry.

    Args:
        func: Callable to execute (no arguments).
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay in seconds.
        max_delay: Maximum delay cap in seconds.
        retryable_exceptions: Tuple of exception types to retry on.
        on_retry: Optional callback(attempt, exception) called before each retry.

    Returns:
        The return value of func().

    Raises:
        The last exception if all retries are exhausted.
    """
    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            return func()
        except retryable_exceptions as e:
            last_exception = e
            if attempt == max_retries:
                raise
            delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
            if on_retry:
                on_retry(attempt + 1, e)
            time.sleep(delay)
    raise last_exception
