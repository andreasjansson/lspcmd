<?php

declare(strict_types=1);

namespace LspcmdFixture;

/**
 * Represents a user in the system.
 */
class User
{
    /**
     * Creates a new User instance.
     *
     * @param string $name The user's full name
     * @param string $email The user's email address
     * @param int $age The user's age in years
     */
    public function __construct(
        private string $name,
        private string $email,
        private int $age
    ) {}

    /**
     * Gets the user's name.
     *
     * @return string The user's name
     */
    public function getName(): string
    {
        return $this->name;
    }

    /**
     * Gets the user's email.
     *
     * @return string The user's email
     */
    public function getEmail(): string
    {
        return $this->email;
    }

    /**
     * Gets the user's age.
     *
     * @return int The user's age
     */
    public function getAge(): int
    {
        return $this->age;
    }

    /**
     * Checks if the user is 18 or older.
     *
     * @return bool True if the user is an adult
     */
    public function isAdult(): bool
    {
        return $this->age >= 18;
    }

    /**
     * Returns a formatted display name.
     *
     * @return string The display name in format "name <email>"
     */
    public function displayName(): string
    {
        return "{$this->name} <{$this->email}>";
    }
}
