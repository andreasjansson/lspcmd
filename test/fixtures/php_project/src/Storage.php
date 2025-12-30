<?php

declare(strict_types=1);

namespace LspcmdFixture;

/**
 * Interface for user storage backends.
 */
interface Storage
{
    /**
     * Saves a user to the storage.
     *
     * @param User $user The user to save
     */
    public function save(User $user): void;

    /**
     * Loads a user by email.
     *
     * @param string $email The email to search for
     * @return User|null The user if found, null otherwise
     */
    public function load(string $email): ?User;

    /**
     * Deletes a user by email.
     *
     * @param string $email The email of the user to delete
     * @return bool True if the user was deleted
     */
    public function delete(string $email): bool;

    /**
     * Lists all users.
     *
     * @return User[] All users in the storage
     */
    public function list(): array;
}
