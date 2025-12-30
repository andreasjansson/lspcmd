<?php

declare(strict_types=1);

namespace LspcmdFixture;

/**
 * Stores users in memory.
 */
class MemoryStorage implements Storage
{
    /** @var array<string, User> */
    private array $users = [];

    /**
     * Saves a user to memory.
     *
     * @param User $user The user to save
     */
    public function save(User $user): void
    {
        $this->users[$user->getEmail()] = $user;
    }

    /**
     * Loads a user by email.
     *
     * @param string $email The email to search for
     * @return User|null The user if found
     */
    public function load(string $email): ?User
    {
        return $this->users[$email] ?? null;
    }

    /**
     * Deletes a user by email.
     *
     * @param string $email The email of the user to delete
     * @return bool True if the user was deleted
     */
    public function delete(string $email): bool
    {
        if (isset($this->users[$email])) {
            unset($this->users[$email]);
            return true;
        }
        return false;
    }

    /**
     * Lists all users.
     *
     * @return User[] All users in the storage
     */
    public function list(): array
    {
        return array_values($this->users);
    }
}
