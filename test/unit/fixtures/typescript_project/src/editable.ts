/**
 * ISOLATED TEST FILE - Used exclusively by rename and mv tests.
 * Do NOT import this from main.ts, user.ts, or other non-editable files.
 * Do NOT use symbols from this file in grep, refs, calls, or other read-only tests.
 */

/**
 * Editable person class for testing rename operations.
 */
export class EditablePerson {
    constructor(
        public name: string,
        public email: string
    ) {}

    greet(): string {
        return `Hello, ${this.name}`;
    }
}

/**
 * Creates an editable sample for testing.
 */
export function editableCreateSample(): EditablePerson {
    return new EditablePerson("Original Name", "original@example.com");
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
