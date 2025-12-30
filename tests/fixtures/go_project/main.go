package main

import "fmt"

type User struct {
	Name  string
	Email string
	Age   int
}

func NewUser(name, email string, age int) *User {
	return &User{Name: name, Email: email, Age: age}
}

// Storage is an interface for user storage backends
type Storage interface {
	Save(user *User) error
	Load(email string) (*User, error)
}

// MemoryStorage stores users in memory
type MemoryStorage struct {
	users map[string]*User
}

func (m *MemoryStorage) Save(user *User) error {
	m.users[user.Email] = user
	return nil
}

func (m *MemoryStorage) Load(email string) (*User, error) {
	return m.users[email], nil
}

// FileStorage stores users in files (stub)
type FileStorage struct {
	basePath string
}

func (f *FileStorage) Save(user *User) error {
	return nil
}

func (f *FileStorage) Load(email string) (*User, error) {
	return nil, nil
}

type UserRepository struct {
	storage Storage
}

func NewUserRepository(storage Storage) *UserRepository {
	return &UserRepository{storage: storage}
}

func (r *UserRepository) AddUser(user *User) {
	r.storage.Save(user)
}

func (r *UserRepository) GetUser(email string) *User {
	user, _ := r.storage.Load(email)
	return user
}

func createSampleUser() *User {
	return NewUser("John Doe", "john@example.com", 30)
}

func main() {
	storage := &MemoryStorage{users: make(map[string]*User)}
	repo := NewUserRepository(storage)
	user := createSampleUser()
	repo.AddUser(user)

	if found := repo.GetUser("john@example.com"); found != nil {
		fmt.Printf("Found user: %s\n", found.Name)
	}
}
