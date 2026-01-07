use serde::{Deserialize, Serialize};
use std::collections::HashMap;

use crate::{CacheInfo, CallNode, FileInfo, LocationInfo, SymbolInfo, WorkspaceInfo};

// ============================================================================
// RPC Protocol
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RpcRequest<P> {
    pub method: String,
    pub params: P,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum RpcResponse<R> {
    Success { result: R },
    Error { error: String },
}

impl<R> RpcResponse<R> {
    pub fn success(result: R) -> Self {
        RpcResponse::Success { result }
    }

    pub fn error(message: impl Into<String>) -> Self {
        RpcResponse::Error {
            error: message.into(),
        }
    }

    pub fn into_result(self) -> Result<R, String> {
        match self {
            RpcResponse::Success { result } => Ok(result),
            RpcResponse::Error { error } => Err(error),
        }
    }
}

// ============================================================================
// Shutdown
// ============================================================================

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ShutdownParams {}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ShutdownResult {
    pub status: String,
}

// ============================================================================
// Describe Session
// ============================================================================

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct DescribeSessionParams {}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DescribeSessionResult {
    pub daemon_pid: u32,
    pub caches: HashMap<String, CacheInfo>,
    pub workspaces: Vec<WorkspaceInfo>,
}

// ============================================================================
// Grep
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GrepParams {
    pub workspace_root: String,
    #[serde(default = "default_pattern")]
    pub pattern: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub kinds: Option<Vec<String>>,
    #[serde(default)]
    pub case_sensitive: bool,
    #[serde(default)]
    pub include_docs: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub paths: Option<Vec<String>>,
    #[serde(default)]
    pub exclude_patterns: Vec<String>,
}

fn default_pattern() -> String {
    ".*".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GrepResult {
    #[serde(default)]
    pub symbols: Vec<SymbolInfo>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub warning: Option<String>,
}

// ============================================================================
// Files
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FilesParams {
    pub workspace_root: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub subpath: Option<String>,
    #[serde(default)]
    pub exclude_patterns: Vec<String>,
    #[serde(default)]
    pub include_patterns: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FilesResult {
    pub files: HashMap<String, FileInfo>,
    pub total_files: u32,
    pub total_bytes: u64,
    pub total_lines: u32,
}

// ============================================================================
// Show
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ShowParams {
    pub workspace_root: String,
    pub path: String,
    pub line: u32,
    #[serde(default)]
    pub column: u32,
    #[serde(default)]
    pub context: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub head: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none", alias = "symbol")]
    pub symbol_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none", alias = "kind")]
    pub symbol_kind: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub range_start_line: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub range_end_line: Option<u32>,
    #[serde(default)]
    pub direct_location: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ShowResult {
    pub path: String,
    pub start_line: u32,
    pub end_line: u32,
    pub content: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub symbol: Option<String>,
    #[serde(default)]
    pub truncated: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub total_lines: Option<u32>,
}

// ============================================================================
// References
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReferencesParams {
    pub workspace_root: String,
    pub path: String,
    pub line: u32,
    #[serde(default)]
    pub column: u32,
    #[serde(default)]
    pub context: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReferencesResult {
    pub locations: Vec<LocationInfo>,
}

// ============================================================================
// Declaration
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeclarationParams {
    pub workspace_root: String,
    pub path: String,
    pub line: u32,
    #[serde(default)]
    pub column: u32,
    #[serde(default)]
    pub context: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeclarationResult {
    pub locations: Vec<LocationInfo>,
}

// ============================================================================
// Implementations
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ImplementationsParams {
    pub workspace_root: String,
    pub path: String,
    pub line: u32,
    #[serde(default)]
    pub column: u32,
    #[serde(default)]
    pub context: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ImplementationsResult {
    #[serde(default)]
    pub locations: Vec<LocationInfo>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

// ============================================================================
// Subtypes
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SubtypesParams {
    pub workspace_root: String,
    pub path: String,
    pub line: u32,
    #[serde(default)]
    pub column: u32,
    #[serde(default)]
    pub context: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SubtypesResult {
    pub locations: Vec<LocationInfo>,
}

// ============================================================================
// Supertypes
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SupertypesParams {
    pub workspace_root: String,
    pub path: String,
    pub line: u32,
    #[serde(default)]
    pub column: u32,
    #[serde(default)]
    pub context: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SupertypesResult {
    pub locations: Vec<LocationInfo>,
}

// ============================================================================
// Calls
// ============================================================================

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum CallsMode {
    Outgoing,
    Incoming,
    Path,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CallsParams {
    pub workspace_root: String,
    pub mode: CallsMode,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub from_path: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub from_line: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub from_column: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub from_symbol: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub to_path: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub to_line: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub to_column: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub to_symbol: Option<String>,
    #[serde(default = "default_max_depth")]
    pub max_depth: u32,
    #[serde(default)]
    pub include_non_workspace: bool,
}

fn default_max_depth() -> u32 {
    3
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CallsResult {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub root: Option<CallNode>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub path: Option<Vec<CallNode>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

// ============================================================================
// Rename
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RenameParams {
    pub workspace_root: String,
    pub path: String,
    pub line: u32,
    #[serde(default)]
    pub column: u32,
    pub new_name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RenameResult {
    pub files_changed: Vec<String>,
}

// ============================================================================
// Move File
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MoveFileParams {
    pub workspace_root: String,
    pub old_path: String,
    pub new_path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MoveFileResult {
    pub files_changed: Vec<String>,
    pub imports_updated: bool,
}

// ============================================================================
// Raw LSP Request
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RawLspRequestParams {
    pub workspace_root: String,
    pub method: String,
    #[serde(default)]
    pub params: serde_json::Value,
    #[serde(default = "default_language")]
    pub language: String,
}

fn default_language() -> String {
    "python".to_string()
}

// ============================================================================
// Workspace Management
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RestartWorkspaceParams {
    pub workspace_root: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RestartWorkspaceResult {
    pub restarted: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RemoveWorkspaceParams {
    pub workspace_root: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RemoveWorkspaceResult {
    pub servers_stopped: Vec<String>,
}

// ============================================================================
// Resolve Symbol
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResolveSymbolParams {
    pub workspace_root: String,
    pub symbol_path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResolveSymbolResult {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub path: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub column: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub kind: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub container: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub range_start_line: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub range_end_line: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub matches: Option<Vec<SymbolInfo>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub total_matches: Option<u32>,
}

impl ResolveSymbolResult {
    pub fn success(
        path: String,
        line: u32,
        column: u32,
        name: Option<String>,
        kind: Option<String>,
        container: Option<String>,
        range_start_line: Option<u32>,
        range_end_line: Option<u32>,
    ) -> Self {
        Self {
            path: Some(path),
            line: Some(line),
            column: Some(column),
            name,
            kind,
            container,
            range_start_line,
            range_end_line,
            error: None,
            matches: None,
            total_matches: None,
        }
    }

    pub fn not_found(symbol: &str) -> Self {
        Self {
            error: Some(format!("Symbol '{}' not found", symbol)),
            path: None,
            line: None,
            column: None,
            name: None,
            kind: None,
            container: None,
            range_start_line: None,
            range_end_line: None,
            matches: None,
            total_matches: None,
        }
    }

    pub fn ambiguous(symbol: &str, matches: Vec<SymbolInfo>, total: u32) -> Self {
        Self {
            error: Some(format!(
                "Symbol '{}' is ambiguous ({} matches)",
                symbol, total
            )),
            matches: Some(matches),
            total_matches: Some(total),
            path: None,
            line: None,
            column: None,
            name: None,
            kind: None,
            container: None,
            range_start_line: None,
            range_end_line: None,
        }
    }
}
