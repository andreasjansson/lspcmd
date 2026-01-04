package main

import (
	"regexp"
	"strings"
)

// ValidateEmail checks if an email address has valid format.
func ValidateEmail(email string) bool {
	pattern := `^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$`
	matched, _ := regexp.MatchString(pattern, email)
	return matched
}

// ValidateAge checks if an age is within reasonable bounds.
func ValidateAge(age int) bool {
	return age >= 0 && age <= 150
}

// FormatName combines first and last name.
func FormatName(first, last string) string {
	return strings.TrimSpace(first + " " + last)
}

// Counter provides a simple counting mechanism.
type Counter struct {
	value int
}

// NewCounter creates a new counter with the given initial value.
func NewCounter(initial int) *Counter {
	return &Counter{value: initial}
}

// Value returns the current counter value.
func (c *Counter) Value() int {
	return c.value
}

// Increment increases the counter by one.
func (c *Counter) Increment() int {
	c.value++
	return c.value
}

// Decrement decreases the counter by one.
func (c *Counter) Decrement() int {
	c.value--
	return c.value
}

// Reset sets the counter back to zero.
func (c *Counter) Reset() {
	c.value = 0
}

// Result represents an operation result that may fail.
type Result[T any] struct {
	value T
	err   error
}

// NewResult creates a successful result.
func NewResult[T any](value T) *Result[T] {
	return &Result[T]{value: value}
}

// NewError creates an error result.
func NewError[T any](err error) *Result[T] {
	return &Result[T]{err: err}
}

// IsOk returns true if the result is successful.
func (r *Result[T]) IsOk() bool {
	return r.err == nil
}

// IsErr returns true if the result is an error.
func (r *Result[T]) IsErr() bool {
	return r.err != nil
}

// Unwrap returns the value or panics if error.
func (r *Result[T]) Unwrap() T {
	if r.err != nil {
		panic(r.err)
	}
	return r.value
}

// UnwrapOr returns the value or a default.
func (r *Result[T]) UnwrapOr(defaultValue T) T {
	if r.err != nil {
		return defaultValue
	}
	return r.value
}

// CountryCodes maps country codes to their full names.
var CountryCodes = map[string]string{
	"US": "United States",
	"CA": "Canada",
	"GB": "United Kingdom",
	"DE": "Germany",
	"FR": "France",
	"JP": "Japan",
	"AU": "Australia",
}

// DefaultPorts contains commonly used network ports.
var DefaultPorts = []int{
	80,
	443,
	8080,
	8443,
	3000,
}
