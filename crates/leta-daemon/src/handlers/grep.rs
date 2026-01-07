use std::path::PathBuf;

use regex::Regex;
use serde_json::{json, Value};

use super::{collect_all_workspace_symbols, collect_symbols_for_paths, is_excluded, HandlerContext};

pub async fn handle_grep(ctx: &HandlerContext, params: Value) -> Result<Value, String> {
    let workspace_root = PathBuf::from(
        params.get("workspace_root")
            .and_then(|v| v.as_str())
            .ok_or("Missing workspace_root")?
    );
    let pattern = params.get("pattern")
        .and_then(|v| v.as_str())
        .unwrap_or(".*");
    let kinds: Option<Vec<String>> = params.get("kinds")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().filter_map(|v| v.as_str().map(String::from)).collect());
    let case_sensitive = params.get("case_sensitive")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    let _include_docs = params.get("include_docs")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    let paths: Option<Vec<PathBuf>> = params.get("paths")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().filter_map(|v| v.as_str().map(PathBuf::from)).collect());
    let exclude_patterns: Vec<String> = params.get("exclude_patterns")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().filter_map(|v| v.as_str().map(String::from)).collect())
        .unwrap_or_default();

    let regex = if case_sensitive {
        Regex::new(pattern)
    } else {
        Regex::new(&format!("(?i){}", pattern))
    }.map_err(|e| format!("Invalid regex pattern '{}': {}", pattern, e))?;

    let kinds_set: Option<std::collections::HashSet<String>> = kinds.map(|k| 
        k.iter().map(|s| s.to_lowercase()).collect()
    );

    let mut symbols = if let Some(paths) = paths {
        collect_symbols_for_paths(ctx, &paths, &workspace_root).await?
    } else {
        collect_all_workspace_symbols(ctx, &workspace_root).await?
    };

    if !exclude_patterns.is_empty() {
        symbols.retain(|s| !is_excluded(&s.path, &exclude_patterns));
    }

    symbols.retain(|s| regex.is_match(&s.name));

    if let Some(ref kinds_set) = kinds_set {
        symbols.retain(|s| kinds_set.contains(&s.kind.to_lowercase()));
    }

    let symbol_values: Vec<Value> = symbols.into_iter().map(|s| {
        let mut obj = json!({
            "name": s.name,
            "kind": s.kind,
            "path": s.path,
            "line": s.line,
            "column": s.column,
        });
        if let Some(container) = s.container {
            obj["container"] = json!(container);
        }
        if let Some(detail) = s.detail {
            obj["detail"] = json!(detail);
        }
        if let Some(range_start) = s.range_start_line {
            obj["range_start_line"] = json!(range_start);
        }
        if let Some(range_end) = s.range_end_line {
            obj["range_end_line"] = json!(range_end);
        }
        obj
    }).collect();

    let warning = if symbol_values.is_empty() && pattern.contains(r"\|") {
        Some("No results. Note: use '|' for alternation, not '\\|' (e.g., 'foo|bar' not 'foo\\|bar')".to_string())
    } else {
        None
    };

    Ok(json!({
        "symbols": symbol_values,
        "warning": warning,
    }))
}
