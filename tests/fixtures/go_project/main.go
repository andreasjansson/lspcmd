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

type UserRepository struct {
	users map[string]*User
}

func NewUserRepository() *UserRepository {
	return &UserRepository{users: make(map[string]*User)}
}

func (r *UserRepository) AddUser(user *User) {
	r.users[user.Email] = user
}

func (r *UserRepository) GetUser(email string) *User {
	return r.users[email]
}

func (r *UserRepository) DeleteUser(email string) bool {
	if _, ok := r.users[email]; ok {
		delete(r.users, email)
		return true
	}
	return false
}

func (r *UserRepository) ListUsers() []*User {
	users := make([]*User, 0, len(r.users))
	for _, user := range r.users {
		users = append(users, user)
	}
	return users
}

func createSampleUser() *User {
	return NewUser("John Doe", "john@example.com", 30)
}

func main() {
	repo := NewUserRepository()
	user := createSampleUser()
	repo.AddUser(user)

	if found := repo.GetUser("john@example.com"); found != nil {
		fmt.Printf("Found user: %s\n", found.Name)
	}
}
