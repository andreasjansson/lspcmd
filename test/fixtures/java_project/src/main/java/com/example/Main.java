package com.example;

import java.util.List;

/**
 * Main entry point for the application.
 */
public class Main {

    /**
     * Creates a sample user for testing.
     *
     * @return A sample user
     */
    public static User createSampleUser() {
        return new User("John Doe", "john@example.com", 30);
    }

    /**
     * Processes all users and prints their display names.
     *
     * @param repo The repository to process
     * @return A list of display names
     */
    public static List<String> processUsers(UserRepository repo) {
        return repo.listUsers().stream()
                .map(User::displayName)
                .toList();
    }

    /**
     * Validates an email address format.
     *
     * @param email The email to validate
     * @return true if the email format is valid
     */
    public static boolean validateEmail(String email) {
        String pattern = "^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$";
        return email.matches(pattern);
    }

    /**
     * Main entry point.
     *
     * @param args Command line arguments
     */
    public static void main(String[] args) {
        Storage storage = new MemoryStorage();
        UserRepository repo = new UserRepository(storage);
        User user = createSampleUser();

        repo.addUser(user);

        User found = repo.getUser("john@example.com");
        if (found != null) {
            System.out.println("Found user: " + found.displayName());
            System.out.println("Is adult: " + found.isAdult());
        }

        List<String> names = processUsers(repo);
        for (String name : names) {
            System.out.println("User: " + name);
        }
    }
}
