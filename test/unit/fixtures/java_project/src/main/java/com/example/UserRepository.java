package com.example;

import java.util.List;

/**
 * Repository for managing user entities.
 * Provides high-level operations on top of a storage backend.
 */
public class UserRepository {
    private Storage storage;

    /**
     * Creates a new repository with the given storage backend.
     *
     * @param storage The storage backend to use
     */
    public UserRepository(Storage storage) {
        this.storage = storage;
    }

    /**
     * Adds a user to the repository.
     *
     * @param user The user to add
     */
    public void addUser(User user) {
        storage.save(user);
    }

    /**
     * Gets a user by email address.
     *
     * @param email The email to look up
     * @return The user if found, null otherwise
     */
    public User getUser(String email) {
        return storage.load(email);
    }

    /**
     * Deletes a user by email address.
     *
     * @param email The email of the user to delete
     * @return true if the user was deleted
     */
    public boolean deleteUser(String email) {
        return storage.delete(email);
    }

    /**
     * Lists all users in the repository.
     *
     * @return A list of all users
     */
    public List<User> listUsers() {
        return storage.list();
    }

    /**
     * Returns the number of users in the repository.
     *
     * @return The user count
     */
    public int countUsers() {
        return storage.list().size();
    }
}
