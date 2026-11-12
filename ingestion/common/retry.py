"""Exponential backoff retry decorator for external HTTP & market data requests."""

from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable, Sequence, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def with_retry(
    max_attempts: int = 3,
    delays: Sequence[float] = (2.0, 4.0, 8.0),
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[F], F]:
    """Retry a function with exponential backoff delays (2s, 4s, 8s by default)."""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_err: BaseException | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_err = exc
                    if attempt >= max_attempts:
                        logger.error(
                            "Function %s failed after %d attempts: %s",
                            func.__name__,
                            max_attempts,
                            exc,
                        )
                        raise
                    delay = delays[min(attempt - 1, len(delays) - 1)]
                    logger.warning(
                        "Attempt %d/%d for %s failed (%s). Retrying in %.1fs...",
                        attempt,
                        max_attempts,
                        func.__name__,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
            if last_err is not None:
                raise last_err
            return None

        return wrapper  # type: ignore[return-value]

    return decorator
