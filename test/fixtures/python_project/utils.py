"""Utility functions and classes for the Python project fixture."""

import re
from typing import TypeVar, Callable, Generic

T = TypeVar("T")


def validate_email(email: str) -> bool:
    """Validate an email address format.
    
    Args:
        email: The email address to validate.
        
    Returns:
        True if the email format is valid, False otherwise.
    """
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def validate_age(age: int) -> bool:
    """Validate that age is within reasonable bounds."""
    return 0 <= age <= 150


def memoize(func: Callable[..., T]) -> Callable[..., T]:
    """Decorator to cache function results.
    
    Args:
        func: The function to memoize.
        
    Returns:
        A wrapped function that caches results.
    """
    cache: dict = {}

    def wrapper(*args, **kwargs):
        key = (args, tuple(sorted(kwargs.items())))
        if key not in cache:
            cache[key] = func(*args, **kwargs)
        return cache[key]

    return wrapper


@memoize
def fibonacci(n: int) -> int:
    """Calculate the nth Fibonacci number.
    
    Uses memoization for efficient computation.
    
    Args:
        n: The index of the Fibonacci number to compute.
        
    Returns:
        The nth Fibonacci number.
    """
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)


class Counter(Generic[T]):
    """A generic counter class.
    
    Attributes:
        initial: The initial value of the counter.
    """

    def __init__(self, initial: int = 0) -> None:
        """Initialize the counter with an optional starting value."""
        self._value = initial

    @property
    def value(self) -> int:
        """Get the current counter value."""
        return self._value

    def increment(self, amount: int = 1) -> int:
        """Increment the counter by the given amount."""
        self._value += amount
        return self._value

    def decrement(self, amount: int = 1) -> int:
        """Decrement the counter by the given amount."""
        self._value -= amount
        return self._value

    def reset(self) -> None:
        """Reset the counter to zero."""
        self._value = 0


class Result(Generic[T]):
    """A result type that can hold either a value or an error."""

    def __init__(self, value: T | None = None, error: str | None = None) -> None:
        self._value = value
        self._error = error

    @property
    def is_ok(self) -> bool:
        """Check if the result is successful."""
        return self._error is None

    @property
    def is_err(self) -> bool:
        """Check if the result is an error."""
        return self._error is not None

    def unwrap(self) -> T:
        """Get the value, raising if it's an error."""
        if self._error is not None:
            raise ValueError(self._error)
        return self._value  # type: ignore

    def unwrap_or(self, default: T) -> T:
        """Get the value or return a default."""
        if self._error is not None:
            return default
        return self._value  # type: ignore


def format_name(first: str, last: str) -> str:
    """Format a full name from first and last names."""
    return f"{first} {last}"
