"""
Rate limiting utilities for API calls
"""
import time
from functools import wraps
from typing import Callable, Dict, Optional
from datetime import datetime, timedelta
import threading


class RateLimiter:
    """
    A thread-safe rate limiter that tracks API call rates

    Uses a sliding window algorithm to limit calls per minute
    """

    def __init__(self, calls_per_minute: int = 60):
        """
        Initialize the rate limiter

        Args:
            calls_per_minute: Maximum number of calls allowed per minute
        """
        self.calls_per_minute = calls_per_minute
        self.calls: Dict[str, list] = {}
        self.lock = threading.Lock()

    def _clean_old_calls(self, key: str) -> None:
        """Remove calls older than 1 minute from the tracking list"""
        if key not in self.calls:
            return

        cutoff = datetime.utcnow() - timedelta(minutes=1)
        self.calls[key] = [t for t in self.calls[key] if t > cutoff]

    def can_call(self, key: str = "default") -> bool:
        """
        Check if a call can be made without exceeding the rate limit

        Args:
            key: Identifier for the rate limit bucket (e.g., account ID)

        Returns:
            True if the call can be made
        """
        with self.lock:
            self._clean_old_calls(key)

            if key not in self.calls:
                return True

            return len(self.calls[key]) < self.calls_per_minute

    def record_call(self, key: str = "default") -> None:
        """
        Record that a call was made

        Args:
            key: Identifier for the rate limit bucket
        """
        with self.lock:
            if key not in self.calls:
                self.calls[key] = []

            self.calls[key].append(datetime.utcnow())
            self._clean_old_calls(key)

    def wait_if_needed(self, key: str = "default") -> float:
        """
        Wait if necessary to respect rate limits

        Args:
            key: Identifier for the rate limit bucket

        Returns:
            Number of seconds waited
        """
        waited = 0.0

        while not self.can_call(key):
            time.sleep(1)
            waited += 1.0

        return waited

    def get_remaining_calls(self, key: str = "default") -> int:
        """
        Get the number of remaining calls allowed in the current window

        Args:
            key: Identifier for the rate limit bucket

        Returns:
            Number of remaining calls
        """
        with self.lock:
            self._clean_old_calls(key)

            if key not in self.calls:
                return self.calls_per_minute

            return max(0, self.calls_per_minute - len(self.calls[key]))

    def get_reset_time(self, key: str = "default") -> Optional[datetime]:
        """
        Get the time when the oldest call in the window will expire

        Args:
            key: Identifier for the rate limit bucket

        Returns:
            Datetime when a call slot will become available, or None if slots are available
        """
        with self.lock:
            self._clean_old_calls(key)

            if key not in self.calls or not self.calls[key]:
                return None

            if len(self.calls[key]) < self.calls_per_minute:
                return None

            # The oldest call will expire 1 minute after it was made
            oldest_call = min(self.calls[key])
            return oldest_call + timedelta(minutes=1)


def rate_limited(
    limiter: RateLimiter, key_func: Callable = None
) -> Callable:
    """
    Decorator to rate limit a function

    Args:
        limiter: RateLimiter instance to use
        key_func: Optional function to extract the rate limit key from args/kwargs

    Returns:
        Decorated function
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Determine the rate limit key
            if key_func:
                key = key_func(*args, **kwargs)
            else:
                key = "default"

            # Wait if we're at the rate limit
            limiter.wait_if_needed(key)

            # Record the call
            limiter.record_call(key)

            # Execute the function
            return func(*args, **kwargs)

        return wrapper

    return decorator


# Global rate limiter for Reddit API
reddit_limiter = RateLimiter(calls_per_minute=60)


def reddit_rate_limited(account_id: str = None) -> Callable:
    """
    Decorator specifically for Reddit API calls

    Args:
        account_id: Optional account ID to use as rate limit key

    Returns:
        Decorated function
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = account_id or "reddit_default"

            # Wait if needed
            reddit_limiter.wait_if_needed(key)

            # Record the call
            reddit_limiter.record_call(key)

            return func(*args, **kwargs)

        return wrapper

    return decorator
