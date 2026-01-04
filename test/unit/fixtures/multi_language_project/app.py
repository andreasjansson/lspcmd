"""Python part of the multi-language project.

This module provides Python services that can interact with Go services.
"""

from dataclasses import dataclass
from typing import Protocol


class ServiceProtocol(Protocol):
    """Protocol for service implementations."""

    def greet(self) -> str:
        """Return a greeting message."""
        ...


@dataclass
class PythonUser:
    """Represents a user in the Python service."""

    name: str
    email: str


class PythonService:
    """A service implemented in Python."""

    def __init__(self, name: str) -> None:
        """Initialize the service with a name.

        Args:
            name: The service name.
        """
        self.name = name
        self._users: list[PythonUser] = []

    def greet(self) -> str:
        """Return a greeting message from Python."""
        return f"Hello from Python, {self.name}!"

    def add_user(self, user: PythonUser) -> None:
        """Add a user to the service."""
        self._users.append(user)

    def get_users(self) -> list[PythonUser]:
        """Get all users."""
        return self._users.copy()


def create_service(name: str) -> PythonService:
    """Create a new Python service.

    Args:
        name: The service name.

    Returns:
        A new PythonService instance.
    """
    return PythonService(name)


def validate_email(email: str) -> bool:
    """Validate an email address format."""
    import re

    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


if __name__ == "__main__":
    service = create_service("World")
    print(service.greet())
