/**
 * Represents a user in the system.
 */
export class User {
    constructor(
        public readonly name: string,
        public readonly email: string,
        public readonly age: number
    ) {}

    /**
     * Checks if the user is an adult (18 or older).
     */
    isAdult(): boolean {
        return this.age >= 18;
    }

    /**
     * Returns a formatted display name.
     */
    displayName(): string {
        return `${this.name} <${this.email}>`;
    }
}

/**
 * Interface for storage backends.
 */
export interface Storage {
    save(user: User): void;
    load(email: string): User | undefined;
    delete(email: string): boolean;
    list(): User[];
}

/**
 * In-memory storage implementation.
 */
export class MemoryStorage implements Storage {
    private users: Map<string, User> = new Map();

    save(user: User): void {
        this.users.set(user.email, user);
    }

    load(email: string): User | undefined {
        return this.users.get(email);
    }

    delete(email: string): boolean {
        return this.users.delete(email);
    }

    list(): User[] {
        return Array.from(this.users.values());
    }
}

/**
 * File-based storage implementation (stub).
 */
export class FileStorage implements Storage {
    private cache: Map<string, User> = new Map();

    constructor(private basePath: string) {}

    getBasePath(): string {
        return this.basePath;
    }

    save(user: User): void {
        // Stub: just cache in memory
        this.cache.set(user.email, user);
    }

    load(email: string): User | undefined {
        return this.cache.get(email);
    }

    delete(email: string): boolean {
        return this.cache.delete(email);
    }

    list(): User[] {
        return Array.from(this.cache.values());
    }
}

/**
 * Repository for managing user entities.
 */
export class UserRepository {
    constructor(private storage: Storage) {}

    addUser(user: User): void {
        this.storage.save(user);
    }

    getUser(email: string): User | undefined {
        return this.storage.load(email);
    }

    deleteUser(email: string): boolean {
        return this.storage.delete(email);
    }

    listUsers(): User[] {
        return this.storage.list();
    }

    countUsers(): number {
        return this.storage.list().length;
    }
}

/**
 * Validates a user's data.
 */
export function validateUser(user: User): string | null {
    if (!user.name) {
        return "name is required";
    }
    if (!user.email) {
        return "email is required";
    }
    if (user.age < 0) {
        return "age must be non-negative";
    }
    return null;
}

/**
 * Country codes mapped to their full names.
 */
export const COUNTRY_CODES: Record<string, string> = {
    "US": "United States",
    "CA": "Canada",
    "GB": "United Kingdom",
    "DE": "Germany",
    "FR": "France",
    "JP": "Japan",
    "AU": "Australia",
};

/**
 * Default configuration values.
 */
export const DEFAULT_CONFIG: string[] = [
    "debug=false",
    "timeout=30",
    "max_retries=3",
    "log_level=INFO",
];
