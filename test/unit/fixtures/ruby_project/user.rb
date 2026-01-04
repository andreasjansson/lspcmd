# frozen_string_literal: true

# Represents a user in the system.
#
# @attr_reader name [String] The user's full name
# @attr_reader email [String] The user's email address
# @attr_reader age [Integer] The user's age in years
class User
  attr_reader :name, :email, :age

  # Creates a new User instance.
  #
  # @param name [String] The user's name
  # @param email [String] The user's email
  # @param age [Integer] The user's age
  def initialize(name, email, age)
    @name = name
    @email = email
    @age = age
  end

  # Checks if the user is 18 or older.
  #
  # @return [Boolean] True if the user is an adult
  def adult?
    @age >= 18
  end

  # Returns a formatted display name.
  #
  # @return [String] The display name in format "name <email>"
  def display_name
    "#{@name} <#{@email}>"
  end
end

# Interface for user storage backends.
class Storage
  # Saves a user to the storage.
  #
  # @param user [User] The user to save
  def save(user)
    raise NotImplementedError
  end

  # Loads a user by email.
  #
  # @param email [String] The email to search for
  # @return [User, nil] The user if found
  def load(email)
    raise NotImplementedError
  end

  # Deletes a user by email.
  #
  # @param email [String] The email of the user to delete
  # @return [Boolean] True if the user was deleted
  def delete(email)
    raise NotImplementedError
  end

  # Lists all users.
  #
  # @return [Array<User>] All users in the storage
  def list
    raise NotImplementedError
  end
end

# Stores users in memory.
class MemoryStorage < Storage
  def initialize
    @users = {}
  end

  # Saves a user to memory.
  #
  # @param user [User] The user to save
  def save(user)
    @users[user.email] = user
  end

  # Loads a user by email.
  #
  # @param email [String] The email to search for
  # @return [User, nil] The user if found
  def load(email)
    @users[email]
  end

  # Deletes a user by email.
  #
  # @param email [String] The email of the user to delete
  # @return [Boolean] True if the user was deleted
  def delete(email)
    if @users.key?(email)
      @users.delete(email)
      true
    else
      false
    end
  end

  # Lists all users.
  #
  # @return [Array<User>] All users in the storage
  def list
    @users.values
  end
end

# Stores users in files (stub implementation).
class FileStorage < Storage
  attr_reader :base_path

  # Creates a new FileStorage instance.
  #
  # @param base_path [String] The base path for file storage
  def initialize(base_path)
    @base_path = base_path
  end

  def save(user)
    # Stub implementation
  end

  def load(email)
    # Stub implementation
    nil
  end

  def delete(email)
    # Stub implementation
    false
  end

  def list
    # Stub implementation
    []
  end
end

# Country codes mapped to their full names.
COUNTRY_CODES = {
  'US' => 'United States',
  'CA' => 'Canada',
  'GB' => 'United Kingdom',
  'DE' => 'Germany',
  'FR' => 'France',
  'JP' => 'Japan',
  'AU' => 'Australia'
}.freeze

# Default configuration values.
DEFAULT_CONFIG = [
  'debug=false',
  'timeout=30',
  'max_retries=3',
  'log_level=INFO'
].freeze

# Provides high-level user management operations.
class UserRepository
  # Creates a new UserRepository instance.
  #
  # @param storage [Storage] The storage backend to use
  def initialize(storage)
    @storage = storage
  end

  # Adds a user to the repository.
  #
  # @param user [User] The user to add
  def add_user(user)
    @storage.save(user)
  end

  # Gets a user by email.
  #
  # @param email [String] The email to search for
  # @return [User, nil] The user if found
  def get_user(email)
    @storage.load(email)
  end

  # Deletes a user by email.
  #
  # @param email [String] The email of the user to delete
  # @return [Boolean] True if the user was deleted
  def delete_user(email)
    @storage.delete(email)
  end

  # Lists all users.
  #
  # @return [Array<User>] All users in the repository
  def list_users
    @storage.list
  end
end
