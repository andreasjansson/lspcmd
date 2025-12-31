"""Unit tests for symbol disambiguation logic.

The disambiguation algorithm must ensure that:
1. Each suggested reference in an ambiguous error is itself unambiguous
2. When a user types a suggested reference, it resolves to exactly one symbol
3. The suggested references use minimal qualification (prefer shorter refs)
"""

import pytest
from lspcmd.daemon.mcp_server import MCPDaemonServer


class TestGenerateUnambiguousRef:
    """Tests for _generate_unambiguous_ref method."""

    def setup_method(self):
        # Create a minimal server instance just to test the methods
        # We'll call the methods directly without starting the server
        self.server = MCPDaemonServer.__new__(MCPDaemonServer)

    def test_unique_container_sufficient(self):
        """When container.name is unique, use that."""
        matches = [
            {"path": "a.py", "line": 10, "name": "save", "kind": "Function", "container": "UserRepo"},
            {"path": "b.py", "line": 20, "name": "save", "kind": "Function", "container": "FileRepo"},
        ]
        
        ref1 = self.server._generate_unambiguous_ref(matches[0], matches, "save")
        ref2 = self.server._generate_unambiguous_ref(matches[1], matches, "save")
        
        assert ref1 == "UserRepo.save"
        assert ref2 == "FileRepo.save"
        # Both refs must be different
        assert ref1 != ref2

    def test_unique_filename_sufficient(self):
        """When filename:name is unique, use that."""
        matches = [
            {"path": "user.py", "line": 10, "name": "validate", "kind": "Function", "container": ""},
            {"path": "order.py", "line": 20, "name": "validate", "kind": "Function", "container": ""},
        ]
        
        ref1 = self.server._generate_unambiguous_ref(matches[0], matches, "validate")
        ref2 = self.server._generate_unambiguous_ref(matches[1], matches, "validate")
        
        assert ref1 == "user.py:validate"
        assert ref2 == "order.py:validate"
        assert ref1 != ref2

    def test_same_filename_different_containers(self):
        """When same filename but different containers, use container.name."""
        matches = [
            {"path": "main.py", "line": 10, "name": "run", "kind": "Function", "container": "Server"},
            {"path": "main.py", "line": 50, "name": "run", "kind": "Function", "container": "Client"},
        ]
        
        ref1 = self.server._generate_unambiguous_ref(matches[0], matches, "run")
        ref2 = self.server._generate_unambiguous_ref(matches[1], matches, "run")
        
        assert ref1 == "Server.run"
        assert ref2 == "Client.run"
        assert ref1 != ref2

    def test_same_container_different_files(self):
        """When same container but different files, use filename:container.name."""
        matches = [
            {"path": "v1/api.py", "line": 10, "name": "handle", "kind": "Function", "container": "Handler"},
            {"path": "v2/api.py", "line": 10, "name": "handle", "kind": "Function", "container": "Handler"},
        ]
        
        ref1 = self.server._generate_unambiguous_ref(matches[0], matches, "handle")
        ref2 = self.server._generate_unambiguous_ref(matches[1], matches, "handle")
        
        # Both have same container "Handler" and same filename "api.py"
        # Need to use path to disambiguate
        assert "v1" in ref1 or ref1.startswith("api.py:10:")
        assert "v2" in ref2 or ref2.startswith("api.py:10:")
        assert ref1 != ref2

    def test_overloaded_methods_same_container(self):
        """Overloaded methods with same name and container need line numbers."""
        matches = [
            {"path": "user.py", "line": 10, "name": "save", "kind": "Function", "container": "Repo"},
            {"path": "user.py", "line": 25, "name": "save", "kind": "Function", "container": "Repo"},
        ]
        
        ref1 = self.server._generate_unambiguous_ref(matches[0], matches, "save")
        ref2 = self.server._generate_unambiguous_ref(matches[1], matches, "save")
        
        # Same file, same container - need line number
        assert ":10:" in ref1
        assert ":25:" in ref2
        assert ref1 != ref2

    def test_no_container_different_files(self):
        """Top-level symbols without container use filename:name."""
        matches = [
            {"path": "utils.py", "line": 5, "name": "log", "kind": "Function", "container": ""},
            {"path": "helpers.py", "line": 3, "name": "log", "kind": "Function", "container": ""},
        ]
        
        ref1 = self.server._generate_unambiguous_ref(matches[0], matches, "log")
        ref2 = self.server._generate_unambiguous_ref(matches[1], matches, "log")
        
        assert ref1 == "utils.py:log"
        assert ref2 == "helpers.py:log"
        assert ref1 != ref2

    def test_no_container_same_file(self):
        """Multiple top-level symbols in same file need line numbers."""
        matches = [
            {"path": "config.py", "line": 10, "name": "DEBUG", "kind": "Variable", "container": ""},
            {"path": "config.py", "line": 50, "name": "DEBUG", "kind": "Variable", "container": ""},
        ]
        
        ref1 = self.server._generate_unambiguous_ref(matches[0], matches, "DEBUG")
        ref2 = self.server._generate_unambiguous_ref(matches[1], matches, "DEBUG")
        
        assert ":10:" in ref1
        assert ":50:" in ref2
        assert ref1 != ref2

    def test_nested_containers(self):
        """Nested containers should use the immediate container."""
        matches = [
            {"path": "a.py", "line": 10, "name": "method", "kind": "Function", "container": "OuterA.Inner"},
            {"path": "b.py", "line": 20, "name": "method", "kind": "Function", "container": "OuterB.Inner"},
        ]
        
        ref1 = self.server._generate_unambiguous_ref(matches[0], matches, "method")
        ref2 = self.server._generate_unambiguous_ref(matches[1], matches, "method")
        
        # Containers are different (OuterA.Inner vs OuterB.Inner)
        assert ref1 != ref2
        # Should use full container path since "Inner.method" would be ambiguous
        assert "OuterA" in ref1 or "a.py" in ref1
        assert "OuterB" in ref2 or "b.py" in ref2

    def test_module_name_collision_with_container(self):
        """Module name 'main' shouldn't collide with container 'main'."""
        matches = [
            # Container is literally 'main' (a function/class called main)
            {"path": "split_lsp_spec.py", "line": 108, "name": "f", "kind": "Variable", "container": "main"},
            # Container is 'save' but file is main.py (module name = main)
            {"path": "main.py", "line": 69, "name": "f", "kind": "Variable", "container": "save"},
            # Container is 'load' but file is main.py (module name = main)  
            {"path": "main.py", "line": 75, "name": "f", "kind": "Variable", "container": "load"},
        ]
        
        ref1 = self.server._generate_unambiguous_ref(matches[0], matches, "f")
        ref2 = self.server._generate_unambiguous_ref(matches[1], matches, "f")
        ref3 = self.server._generate_unambiguous_ref(matches[2], matches, "f")
        
        # All refs must be unique
        refs = [ref1, ref2, ref3]
        assert len(set(refs)) == 3, f"Refs not unique: {refs}"
        
        # Each ref should be parseable and unambiguous
        # main.f should NOT match multiple things
        # save.f and load.f are unambiguous containers
        assert ref2 == "save.f"
        assert ref3 == "load.f"
        # ref1 needs to be different from "main.f" if that would be ambiguous
        # It could be "split_lsp_spec.py:main.f" or just "main.f" if module matching is disabled

    def test_go_style_method_receivers(self):
        """Go methods like (*Type).Method should disambiguate correctly."""
        matches = [
            {"path": "storage.go", "line": 10, "name": "(*MemoryStorage).Save", "kind": "Method", "container": ""},
            {"path": "storage.go", "line": 50, "name": "(*FileStorage).Save", "kind": "Method", "container": ""},
        ]
        
        ref1 = self.server._generate_unambiguous_ref(matches[0], matches, "Save")
        ref2 = self.server._generate_unambiguous_ref(matches[1], matches, "Save")
        
        # Should use the receiver type to disambiguate
        assert "MemoryStorage" in ref1
        assert "FileStorage" in ref2
        assert ref1 != ref2

    def test_java_method_signatures(self):
        """Java methods with signatures like save(User) should normalize."""
        matches = [
            {"path": "Repo.java", "line": 10, "name": "save(User)", "kind": "Method", "container": "UserRepo"},
            {"path": "Repo.java", "line": 30, "name": "save(Order)", "kind": "Method", "container": "OrderRepo"},
        ]
        
        ref1 = self.server._generate_unambiguous_ref(matches[0], matches, "save")
        ref2 = self.server._generate_unambiguous_ref(matches[1], matches, "save")
        
        # Should use container to disambiguate (normalized name is "save")
        assert "UserRepo" in ref1
        assert "OrderRepo" in ref2
        assert ref1 != ref2

    def test_single_match_returns_simple_ref(self):
        """When there's only one match, ref can be simple."""
        matches = [
            {"path": "user.py", "line": 10, "name": "User", "kind": "Class", "container": ""},
        ]
        
        ref = self.server._generate_unambiguous_ref(matches[0], matches, "User")
        # For single match, any ref works - prefer simplest
        assert ref in ["User", "user.py:User"]


class TestAllRefsUnique:
    """Test that all generated refs for a match set are unique."""

    def setup_method(self):
        self.server = MCPServer.__new__(MCPServer)

    def _get_all_refs(self, matches, target_name):
        """Generate refs for all matches and return them."""
        return [
            self.server._generate_unambiguous_ref(m, matches, target_name)
            for m in matches
        ]

    def test_many_matches_all_unique(self):
        """When there are many matches, all refs must still be unique."""
        matches = [
            {"path": "a.py", "line": 1, "name": "f", "kind": "Variable", "container": "func1"},
            {"path": "a.py", "line": 2, "name": "f", "kind": "Variable", "container": "func2"},
            {"path": "b.py", "line": 1, "name": "f", "kind": "Variable", "container": "func1"},
            {"path": "b.py", "line": 2, "name": "f", "kind": "Variable", "container": "func2"},
            {"path": "c.py", "line": 1, "name": "f", "kind": "Variable", "container": ""},
            {"path": "c.py", "line": 2, "name": "f", "kind": "Variable", "container": ""},
        ]
        
        refs = self._get_all_refs(matches, "f")
        
        # All refs must be unique
        assert len(set(refs)) == len(matches), f"Duplicate refs found: {refs}"

    def test_complex_real_world_scenario(self):
        """Simulate a real scenario with mixed containers and files."""
        matches = [
            {"path": "src/models/user.py", "line": 10, "name": "save", "kind": "Method", "container": "User"},
            {"path": "src/models/user.py", "line": 50, "name": "save", "kind": "Method", "container": "UserProfile"},
            {"path": "src/models/order.py", "line": 15, "name": "save", "kind": "Method", "container": "Order"},
            {"path": "src/repos/user_repo.py", "line": 20, "name": "save", "kind": "Method", "container": "UserRepo"},
            {"path": "src/repos/user_repo.py", "line": 60, "name": "save", "kind": "Method", "container": "UserRepo"},  # overload
            {"path": "tests/test_user.py", "line": 30, "name": "save", "kind": "Function", "container": ""},
        ]
        
        refs = self._get_all_refs(matches, "save")
        
        # All refs must be unique
        assert len(set(refs)) == len(matches), f"Duplicate refs found: {refs}"
        
        # Verify some expected patterns
        # User.save and UserProfile.save should be distinguishable by container
        user_ref = refs[0]
        profile_ref = refs[1]
        assert user_ref != profile_ref
        
        # The two UserRepo.save methods need line numbers
        repo_ref1 = refs[3]
        repo_ref2 = refs[4]
        assert repo_ref1 != repo_ref2
        assert ":20:" in repo_ref1 or ":60:" in repo_ref2


class TestResolveSymbolRoundTrip:
    """Test that suggested refs actually resolve back to the correct symbol.
    
    This is the key invariant: if we suggest "Container.name" as a ref,
    then "lspcmd show Container.name" must resolve to that exact symbol.
    """

    def setup_method(self):
        self.server = MCPServer.__new__(MCPServer)

    def test_container_ref_resolves(self):
        """A Container.name ref should match only that container."""
        all_symbols = [
            {"path": "a.py", "line": 10, "name": "save", "kind": "Method", "container": "UserRepo"},
            {"path": "b.py", "line": 20, "name": "save", "kind": "Method", "container": "FileRepo"},
        ]
        
        # Generate refs
        ref1 = self.server._generate_unambiguous_ref(all_symbols[0], all_symbols, "save")
        
        # Now simulate resolving ref1
        # If ref1 is "UserRepo.save", it should match only all_symbols[0]
        if "." in ref1 and ":" not in ref1:
            container, name = ref1.rsplit(".", 1)
            matches = [
                s for s in all_symbols
                if s["name"] == name and self.server._get_effective_container(s) == container
            ]
            assert len(matches) == 1
            assert matches[0] == all_symbols[0]

    def test_filename_ref_resolves(self):
        """A filename:name ref should match only symbols in that file."""
        all_symbols = [
            {"path": "user.py", "line": 10, "name": "log", "kind": "Function", "container": ""},
            {"path": "order.py", "line": 20, "name": "log", "kind": "Function", "container": ""},
        ]
        
        ref1 = self.server._generate_unambiguous_ref(all_symbols[0], all_symbols, "log")
        
        # If ref1 is "user.py:log", it should match only all_symbols[0]
        if ":" in ref1 and ref1.count(":") == 1:
            filename, name = ref1.split(":")
            from pathlib import Path
            matches = [
                s for s in all_symbols
                if Path(s["path"]).name == filename and s["name"] == name
            ]
            assert len(matches) == 1
            assert matches[0] == all_symbols[0]
