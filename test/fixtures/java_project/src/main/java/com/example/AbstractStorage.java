package com.example;

/**
 * Abstract base class for storage implementations.
 * Provides common functionality for all storage backends.
 */
public abstract class AbstractStorage implements Storage {
    protected String name;

    /**
     * Creates a new storage with the given name.
     *
     * @param name The name identifying this storage backend
     */
    public AbstractStorage(String name) {
        this.name = name;
    }

    /**
     * Gets the storage backend name.
     *
     * @return The storage name
     */
    public String getName() {
        return name;
    }

    /**
     * Checks if a user exists in storage.
     *
     * @param email The email to check
     * @return true if the user exists
     */
    public boolean exists(String email) {
        return load(email) != null;
    }
}
