//! Module with intentional errors for diagnostics testing.

/// Function with undefined variable error.
pub fn undefined_variable() -> i32 {
    undefined_var  // Error: not found in scope
}

/// Function with type mismatch error.
pub fn type_error() -> i32 {
    "not an int".to_string()  // Error: expected i32, found String
}

/// Function with mismatched types in let binding.
pub fn binding_error() {
    let x: i32 = "string";  // Error: mismatched types
}

/// Struct with unused field warning.
#[allow(dead_code)]
pub struct UnusedFields {
    used: i32,
    unused_field: String,  // Warning: field never read
}
