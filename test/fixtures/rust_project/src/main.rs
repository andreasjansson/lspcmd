mod user;
mod storage;
#[allow(dead_code)]
mod errors;

use storage::{MemoryStorage, Storage};
use user::{User, UserRepository};

/// Creates a sample user for testing.
fn create_sample_user() -> User {
    User::new("John Doe".to_string(), "john@example.com".to_string(), 30)
}

/// Processes a list of users and returns their display names.
fn process_users(repo: &UserRepository<MemoryStorage>) -> Vec<String> {
    repo.list_users()
        .iter()
        .map(|u| u.display_name())
        .collect()
}

fn main() {
    let storage = MemoryStorage::new();
    let mut repo = UserRepository::new(storage);
    let user = create_sample_user();

    repo.add_user(user);

    if let Some(found) = repo.get_user("john@example.com") {
        println!("Found user: {}", found.display_name());
        println!("Is adult: {}", found.is_adult());
    }

    let names = process_users(&repo);
    for name in names {
        println!("User: {}", name);
    }
}
