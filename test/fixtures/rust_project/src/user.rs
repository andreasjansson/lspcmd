use crate::storage::Storage;

/// Represents a user in the system.
#[derive(Debug, Clone)]
pub struct User {
    name: String,
    email: String,
    age: u32,
}

impl User {
    /// Creates a new User instance.
    pub fn new(name: String, email: String, age: u32) -> Self {
        Self { name, email, age }
    }

    /// Returns the user's name.
    pub fn name(&self) -> &str {
        &self.name
    }

    /// Returns the user's email address.
    pub fn email(&self) -> &str {
        &self.email
    }

    /// Returns the user's age.
    pub fn age(&self) -> u32 {
        self.age
    }

    /// Checks if the user is an adult (18 or older).
    pub fn is_adult(&self) -> bool {
        self.age >= 18
    }

    /// Returns a formatted display name.
    pub fn display_name(&self) -> String {
        format!("{} <{}>", self.name, self.email)
    }
}

/// Repository for managing user entities.
pub struct UserRepository<S: Storage> {
    storage: S,
}

impl<S: Storage> UserRepository<S> {
    /// Creates a new repository with the given storage.
    pub fn new(storage: S) -> Self {
        Self { storage }
    }

    /// Adds a user to the repository.
    pub fn add_user(&mut self, user: User) {
        self.storage.save(user.email().to_string(), user);
    }

    /// Retrieves a user by email address.
    pub fn get_user(&self, email: &str) -> Option<&User> {
        self.storage.load(email)
    }

    /// Deletes a user by email address.
    pub fn delete_user(&mut self, email: &str) -> bool {
        self.storage.delete(email)
    }

    /// Lists all users in the repository.
    pub fn list_users(&self) -> Vec<&User> {
        self.storage.list()
    }

    /// Returns the number of users.
    pub fn count(&self) -> usize {
        self.storage.list().len()
    }
}

/// Validates a user's data.
pub fn validate_user(user: &User) -> Result<(), String> {
    if user.name().is_empty() {
        return Err("name is required".to_string());
    }
    if user.email().is_empty() {
        return Err("email is required".to_string());
    }
    Ok(())
}
