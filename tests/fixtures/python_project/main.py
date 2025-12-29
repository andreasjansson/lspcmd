from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    name: str
    email: str
    age: int


class UserRepository:
    def __init__(self):
        self._users: dict[str, User] = {}

    def add_user(self, user: User) -> None:
        self._users[user.email] = user

    def get_user(self, email: str) -> Optional[User]:
        return self._users.get(email)

    def delete_user(self, email: str) -> bool:
        if email in self._users:
            del self._users[email]
            return True
        return False

    def list_users(self) -> list[User]:
        return list(self._users.values())


def create_sample_user() -> User:
    return User(name="John Doe", email="john@example.com", age=30)


def main():
    repo = UserRepository()
    user = create_sample_user()
    repo.add_user(user)
    
    found = repo.get_user("john@example.com")
    if found:
        print(f"Found user: {found.name}")


if __name__ == "__main__":
    main()
