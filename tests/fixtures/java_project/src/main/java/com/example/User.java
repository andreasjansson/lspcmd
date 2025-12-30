package com.example;

/**
 * Represents a user in the system.
 */
public class User {
    private String name;
    private String email;
    private int age;

    /**
     * Creates a new User instance.
     *
     * @param name  The user's full name
     * @param email The user's email address
     * @param age   The user's age in years
     */
    public User(String name, String email, int age) {
        this.name = name;
        this.email = email;
        this.age = age;
    }

    /**
     * Gets the user's name.
     *
     * @return The user's name
     */
    public String getName() {
        return name;
    }

    /**
     * Gets the user's email address.
     *
     * @return The user's email
     */
    public String getEmail() {
        return email;
    }

    /**
     * Gets the user's age.
     *
     * @return The user's age
     */
    public int getAge() {
        return age;
    }

    /**
     * Checks if the user is an adult (18 or older).
     *
     * @return true if the user is 18 or older
     */
    public boolean isAdult() {
        return age >= 18;
    }

    /**
     * Returns a formatted display name.
     *
     * @return The display name in format "Name <email>"
     */
    public String displayName() {
        return String.format("%s <%s>", name, email);
    }

    @Override
    public String toString() {
        return "User{name='" + name + "', email='" + email + "', age=" + age + "}";
    }
}
