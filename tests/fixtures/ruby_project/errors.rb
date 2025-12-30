# frozen_string_literal: true

# File with intentional errors for diagnostics testing.

# Method with undefined variable
def undefined_variable
  undefined_var  # Error: undefined local variable
end

# Method with type error (for sorbet/solargraph if type checking enabled)
# @param x [Integer]
# @return [Integer]
def type_error(x)
  'not an integer'  # Returns wrong type
end

# Method with undefined constant
def undefined_constant
  UndefinedConstant.new  # Error: uninitialized constant
end

# Method calling undefined method
def undefined_method
  'hello'.nonexistent_method  # Error: undefined method
end

# Class with duplicate method definition
class DuplicateMethods
  def foo
    1
  end

  def foo  # Warning: method redefined
    2
  end
end
