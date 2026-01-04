/**
 * ISOLATED TEST FILE - Imports from editable.ts for testing cross-file rename and mv.
 * Do NOT import this from main.ts, user.ts, or other non-editable files.
 */

import { EditablePerson, editableCreateSample } from './editable';

/**
 * Uses EditablePerson to test that rename propagates across files.
 */
export function useEditablePerson(person: EditablePerson): string {
    return person.greet();
}

/**
 * Creates and uses a sample to test cross-file references.
 */
export function createAndGreet(): string {
    const sample = editableCreateSample();
    return useEditablePerson(sample);
}
