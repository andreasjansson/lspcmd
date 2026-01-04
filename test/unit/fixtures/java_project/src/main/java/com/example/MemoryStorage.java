package com.example;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * In-memory storage implementation.
 * Stores users in a HashMap for fast access.
 */
public class MemoryStorage extends AbstractStorage {
    private Map<String, User> users = new HashMap<>();

    /**
     * Creates a new in-memory storage.
     */
    public MemoryStorage() {
        super("memory");
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public void save(User user) {
        users.put(user.getEmail(), user);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public User load(String email) {
        return users.get(email);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public boolean delete(String email) {
        return users.remove(email) != null;
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public List<User> list() {
        return new ArrayList<>(users.values());
    }

    /**
     * Returns the number of stored users.
     *
     * @return The user count
     */
    public int size() {
        return users.size();
    }

    /**
     * Clears all stored users.
     */
    public void clear() {
        users.clear();
    }
}
