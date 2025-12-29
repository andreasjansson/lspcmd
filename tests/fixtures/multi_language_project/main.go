package main

import "fmt"

// GoService is a service implemented in Go
type GoService struct {
	Name string
}

// NewGoService creates a new GoService
func NewGoService(name string) *GoService {
	return &GoService{Name: name}
}

// Greet returns a greeting from Go
func (s *GoService) Greet() string {
	return fmt.Sprintf("Hello from Go, %s!", s.Name)
}

func main() {
	service := NewGoService("World")
	fmt.Println(service.Greet())
}
