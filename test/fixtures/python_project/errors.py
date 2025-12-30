"""File with intentional errors for diagnostics testing."""


def undefined_variable():
    """Uses an undefined variable."""
    return undefined_var  # Type error: undefined


def type_error():
    """Type mismatch error."""
    x: int = "not an int"  # Type error: str assigned to int
    return x


def missing_return() -> int:
    """Missing return statement."""
    x = 42
    # Missing return - pyright will warn


class BadClass:
    """Class with errors."""

    def bad_method(self) -> str:
        return 123  # Type error: int instead of str
