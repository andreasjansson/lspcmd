"""Unit tests for symbol disambiguation logic.

The disambiguation algorithm must ensure that:
1. Each suggested reference in an ambiguous error is itself unambiguous
2. When a user types a suggested reference, it resolves to exactly one symbol
3. The suggested references use minimal qualification (prefer shorter refs)

The KEY INVARIANT: for every ref we suggest, resolving that ref must return
exactly the symbol we generated it for. This is tested in TestRoundTripConsistency.
"""

import pytest
from lspcmd.daemon.server import DaemonServer


class TestRoundTripConsistency:
    """The critical invariant: suggested refs must resolve back to exactly one symbol.
    
    This tests the exact bug reported: when `main.f` is suggested but resolving
    `main.f` returns multiple matches because it also matches files named main.py.
    """

    def setup_method(self):
        self.server = MCPDaemonServer.__new__(MCPDaemonServer)

    def _resolve_ref(self, ref: str, all_symbols: list[dict]) -> list[dict]:
        """Simulate resolving a ref against a symbol list.
        
        This must match the logic in _handle_resolve_symbol, including
        module name matching (main.f matches f in main.py).
        """
        from pathlib import Path
        
        path_filter = None
        line_filter = None
        symbol_path = ref
        
        colon_count = ref.count(":")
        if colon_count == 2:
            path_filter, line_str, symbol_path = ref.split(":", 2)
            try:
                line_filter = int(line_str)
            except ValueError:
                # It's file:Container.name format
                symbol_path = f"{line_str}:{symbol_path}"
        elif colon_count == 1:
            path_filter, symbol_path = ref.split(":", 1)
        
        candidates = all_symbols
        
        # Apply path filter (filename match)
        if path_filter:
            candidates = [s for s in candidates if Path(s.get("path", "")).name == path_filter]
        
        # Apply line filter
        if line_filter is not None:
            candidates = [s for s in candidates if s.get("line") == line_filter]
        
        parts = symbol_path.split(".")
        target_name = parts[-1]
        
        # Match by name and container
        if len(parts) == 1:
            # Simple name - match any symbol with that name
            return [s for s in candidates 
                    if self.server._normalize_symbol_name(s.get("name", "")) == target_name]
        else:
            # Qualified name: Container.name
            container_str = ".".join(parts[:-1])
            matches = []
            for sym in candidates:
                sym_name = self.server._normalize_symbol_name(sym.get("name", ""))
                if sym_name != target_name:
                    continue
                
                sym_container = sym.get("container", "") or ""
                sym_container_normalized = self.server._normalize_container(sym_container)
                sym_path = sym.get("path", "")
                module_name = self.server._get_module_name(sym_path)
                full_container = f"{module_name}.{sym_container_normalized}" if sym_container_normalized else module_name
                
                # Match using same logic as _handle_resolve_symbol
                if sym_container_normalized == container_str:
                    matches.append(sym)
                elif sym_container == container_str:
                    matches.append(sym)
                elif full_container == container_str:
                    matches.append(sym)
                elif full_container.endswith(f".{container_str}"):
                    matches.append(sym)
                elif len(parts) == 2 and parts[0] == module_name:
                    # Module name matching: main.f matches f in main.py
                    matches.append(sym)
            return matches

    def test_main_f_bug(self):
        """Reproduce the exact bug: main.f suggested but resolves to 3 symbols."""
        all_symbols = [
            {"path": "split_lsp_spec.py", "line": 108, "name": "f", "kind": "Variable", "container": "main"},
            {"path": "main.py", "line": 69, "name": "f", "kind": "Variable", "container": "save"},
            {"path": "main.py", "line": 75, "name": "f", "kind": "Variable", "container": "load"},
        ]
        
        # Generate refs for each symbol
        refs = [self.server._generate_unambiguous_ref(s, all_symbols, "f") for s in all_symbols]
        
        # Each ref must be unique
        assert len(set(refs)) == len(refs), f"Duplicate refs: {refs}"
        
        # Each ref must resolve to exactly 1 symbol
        for i, ref in enumerate(refs):
            resolved = self._resolve_ref(ref, all_symbols)
            assert len(resolved) == 1, f"Ref '{ref}' resolved to {len(resolved)} symbols: {resolved}"
            assert resolved[0] == all_symbols[i], f"Ref '{ref}' resolved to wrong symbol"

    def test_same_container_name_different_meanings(self):
        """Container 'main' vs module name 'main' should not collide."""
        all_symbols = [
            # 'main' is literally a function/class container
            {"path": "app.py", "line": 10, "name": "x", "kind": "Variable", "container": "main"},
            # 'main' is the module name (file is main.py), but container is different
            {"path": "main.py", "line": 20, "name": "x", "kind": "Variable", "container": "setup"},
            {"path": "main.py", "line": 30, "name": "x", "kind": "Variable", "container": "cleanup"},
        ]
        
        refs = [self.server._generate_unambiguous_ref(s, all_symbols, "x") for s in all_symbols]
        
        assert len(set(refs)) == len(refs), f"Duplicate refs: {refs}"
        
        for i, ref in enumerate(refs):
            resolved = self._resolve_ref(ref, all_symbols)
            assert len(resolved) == 1, f"Ref '{ref}' resolved to {len(resolved)} symbols"
            assert resolved[0] == all_symbols[i]

    def test_all_refs_resolve_uniquely(self):
        """Generic test: any set of symbols should produce unique resolvable refs."""
        test_cases = [
            # Case 1: Same name, different containers
            [
                {"path": "a.py", "line": 1, "name": "save", "container": "UserRepo"},
                {"path": "b.py", "line": 2, "name": "save", "container": "FileRepo"},
            ],
            # Case 2: Same name, same container, different files
            [
                {"path": "v1/api.py", "line": 1, "name": "handle", "container": "Handler"},
                {"path": "v2/api.py", "line": 2, "name": "handle", "container": "Handler"},
            ],
            # Case 3: Same name, same container, same file (overloads)
            [
                {"path": "repo.py", "line": 10, "name": "save", "container": "Repo"},
                {"path": "repo.py", "line": 50, "name": "save", "container": "Repo"},
            ],
            # Case 4: No containers, different files
            [
                {"path": "utils.py", "line": 1, "name": "log", "container": ""},
                {"path": "helpers.py", "line": 1, "name": "log", "container": ""},
            ],
            # Case 5: Mixed containers and no containers
            [
                {"path": "a.py", "line": 1, "name": "run", "container": "Server"},
                {"path": "b.py", "line": 1, "name": "run", "container": ""},
                {"path": "c.py", "line": 1, "name": "run", "container": "Client"},
            ],
        ]
        
        for symbols in test_cases:
            refs = [self.server._generate_unambiguous_ref(s, symbols, s["name"]) for s in symbols]
            
            # All refs unique
            assert len(set(refs)) == len(refs), f"Duplicate refs {refs} for {symbols}"
            
            # Each ref resolves to exactly the right symbol
            for i, ref in enumerate(refs):
                resolved = self._resolve_ref(ref, symbols)
                assert len(resolved) == 1, f"Ref '{ref}' resolved to {len(resolved)}: {resolved}"


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
        """When same container but different files with same name, use line numbers."""
        matches = [
            {"path": "v1/api.py", "line": 10, "name": "handle", "kind": "Function", "container": "Handler"},
            {"path": "v2/api.py", "line": 20, "name": "handle", "kind": "Function", "container": "Handler"},
        ]
        
        ref1 = self.server._generate_unambiguous_ref(matches[0], matches, "handle")
        ref2 = self.server._generate_unambiguous_ref(matches[1], matches, "handle")
        
        # Both have same container "Handler" and same filename "api.py"
        # With different lines, we can use line numbers to disambiguate
        assert ref1 != ref2
        # One should have :10: and the other :20:
        assert ":10:" in ref1 or ":20:" in ref2

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
        
        # Refs must be unique - could use receiver type or line numbers
        assert ref1 != ref2
        # Either uses receiver (MemoryStorage.Save) or line numbers (storage.go:10:Save)
        assert "MemoryStorage" in ref1 or ":10:" in ref1
        assert "FileStorage" in ref2 or ":50:" in ref2

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
        self.server = MCPDaemonServer.__new__(MCPDaemonServer)

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


class TestResolutionLogicMatchesGeneration:
    """Verify that the ACTUAL resolution code matches what we expect.
    
    This catches bugs where the unit test simulation doesn't match reality.
    """

    def setup_method(self):
        self.server = MCPDaemonServer.__new__(MCPDaemonServer)
        # Initialize minimal required attributes
        self.server.session = None  # Not needed for this test

    def test_module_name_matching_is_intentional(self):
        """Verify main.f DOES match symbols in main.py (module name matching).
        
        This is intentional behavior - main.f should match:
        1. Symbol f with container "main"
        2. Symbol f in file main.py (module name = main)
        
        The disambiguation algorithm must account for this!
        """
        from pathlib import Path
        
        # Simulate the resolution logic for "main.f"
        symbol_path = "main.f"
        parts = symbol_path.split(".")
        container_str = ".".join(parts[:-1])  # "main"
        target_name = parts[-1]  # "f"
        
        test_symbols = [
            {"path": "app.py", "line": 10, "name": "f", "container": "main"},
            {"path": "main.py", "line": 20, "name": "f", "container": "save"},
        ]
        
        matches = []
        for sym in test_symbols:
            sym_name = sym.get("name", "")
            if sym_name != target_name:
                continue
            
            sym_container = self.server._get_effective_container(sym)
            sym_container_normalized = self.server._normalize_container(sym_container)
            module_name = self.server._get_module_name(sym["path"])
            
            # Container matching
            if sym_container_normalized == container_str or sym_container == container_str:
                matches.append(sym)
            # Module name matching (this is the key feature!)
            elif len(parts) == 2 and parts[0] == module_name:
                matches.append(sym)
        
        # BOTH should match - that's the intended behavior
        # main.f matches "f in container main" AND "f in main.py"
        assert len(matches) == 2
        
        # This is why disambiguation must generate DIFFERENT refs for these!


class TestNormalizeSymbolName:
    """Tests for _normalize_symbol_name - extracts base name from decorated names."""

    def setup_method(self):
        self.server = MCPDaemonServer.__new__(MCPDaemonServer)

    def test_simple_name_unchanged(self):
        assert self.server._normalize_symbol_name("save") == "save"
        assert self.server._normalize_symbol_name("UserRepository") == "UserRepository"
        assert self.server._normalize_symbol_name("__init__") == "__init__"

    def test_java_method_signature(self):
        """Java methods like save(User) -> save"""
        assert self.server._normalize_symbol_name("save(User)") == "save"
        assert self.server._normalize_symbol_name("find(String, int)") == "find"
        assert self.server._normalize_symbol_name("process()") == "process"

    def test_go_pointer_receiver(self):
        """Go methods like (*Type).Method -> Method"""
        assert self.server._normalize_symbol_name("(*MemoryStorage).Save") == "Save"
        assert self.server._normalize_symbol_name("(*UserRepo).FindByID") == "FindByID"

    def test_go_value_receiver(self):
        """Go methods like (Type).Method -> Method"""
        assert self.server._normalize_symbol_name("(Config).Validate") == "Validate"
        assert self.server._normalize_symbol_name("(User).String") == "String"

    def test_mixed_patterns_no_match(self):
        """Names that look similar but don't match patterns stay unchanged."""
        # Not a valid Java signature (missing closing paren)
        assert self.server._normalize_symbol_name("save(User") == "save(User"
        # Not a valid Go receiver (no dot)
        assert self.server._normalize_symbol_name("(*Type)") == "(*Type)"


class TestGetEffectiveContainer:
    """Tests for _get_effective_container - extracts container from symbol."""

    def setup_method(self):
        self.server = MCPDaemonServer.__new__(MCPDaemonServer)

    def test_explicit_container(self):
        """When container field is set, use it."""
        sym = {"name": "save", "container": "UserRepo"}
        assert self.server._get_effective_container(sym) == "UserRepo"

    def test_no_container(self):
        """When no container, return empty string."""
        sym = {"name": "main", "container": ""}
        assert self.server._get_effective_container(sym) == ""
        sym = {"name": "main"}
        assert self.server._get_effective_container(sym) == ""

    def test_go_pointer_receiver_in_name(self):
        """Go methods embed receiver in name: (*Type).Method"""
        sym = {"name": "(*MemoryStorage).Save", "container": ""}
        assert self.server._get_effective_container(sym) == "MemoryStorage"

    def test_go_value_receiver_in_name(self):
        """Go methods with value receiver: (Type).Method"""
        sym = {"name": "(Config).Validate", "container": ""}
        assert self.server._get_effective_container(sym) == "Config"

    def test_rust_impl_block(self):
        """Rust impl blocks like 'impl Storage for MemoryStorage'"""
        sym = {"name": "save", "container": "impl Storage for MemoryStorage"}
        assert self.server._get_effective_container(sym) == "MemoryStorage"

    def test_rust_simple_impl(self):
        """Rust simple impl: 'impl MemoryStorage'"""
        sym = {"name": "new", "container": "impl MemoryStorage"}
        assert self.server._get_effective_container(sym) == "MemoryStorage"


class TestRefResolvesUniquely:
    """Tests for _ref_resolves_uniquely - the core disambiguation check."""

    def setup_method(self):
        self.server = MCPDaemonServer.__new__(MCPDaemonServer)

    def test_container_ref_unique(self):
        """Container.name ref is unique when containers differ."""
        symbols = [
            {"path": "a.py", "line": 1, "name": "save", "container": "UserRepo"},
            {"path": "b.py", "line": 1, "name": "save", "container": "FileRepo"},
        ]
        target = symbols[0]
        assert self.server._ref_resolves_uniquely("UserRepo.save", target, symbols)
        assert self.server._ref_resolves_uniquely("FileRepo.save", symbols[1], symbols)

    def test_container_ref_not_unique_module_collision(self):
        """Container.name is NOT unique when module name matches."""
        symbols = [
            {"path": "app.py", "line": 1, "name": "f", "container": "main"},  # container is "main"
            {"path": "main.py", "line": 1, "name": "f", "container": "other"},  # module is "main"
        ]
        # "main.f" matches BOTH - first via container, second via module name
        assert not self.server._ref_resolves_uniquely("main.f", symbols[0], symbols)

    def test_filename_ref_unique(self):
        """filename:name ref is unique when filenames differ."""
        symbols = [
            {"path": "user.py", "line": 1, "name": "validate", "container": ""},
            {"path": "order.py", "line": 1, "name": "validate", "container": ""},
        ]
        assert self.server._ref_resolves_uniquely("user.py:validate", symbols[0], symbols)
        assert self.server._ref_resolves_uniquely("order.py:validate", symbols[1], symbols)

    def test_filename_ref_not_unique_same_file(self):
        """filename:name is NOT unique when same filename."""
        symbols = [
            {"path": "utils.py", "line": 10, "name": "log", "container": ""},
            {"path": "utils.py", "line": 50, "name": "log", "container": ""},
        ]
        assert not self.server._ref_resolves_uniquely("utils.py:log", symbols[0], symbols)

    def test_line_ref_always_unique(self):
        """filename:line:name is always unique (assuming unique lines)."""
        symbols = [
            {"path": "utils.py", "line": 10, "name": "log", "container": ""},
            {"path": "utils.py", "line": 50, "name": "log", "container": ""},
        ]
        assert self.server._ref_resolves_uniquely("utils.py:10:log", symbols[0], symbols)
        assert self.server._ref_resolves_uniquely("utils.py:50:log", symbols[1], symbols)

    def test_go_effective_container(self):
        """Go methods use effective container from name."""
        symbols = [
            {"path": "storage.go", "line": 10, "name": "(*MemoryStorage).Save", "container": ""},
            {"path": "storage.go", "line": 50, "name": "(*FileStorage).Save", "container": ""},
        ]
        assert self.server._ref_resolves_uniquely("MemoryStorage.Save", symbols[0], symbols)
        assert self.server._ref_resolves_uniquely("FileStorage.Save", symbols[1], symbols)


class TestDisambiguationPreferenceOrder:
    """Test that disambiguation prefers shorter refs."""

    def setup_method(self):
        self.server = MCPDaemonServer.__new__(MCPDaemonServer)

    def test_prefers_container_over_filename(self):
        """When container is unique, prefer Container.name over file.py:name."""
        symbols = [
            {"path": "repos/user.py", "line": 10, "name": "save", "container": "UserRepo"},
            {"path": "repos/file.py", "line": 10, "name": "save", "container": "FileRepo"},
        ]
        ref1 = self.server._generate_unambiguous_ref(symbols[0], symbols, "save")
        ref2 = self.server._generate_unambiguous_ref(symbols[1], symbols, "save")
        
        # Should use container, not filename
        assert ref1 == "UserRepo.save"
        assert ref2 == "FileRepo.save"

    def test_prefers_filename_over_line_when_unique(self):
        """When filename is unique, prefer file.py:name over file.py:line:name."""
        symbols = [
            {"path": "user.py", "line": 10, "name": "validate", "container": ""},
            {"path": "order.py", "line": 20, "name": "validate", "container": ""},
        ]
        ref1 = self.server._generate_unambiguous_ref(symbols[0], symbols, "validate")
        
        # Should use filename:name, not filename:line:name
        assert ref1 == "user.py:validate"
        assert ":10:" not in ref1

    def test_falls_back_to_line_when_needed(self):
        """When nothing else works, use file.py:line:name."""
        symbols = [
            {"path": "config.py", "line": 10, "name": "DEBUG", "container": ""},
            {"path": "config.py", "line": 50, "name": "DEBUG", "container": ""},
        ]
        ref1 = self.server._generate_unambiguous_ref(symbols[0], symbols, "DEBUG")
        ref2 = self.server._generate_unambiguous_ref(symbols[1], symbols, "DEBUG")
        
        assert "config.py:10:DEBUG" == ref1
        assert "config.py:50:DEBUG" == ref2


class TestModuleNameCollisionHandling:
    """Test the specific bug: container name colliding with module name."""

    def setup_method(self):
        self.server = MCPDaemonServer.__new__(MCPDaemonServer)

    def test_avoids_ambiguous_container_ref(self):
        """When Container.name would match via module too, use file.py:name."""
        symbols = [
            # Container is literally "main"
            {"path": "split_lsp_spec.py", "line": 108, "name": "f", "container": "main"},
            # File is main.py, so module name is "main"
            {"path": "main.py", "line": 69, "name": "f", "container": "save"},
        ]
        
        ref1 = self.server._generate_unambiguous_ref(symbols[0], symbols, "f")
        ref2 = self.server._generate_unambiguous_ref(symbols[1], symbols, "f")
        
        # ref1 cannot be "main.f" because that also matches main.py
        assert ref1 != "main.f"
        # ref2 can be "save.f" because "save" is unique
        assert ref2 == "save.f"
        # ref1 should use filename to disambiguate
        assert "split_lsp_spec.py" in ref1

    def test_three_way_collision(self):
        """The exact bug case: f in main container + two f's in main.py."""
        symbols = [
            {"path": "split_lsp_spec.py", "line": 108, "name": "f", "container": "main"},
            {"path": "main.py", "line": 69, "name": "f", "container": "save"},
            {"path": "main.py", "line": 75, "name": "f", "container": "load"},
        ]
        
        refs = [self.server._generate_unambiguous_ref(s, symbols, "f") for s in symbols]
        
        # All refs must be unique
        assert len(set(refs)) == 3, f"Duplicate refs: {refs}"
        
        # save.f and load.f should work (unique containers)
        assert "save.f" in refs
        assert "load.f" in refs
        
        # The first one can't use main.f
        assert "main.f" not in refs

    def test_module_name_match_both_directions(self):
        """Test collision in both directions: module matches container and vice versa."""
        symbols = [
            {"path": "utils.py", "line": 10, "name": "helper", "container": "config"},
            {"path": "config.py", "line": 20, "name": "helper", "container": "utils"},
        ]
        
        refs = [self.server._generate_unambiguous_ref(s, symbols, "helper") for s in symbols]
        
        # Both "config.helper" and "utils.helper" are ambiguous!
        # config.helper matches: first (container=config) + second (module=config)
        # utils.helper matches: first (module=utils) + second (container=utils)
        assert len(set(refs)) == 2
        # Must use filenames
        assert "utils.py" in refs[0] or "config.py" in refs[0]


class TestGoMethodDisambiguation:
    """Test disambiguation for Go-style methods with receivers."""

    def setup_method(self):
        self.server = MCPDaemonServer.__new__(MCPDaemonServer)

    def test_go_methods_use_receiver_type(self):
        """Go methods (*Type).Method should disambiguate using Type."""
        symbols = [
            {"path": "storage.go", "line": 10, "name": "(*MemoryStorage).Save", "container": ""},
            {"path": "storage.go", "line": 50, "name": "(*FileStorage).Save", "container": ""},
        ]
        
        ref1 = self.server._generate_unambiguous_ref(symbols[0], symbols, "Save")
        ref2 = self.server._generate_unambiguous_ref(symbols[1], symbols, "Save")
        
        assert ref1 == "MemoryStorage.Save"
        assert ref2 == "FileStorage.Save"

    def test_go_interface_vs_implementations(self):
        """Interface method vs implementation methods."""
        symbols = [
            {"path": "main.go", "line": 32, "name": "Save", "container": "Storage"},  # interface
            {"path": "main.go", "line": 49, "name": "(*MemoryStorage).Save", "container": ""},
            {"path": "main.go", "line": 95, "name": "(*FileStorage).Save", "container": ""},
        ]
        
        refs = [self.server._generate_unambiguous_ref(s, symbols, "Save") for s in symbols]
        
        assert len(set(refs)) == 3
        assert "Storage.Save" in refs
        assert "MemoryStorage.Save" in refs
        assert "FileStorage.Save" in refs

    def test_go_value_receiver(self):
        """Go methods with value receiver (Type).Method."""
        symbols = [
            {"path": "types.go", "line": 10, "name": "(User).String", "container": ""},
            {"path": "types.go", "line": 20, "name": "(Config).String", "container": ""},
        ]
        
        ref1 = self.server._generate_unambiguous_ref(symbols[0], symbols, "String")
        ref2 = self.server._generate_unambiguous_ref(symbols[1], symbols, "String")
        
        assert ref1 == "User.String"
        assert ref2 == "Config.String"


class TestJavaMethodDisambiguation:
    """Test disambiguation for Java-style methods with signatures."""

    def setup_method(self):
        self.server = MCPDaemonServer.__new__(MCPDaemonServer)

    def test_java_overloaded_methods(self):
        """Java overloaded methods with different signatures."""
        symbols = [
            {"path": "UserRepo.java", "line": 10, "name": "save(User)", "container": "UserRepo"},
            {"path": "UserRepo.java", "line": 30, "name": "save(User, boolean)", "container": "UserRepo"},
        ]
        
        refs = [self.server._generate_unambiguous_ref(s, symbols, "save") for s in symbols]
        
        # Same container, same file - need line numbers
        assert len(set(refs)) == 2
        assert ":10:" in refs[0]
        assert ":30:" in refs[1]

    def test_java_methods_different_classes(self):
        """Java methods in different classes use container."""
        symbols = [
            {"path": "Repo.java", "line": 10, "name": "save(User)", "container": "UserRepo"},
            {"path": "Repo.java", "line": 50, "name": "save(Order)", "container": "OrderRepo"},
        ]
        
        ref1 = self.server._generate_unambiguous_ref(symbols[0], symbols, "save")
        ref2 = self.server._generate_unambiguous_ref(symbols[1], symbols, "save")
        
        assert ref1 == "UserRepo.save"
        assert ref2 == "OrderRepo.save"


class TestResolveSymbolRoundTrip:
    """Test that suggested refs actually resolve back to the correct symbol.
    
    This is the key invariant: if we suggest "Container.name" as a ref,
    then "lspcmd show Container.name" must resolve to that exact symbol.
    """

    def setup_method(self):
        self.server = MCPDaemonServer.__new__(MCPDaemonServer)

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
