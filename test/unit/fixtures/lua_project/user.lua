--- User module for managing users in the system.
-- @module user

local M = {}

--- Represents a user in the system.
-- @class User
-- @field name string The user's full name
-- @field email string The user's email address
-- @field age number The user's age in years
local User = {}
User.__index = User

--- Creates a new User instance.
-- @param name string The user's name
-- @param email string The user's email
-- @param age number The user's age
-- @return User A new user instance
function User.new(name, email, age)
    local self = setmetatable({}, User)
    self.name = name
    self.email = email
    self.age = age
    return self
end

--- Checks if the user is 18 or older.
-- @return boolean True if the user is an adult
function User:isAdult()
    return self.age >= 18
end

--- Returns a formatted display name.
-- @return string The display name in format "name <email>"
function User:displayName()
    return string.format("%s <%s>", self.name, self.email)
end

M.User = User

--- Interface for user storage backends.
-- @class Storage
local Storage = {}
Storage.__index = Storage

function Storage.new()
    local self = setmetatable({}, Storage)
    return self
end

function Storage:save(user)
    error("Not implemented")
end

function Storage:load(email)
    error("Not implemented")
end

function Storage:remove(email)
    error("Not implemented")
end

function Storage:list()
    error("Not implemented")
end

M.Storage = Storage

--- Stores users in memory.
-- @class MemoryStorage
-- @field users table Internal storage table
local MemoryStorage = {}
MemoryStorage.__index = MemoryStorage

--- Creates a new MemoryStorage instance.
-- @return MemoryStorage A new memory storage instance
function MemoryStorage.new()
    local self = setmetatable({}, MemoryStorage)
    self.users = {}
    return self
end

--- Saves a user to memory.
-- @param user User The user to save
function MemoryStorage:save(user)
    self.users[user.email] = user
end

--- Loads a user by email.
-- @param email string The email to search for
-- @return User|nil The user if found, nil otherwise
function MemoryStorage:load(email)
    return self.users[email]
end

--- Removes a user by email.
-- @param email string The email of the user to remove
-- @return boolean True if the user was removed
function MemoryStorage:remove(email)
    if self.users[email] then
        self.users[email] = nil
        return true
    end
    return false
end

--- Lists all users.
-- @return table Array of all users
function MemoryStorage:list()
    local result = {}
    for _, user in pairs(self.users) do
        table.insert(result, user)
    end
    return result
end

M.MemoryStorage = MemoryStorage

--- Stores users in files (stub implementation).
-- @class FileStorage
-- @field basePath string Base path for file storage
local FileStorage = {}
FileStorage.__index = FileStorage

--- Creates a new FileStorage instance.
-- @param basePath string The base path for file storage
-- @return FileStorage A new file storage instance
function FileStorage.new(basePath)
    local self = setmetatable({}, FileStorage)
    self.basePath = basePath
    return self
end

function FileStorage:save(user)
    -- Stub implementation
end

function FileStorage:load(email)
    -- Stub implementation
    return nil
end

function FileStorage:remove(email)
    -- Stub implementation
    return false
end

function FileStorage:list()
    -- Stub implementation
    return {}
end

M.FileStorage = FileStorage

--- Provides high-level user management operations.
-- @class UserRepository
-- @field storage Storage The storage backend
local UserRepository = {}
UserRepository.__index = UserRepository

--- Creates a new UserRepository instance.
-- @param storage Storage The storage backend to use
-- @return UserRepository A new repository instance
function UserRepository.new(storage)
    local self = setmetatable({}, UserRepository)
    self.storage = storage
    return self
end

--- Adds a user to the repository.
-- @param user User The user to add
function UserRepository:addUser(user)
    self.storage:save(user)
end

--- Gets a user by email.
-- @param email string The email to search for
-- @return User|nil The user if found
function UserRepository:getUser(email)
    return self.storage:load(email)
end

--- Deletes a user by email.
-- @param email string The email of the user to delete
-- @return boolean True if the user was deleted
function UserRepository:deleteUser(email)
    return self.storage:remove(email)
end

--- Lists all users.
-- @return table Array of all users
function UserRepository:listUsers()
    return self.storage:list()
end

M.UserRepository = UserRepository

--- Country codes mapped to their full names.
M.COUNTRY_CODES = {
    US = "United States",
    CA = "Canada",
    GB = "United Kingdom",
    DE = "Germany",
    FR = "France",
    JP = "Japan",
    AU = "Australia",
}

--- Default configuration values.
M.DEFAULT_CONFIG = {
    "debug=false",
    "timeout=30",
    "max_retries=3",
    "log_level=INFO",
}

return M
