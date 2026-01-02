"""RPC request and response models for daemon communication."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


# Base models for RPC
class RpcRequest(BaseModel):
    """Base RPC request wrapper."""
    method: str
    params: dict = Field(default_factory=dict)


class RpcResponse(BaseModel):
    """Base RPC response wrapper."""
    result: dict | list | None = None
    error: str | None = None


# Symbol representation used in many responses
class SymbolInfo(BaseModel):
    name: str
    kind: str
    path: str
    line: int
    column: int = 0
    container: str | None = None
    detail: str | None = None
    documentation: str | None = None
    range_start_line: int | None = None
    range_end_line: int | None = None


class LocationInfo(BaseModel):
    path: str
    line: int
    column: int = 0
    context: list[str] | None = None
    context_start: int | None = None
    # For type hierarchy results
    name: str | None = None
    kind: str | None = None
    detail: str | None = None


# === Shutdown ===
class ShutdownParams(BaseModel):
    pass


class ShutdownResult(BaseModel):
    status: Literal["shutting_down"]


# === Describe Session ===
class DescribeSessionParams(BaseModel):
    pass


class CacheInfo(BaseModel):
    current_bytes: int
    max_bytes: int
    entries: int


class WorkspaceInfo(BaseModel):
    root: str
    language: str
    server_pid: int | None = None
    open_documents: list[str]


class DescribeSessionResult(BaseModel):
    daemon_pid: int
    caches: dict[str, CacheInfo]
    workspaces: list[WorkspaceInfo]


# === Grep ===
class GrepParams(BaseModel):
    workspace_root: str
    pattern: str = ".*"
    kinds: list[str] | None = None
    case_sensitive: bool = False
    include_docs: bool = False
    paths: list[str] | None = None
    exclude_patterns: list[str] = Field(default_factory=list)


class GrepResult(BaseModel):
    symbols: list[SymbolInfo] = Field(default_factory=list)
    warning: str | None = None


# === Files ===
class FilesParams(BaseModel):
    workspace_root: str
    subpath: str | None = None
    exclude_patterns: list[str] = Field(default_factory=list)
    include_patterns: list[str] = Field(default_factory=list)


class FileInfo(BaseModel):
    path: str
    lines: int
    bytes: int
    symbols: dict[str, int] = Field(default_factory=dict)


class FilesResult(BaseModel):
    files: dict[str, FileInfo]
    total_files: int
    total_bytes: int
    total_lines: int


# === Show ===
class ShowParams(BaseModel):
    workspace_root: str
    path: str
    line: int
    column: int = 0
    context: int = 0
    head: int | None = None
    body: bool = True
    symbol_name: str | None = None
    symbol_kind: str | None = None
    range_start_line: int | None = None
    range_end_line: int | None = None


class ShowResult(BaseModel):
    path: str
    start_line: int
    end_line: int
    content: str
    symbol: str | None = None
    truncated: bool = False
    total_lines: int | None = None


# === References ===
class ReferencesParams(BaseModel):
    workspace_root: str
    path: str
    line: int
    column: int = 0
    context: int = 0


class ReferencesResult(BaseModel):
    locations: list[LocationInfo]


# === Declaration ===
class DeclarationParams(BaseModel):
    workspace_root: str
    path: str
    line: int
    column: int = 0
    context: int = 0


class DeclarationResult(BaseModel):
    locations: list[LocationInfo]


# === Implementations ===
class ImplementationsParams(BaseModel):
    workspace_root: str
    path: str
    line: int
    column: int = 0
    context: int = 0


class ImplementationsResult(BaseModel):
    locations: list[LocationInfo]


# === Subtypes ===
class SubtypesParams(BaseModel):
    workspace_root: str
    path: str
    line: int
    column: int = 0
    context: int = 0


class SubtypesResult(BaseModel):
    locations: list[LocationInfo]


# === Supertypes ===
class SupertypesParams(BaseModel):
    workspace_root: str
    path: str
    line: int
    column: int = 0
    context: int = 0


class SupertypesResult(BaseModel):
    locations: list[LocationInfo]


# === Calls ===
class CallsParams(BaseModel):
    workspace_root: str
    mode: Literal["outgoing", "incoming", "path"]
    from_path: str | None = None
    from_line: int | None = None
    from_column: int | None = None
    from_symbol: str | None = None
    to_path: str | None = None
    to_line: int | None = None
    to_column: int | None = None
    to_symbol: str | None = None
    max_depth: int = 3
    include_non_workspace: bool = False


class CallNode(BaseModel):
    name: str
    kind: str | None = None
    detail: str | None = None
    path: str | None = None
    line: int | None = None
    column: int | None = None
    calls: list["CallNode"] | None = None
    called_by: list["CallNode"] | None = None


class CallsResult(BaseModel):
    root: CallNode | None = None
    path: list[CallNode] | None = None
    message: str | None = None


# === Rename ===
class RenameParams(BaseModel):
    workspace_root: str
    path: str
    line: int
    column: int = 0
    new_name: str


class RenameResult(BaseModel):
    files_changed: list[str]


# === Move File ===
class MoveFileParams(BaseModel):
    workspace_root: str
    old_path: str
    new_path: str


class MoveFileResult(BaseModel):
    files_changed: list[str]
    imports_updated: bool


# === Replace Function ===
class ReplaceFunctionParams(BaseModel):
    workspace_root: str
    symbol: str
    new_contents: str
    check_signature: bool = True


class ReplaceFunctionResult(BaseModel):
    path: str
    old_range: tuple[int, int]
    new_range: tuple[int, int]
    message: str | None = None


# === Raw LSP Request ===
class RawLspRequestParams(BaseModel):
    workspace_root: str
    method: str
    params: dict = Field(default_factory=dict)
    language: str = "python"


# === Workspace Management ===
class RestartWorkspaceParams(BaseModel):
    workspace_root: str


class RestartWorkspaceResult(BaseModel):
    restarted: list[str]


class RemoveWorkspaceParams(BaseModel):
    workspace_root: str


class RemoveWorkspaceResult(BaseModel):
    servers_stopped: list[str]


# === Resolve Symbol ===
class ResolveSymbolParams(BaseModel):
    workspace_root: str
    symbol_path: str


class ResolveSymbolResult(BaseModel):
    # Success fields (all optional in case of error)
    path: str | None = None
    line: int | None = None
    column: int | None = None
    name: str | None = None
    kind: str | None = None
    container: str | None = None
    range_start_line: int | None = None
    range_end_line: int | None = None
    # Error fields
    error: str | None = None
    matches: list[SymbolInfo] | None = None
    total: int | None = None
