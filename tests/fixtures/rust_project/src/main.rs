mod user;

use user::{User, UserRepository};

fn create_sample_user() -> User {
    User::new("John Doe".to_string(), "john@example.com".to_string(), 30)
}

fn main() {
    let mut repo = UserRepository::new();
    let user = create_sample_user();
    repo.add_user(user);

    if let Some(found) = repo.get_user("john@example.com") {
        println!("Found user: {}", found.name());
    }
}
