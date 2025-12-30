/**
 * File with intentional errors for diagnostics testing.
 */

// Undefined variable
function undefinedVariable(): number {
    return undefinedVar;
}

// Type error
function typeError(): number {
    const x: number = "not a number";
    return x;
}

// Missing return
function missingReturn(): string {
    const x = "hello";
    // Missing return statement
}

// Property does not exist
interface Person {
    name: string;
}

function propertyError(p: Person): void {
    console.log(p.nonExistent);
}

// Wrong number of arguments
function twoArgs(a: number, b: number): number {
    return a + b;
}

function callError(): void {
    twoArgs(1);  // Missing argument
}

export { undefinedVariable, typeError, missingReturn, propertyError, callError };
