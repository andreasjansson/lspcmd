// File with intentional errors for diagnostics testing.

#include <string>

// Undefined variable
int undefinedVariable() {
    return undefinedVar;  // Error: use of undeclared identifier
}

// Type error
int typeError() {
    int x = "not an int";  // Error: cannot initialize int with string
    return x;
}

// Missing return
int missingReturn() {
    int x = 42;
    // Missing return statement - warning
}

// Wrong number of arguments
void twoArgs(int a, int b) {}

void argumentError() {
    twoArgs(1);  // Error: too few arguments
}

// Incompatible types
void typeConversion() {
    int* ptr = 42;  // Error: cannot initialize pointer with int
}
