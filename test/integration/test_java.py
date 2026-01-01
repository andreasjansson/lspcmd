import os
import shutil
import time

import pytest

from lspcmd.utils.config import add_workspace_root, load_config

from .conftest import (
    FIXTURES_DIR,
    format_output,
    requires_jdtls,
    run_request,
)


class TestJavaIntegration:
    """Integration tests for Java using jdtls."""

    @pytest.fixture(autouse=True)
    def check_jdtls(self):
        requires_jdtls()

    @pytest.fixture(scope="class")
    def project(self, class_temp_dir):
        src = FIXTURES_DIR / "java_project"
        dst = class_temp_dir / "java_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def workspace(self, project, class_daemon, class_isolated_config):
        config = load_config()
        add_workspace_root(project, config)
        run_request("grep", {
            "paths": [str(project / "src" / "main" / "java" / "com" / "example" / "Main.java")],
            "workspace_root": str(project),
            "pattern": ".*",
        })
        time.sleep(3.0)
        return project

    # =========================================================================
    # grep tests
    # =========================================================================

    def test_grep_pattern_filter(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "main" / "java" / "com" / "example" / "User.java")],
            "workspace_root": str(workspace),
            "pattern": "^get",
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main/java/com/example/User.java:29 [Method] getName() ( : String) in User
src/main/java/com/example/User.java:38 [Method] getEmail() ( : String) in User
src/main/java/com/example/User.java:47 [Method] getAge() ( : int) in User"""

    def test_grep_kind_filter_class(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "main" / "java" / "com" / "example" / "User.java")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["class"],
        })
        output = format_output(response["result"], "plain")
        assert output == "src/main/java/com/example/User.java:6 [Class] User"

    def test_grep_kind_filter_method(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "main" / "java" / "com" / "example" / "User.java")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["method"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main/java/com/example/User.java:29 [Method] getName() ( : String) in User
src/main/java/com/example/User.java:38 [Method] getEmail() ( : String) in User
src/main/java/com/example/User.java:47 [Method] getAge() ( : int) in User
src/main/java/com/example/User.java:56 [Method] isAdult() ( : boolean) in User
src/main/java/com/example/User.java:65 [Method] displayName() ( : String) in User
src/main/java/com/example/User.java:70 [Method] toString() ( : String) in User"""

    def test_grep_case_sensitive(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "main" / "java" / "com" / "example" / "User.java")],
            "workspace_root": str(workspace),
            "pattern": "^User$",
            "case_sensitive": False,
        })
        output = format_output(response["result"], "plain")
        assert output == "src/main/java/com/example/User.java:6 [Class] User"
        
        response = run_request("grep", {
            "paths": [str(workspace / "src" / "main" / "java" / "com" / "example" / "User.java")],
            "workspace_root": str(workspace),
            "pattern": "^user$",
            "case_sensitive": True,
        })
        lowercase_output = format_output(response["result"], "plain")
        assert lowercase_output == "No results"

    def test_grep_combined_filters(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "workspace_root": str(workspace),
            "pattern": "Storage",
            "kinds": ["class"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main/java/com/example/AbstractStorage.java:7 [Class] AbstractStorage
src/main/java/com/example/FileStorage.java:12 [Class] FileStorage
src/main/java/com/example/MemoryStorage.java:12 [Class] MemoryStorage"""

    def test_grep_multiple_files(self, workspace):
        os.chdir(workspace)
        src_dir = workspace / "src" / "main" / "java" / "com" / "example"
        response = run_request("grep", {
            "paths": [str(src_dir / "Main.java"), str(src_dir / "User.java")],
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["method"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main/java/com/example/Main.java:15 [Method] createSampleUser() ( : User) in Main
src/main/java/com/example/Main.java:25 [Method] processUsers(UserRepository) ( : List<String>) in Main
src/main/java/com/example/Main.java:37 [Method] validateEmail(String) ( : boolean) in Main
src/main/java/com/example/Main.java:47 [Method] main(String[]) ( : void) in Main
src/main/java/com/example/User.java:29 [Method] getName() ( : String) in User
src/main/java/com/example/User.java:38 [Method] getEmail() ( : String) in User
src/main/java/com/example/User.java:47 [Method] getAge() ( : int) in User
src/main/java/com/example/User.java:56 [Method] isAdult() ( : boolean) in User
src/main/java/com/example/User.java:65 [Method] displayName() ( : String) in User
src/main/java/com/example/User.java:70 [Method] toString() ( : String) in User"""

    def test_grep_workspace_wide(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "workspace_root": str(workspace),
            "pattern": "validate",
            "case_sensitive": False,
            "kinds": ["method"],
        })
        output = format_output(response["result"], "plain")
        assert output == "src/main/java/com/example/Main.java:37 [Method] validateEmail(String) ( : boolean) in Main"

    def test_grep_exclude_pattern(self, workspace):
        os.chdir(workspace)
        response = run_request("grep", {
            "workspace_root": str(workspace),
            "pattern": ".*",
            "kinds": ["class"],
            "exclude_patterns": ["Errors.java"],
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main/java/com/example/AbstractStorage.java:7 [Class] AbstractStorage
src/main/java/com/example/User.java:6 [Class] User
src/main/java/com/example/Main.java:8 [Class] Main
src/main/java/com/example/UserRepository.java:9 [Class] UserRepository
src/main/java/com/example/FileStorage.java:12 [Class] FileStorage
src/main/java/com/example/MemoryStorage.java:12 [Class] MemoryStorage"""

    def test_grep_with_docs(self, workspace):
        os.chdir(workspace)
        src_dir = workspace / "src" / "main" / "java" / "com" / "example"
        response = run_request("grep", {
            "paths": [str(src_dir / "Main.java")],
            "workspace_root": str(workspace),
            "pattern": "createSampleUser",
            "kinds": ["method"],
            "include_docs": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main/java/com/example/Main.java:15 [Method] createSampleUser() ( : User) in Main
    User com.example.Main.createSampleUser()
    Creates a sample user for testing.
    
     *  **Returns:**
        
         *  A sample user
"""

    # =========================================================================
    # definition tests
    # =========================================================================

    def test_definition_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "Main.java"),
            "workspace_root": str(workspace),
            "line": 50,
            "column": 21,
            "context": 0,
            "body": False,
        })
        output = format_output(response["result"], "plain")
        assert output == "src/main/java/com/example/Main.java:15     public static User createSampleUser() {"

    def test_definition_with_body(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "Main.java"),
            "workspace_root": str(workspace),
            "line": 50,
            "column": 21,
            "context": 0,
            "body": True,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main/java/com/example/Main.java:10-17

    /**
     * Creates a sample user for testing.
     *
     * @return A sample user
     */
    public static User createSampleUser() {
        return new User("John Doe", "john@example.com", 30);
    }"""

    def test_definition_with_context(self, workspace):
        os.chdir(workspace)
        response = run_request("definition", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "Main.java"),
            "workspace_root": str(workspace),
            "line": 50,
            "column": 21,
            "context": 1,
            "body": False,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main/java/com/example/Main.java:14-16
     */
    public static User createSampleUser() {
        return new User("John Doe", "john@example.com", 30);
"""

    # =========================================================================
    # references tests
    # =========================================================================

    def test_references_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("references", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "User.java"),
            "workspace_root": str(workspace),
            "line": 6,
            "column": 13,
            "context": 0,
        })
        output = format_output(response["result"], "plain")
        assert output == """\
src/main/java/com/example/FileStorage.java:14     private Map<String, User> cache = new HashMap<>();
src/main/java/com/example/FileStorage.java:39     public void save(User user) {
src/main/java/com/example/FileStorage.java:48     public User load(String email) {
src/main/java/com/example/FileStorage.java:64     public List<User> list() {
src/main/java/com/example/Main.java:15     public static User createSampleUser() {
src/main/java/com/example/Main.java:16         return new User("John Doe", "john@example.com", 30);
src/main/java/com/example/Main.java:27                 .map(User::displayName)
src/main/java/com/example/Main.java:50         User user = createSampleUser();
src/main/java/com/example/Main.java:54         User found = repo.getUser("john@example.com");
src/main/java/com/example/MemoryStorage.java:13     private Map<String, User> users = new HashMap<>();
src/main/java/com/example/MemoryStorage.java:26     public void save(User user) {
src/main/java/com/example/MemoryStorage.java:34     public User load(String email) {
src/main/java/com/example/MemoryStorage.java:50     public List<User> list() {
src/main/java/com/example/Storage.java:14     void save(User user);
src/main/java/com/example/Storage.java:22     User load(String email);
src/main/java/com/example/Storage.java:37     List<User> list();
src/main/java/com/example/User.java:6 public class User {
src/main/java/com/example/UserRepository.java:26     public void addUser(User user) {
src/main/java/com/example/UserRepository.java:36     public User getUser(String email) {
src/main/java/com/example/UserRepository.java:55     public List<User> listUsers() {"""

    # =========================================================================
    # implementations tests
    # =========================================================================

    def test_implementations_basic(self, workspace):
        os.chdir(workspace)
        response = run_request("implementations", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "Storage.java"),
            "workspace_root": str(workspace),
            "line": 8,
            "column": 17,
            "context": 0,
        })
        output = format_output(response["result"], "plain")
        # Order is non-deterministic for jdtls, so check parts
        assert "AbstractStorage.java:7" in output
        assert "FileStorage.java:12" in output
        assert "MemoryStorage.java:12" in output

    # =========================================================================
    # describe (hover) tests
    # =========================================================================

    def test_describe_hover(self, workspace):
        os.chdir(workspace)
        response = run_request("describe", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "User.java"),
            "workspace_root": str(workspace),
            "line": 6,
            "column": 13,
        })
        output = format_output(response["result"], "plain")
        assert output == "com.example.User\nRepresents a user in the system."

    # =========================================================================
    # diagnostics tests
    # =========================================================================

    def test_diagnostics_single_file(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "Errors.java"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        assert "Errors.java" in output
        assert "error" in output.lower()

    def test_diagnostics_undefined_variable(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "Errors.java"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        assert "undefinedVar" in output or "cannot find symbol" in output.lower() or "cannot be resolved" in output.lower()

    def test_diagnostics_type_error(self, workspace):
        os.chdir(workspace)
        response = run_request("diagnostics", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "Errors.java"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")
        has_type_error = "incompatible" in output.lower() or "cannot convert" in output.lower() or "type mismatch" in output.lower()
        assert has_type_error, f"Expected type error in output: {output}"

    # =========================================================================
    # move-file tests
    # =========================================================================

    def test_move_file_renames_class(self, workspace):
        os.chdir(workspace)
        
        base_path = workspace / "src" / "main" / "java" / "com" / "example"
        user_path = base_path / "User.java"
        person_path = base_path / "Person.java"
        
        # Save original state for restoration
        original_user = user_path.read_text()
        original_main = (base_path / "Main.java").read_text()
        original_storage = (base_path / "Storage.java").read_text()
        original_memory_storage = (base_path / "MemoryStorage.java").read_text()
        original_file_storage = (base_path / "FileStorage.java").read_text()
        original_user_repository = (base_path / "UserRepository.java").read_text()
        
        try:
            # Verify User.java exists and check initial class usage
            assert user_path.exists()
            assert "User createSampleUser()" in original_main
            assert "new User(" in original_main
            
            # Rename User.java to Person.java
            response = run_request("move-file", {
                "old_path": str(user_path),
                "new_path": str(person_path),
                "workspace_root": str(workspace),
            })
            output = format_output(response["result"], "plain")
            
            # Verify the file was moved
            assert not user_path.exists()
            assert person_path.exists()
            
            # jdtls updates class references across multiple files
            assert "Moved file and updated imports in" in output
            assert "src/main/java/com/example/Main.java" in output
            assert "src/main/java/com/example/Person.java" in output
            
            # Check that class references were updated in Main.java
            updated_main = (base_path / "Main.java").read_text()
            assert "Person createSampleUser()" in updated_main
            assert "new Person(" in updated_main
            assert "new User(" not in updated_main
        finally:
            # Restore original state
            if person_path.exists():
                person_path.unlink()
            user_path.write_text(original_user)
            (base_path / "Main.java").write_text(original_main)
            (base_path / "Storage.java").write_text(original_storage)
            (base_path / "MemoryStorage.java").write_text(original_memory_storage)
            (base_path / "FileStorage.java").write_text(original_file_storage)
            (base_path / "UserRepository.java").write_text(original_user_repository)

    # =========================================================================
    # resolve-symbol disambiguation tests
    # =========================================================================

    def test_resolve_symbol_unique_class(self, workspace):
        """Test resolving a unique class name."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "UserRepository",
        })
        result = response["result"]
        assert result["name"] == "UserRepository"
        assert result["kind"] == "Class"

    def test_resolve_symbol_ambiguous_shows_container_refs(self, workspace):
        """Test that ambiguous Java symbols show Class.method format (normalized, no params)."""
        os.chdir(workspace)
        # First warm up the workspace with all Storage files
        run_request("grep", {
            "paths": [str(workspace / "src" / "main" / "java" / "com" / "example")],
            "workspace_root": str(workspace),
            "pattern": "save",
        })
        time.sleep(1.0)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "save",
        })
        result = response["result"]
        assert result["error"] == "Symbol 'save' is ambiguous (3 matches)"
        assert result["total_matches"] == 3
        refs = sorted([m["ref"] for m in result["matches"]])
        assert refs == ["FileStorage.save", "MemoryStorage.save", "Storage.save"]

    def test_resolve_symbol_class_method(self, workspace):
        """Test resolving Class.method format (without params)."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "MemoryStorage.save",
        })
        result = response["result"]
        assert result["name"] == "save(User)"
        assert result["kind"] == "Method"

    def test_resolve_symbol_file_filter(self, workspace):
        """Test resolving with file filter."""
        os.chdir(workspace)
        response = run_request("resolve-symbol", {
            "workspace_root": str(workspace),
            "symbol_path": "Main.java:Main",
        })
        result = response["result"]
        assert result["name"] == "Main"
        assert result["path"].endswith("Main.java")
