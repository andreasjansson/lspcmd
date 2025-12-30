"""Integration tests for lspcmd.

Tests LSP features using the actual CLI interface (run_request + format_output).
Uses pytest-xdist for parallel execution to test concurrent daemon access.

Run with: pytest tests/test_integration.py -n auto
"""

import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest

from lspcmd.cli import run_request, ensure_daemon_running
from lspcmd.output.formatters import format_output
from lspcmd.utils.config import add_workspace_root, load_config

from .conftest import (
    requires_pyright,
    requires_rust_analyzer,
    requires_gopls,
    requires_typescript_lsp,
    requires_jdtls,
    FIXTURES_DIR,
)

os.environ["LSPCMD_REQUEST_TIMEOUT"] = "60"


@pytest.fixture(scope="class")
def class_temp_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("integration")


@pytest.fixture(scope="class")
def class_isolated_config(class_temp_dir):
    # Use /tmp for cache to avoid AF_UNIX path length limits (max ~104 chars)
    # The socket path would be too long if we used pytest's temp dir
    cache_dir = Path(tempfile.mkdtemp(prefix="lspcmd_test_"))
    config_dir = class_temp_dir / "config"
    config_dir.mkdir()
    old_cache = os.environ.get("XDG_CACHE_HOME")
    old_config = os.environ.get("XDG_CONFIG_HOME")
    os.environ["XDG_CACHE_HOME"] = str(cache_dir)
    os.environ["XDG_CONFIG_HOME"] = str(config_dir)
    yield {"cache": cache_dir, "config": config_dir}
    if old_cache:
        os.environ["XDG_CACHE_HOME"] = old_cache
    else:
        os.environ.pop("XDG_CACHE_HOME", None)
    if old_config:
        os.environ["XDG_CONFIG_HOME"] = old_config
    else:
        os.environ.pop("XDG_CONFIG_HOME", None)
    shutil.rmtree(cache_dir, ignore_errors=True)


@pytest.fixture(scope="class")
def class_daemon(class_isolated_config):
    ensure_daemon_running()
    time.sleep(0.5)
    yield
    try:
        run_request("shutdown", {})
    except Exception:
        pass


# =============================================================================
# Python Integration Tests (pyright)
# =============================================================================


class TestPythonIntegration:
    """Integration tests for Python using pyright."""

    @pytest.fixture(autouse=True)
    def check_pyright(self):
        requires_pyright()

    @pytest.fixture(scope="class")
    def project(self, class_temp_dir):
        src = FIXTURES_DIR / "python_project"
        dst = class_temp_dir / "python_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def workspace(self, project, class_daemon, class_isolated_config):
        config = load_config()
        add_workspace_root(project, config)
        # Warm up the server
        run_request("list-symbols", {
            "path": str(project / "main.py"),
            "workspace_root": str(project),
        })
        time.sleep(1.0)
        return project

    def test_grep_document_symbols(self, workspace):
        response = run_request("list-symbols", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")

        assert output == """\
main.py:12 [Class] StorageProtocol
main.py:15 [Method] save in StorageProtocol
main.py:15 [Variable] key in save
main.py:15 [Variable] value in save
main.py:19 [Method] load in StorageProtocol
main.py:19 [Variable] key in load
main.py:24 [Class] User
main.py:33 [Variable] name in User
main.py:34 [Variable] email in User
main.py:35 [Variable] age in User
main.py:37 [Method] is_adult in User
main.py:41 [Method] display_name in User
main.py:46 [Class] MemoryStorage
main.py:49 [Method] __init__ in MemoryStorage
main.py:52 [Method] save in MemoryStorage
main.py:52 [Variable] key in save
main.py:52 [Variable] value in save
main.py:55 [Method] load in MemoryStorage
main.py:55 [Variable] key in load
main.py:50 [Variable] _data in MemoryStorage
main.py:59 [Class] FileStorage
main.py:62 [Method] __init__ in FileStorage
main.py:62 [Variable] base_path in __init__
main.py:65 [Method] save in FileStorage
main.py:65 [Variable] key in save
main.py:65 [Variable] value in save
main.py:66 [Variable] path in save
main.py:67 [Variable] f in save
main.py:70 [Method] load in FileStorage
main.py:70 [Variable] key in load
main.py:71 [Variable] path in load
main.py:73 [Variable] f in load
main.py:63 [Variable] _base_path in FileStorage
main.py:78 [Class] UserRepository
main.py:84 [Method] __init__ in UserRepository
main.py:87 [Method] add_user in UserRepository
main.py:87 [Variable] user in add_user
main.py:91 [Method] get_user in UserRepository
main.py:91 [Variable] email in get_user
main.py:95 [Method] delete_user in UserRepository
main.py:95 [Variable] email in delete_user
main.py:102 [Method] list_users in UserRepository
main.py:106 [Method] count_users in UserRepository
main.py:85 [Variable] _users in UserRepository
main.py:111 [Function] create_sample_user
main.py:116 [Function] process_users
main.py:116 [Variable] repo in process_users
main.py:125 [Function] main
main.py:127 [Variable] repo in main
main.py:128 [Variable] user in main
main.py:131 [Variable] found in main"""

    def test_find_definition(self, workspace):
        # Line 128: "user = create_sample_user()", column 11 is start of "create_sample_user"
        os.chdir(workspace)
        response = run_request("find-definition", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 128,
            "column": 11,
            "context": 0,
        })
        output = format_output(response["result"], "plain")

        assert output == "main.py:111 def create_sample_user() -> User:"

    def test_find_definition_with_context(self, workspace):
        os.chdir(workspace)
        response = run_request("find-definition", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 128,
            "column": 11,
            "context": 2,
        })
        output = format_output(response["result"], "plain")

        assert output == """\
main.py:109-113


def create_sample_user() -> User:
    \"\"\"Create a sample user for testing.\"\"\"
    return User(name="John Doe", email="john@example.com", age=30)
"""

    def test_find_references(self, workspace):
        # Line 25: "class User:", column 6 is start of "User"
        os.chdir(workspace)
        response = run_request("find-references", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 25,
            "column": 6,
            "context": 0,
        })
        output = format_output(response["result"], "plain")

        assert output == """\
main.py:25 class User:
main.py:85         self._users: dict[str, User] = {}
main.py:87     def add_user(self, user: User) -> None:
main.py:91     def get_user(self, email: str) -> Optional[User]:
main.py:102     def list_users(self) -> list[User]:
main.py:111 def create_sample_user() -> User:
main.py:113     return User(name="John Doe", email="john@example.com", age=30)"""

    def test_describe_hover(self, workspace):
        # Line 25: "class User:", column 6 is start of "User"
        response = run_request("describe", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 25,
            "column": 6,
        })
        output = format_output(response["result"], "plain")

        assert output == """\
```python
(class) User
```
---
Represents a user in the system.

Attributes:  
&nbsp;&nbsp;&nbsp;&nbsp;name: The user's full name.  
&nbsp;&nbsp;&nbsp;&nbsp;email: The user's email address (used as unique identifier).  
&nbsp;&nbsp;&nbsp;&nbsp;age: The user's age in years."""

    def test_rename(self, workspace):
        response = run_request("rename", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 25,
            "column": 6,
            "new_name": "Person",
        })
        output = format_output(response["result"], "plain")

        assert output == """\
Renamed in 1 file(s):
  main.py"""

        # Revert the rename
        run_request("rename", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 25,
            "column": 6,
            "new_name": "User",
        })

    def test_print_definition(self, workspace):
        response = run_request("print-definition", {
            "path": str(workspace / "main.py"),
            "workspace_root": str(workspace),
            "line": 128,
            "column": 11,
        })
        output = format_output(response["result"], "plain")

        assert output == """\
main.py:111-113

def create_sample_user() -> User:
    \"\"\"Create a sample user for testing.\"\"\"
    return User(name="John Doe", email="john@example.com", age=30)"""


# =============================================================================
# Go Integration Tests (gopls)
# =============================================================================


class TestGoIntegration:
    """Integration tests for Go using gopls."""

    @pytest.fixture(autouse=True)
    def check_gopls(self):
        requires_gopls()

    @pytest.fixture(scope="class")
    def project(self, class_temp_dir):
        src = FIXTURES_DIR / "go_project"
        dst = class_temp_dir / "go_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def workspace(self, project, class_daemon, class_isolated_config):
        config = load_config()
        add_workspace_root(project, config)
        run_request("list-symbols", {
            "path": str(project / "main.go"),
            "workspace_root": str(project),
        })
        time.sleep(1.0)
        return project

    def test_grep_document_symbols(self, workspace):
        response = run_request("list-symbols", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")

        assert output == """\
main.go:9 [Struct] User (struct{...})
main.go:10 [Field] Name (string) in User
main.go:11 [Field] Email (string) in User
main.go:12 [Field] Age (int) in User
main.go:16 [Function] NewUser (func(name, email string, age int) *User)
main.go:21 [Method] (*User).IsAdult (func() bool)
main.go:26 [Method] (*User).DisplayName (func() string)
main.go:31 [Interface] Storage (interface{...})
main.go:32 [Method] Save (func(user *User) error) in Storage
main.go:33 [Method] Load (func(email string) (*User, error)) in Storage
main.go:34 [Method] Delete (func(email string) error) in Storage
main.go:35 [Method] List (func() ([]*User, error)) in Storage
main.go:39 [Struct] MemoryStorage (struct{...})
main.go:40 [Field] users (map[string]*User) in MemoryStorage
main.go:44 [Function] NewMemoryStorage (func() *MemoryStorage)
main.go:49 [Method] (*MemoryStorage).Save (func(user *User) error)
main.go:58 [Method] (*MemoryStorage).Load (func(email string) (*User, error))
main.go:67 [Method] (*MemoryStorage).Delete (func(email string) error)
main.go:76 [Method] (*MemoryStorage).List (func() ([]*User, error))
main.go:85 [Struct] FileStorage (struct{...})
main.go:86 [Field] basePath (string) in FileStorage
main.go:90 [Function] NewFileStorage (func(basePath string) *FileStorage)
main.go:95 [Method] (*FileStorage).Save (func(user *User) error)
main.go:101 [Method] (*FileStorage).Load (func(email string) (*User, error))
main.go:107 [Method] (*FileStorage).Delete (func(email string) error)
main.go:113 [Method] (*FileStorage).List (func() ([]*User, error))
main.go:119 [Struct] UserRepository (struct{...})
main.go:120 [Field] storage (Storage) in UserRepository
main.go:124 [Function] NewUserRepository (func(storage Storage) *UserRepository)
main.go:129 [Method] (*UserRepository).AddUser (func(user *User) error)
main.go:134 [Method] (*UserRepository).GetUser (func(email string) (*User, error))
main.go:139 [Method] (*UserRepository).DeleteUser (func(email string) error)
main.go:144 [Method] (*UserRepository).ListUsers (func() ([]*User, error))
main.go:149 [Function] createSampleUser (func() *User)
main.go:154 [Interface] Validator (interface{...})
main.go:155 [Method] Validate (func() error) in Validator
main.go:159 [Function] ValidateUser (func(user *User) error)
main.go:172 [Function] main (func())"""

    def test_find_definition(self, workspace):
        # Line 174: "repo := NewUserRepository(storage)", column 9 is start of "NewUserRepository"
        os.chdir(workspace)
        response = run_request("find-definition", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 174,
            "column": 9,
            "context": 0,
        })
        output = format_output(response["result"], "plain")

        assert output == "main.go:124 func NewUserRepository(storage Storage) *UserRepository {"

    def test_find_references(self, workspace):
        os.chdir(workspace)
        response = run_request("find-references", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 9,
            "column": 5,
            "context": 0,
        })
        output = format_output(response["result"], "plain")

        assert output == """\
main.go:9 type User struct {
main.go:16 func NewUser(name, email string, age int) *User {
main.go:17 \treturn &User{Name: name, Email: email, Age: age}
main.go:21 func (u *User) IsAdult() bool {
main.go:26 func (u *User) DisplayName() string {
main.go:32 \tSave(user *User) error
main.go:33 \tLoad(email string) (*User, error)
main.go:35 \tList() ([]*User, error)
main.go:40 \tusers map[string]*User
main.go:45 \treturn &MemoryStorage{users: make(map[string]*User)}
main.go:49 func (m *MemoryStorage) Save(user *User) error {
main.go:58 func (m *MemoryStorage) Load(email string) (*User, error) {
main.go:76 func (m *MemoryStorage) List() ([]*User, error) {
main.go:77 \tresult := make([]*User, 0, len(m.users))
main.go:95 func (f *FileStorage) Save(user *User) error {
main.go:101 func (f *FileStorage) Load(email string) (*User, error) {
main.go:113 func (f *FileStorage) List() ([]*User, error) {
main.go:129 func (r *UserRepository) AddUser(user *User) error {
main.go:134 func (r *UserRepository) GetUser(email string) (*User, error) {
main.go:144 func (r *UserRepository) ListUsers() ([]*User, error) {
main.go:149 func createSampleUser() *User {
main.go:159 func ValidateUser(user *User) error {"""

    def test_find_implementations(self, workspace):
        os.chdir(workspace)
        response = run_request("find-implementations", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 31,
            "column": 5,
            "context": 0,
        })
        output = format_output(response["result"], "plain")

        assert output == """\
main.go:39 type MemoryStorage struct {
main.go:85 type FileStorage struct {"""

    def test_describe_hover(self, workspace):
        response = run_request("describe", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 9,
            "column": 5,
        })
        output = format_output(response["result"], "plain")

        assert output == """\
```go
type User struct { // size=40 (0x28), class=48 (0x30)
\tName  string
\tEmail string
\tAge   int
}
```

---

User represents a user in the system.


```go
func (u *User) DisplayName() string
func (u *User) IsAdult() bool
```"""

    def test_rename(self, workspace):
        response = run_request("rename", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 9,
            "column": 5,
            "new_name": "Person",
        })
        output = format_output(response["result"], "plain")

        assert output == """\
Renamed in 1 file(s):
  main.go"""

        # Revert the rename
        run_request("rename", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 9,
            "column": 5,
            "new_name": "User",
        })

    def test_print_definition(self, workspace):
        response = run_request("print-definition", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
            "line": 174,
            "column": 9,
        })
        output = format_output(response["result"], "plain")

        assert output == """\
main.go:124-126

func NewUserRepository(storage Storage) *UserRepository {
\treturn &UserRepository{storage: storage}
}"""


# =============================================================================
# Rust Integration Tests (rust-analyzer)
# =============================================================================


class TestRustIntegration:
    """Integration tests for Rust using rust-analyzer."""

    @pytest.fixture(autouse=True)
    def check_rust_analyzer(self):
        requires_rust_analyzer()

    @pytest.fixture(scope="class")
    def project(self, class_temp_dir):
        src = FIXTURES_DIR / "rust_project"
        dst = class_temp_dir / "rust_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def workspace(self, project, class_daemon, class_isolated_config):
        config = load_config()
        add_workspace_root(project, config)
        # rust-analyzer needs more time to fully index
        for f in ["main.rs", "user.rs", "storage.rs"]:
            run_request("list-symbols", {
                "path": str(project / "src" / f),
                "workspace_root": str(project),
            })
        time.sleep(4.0)
        return project

    def test_grep_document_symbols_user(self, workspace):
        response = run_request("list-symbols", {
            "path": str(workspace / "src" / "user.rs"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")

        assert output == """\
src/user.rs:3 [Struct] User
src/user.rs:6 [Field] name (String) in User
src/user.rs:7 [Field] email (String) in User
src/user.rs:8 [Field] age (u32) in User
src/user.rs:11 [Object] impl User
src/user.rs:12 [Function] new (fn(name: String, email: String, age: u32) -> Self) in impl User
src/user.rs:17 [Method] name (fn(&self) -> &str) in impl User
src/user.rs:22 [Method] email (fn(&self) -> &str) in impl User
src/user.rs:27 [Method] age (fn(&self) -> u32) in impl User
src/user.rs:32 [Method] is_adult (fn(&self) -> bool) in impl User
src/user.rs:37 [Method] display_name (fn(&self) -> String) in impl User
src/user.rs:43 [Struct] UserRepository
src/user.rs:45 [Field] storage (S) in UserRepository
src/user.rs:48 [Object] impl UserRepository<S>
src/user.rs:49 [Function] new (fn(storage: S) -> Self) in impl UserRepository<S>
src/user.rs:54 [Method] add_user (fn(&mut self, user: User)) in impl UserRepository<S>
src/user.rs:59 [Method] get_user (fn(&self, email: &str) -> Option<&User>) in impl UserRepository<S>
src/user.rs:64 [Method] delete_user (fn(&mut self, email: &str) -> bool) in impl UserRepository<S>
src/user.rs:69 [Method] list_users (fn(&self) -> Vec<&User>) in impl UserRepository<S>
src/user.rs:74 [Method] count (fn(&self) -> usize) in impl UserRepository<S>
src/user.rs:80 [Function] validate_user (fn(user: &User) -> Result<(), String>)"""

    def test_grep_document_symbols_storage(self, workspace):
        response = run_request("list-symbols", {
            "path": str(workspace / "src" / "storage.rs"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")

        assert output == """\
src/storage.rs:4 [Interface] Storage
src/storage.rs:6 [Method] save (fn(&mut self, key: String, user: User)) in Storage
src/storage.rs:9 [Method] load (fn(&self, key: &str) -> Option<&User>) in Storage
src/storage.rs:12 [Method] delete (fn(&mut self, key: &str) -> bool) in Storage
src/storage.rs:15 [Method] list (fn(&self) -> Vec<&User>) in Storage
src/storage.rs:19 [Struct] MemoryStorage
src/storage.rs:21 [Field] users (HashMap<String, User>) in MemoryStorage
src/storage.rs:24 [Object] impl MemoryStorage
src/storage.rs:25 [Function] new (fn() -> Self) in impl MemoryStorage
src/storage.rs:33 [Object] impl Default for MemoryStorage
src/storage.rs:34 [Function] default (fn() -> Self) in impl Default for MemoryStorage
src/storage.rs:39 [Object] impl Storage for MemoryStorage
src/storage.rs:40 [Method] save (fn(&mut self, key: String, user: User)) in impl Storage for MemoryStorage
src/storage.rs:44 [Method] load (fn(&self, key: &str) -> Option<&User>) in impl Storage for MemoryStorage
src/storage.rs:48 [Method] delete (fn(&mut self, key: &str) -> bool) in impl Storage for MemoryStorage
src/storage.rs:52 [Method] list (fn(&self) -> Vec<&User>) in impl Storage for MemoryStorage
src/storage.rs:57 [Struct] FileStorage
src/storage.rs:59 [Field] base_path (String) in FileStorage
src/storage.rs:60 [Field] cache (HashMap<String, User>) in FileStorage
src/storage.rs:63 [Object] impl FileStorage
src/storage.rs:64 [Function] new (fn(base_path: String) -> Self) in impl FileStorage
src/storage.rs:72 [Method] base_path (fn(&self) -> &str) in impl FileStorage
src/storage.rs:78 [Object] impl Storage for FileStorage
src/storage.rs:79 [Method] save (fn(&mut self, key: String, user: User)) in impl Storage for FileStorage
src/storage.rs:84 [Method] load (fn(&self, key: &str) -> Option<&User>) in impl Storage for FileStorage
src/storage.rs:88 [Method] delete (fn(&mut self, key: &str) -> bool) in impl Storage for FileStorage
src/storage.rs:92 [Method] list (fn(&self) -> Vec<&User>) in impl Storage for FileStorage"""

    def test_find_definition(self, workspace):
        # Line 23: "let user = create_sample_user();", column 16 is start of "create_sample_user"
        os.chdir(workspace)
        response = run_request("find-definition", {
            "path": str(workspace / "src" / "main.rs"),
            "workspace_root": str(workspace),
            "line": 23,
            "column": 16,
            "context": 0,
        })
        output = format_output(response["result"], "plain")

        assert output == "src/main.rs:8 fn create_sample_user() -> User {"

    def test_find_references(self, workspace):
        # Line 8: "fn create_sample_user() -> User {"
        os.chdir(workspace)
        response = run_request("find-references", {
            "path": str(workspace / "src" / "main.rs"),
            "workspace_root": str(workspace),
            "line": 8,
            "column": 3,
            "context": 0,
        })
        output = format_output(response["result"], "plain")

        assert output == """\
src/main.rs:23     let user = create_sample_user();
src/main.rs:8 fn create_sample_user() -> User {"""

    def test_print_definition(self, workspace):
        response = run_request("print-definition", {
            "path": str(workspace / "src" / "main.rs"),
            "workspace_root": str(workspace),
            "line": 10,
            "column": 15,
        })
        output = format_output(response["result"], "plain")

        assert output == """\
src/main.rs:15-17

fn create_sample_user() -> User {
    User::new("John Doe".to_string(), "john@example.com".to_string(), 30)
}"""


# =============================================================================
# TypeScript Integration Tests (typescript-language-server)
# =============================================================================


class TestTypeScriptIntegration:
    """Integration tests for TypeScript using typescript-language-server."""

    @pytest.fixture(autouse=True)
    def check_typescript_lsp(self):
        requires_typescript_lsp()

    @pytest.fixture(scope="class")
    def project(self, class_temp_dir):
        src = FIXTURES_DIR / "typescript_project"
        dst = class_temp_dir / "typescript_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def workspace(self, project, class_daemon, class_isolated_config):
        config = load_config()
        add_workspace_root(project, config)
        run_request("list-symbols", {
            "path": str(project / "src" / "main.ts"),
            "workspace_root": str(project),
        })
        time.sleep(1.0)
        return project

    def test_grep_document_symbols(self, workspace):
        response = run_request("list-symbols", {
            "path": str(workspace / "src" / "user.ts"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")

        assert output == """\
src/user.ts:4 [Class] User
src/user.ts:5 [Constructor] constructor in User
src/user.ts:13 [Method] isAdult in User
src/user.ts:20 [Method] displayName in User
src/user.ts:28 [Interface] Storage
src/user.ts:29 [Method] save in Storage
src/user.ts:30 [Method] load in Storage
src/user.ts:31 [Method] delete in Storage
src/user.ts:32 [Method] list in Storage
src/user.ts:38 [Class] MemoryStorage
src/user.ts:39 [Property] users in MemoryStorage
src/user.ts:41 [Method] save in MemoryStorage
src/user.ts:45 [Method] load in MemoryStorage
src/user.ts:49 [Method] delete in MemoryStorage
src/user.ts:53 [Method] list in MemoryStorage
src/user.ts:61 [Class] FileStorage
src/user.ts:62 [Property] cache in FileStorage
src/user.ts:64 [Constructor] constructor in FileStorage
src/user.ts:66 [Method] getBasePath in FileStorage
src/user.ts:70 [Method] save in FileStorage
src/user.ts:75 [Method] load in FileStorage
src/user.ts:79 [Method] delete in FileStorage
src/user.ts:83 [Method] list in FileStorage
src/user.ts:91 [Class] UserRepository
src/user.ts:92 [Constructor] constructor in UserRepository
src/user.ts:94 [Method] addUser in UserRepository
src/user.ts:98 [Method] getUser in UserRepository
src/user.ts:102 [Method] deleteUser in UserRepository
src/user.ts:106 [Method] listUsers in UserRepository
src/user.ts:110 [Method] countUsers in UserRepository
src/user.ts:118 [Function] validateUser"""

    def test_find_definition(self, workspace):
        response = run_request("find-definition", {
            "path": str(workspace / "src" / "main.ts"),
            "workspace_root": str(workspace),
            "line": 16,
            "column": 17,
            "context": 0,
        })
        output = format_output(response["result"], "plain")

        assert output == "src/main.ts:3 function createSampleUser(): User {"

    def test_find_references(self, workspace):
        response = run_request("find-references", {
            "path": str(workspace / "src" / "user.ts"),
            "workspace_root": str(workspace),
            "line": 4,
            "column": 13,
            "context": 0,
        })
        output = format_output(response["result"], "plain")

        assert output == """\
src/user.ts:4 export class User {
src/user.ts:29     save(user: User): void;
src/user.ts:30     load(email: string): User | undefined;
src/user.ts:32     list(): User[];
src/user.ts:41     save(user: User): void {
src/user.ts:45     load(email: string): User | undefined {
src/user.ts:53     list(): User[] {
src/user.ts:70     save(user: User): void {
src/user.ts:75     load(email: string): User | undefined {
src/user.ts:83     list(): User[] {
src/user.ts:118 export function validateUser(user: User): string | null {
src/main.ts:1 import { User, MemoryStorage, UserRepository } from './user';
src/main.ts:3 function createSampleUser(): User {"""

    def test_find_implementations(self, workspace):
        response = run_request("find-implementations", {
            "path": str(workspace / "src" / "user.ts"),
            "workspace_root": str(workspace),
            "line": 28,
            "column": 17,
            "context": 0,
        })
        output = format_output(response["result"], "plain")

        assert output == """\
src/user.ts:38 export class MemoryStorage implements Storage {
src/user.ts:61 export class FileStorage implements Storage {"""

    def test_describe_hover(self, workspace):
        response = run_request("describe", {
            "path": str(workspace / "src" / "user.ts"),
            "workspace_root": str(workspace),
            "line": 4,
            "column": 13,
        })
        output = format_output(response["result"], "plain")

        assert output == """\
```typescript
class User
```
Represents a user in the system."""

    def test_print_definition(self, workspace):
        response = run_request("print-definition", {
            "path": str(workspace / "src" / "main.ts"),
            "workspace_root": str(workspace),
            "line": 16,
            "column": 17,
        })
        output = format_output(response["result"], "plain")

        assert output == """\
src/main.ts:3-5

function createSampleUser(): User {
    return new User("John Doe", "john@example.com", 30);
}"""


# =============================================================================
# Java Integration Tests (jdtls)
# =============================================================================


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
        run_request("list-symbols", {
            "path": str(project / "src" / "main" / "java" / "com" / "example" / "Main.java"),
            "workspace_root": str(project),
        })
        time.sleep(3.0)
        return project

    def test_grep_document_symbols(self, workspace):
        response = run_request("list-symbols", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "User.java"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")

        assert output == """\
src/main/java/com/example/User.java:3 [Class] User
src/main/java/com/example/User.java:4 [Field] name in User
src/main/java/com/example/User.java:5 [Field] email in User
src/main/java/com/example/User.java:6 [Field] age in User
src/main/java/com/example/User.java:8 [Constructor] User in User
src/main/java/com/example/User.java:14 [Method] getName in User
src/main/java/com/example/User.java:18 [Method] getEmail in User
src/main/java/com/example/User.java:22 [Method] getAge in User
src/main/java/com/example/User.java:26 [Method] isAdult in User
src/main/java/com/example/User.java:30 [Method] displayName in User"""

    def test_find_definition(self, workspace):
        response = run_request("find-definition", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "Main.java"),
            "workspace_root": str(workspace),
            "line": 9,
            "column": 28,
            "context": 0,
        })
        output = format_output(response["result"], "plain")

        assert output == "src/main/java/com/example/Main.java:18     public static User createSampleUser() {"

    def test_find_references(self, workspace):
        response = run_request("find-references", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "User.java"),
            "workspace_root": str(workspace),
            "line": 3,
            "column": 13,
            "context": 0,
        })
        output = format_output(response["result"], "plain")

        lines = output.split("\n")
        assert "src/main/java/com/example/User.java:3 public class User {" in lines

    def test_find_implementations(self, workspace):
        response = run_request("find-implementations", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "Storage.java"),
            "workspace_root": str(workspace),
            "line": 5,
            "column": 17,
            "context": 0,
        })
        output = format_output(response["result"], "plain")

        lines = output.split("\n")
        assert any("MemoryStorage" in line for line in lines)

    def test_describe_hover(self, workspace):
        response = run_request("describe", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "User.java"),
            "workspace_root": str(workspace),
            "line": 3,
            "column": 13,
        })
        result = response["result"]

        assert "contents" in result
        assert "User" in result["contents"]

    def test_print_definition(self, workspace):
        response = run_request("print-definition", {
            "path": str(workspace / "src" / "main" / "java" / "com" / "example" / "Main.java"),
            "workspace_root": str(workspace),
            "line": 9,
            "column": 28,
        })
        output = format_output(response["result"], "plain")

        assert "createSampleUser" in output
        assert "return new User" in output


# =============================================================================
# Multi-Language Project Tests
# =============================================================================


class TestMultiLanguageIntegration:
    """Integration tests for multi-language projects."""

    @pytest.fixture(scope="class")
    def project(self, class_temp_dir):
        src = FIXTURES_DIR / "multi_language_project"
        dst = class_temp_dir / "multi_language_project"
        shutil.copytree(src, dst)
        return dst

    @pytest.fixture(scope="class")
    def workspace(self, project, class_daemon, class_isolated_config):
        config = load_config()
        add_workspace_root(project, config)
        return project

    def test_python_symbols(self, workspace):
        requires_pyright()

        run_request("list-symbols", {
            "path": str(workspace / "app.py"),
            "workspace_root": str(workspace),
        })
        time.sleep(0.5)

        response = run_request("list-symbols", {
            "path": str(workspace / "app.py"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")

        assert output == """\
app.py:10 [Class] ServiceProtocol
app.py:14 [Method] greet in ServiceProtocol
app.py:20 [Class] PythonUser
app.py:27 [Class] PythonService
app.py:30 [Method] __init__ in PythonService
app.py:38 [Method] greet in PythonService
app.py:42 [Method] add_user in PythonService
app.py:46 [Method] get_users in PythonService
app.py:51 [Function] create_service
app.py:62 [Function] validate_email"""

    def test_go_symbols(self, workspace):
        requires_gopls()

        run_request("list-symbols", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
        })
        time.sleep(0.5)

        response = run_request("list-symbols", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
        })
        output = format_output(response["result"], "plain")

        assert output == """\
main.go:6 [Struct] GoUser
main.go:7 [Field] Name in GoUser
main.go:8 [Field] Email in GoUser
main.go:12 [Struct] GoService
main.go:13 [Field] Name in GoService
main.go:14 [Field] users in GoService
main.go:18 [Function] NewGoService
main.go:26 [Method] Greet in GoService
main.go:31 [Method] AddUser in GoService
main.go:36 [Method] GetUsers in GoService
main.go:43 [Interface] Servicer
main.go:44 [Method] Greet in Servicer
main.go:48 [Function] CreateService
main.go:53 [Function] ValidateEmail
main.go:63 [Function] main"""

    def test_both_languages_in_same_workspace(self, workspace):
        requires_pyright()
        requires_gopls()

        # Python
        py_response = run_request("list-symbols", {
            "path": str(workspace / "app.py"),
            "workspace_root": str(workspace),
        })
        py_symbols = py_response["result"]
        py_names = [s["name"] for s in py_symbols]
        assert "PythonService" in py_names
        assert "PythonUser" in py_names

        # Go
        go_response = run_request("list-symbols", {
            "path": str(workspace / "main.go"),
            "workspace_root": str(workspace),
        })
        go_symbols = go_response["result"]
        go_names = [s["name"] for s in go_symbols]
        assert "GoService" in go_names
        assert "GoUser" in go_names
