import { User, UserRepository, MemoryStorage, validateUser } from './user';

/**
 * Creates a sample user for testing.
 */
function createSampleUser(): User {
    return new User("John Doe", "john@example.com", 30);
}

/**
 * Processes all users and returns their display names.
 */
function processUsers(repo: UserRepository): string[] {
    return repo.listUsers().map(user => user.displayName());
}

/**
 * Validates an email address format.
 */
function validateEmail(email: string): boolean {
    const pattern = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
    return pattern.test(email);
}

/**
 * Counter class for demonstration.
 */
class Counter {
    private value: number;

    constructor(initial: number = 0) {
        this.value = initial;
    }

    getValue(): number {
        return this.value;
    }

    increment(): number {
        return ++this.value;
    }

    decrement(): number {
        return --this.value;
    }

    reset(): void {
        this.value = 0;
    }
}

// Unused import for organize-imports test
import * as path from 'path';

function main(): void {
    const storage = new MemoryStorage();
    const repo = new UserRepository(storage);
    const user = createSampleUser();

    const validationError = validateUser(user);
    if (validationError) {
        console.error(`Validation failed: ${validationError}`);
        return;
    }

    repo.addUser(user);

    const found = repo.getUser("john@example.com");
    if (found) {
        console.log(`Found user: ${found.displayName()}`);
        console.log(`Is adult: ${found.isAdult()}`);
    }

    const names = processUsers(repo);
    names.forEach(name => console.log(`User: ${name}`));

    const counter = new Counter(10);
    console.log(`Counter: ${counter.getValue()}`);
}

main();
