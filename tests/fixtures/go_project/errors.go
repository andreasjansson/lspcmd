package main

// ErrorFunc has intentional errors for diagnostics testing.
func ErrorFunc() {
	// Undefined variable
	_ = undefinedVar

	// Type mismatch
	var x int = "not an int"
	_ = x

	// Unused variable (if strict mode)
	unusedVar := 42
}

// TypeErrorFunc has a return type error.
func TypeErrorFunc() int {
	return "string" // Wrong return type
}
