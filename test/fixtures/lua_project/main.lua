--- Main entry point for the application.
-- @module main

local user = require("user")

--- Creates a sample user for testing.
-- @return User A sample user instance
local function createSampleUser()
    return user.User.new("John Doe", "john@example.com", 30)
end

--- Validates a user and throws an error if invalid.
-- @param u User The user to validate
local function validateUser(u)
    if not u.name or u.name == "" then
        error("name is required")
    end
    if not u.email or u.email == "" then
        error("email is required")
    end
    if u.age < 0 then
        error("age must be non-negative")
    end
end

--- Processes users in a repository.
-- @param repo UserRepository The repository to process
local function processUsers(repo)
    local users = repo:listUsers()
    for _, u in ipairs(users) do
        print(u:displayName())
    end
end

--- Main function.
local function main()
    local storage = user.MemoryStorage.new()
    local repo = user.UserRepository.new(storage)

    local sampleUser = createSampleUser()
    validateUser(sampleUser)

    repo:addUser(sampleUser)

    local found = repo:getUser("john@example.com")
    if found then
        print("Found user: " .. found:displayName())
        print("Is adult: " .. tostring(found:isAdult()))
    end

    processUsers(repo)
end

-- Export for testing
return {
    createSampleUser = createSampleUser,
    validateUser = validateUser,
    processUsers = processUsers,
    main = main,
}
