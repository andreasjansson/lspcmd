package com.example;

import java.util.List;

/**
 * Interface defining the storage operations for users.
 */
public interface Storage {
    /**
     * Saves a user to storage.
     *
     * @param user The user to save
     */
    void save(User user);

    /**
     * Loads a user by email address.
     *
     * @param email The email to look up
     * @return The user if found, null otherwise
     */
    User load(String email);

    /**
     * Deletes a user by email address.
     *
     * @param email The email of the user to delete
     * @return true if the user was deleted
     */
    boolean delete(String email);

    /**
     * Lists all stored users.
     *
     * @return A list of all users
     */
    List<User> list();
}
