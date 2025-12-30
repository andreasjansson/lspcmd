package com.example;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * File-based storage implementation.
 * Stores users in files (stub implementation).
 */
public class FileStorage extends AbstractStorage {
    private String basePath;
    private Map<String, User> cache = new HashMap<>();

    /**
     * Creates a new file storage with the given base path.
     *
     * @param basePath The base directory for storing files
     */
    public FileStorage(String basePath) {
        super("file");
        this.basePath = basePath;
    }

    /**
     * Gets the base path for file storage.
     *
     * @return The base path
     */
    public String getBasePath() {
        return basePath;
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public void save(User user) {
        // Stub: just cache in memory
        cache.put(user.getEmail(), user);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public User load(String email) {
        return cache.get(email);
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public boolean delete(String email) {
        return cache.remove(email) != null;
    }

    /**
     * {@inheritDoc}
     */
    @Override
    public List<User> list() {
        return new ArrayList<>(cache.values());
    }
}
