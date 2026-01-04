<?php

declare(strict_types=1);

namespace LetaFixture;

/**
 * Class with intentional errors for diagnostics testing.
 */
class Errors
{
    /**
     * Method with undefined variable.
     */
    public function undefinedVariable(): int
    {
        return $undefinedVar;  // Error: undefined variable
    }

    /**
     * Method with type mismatch.
     */
    public function typeError(): int
    {
        return "not an int";  // Error: return type mismatch
    }

    /**
     * Method calling undefined method.
     */
    public function undefinedMethod(): void
    {
        $this->nonExistentMethod();  // Error: undefined method
    }

    /**
     * Method with wrong argument count.
     */
    public function argumentError(): void
    {
        substr("hello");  // Error: too few arguments
    }

    /**
     * Method with undefined class.
     */
    public function undefinedClass(): void
    {
        $obj = new UndefinedClass();  // Error: undefined class
    }
}
