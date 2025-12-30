"""
async_utils.py - Async-to-sync bridging utilities.

This module provides clean utilities for running async code from sync contexts.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Coroutine, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def run_async_safely(coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine safely, handling event loop context.

    This function provides a clean sync-to-async bridge that:
    - Creates a new event loop if none exists
    - Properly handles cleanup
    - Handles being called from an async context gracefully

    Note: This should only be called from synchronous code. If called
    from within an async context, a warning is logged and the coroutine
    is run in a separate thread pool executor.

    Args:
        coro: The coroutine to run.

    Returns:
        The result of the coroutine.
    """
    try:
        # Check if there's already a running loop
        asyncio.get_running_loop()
        # We're in an async context - this shouldn't happen in normal usage
        # Log a warning and create a new loop in a thread
        logger.warning("run_async_safely called from async context. Consider using await directly.")
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    except RuntimeError:
        # No running loop - create one and run
        return asyncio.run(coro)
