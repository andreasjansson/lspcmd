<?php

declare(strict_types=1);

namespace LetaFixture;

/**
 * Main application class.
 */
class Main
{
    /**
     * Creates a sample user for testing.
     *
     * @return User A sample user instance
     */
    public static function createSampleUser(): User
    {
        return new User('John Doe', 'john@example.com', 30);
    }

    /**
     * Validates a user and throws an exception if invalid.
     *
     * @param User $user The user to validate
     * @throws \InvalidArgumentException If the user is invalid
     */
    public static function validateUser(User $user): void
    {
        if (empty($user->getName())) {
            throw new \InvalidArgumentException('name is required');
        }
        if (empty($user->getEmail())) {
            throw new \InvalidArgumentException('email is required');
        }
        if ($user->getAge() < 0) {
            throw new \InvalidArgumentException('age must be non-negative');
        }
    }

    /**
     * Processes users in a repository.
     *
     * @param UserRepository $repo The repository to process
     * @return string[] The display names of all users
     */
    public static function processUsers(UserRepository $repo): array
    {
        return array_map(
            fn(User $user) => $user->displayName(),
            $repo->listUsers()
        );
    }

    /**
     * Main entry point.
     */
    public static function run(): void
    {
        $storage = new MemoryStorage();
        $repo = new UserRepository($storage);

        $user = self::createSampleUser();
        self::validateUser($user);

        $repo->addUser($user);

        $found = $repo->getUser('john@example.com');
        if ($found !== null) {
            echo "Found user: {$found->displayName()}\n";
            echo "Is adult: " . ($found->isAdult() ? 'true' : 'false') . "\n";
        }

        $names = self::processUsers($repo);
        foreach ($names as $name) {
            echo "User: {$name}\n";
        }
    }
}
