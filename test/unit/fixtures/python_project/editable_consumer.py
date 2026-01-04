"""
ISOLATED TEST FILE - Imports from editable.py for testing cross-file rename and mv.
Do NOT import this from main.py, utils.py, or other non-editable files.
"""

from editable import EditablePerson, editable_create_sample


def use_editable_person(person: EditablePerson) -> str:
    """Uses EditablePerson to test that rename propagates across files."""
    return person.greet()


def create_and_greet() -> str:
    """Creates and uses a sample to test cross-file references."""
    sample = editable_create_sample()
    return use_editable_person(sample)
