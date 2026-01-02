package main

// ISOLATED TEST FILE - Used exclusively by rename and mv tests.
// Do NOT use symbols from this file in grep, refs, calls, or other read-only tests.

import "fmt"

// EditablePerson is a type for testing rename operations.
type EditablePerson struct {
	Name  string
	Email string
}

// NewEditablePerson creates a new EditablePerson.
func NewEditablePerson(name, email string) *EditablePerson {
	return &EditablePerson{Name: name, Email: email}
}

// Greet returns a greeting message.
func (p *EditablePerson) Greet() string {
	return fmt.Sprintf("Hello, %s", p.Name)
}

// editableCreateSample creates an editable sample for testing replace-function.
func editableCreateSample() *EditablePerson {
	return NewEditablePerson("Original Name", "original@example.com")
}

// editableValidateEmail validates an editable email address.
func editableValidateEmail(email string) bool {
	for _, c := range email {
		if c == '@' {
			return true
		}
	}
	return false
}

// EditableStorage is a storage class for testing method replacement.
type EditableStorage struct {
	data map[string]string
}

// NewEditableStorage creates a new EditableStorage.
func NewEditableStorage() *EditableStorage {
	return &EditableStorage{data: make(map[string]string)}
}

// Save stores a value.
func (s *EditableStorage) Save(key, value string) {
	s.data[key] = value
}

// Load retrieves a value.
func (s *EditableStorage) Load(key string) (string, bool) {
	v, ok := s.data[key]
	return v, ok
}
