<?php

declare(strict_types=1);

namespace LspcmdFixture;

/**
 * Stores users in files (stub implementation).
 */
class FileStorage implements Storage
{
    /**
     * Creates a new FileStorage instance.
     *
     * @param string $basePath The base path for file storage
     */
    public function __construct(
        private string $basePath
    ) {}

    /**
     * Gets the base path.
     *
     * @return string The base path
     */
    public function getBasePath(): string
    {
        return $this->basePath;
    }

    /**
     * Saves a user to a file.
     *
     * @param User $user The user to save
     */
    public function save(User $user): void
    {
        // Stub implementation
    }

    /**
     * Loads a user from a file.
     *
     * @param string $email The email to search for
     * @return User|null The user if found
     */
    public function load(string $email): ?User
    {
        // Stub implementation
        return null;
    }

    /**
     * Deletes a user file.
     *
     * @param string $email The email of the user to delete
     * @return bool True if the user was deleted
     */
    public function delete(string $email): bool
    {
        // Stub implementation
        return false;
    }

    /**
     * Lists all users from files.
     *
     * @return User[] All users
     */
    public function list(): array
    {
        // Stub implementation
        return [];
    }
}
