#pragma once

#include <string>
#include <memory>
#include <vector>
#include <unordered_map>
#include <optional>
#include <stdexcept>

namespace example {

/// Represents a user in the system.
class User {
public:
    User(std::string name, std::string email, int age)
        : name_(std::move(name)), email_(std::move(email)), age_(age) {}

    const std::string& name() const { return name_; }
    const std::string& email() const { return email_; }
    int age() const { return age_; }

    /// Checks if the user is 18 or older.
    bool isAdult() const { return age_ >= 18; }

    /// Returns a formatted display name.
    std::string displayName() const {
        return name_ + " <" + email_ + ">";
    }

private:
    std::string name_;
    std::string email_;
    int age_;
};

/// Interface for user storage backends.
class Storage {
public:
    virtual ~Storage() = default;

    virtual void save(const User& user) = 0;
    virtual std::optional<User> load(const std::string& email) = 0;
    virtual bool remove(const std::string& email) = 0;
    virtual std::vector<User> list() = 0;
};

/// Stores users in memory.
class MemoryStorage : public Storage {
public:
    void save(const User& user) override {
        users_[user.email()] = user;
    }

    std::optional<User> load(const std::string& email) override {
        auto it = users_.find(email);
        if (it != users_.end()) {
            return it->second;
        }
        return std::nullopt;
    }

    bool remove(const std::string& email) override {
        return users_.erase(email) > 0;
    }

    std::vector<User> list() override {
        std::vector<User> result;
        result.reserve(users_.size());
        for (const auto& [email, user] : users_) {
            result.push_back(user);
        }
        return result;
    }

private:
    std::unordered_map<std::string, User> users_;
};

/// Stores users in files (stub implementation).
class FileStorage : public Storage {
public:
    explicit FileStorage(std::string basePath)
        : basePath_(std::move(basePath)) {}

    void save(const User& user) override {
        // Stub implementation
    }

    std::optional<User> load(const std::string& email) override {
        // Stub implementation
        return std::nullopt;
    }

    bool remove(const std::string& email) override {
        // Stub implementation
        return false;
    }

    std::vector<User> list() override {
        // Stub implementation
        return {};
    }

private:
    std::string basePath_;
};

/// Provides high-level user management operations.
class UserRepository {
public:
    explicit UserRepository(std::unique_ptr<Storage> storage)
        : storage_(std::move(storage)) {}

    void addUser(const User& user) {
        storage_->save(user);
    }

    std::optional<User> getUser(const std::string& email) {
        return storage_->load(email);
    }

    bool deleteUser(const std::string& email) {
        return storage_->remove(email);
    }

    std::vector<User> listUsers() {
        return storage_->list();
    }

private:
    std::unique_ptr<Storage> storage_;
};

/// Creates a sample user for testing.
inline User createSampleUser() {
    return User("John Doe", "john@example.com", 30);
}

/// Validates a user.
inline void validateUser(const User& user) {
    if (user.name().empty()) {
        throw std::invalid_argument("name is required");
    }
    if (user.email().empty()) {
        throw std::invalid_argument("email is required");
    }
    if (user.age() < 0) {
        throw std::invalid_argument("age must be non-negative");
    }
}

} // namespace example
