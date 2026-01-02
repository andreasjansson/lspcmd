/**
 * This file contains functions used exclusively by replace-function tests.
 * Do not use these symbols in other tests to avoid parallel test interference.
 */

import { User } from './user';

/**
 * Creates an editable sample user for testing.
 */
export function editableCreateUser(): User {
    return new User("Original Name", "original@example.com", 30);
}

/**
 * Validates an editable email address.
 */
export function editableValidateEmail(email: string): boolean {
    return email.includes("@");
}

/**
 * Editable storage class for testing method replacement.
 */
export class EditableStorage {
    private data: Map<string, string> = new Map();

    save(key: string, value: string): void {
        this.data.set(key, value);
    }

    load(key: string): string | undefined {
        return this.data.get(key);
    }
}
