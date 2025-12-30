package main

import (
	"errors"
	"fmt"
)

// User represents a user in the system.
type User struct {
	Name  string
	Email string
	Age   int
}

// NewUser creates a new User instance.
func NewUser(name, email string, age int) *User {
	return &User{Name: name, Email: email, Age: age}
}

// IsAdult checks if the user is 18 or older.
func (u *User) IsAdult() bool {
	return u.Age >= 18
}

// DisplayName returns a formatted display name.
func (u *User) DisplayName() string {
	return fmt.Sprintf("%s <%s>", u.Name, u.Email)
}

// Storage is an interface for user storage backends.
type Storage interface {
	Save(user *User) error
	Load(email string) (*User, error)
	Delete(email string) error
	List() ([]*User, error)
}

// MemoryStorage stores users in memory.
type MemoryStorage struct {
	users map[string]*User
}

// NewMemoryStorage creates a new in-memory storage.
func NewMemoryStorage() *MemoryStorage {
	return &MemoryStorage{users: make(map[string]*User)}
}

// Save stores a user in memory.
func (m *MemoryStorage) Save(user *User) error {
	if user == nil {
		return errors.New("user cannot be nil")
	}
	m.users[user.Email] = user
	return nil
}

// Load retrieves a user by email.
func (m *MemoryStorage) Load(email string) (*User, error) {
	user, ok := m.users[email]
	if !ok {
		return nil, errors.New("user not found")
	}
	return user, nil
}

// Delete removes a user by email.
func (m *MemoryStorage) Delete(email string) error {
	if _, ok := m.users[email]; !ok {
		return errors.New("user not found")
	}
	delete(m.users, email)
	return nil
}

// List returns all users.
func (m *MemoryStorage) List() ([]*User, error) {
	result := make([]*User, 0, len(m.users))
	for _, user := range m.users {
		result = append(result, user)
	}
	return result, nil
}

// FileStorage stores users in files (stub implementation).
type FileStorage struct {
	basePath string
}

// NewFileStorage creates a new file-based storage.
func NewFileStorage(basePath string) *FileStorage {
	return &FileStorage{basePath: basePath}
}

// Save stores a user to a file.
func (f *FileStorage) Save(user *User) error {
	// Stub implementation
	return nil
}

// Load retrieves a user from a file.
func (f *FileStorage) Load(email string) (*User, error) {
	// Stub implementation
	return nil, errors.New("not implemented")
}

// Delete removes a user file.
func (f *FileStorage) Delete(email string) error {
	// Stub implementation
	return nil
}

// List returns all users from files.
func (f *FileStorage) List() ([]*User, error) {
	// Stub implementation
	return nil, nil
}

// UserRepository provides high-level user management operations.
type UserRepository struct {
	storage Storage
}

// NewUserRepository creates a new repository with the given storage.
func NewUserRepository(storage Storage) *UserRepository {
	return &UserRepository{storage: storage}
}

// AddUser adds a user to the repository.
func (r *UserRepository) AddUser(user *User) error {
	return r.storage.Save(user)
}

// GetUser retrieves a user by email.
func (r *UserRepository) GetUser(email string) (*User, error) {
	return r.storage.Load(email)
}

// DeleteUser removes a user by email.
func (r *UserRepository) DeleteUser(email string) error {
	return r.storage.Delete(email)
}

// ListUsers returns all users.
func (r *UserRepository) ListUsers() ([]*User, error) {
	return r.storage.List()
}

// createSampleUser creates a sample user for testing.
func createSampleUser() *User {
	return NewUser("John Doe", "john@example.com", 30)
}

// Validator defines validation behavior.
type Validator interface {
	Validate() error
}

// ValidateUser checks if a user is valid.
func ValidateUser(user *User) error {
	if user.Name == "" {
		return errors.New("name is required")
	}
	if user.Email == "" {
		return errors.New("email is required")
	}
	if user.Age < 0 {
		return errors.New("age must be non-negative")
	}
	return nil
}

func main() {
	storage := NewMemoryStorage()
	repo := NewUserRepository(storage)
	user := createSampleUser()

	if err := repo.AddUser(user); err != nil {
		fmt.Printf("Error adding user: %v\n", err)
		return
	}

	if found, err := repo.GetUser("john@example.com"); err == nil {
		fmt.Printf("Found user: %s\n", found.DisplayName())
		fmt.Printf("Is adult: %v\n", found.IsAdult())
	}
}
