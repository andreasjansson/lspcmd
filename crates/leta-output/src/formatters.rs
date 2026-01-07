use std::collections::HashMap;
use std::path::PathBuf;

use leta_types::*;

pub fn format_grep_result(result: &GrepResult) -> String {
    if let Some(warning) = &result.warning {
        return format!("Warning: {}", warning);
    }
    format_symbols(&result.symbols)
}

pub fn format_references_result(result: &ReferencesResult) -> String {
    format_locations(&result.locations)
}

pub fn format_declaration_result(result: &DeclarationResult) -> String {
    format_locations(&result.locations)
}

pub fn format_implementations_result(result: &ImplementationsResult) -> String {
    if let Some(error) = &result.error {
        return format!("Error: {}", error);
    }
    format_locations(&result.locations)
}

pub fn format_subtypes_result(result: &SubtypesResult) -> String {
    format_locations(&result.locations)
}

pub fn format_supertypes_result(result: &SupertypesResult) -> String {
    format_locations(&result.locations)
}

pub fn format_show_result(result: &ShowResult) -> String {
    let location = if result.start_line == result.end_line {
        format!("{}:{}", result.path, result.start_line)
    } else {
        format!("{}:{}-{}", result.path, result.start_line, result.end_line)
    };

    let mut lines = vec![location, String::new(), result.content.clone()];

    if result.truncated {
        let head = 200;
        let total_lines = result.total_lines.unwrap_or(head);
        let symbol = result.symbol.as_deref().unwrap_or("SYMBOL");
        lines.push(String::new());
        lines.push(format!(
            "[truncated after {} lines, use `leta show \"{}\" --head {}` to show the full {} lines]",
            head, symbol, total_lines, total_lines
        ));
    }

    lines.join("\n")
}

pub fn format_rename_result(result: &RenameResult) -> String {
    let mut files: Vec<_> = result.files_changed.iter().collect();
    files.sort();
    format!(
        "Renamed in {} file(s):\n{}",
        files.len(),
        files
            .iter()
            .map(|f| format!("  {}", f))
            .collect::<Vec<_>>()
            .join("\n")
    )
}

pub fn format_move_file_result(result: &MoveFileResult) -> String {
    let mut files: Vec<_> = result.files_changed.iter().collect();
    files.sort();
    if result.imports_updated {
        format!(
            "Moved file and updated imports in {} file(s):\n{}",
            files.len(),
            files
                .iter()
                .map(|f| format!("  {}", f))
                .collect::<Vec<_>>()
                .join("\n")
        )
    } else if let Some(first) = files.first() {
        format!("Moved file (imports not updated):\n  {}", first)
    } else {
        "File moved".to_string()
    }
}

pub fn format_restart_workspace_result(result: &RestartWorkspaceResult) -> String {
    format!(
        "Restarted {} server(s): {}",
        result.restarted.len(),
        result.restarted.join(", ")
    )
}

pub fn format_remove_workspace_result(result: &RemoveWorkspaceResult) -> String {
    format!(
        "Stopped {} server(s): {}",
        result.servers_stopped.len(),
        result.servers_stopped.join(", ")
    )
}

pub fn format_files_result(result: &FilesResult) -> String {
    if result.files.is_empty() {
        return "0 files, 0B".to_string();
    }

    let tree = build_tree(&result.files);
    let mut lines = Vec::new();
    render_tree(&tree, &mut lines, "", true);
    lines.push(String::new());
    lines.push(format!(
        "{} files, {}, {} lines",
        result.total_files,
        format_size(result.total_bytes),
        result.total_lines
    ));

    lines.join("\n")
}

pub fn format_calls_result(result: &CallsResult) -> String {
    if let Some(error) = &result.error {
        return format!("Error: {}", error);
    }
    if let Some(message) = &result.message {
        return message.clone();
    }
    if let Some(root) = &result.root {
        return format_call_tree(root);
    }
    if let Some(path) = &result.path {
        return format_call_path(path);
    }
    String::new()
}

pub fn format_describe_session_result(result: &DescribeSessionResult) -> String {
    let mut lines = vec![format!("Daemon PID: {}", result.daemon_pid)];

    if !result.caches.is_empty() {
        lines.push("\nCaches:".to_string());
        if let Some(hover) = result.caches.get("hover_cache") {
            lines.push(format!(
                "  Hover:  {} / {} ({} entries)",
                format_size(hover.current_bytes),
                format_size(hover.max_bytes),
                hover.entries
            ));
        }
        if let Some(symbol) = result.caches.get("symbol_cache") {
            lines.push(format!(
                "  Symbol: {} / {} ({} entries)",
                format_size(symbol.current_bytes),
                format_size(symbol.max_bytes),
                symbol.entries
            ));
        }
    }

    if result.workspaces.is_empty() {
        lines.push("\nNo active workspaces".to_string());
    } else {
        lines.push("\nActive workspaces:".to_string());
        for ws in &result.workspaces {
            let status = if ws.server_pid.is_some() {
                "running"
            } else {
                "stopped"
            };
            let pid_str = ws
                .server_pid
                .map(|p| format!(", PID {}", p))
                .unwrap_or_default();

            lines.push(format!("\n  {}", ws.root));
            lines.push(format!(
                "    Server: {} ({}{})",
                ws.language, status, pid_str
            ));
            if !ws.open_documents.is_empty() {
                lines.push(format!("    Open documents ({}):", ws.open_documents.len()));
                for doc in ws.open_documents.iter().take(5) {
                    lines.push(format!("      {}", doc));
                }
                if ws.open_documents.len() > 5 {
                    lines.push(format!(
                        "      ... and {} more",
                        ws.open_documents.len() - 5
                    ));
                }
            }
        }
    }

    lines.join("\n")
}

pub fn format_resolve_symbol_result(result: &ResolveSymbolResult) -> String {
    if let Some(error) = &result.error {
        let mut lines = vec![format!("Error: {}", error)];
        if let Some(matches) = &result.matches {
            for m in matches {
                let container = m
                    .container
                    .as_ref()
                    .map(|c| format!(" in {}", c))
                    .unwrap_or_default();
                let kind = format!("[{}] ", m.kind);
                let detail = m
                    .detail
                    .as_ref()
                    .map(|d| format!(" ({})", d))
                    .unwrap_or_default();
                let ref_str = m.r#ref.as_deref().unwrap_or("");
                lines.push(format!("  {}", ref_str));
                lines.push(format!(
                    "    {}:{} {}{}{}{}",
                    m.path, m.line, kind, m.name, detail, container
                ));
            }
            if let Some(total) = result.total_matches {
                let shown = matches.len() as u32;
                if total > shown {
                    lines.push(format!("  ... and {} more", total - shown));
                }
            }
        }
        return lines.join("\n");
    }
    format!(
        "{}:{}",
        result.path.as_deref().unwrap_or(""),
        result.line.unwrap_or(0)
    )
}

fn format_locations(locations: &[LocationInfo]) -> String {
    let mut lines = Vec::new();
    for loc in locations {
        if loc.name.is_some() && loc.kind.is_some() {
            let mut parts = vec![
                format!("{}:{}", loc.path, loc.line),
                format!("[{}]", loc.kind.as_ref().unwrap()),
                loc.name.clone().unwrap(),
            ];
            if let Some(detail) = &loc.detail {
                parts.push(format!("({})", detail));
            }
            lines.push(parts.join(" "));
        } else if let Some(context) = &loc.context_lines {
            let context_start = loc.context_start.unwrap_or(loc.line);
            let context_end = context_start + context.len() as u32 - 1;
            lines.push(format!("{}:{}-{}", loc.path, context_start, context_end));
            for line in context {
                lines.push(line.clone());
            }
            lines.push(String::new());
        } else {
            let line_content = get_line_content(&loc.path, loc.line);
            if let Some(content) = line_content {
                lines.push(format!("{}:{} {}", loc.path, loc.line, content));
            } else {
                lines.push(format!("{}:{}", loc.path, loc.line));
            }
        }
    }
    lines.join("\n")
}

fn get_line_content(path: &str, line: u32) -> Option<String> {
    let file_path = PathBuf::from(path);
    let file_path = if file_path.is_absolute() {
        file_path
    } else {
        std::env::current_dir().ok()?.join(&file_path)
    };

    let content = std::fs::read_to_string(&file_path).ok()?;
    let lines: Vec<&str> = content.lines().collect();
    if line > 0 && (line as usize) <= lines.len() {
        Some(lines[line as usize - 1].to_string())
    } else {
        None
    }
}

fn format_symbols(symbols: &[SymbolInfo]) -> String {
    let mut lines = Vec::new();
    for sym in symbols {
        let location = format!("{}:{}", sym.path, sym.line);
        let mut parts = vec![location, format!("[{}]", sym.kind), sym.name.clone()];
        if let Some(detail) = &sym.detail {
            parts.push(format!("({})", detail));
        }
        if let Some(container) = &sym.container {
            parts.push(format!("in {}", container));
        }
        lines.push(parts.join(" "));

        if let Some(doc) = &sym.documentation {
            for doc_line in doc.trim().lines() {
                lines.push(format!("    {}", doc_line));
            }
            lines.push(String::new());
        }
    }
    lines.join("\n")
}

fn format_size(size: u64) -> String {
    if size < 1024 {
        format!("{}B", size)
    } else if size < 1024 * 1024 {
        format!("{:.1}KB", size as f64 / 1024.0)
    } else {
        format!("{:.1}MB", size as f64 / (1024.0 * 1024.0))
    }
}

enum TreeNode {
    File(FileInfo),
    Dir(HashMap<String, TreeNode>),
}

fn build_tree(files: &HashMap<String, FileInfo>) -> HashMap<String, TreeNode> {
    let mut tree: HashMap<String, TreeNode> = HashMap::new();

    for (rel_path, info) in files {
        let parts: Vec<&str> = rel_path.split('/').collect();
        let mut current = &mut tree;

        for (i, part) in parts.iter().enumerate() {
            if i == parts.len() - 1 {
                current.insert(part.to_string(), TreeNode::File(info.clone()));
            } else {
                current = match current
                    .entry(part.to_string())
                    .or_insert_with(|| TreeNode::Dir(HashMap::new()))
                {
                    TreeNode::Dir(map) => map,
                    _ => unreachable!(),
                };
            }
        }
    }

    tree
}

fn render_tree(
    node: &HashMap<String, TreeNode>,
    lines: &mut Vec<String>,
    prefix: &str,
    is_root: bool,
) {
    let mut entries: Vec<_> = node.keys().collect();
    entries.sort_by(|a, b| {
        let a_is_dir = matches!(node.get(*a), Some(TreeNode::Dir(_)));
        let b_is_dir = matches!(node.get(*b), Some(TreeNode::Dir(_)));
        match (a_is_dir, b_is_dir) {
            (true, false) => std::cmp::Ordering::Less,
            (false, true) => std::cmp::Ordering::Greater,
            _ => a.cmp(b),
        }
    });

    for (i, name) in entries.iter().enumerate() {
        let is_last = i == entries.len() - 1;
        let child = node.get(*name).unwrap();

        let (connector, new_prefix) = if is_root {
            ("".to_string(), "".to_string())
        } else {
            let connector = if is_last { "└── " } else { "├── " };
            let new_prefix = format!("{}{}", prefix, if is_last { "    " } else { "│   " });
            (connector.to_string(), new_prefix)
        };

        match child {
            TreeNode::File(info) => {
                let info_str = format_file_info(info);
                lines.push(format!("{}{}{} ({})", prefix, connector, name, info_str));
            }
            TreeNode::Dir(children) => {
                lines.push(format!("{}{}{}", prefix, connector, name));
                render_tree(children, lines, &new_prefix, false);
            }
        }
    }
}

fn format_file_info(info: &FileInfo) -> String {
    let mut parts = vec![format_size(info.bytes), format!("{} lines", info.lines)];

    let symbol_order = ["class", "struct", "interface", "enum", "function", "method"];
    for kind in &symbol_order {
        if let Some(&count) = info.symbols.get(*kind) {
            if count > 0 {
                let label = if count == 1 {
                    kind.to_string()
                } else if *kind == "class" {
                    "classes".to_string()
                } else {
                    format!("{}s", kind)
                };
                parts.push(format!("{} {}", count, label));
            }
        }
    }

    parts.join(", ")
}

fn is_stdlib_path(path: &str) -> bool {
    path.contains("/typeshed-fallback/stdlib/")
        || path.contains("/typeshed/stdlib/")
        || (path.contains("/libexec/src/") && !path.contains("/mod/"))
        || (path.ends_with(".d.ts")
            && path
                .split('/')
                .last()
                .map(|f| f.starts_with("lib."))
                .unwrap_or(false))
        || path.contains("/rustlib/src/rust/library/")
}

fn format_call_tree(node: &CallNode) -> String {
    let mut lines = Vec::new();

    let mut parts: Vec<String> = Vec::new();
    if let Some(path) = &node.path {
        parts.push(format!("{}:{}", path, node.line.unwrap_or(0)));
    }
    if let Some(kind) = &node.kind {
        parts.push(format!("[{}]", kind));
    }
    parts.push(node.name.clone());
    if let Some(detail) = &node.detail {
        parts.push(format!("({})", detail));
    }
    lines.push(parts.join(" "));

    if let Some(calls) = &node.calls {
        lines.push(String::new());
        lines.push("Outgoing calls:".to_string());
        if !calls.is_empty() {
            render_calls_tree(calls, &mut lines, "  ", true);
        }
    } else if let Some(called_by) = &node.called_by {
        lines.push(String::new());
        lines.push("Incoming calls:".to_string());
        if !called_by.is_empty() {
            render_calls_tree(called_by, &mut lines, "  ", false);
        }
    }

    lines.join("\n")
}

fn render_calls_tree(items: &[CallNode], lines: &mut Vec<String>, prefix: &str, is_outgoing: bool) {
    for (i, item) in items.iter().enumerate() {
        let is_last = i == items.len() - 1;
        let connector = if is_last { "└── " } else { "├── " };
        let child_prefix = format!("{}{}", prefix, if is_last { "    " } else { "│   " });

        let path = item.path.as_deref().unwrap_or("");
        let line = item.line.unwrap_or(0);

        let mut parts: Vec<String> = Vec::new();
        if is_stdlib_path(path) {
            if let Some(kind) = &item.kind {
                parts.push(format!("[{}]", kind));
            }
        } else {
            parts.push(format!("{}:{}", path, line));
            if let Some(kind) = &item.kind {
                parts.push(format!("[{}]", kind));
            }
        }
        parts.push(item.name.clone());
        if let Some(detail) = &item.detail {
            parts.push(format!("({})", detail));
        }
        lines.push(format!("{}{}{}", prefix, connector, parts.join(" ")));

        let children = if is_outgoing {
            &item.calls
        } else {
            &item.called_by
        };
        if let Some(children) = children {
            render_calls_tree(children, lines, &child_prefix, is_outgoing);
        }
    }
}

fn format_call_path(path: &[CallNode]) -> String {
    if path.is_empty() {
        return "Empty path".to_string();
    }

    let mut lines = vec!["Call path:".to_string()];
    for (i, item) in path.iter().enumerate() {
        let file_path = item.path.as_deref().unwrap_or("");
        let line = item.line.unwrap_or(0);

        let mut parts = vec![format!("{}:{}", file_path, line)];
        if let Some(kind) = &item.kind {
            parts.push(format!("[{}]", kind));
        }
        parts.push(item.name.clone());
        if let Some(detail) = &item.detail {
            parts.push(format!("({})", detail));
        }

        let arrow = if i == 0 { "" } else { "  → " };
        lines.push(format!("{}{}", arrow, parts.join(" ")));
    }

    lines.join("\n")
}
