--- File with intentional errors for diagnostics testing.
-- @module errors

--- Function with undefined variable.
-- @return number The result (has error)
local function undefinedVariable()
    return undefined_var  -- Error: undefined global
end

--- Function with type annotation error.
-- @param x number The input
-- @return number The result
local function typeError(x)
    ---@type number
    local y = "not a number"  -- Warning: type mismatch
    return y
end

--- Function with redundant return.
-- @return nil
local function redundantReturn()
    return nil, "extra"  -- Warning: redundant return value
end

--- Function calling non-existent method.
local function methodError()
    local s = "hello"
    return s:nonExistentMethod()  -- Error: undefined method
end

return {
    undefinedVariable = undefinedVariable,
    typeError = typeError,
    redundantReturn = redundantReturn,
    methodError = methodError,
}
