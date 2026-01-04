# frozen_string_literal: true

require_relative 'user'

# Creates a sample user for testing.
#
# @return [User] A sample user instance
def create_sample_user
  User.new('John Doe', 'john@example.com', 30)
end

# Validates a user and raises an error if invalid.
#
# @param user [User] The user to validate
# @raise [ArgumentError] If the user is invalid
def validate_user(user)
  raise ArgumentError, 'name is required' if user.name.nil? || user.name.empty?
  raise ArgumentError, 'email is required' if user.email.nil? || user.email.empty?
  raise ArgumentError, 'age must be non-negative' if user.age.negative?
end

# Processes users in a repository.
#
# @param repo [UserRepository] The repository to process
# @return [Array<String>] The display names of all users
def process_users(repo)
  repo.list_users.map(&:display_name)
end

# Main entry point.
def main
  storage = MemoryStorage.new
  repo = UserRepository.new(storage)

  user = create_sample_user
  validate_user(user)

  repo.add_user(user)

  found = repo.get_user('john@example.com')
  if found
    puts "Found user: #{found.display_name}"
    puts "Is adult: #{found.adult?}"
  end

  names = process_users(repo)
  names.each { |name| puts "User: #{name}" }
end

main if __FILE__ == $PROGRAM_NAME
