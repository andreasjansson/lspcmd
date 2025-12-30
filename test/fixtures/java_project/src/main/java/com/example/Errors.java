package com.example;

/**
 * Class with intentional errors for diagnostics testing.
 */
public class Errors {

    /**
     * Method with undefined variable.
     */
    public int undefinedVariable() {
        return undefinedVar;  // Error: cannot find symbol
    }

    /**
     * Method with type mismatch.
     */
    public int typeError() {
        String x = 123;  // Error: incompatible types
        return x;
    }

    /**
     * Method with missing return.
     */
    public String missingReturn() {
        String x = "hello";
        // Missing return statement
    }

    /**
     * Method calling non-existent method.
     */
    public void methodError() {
        String s = "hello";
        s.nonExistentMethod();  // Error: cannot find symbol
    }

    /**
     * Method with wrong argument count.
     */
    public void argumentError() {
        Math.max(1);  // Error: wrong number of arguments
    }
}
