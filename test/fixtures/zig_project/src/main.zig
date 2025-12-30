const std = @import("std");
const user = @import("user.zig");

pub fn main() !void {
    const allocator = std.heap.page_allocator;

    var storage = user.MemoryStorage.init(allocator);
    defer storage.deinit();

    var repo = user.UserRepository.init(&storage);

    const sample_user = createSampleUser();
    try repo.addUser(sample_user);

    if (repo.getUser("john@example.com")) |found| {
        std.debug.print("Found user: {s}\n", .{found.displayName()});
        std.debug.print("Is adult: {}\n", .{found.isAdult()});
    }
}

/// Creates a sample user for testing.
pub fn createSampleUser() user.User {
    return user.User.init("John Doe", "john@example.com", 30);
}

/// Validates a user and returns an error if invalid.
pub fn validateUser(u: user.User) !void {
    if (u.name.len == 0) {
        return error.NameRequired;
    }
    if (u.email.len == 0) {
        return error.EmailRequired;
    }
    if (u.age < 0) {
        return error.InvalidAge;
    }
}

test "createSampleUser returns valid user" {
    const u = createSampleUser();
    try std.testing.expectEqualStrings("John Doe", u.name);
    try std.testing.expectEqualStrings("john@example.com", u.email);
    try std.testing.expectEqual(@as(i32, 30), u.age);
}
