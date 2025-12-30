"""Main module for the Python project fixture.

This module contains user management functionality including
the User data class and UserRepository for storage operations.
"""

from dataclasses import dataclass
from typing import Optional, Protocol
import os

from utils import validate_email


class StorageProtocol(Protocol):
    """Protocol defining the storage interface."""

    def save(self, key: str, value: str) -> None:
        """Save a value with the given key."""
        ...

    def load(self, key: str) -> Optional[str]:
        """Load a value by key."""
        ...


@dataclass
class User:
    """Represents a user in the system.
    
    Attributes:
        name: The user's full name.
        email: The user's email address (used as unique identifier).
        age: The user's age in years.
    """
    name: str
    email: str
    age: int

    def is_adult(self) -> bool:
        """Check if the user is an adult (18 or older)."""
        return self.age >= 18

    def display_name(self) -> str:
        """Get a formatted display name."""
        return f"{self.name} <{self.email}>"


class MemoryStorage:
    """In-memory storage implementation."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def save(self, key: str, value: str) -> None:
        self._data[key] = value

    def load(self, key: str) -> Optional[str]:
        return self._data.get(key)


class FileStorage:
    """File-based storage implementation."""

    def __init__(self, base_path: str) -> None:
        self._base_path = base_path

    def save(self, key: str, value: str) -> None:
        path = os.path.join(self._base_path, key)
        with open(path, "w") as f:
            f.write(value)

    def load(self, key: str) -> Optional[str]:
        path = os.path.join(self._base_path, key)
        if os.path.exists(path):
            with open(path) as f:
                return f.read()
        return None


class UserRepository:
    """Repository for managing user entities.
    
    Provides CRUD operations for User objects with an in-memory store.
    """

    def __init__(self) -> None:
        self._users: dict[str, User] = {}

    def add_user(self, user: User) -> None:
        """Add a user to the repository."""
        self._users[user.email] = user

    def get_user(self, email: str) -> Optional[User]:
        """Retrieve a user by email address."""
        return self._users.get(email)

    def delete_user(self, email: str) -> bool:
        """Delete a user by email. Returns True if user was deleted."""
        if email in self._users:
            del self._users[email]
            return True
        return False

    def list_users(self) -> list[User]:
        """List all users in the repository."""
        return list(self._users.values())

    def count_users(self) -> int:
        """Return the number of users in the repository."""
        return len(self._users)


def create_sample_user() -> User:
    """Create a sample user for testing."""
    return User(name="John Doe", email="john@example.com", age=30)


def process_users(repo: UserRepository) -> list[str]:
    """Process all users and return their display names."""
    return [user.display_name() for user in repo.list_users()]


# Intentional unused import for organize-imports test
import sys


def main() -> None:
    """Main entry point."""
    repo = UserRepository()
    user = create_sample_user()
    
    if not validate_email(user.email):
        print(f"Invalid email: {user.email}")
        return
    
    repo.add_user(user)

    found = repo.get_user("john@example.com")
    if found:
        print(f"Found user: {found.name}")
        print(f"Is adult: {found.is_adult()}")


if __name__ == "__main__":
    main()
