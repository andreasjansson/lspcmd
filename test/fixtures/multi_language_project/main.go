package main

import "fmt"

// GoUser represents a user in the Go service.
type GoUser struct {
	Name  string
	Email string
}

// GoService is a service implemented in Go.
type GoService struct {
	Name  string
	users []GoUser
}

// NewGoService creates a new GoService.
func NewGoService(name string) *GoService {
	return &GoService{
		Name:  name,
		users: make([]GoUser, 0),
	}
}

// Greet returns a greeting from Go.
func (s *GoService) Greet() string {
	return fmt.Sprintf("Hello from Go, %s!", s.Name)
}

// AddUser adds a user to the service.
func (s *GoService) AddUser(user GoUser) {
	s.users = append(s.users, user)
}

// GetUsers returns all users.
func (s *GoService) GetUsers() []GoUser {
	result := make([]GoUser, len(s.users))
	copy(result, s.users)
	return result
}

// Servicer defines the service interface.
type Servicer interface {
	Greet() string
}

// CreateService creates a new Go service.
func CreateService(name string) *GoService {
	return NewGoService(name)
}

// ValidateEmail validates an email address format.
func ValidateEmail(email string) bool {
	// Simple validation
	for i, c := range email {
		if c == '@' && i > 0 && i < len(email)-1 {
			return true
		}
	}
	return false
}

func main() {
	service := CreateService("World")
	fmt.Println(service.Greet())

	service.AddUser(GoUser{Name: "John", Email: "john@example.com"})
	users := service.GetUsers()
	for _, user := range users {
		fmt.Printf("User: %s <%s>\n", user.Name, user.Email)
	}
}
