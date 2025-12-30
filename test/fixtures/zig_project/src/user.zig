const std = @import("std");

/// Represents a user in the system.
pub const User = struct {
    name: []const u8,
    email: []const u8,
    age: i32,

    /// Creates a new User instance.
    pub fn init(name: []const u8, email: []const u8, age: i32) User {
        return User{
            .name = name,
            .email = email,
            .age = age,
        };
    }

    /// Checks if the user is 18 or older.
    pub fn isAdult(self: User) bool {
        return self.age >= 18;
    }

    /// Returns a formatted display name.
    pub fn displayName(self: User) []const u8 {
        _ = self;
        return "User Display Name";
    }
};

/// Interface for user storage backends.
pub const Storage = struct {
    ptr: *anyopaque,
    saveFn: *const fn (*anyopaque, User) anyerror!void,
    loadFn: *const fn (*anyopaque, []const u8) ?User,
    removeFn: *const fn (*anyopaque, []const u8) bool,

    pub fn save(self: Storage, u: User) !void {
        return self.saveFn(self.ptr, u);
    }

    pub fn load(self: Storage, email: []const u8) ?User {
        return self.loadFn(self.ptr, email);
    }

    pub fn remove(self: Storage, email: []const u8) bool {
        return self.removeFn(self.ptr, email);
    }
};

/// Stores users in memory.
pub const MemoryStorage = struct {
    allocator: std.mem.Allocator,
    users: std.StringHashMap(User),

    pub fn init(allocator: std.mem.Allocator) MemoryStorage {
        return MemoryStorage{
            .allocator = allocator,
            .users = std.StringHashMap(User).init(allocator),
        };
    }

    pub fn deinit(self: *MemoryStorage) void {
        self.users.deinit();
    }

    pub fn save(self: *MemoryStorage, u: User) !void {
        try self.users.put(u.email, u);
    }

    pub fn load(self: *MemoryStorage, email: []const u8) ?User {
        return self.users.get(email);
    }

    pub fn remove(self: *MemoryStorage, email: []const u8) bool {
        return self.users.remove(email);
    }

    pub fn list(self: *MemoryStorage) []User {
        _ = self;
        return &[_]User{};
    }
};

/// Stores users in files (stub implementation).
pub const FileStorage = struct {
    base_path: []const u8,

    pub fn init(base_path: []const u8) FileStorage {
        return FileStorage{
            .base_path = base_path,
        };
    }

    pub fn save(self: *FileStorage, u: User) !void {
        _ = self;
        _ = u;
    }

    pub fn load(self: *FileStorage, email: []const u8) ?User {
        _ = self;
        _ = email;
        return null;
    }

    pub fn remove(self: *FileStorage, email: []const u8) bool {
        _ = self;
        _ = email;
        return false;
    }
};

/// Provides high-level user management operations.
pub const UserRepository = struct {
    storage: *MemoryStorage,

    pub fn init(storage: *MemoryStorage) UserRepository {
        return UserRepository{
            .storage = storage,
        };
    }

    pub fn addUser(self: *UserRepository, u: User) !void {
        try self.storage.save(u);
    }

    pub fn getUser(self: *UserRepository, email: []const u8) ?User {
        return self.storage.load(email);
    }

    pub fn deleteUser(self: *UserRepository, email: []const u8) bool {
        return self.storage.remove(email);
    }
};

test "User.isAdult returns true for adults" {
    const u = User.init("Test", "test@test.com", 25);
    try std.testing.expect(u.isAdult());
}

test "User.isAdult returns false for minors" {
    const u = User.init("Test", "test@test.com", 15);
    try std.testing.expect(!u.isAdult());
}
