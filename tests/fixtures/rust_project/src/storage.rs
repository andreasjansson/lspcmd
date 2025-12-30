use std::collections::HashMap;
use crate::user::User;

/// Trait defining the storage interface.
pub trait Storage {
    /// Saves a user with the given key.
    fn save(&mut self, key: String, user: User);

    /// Loads a user by key.
    fn load(&self, key: &str) -> Option<&User>;

    /// Deletes a user by key.
    fn delete(&mut self, key: &str) -> bool;

    /// Lists all stored users.
    fn list(&self) -> Vec<&User>;
}

/// In-memory storage implementation.
pub struct MemoryStorage {
    users: HashMap<String, User>,
}

impl MemoryStorage {
    /// Creates a new empty memory storage.
    pub fn new() -> Self {
        Self {
            users: HashMap::new(),
        }
    }
}

impl Default for MemoryStorage {
    fn default() -> Self {
        Self::new()
    }
}

impl Storage for MemoryStorage {
    fn save(&mut self, key: String, user: User) {
        self.users.insert(key, user);
    }

    fn load(&self, key: &str) -> Option<&User> {
        self.users.get(key)
    }

    fn delete(&mut self, key: &str) -> bool {
        self.users.remove(key).is_some()
    }

    fn list(&self) -> Vec<&User> {
        self.users.values().collect()
    }
}

/// File-based storage implementation (stub).
pub struct FileStorage {
    base_path: String,
    cache: HashMap<String, User>,
}

impl FileStorage {
    /// Creates a new file storage with the given base path.
    pub fn new(base_path: String) -> Self {
        Self {
            base_path,
            cache: HashMap::new(),
        }
    }

    /// Returns the base path.
    pub fn base_path(&self) -> &str {
        &self.base_path
    }
}

impl Storage for FileStorage {
    fn save(&mut self, key: String, user: User) {
        // Stub: just cache in memory
        self.cache.insert(key, user);
    }

    fn load(&self, key: &str) -> Option<&User> {
        self.cache.get(key)
    }

    fn delete(&mut self, key: &str) -> bool {
        self.cache.remove(key).is_some()
    }

    fn list(&self) -> Vec<&User> {
        self.cache.values().collect()
    }
}
