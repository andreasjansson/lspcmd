"""
ISOLATED TEST FILE - Used exclusively by rename and mv tests.
Do NOT import this from main.py, utils.py, or other non-editable files.
Do NOT use symbols from this file in grep, refs, calls, or other read-only tests.
"""

from dataclasses import dataclass


@dataclass
class EditablePerson:
    """Editable person class for testing rename operations."""

    name: str
    email: str

    def greet(self) -> str:
        return f"Hello, {self.name}"


def editable_create_sample() -> EditablePerson:
    """Create an editable sample for testing."""
    return EditablePerson(name="Original Name", email="original@example.com")


def editable_validate_email(email: str) -> bool:
    """Validate an editable email address."""
    return "@" in email


class EditableStorage:
    """Editable storage class for testing method replacement."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def save(self, key: str, value: str) -> None:
        """Save a value."""
        self._data[key] = value

    def load(self, key: str) -> str | None:
        """Load a value."""
        return self._data.get(key)
