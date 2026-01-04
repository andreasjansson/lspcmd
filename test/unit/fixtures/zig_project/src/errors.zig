// File with intentional errors for diagnostics testing.

const std = @import("std");

/// Function with undefined identifier.
pub fn undefinedVariable() i32 {
    return undefined_var; // Error: undefined identifier
}

/// Function with type mismatch.
pub fn typeError() i32 {
    const x: i32 = "not an int"; // Error: expected i32, found []const u8
    return x;
}

/// Function with wrong return type.
pub fn returnTypeError() i32 {
    return "string"; // Error: expected i32, found []const u8
}

/// Function with unreachable code.
pub fn unreachableCode() void {
    return;
    const x = 42; // Warning: unreachable code
    _ = x;
}
