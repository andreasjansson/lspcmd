use std::collections::HashMap;

use leta_types::{
    CallNode, CallsResult, DescribeSessionResult, FileInfo, FilesResult, GrepResult,
    ImplementationsResult, LocationInfo, ReferencesResult, ResolveSymbolResult, ShowResult,
};

pub fn format_size(bytes: u64) -> String {
    const KB: u64 = 1024;
    const MB: u64 = KB * 1024;
    const GB: u64 = MB * 1024;

    if bytes >= GB {
        format!("{:.1}GB", bytes as f64 / GB as f64)
    } else if bytes >= MB {
        format!("{:.1}MB", bytes as f64 / MB as f64)
    } else if bytes >= KB {
        format!("{:.1}KB", bytes as f64 / KB as f64)
    } else {
        format!("{}B", bytes)
    }
}

pub fn format_profiling(profiling: &leta_types::ProfilingData) -> String {
    let mut lines = Vec::new();

    let total_us: u64 = profiling.functions.first().map(|f| f.total_us).unwrap_or(0);
    lines.push(format!(
        "[profile] {:>8}  total",
        format_duration_us(total_us)
    ));

    let cache = &profiling.cache;
    let symbol_total = cache.symbol_hits + cache.symbol_misses;
    let hover_total = cache.hover_hits + cache.hover_misses;

    if symbol_total > 0 || hover_total > 0 {
        if symbol_total > 0 {
            lines.push(format!(
                "[cache]   symbol: {}/{} ({:.0}% hit)",
                cache.symbol_hits,
                symbol_total,
                cache.symbol_hit_rate()
            ));
        }
        if hover_total > 0 {
            lines.push(format!(
                "[cache]   hover:  {}/{} ({:.0}% hit)",
                cache.hover_hits,
                hover_total,
                cache.hover_hit_rate()
            ));
        }
    }

    lines.join("\n")
}

pub fn format_grep_result(result: &GrepResult, include_docs: bool) -> String {
    let mut lines = Vec::new();
    for sym in &result.symbols {
        let path = format!("{}:{}", sym.path, sym.line);
        let container = sym
            .container
            .as_ref()
            .map(|c| format!(" in {}", c))
            .unwrap_or_default();
        let kind = format!("[{}] ", sym.kind);

        lines.push(format!("{:<60} {}{}{}", path, kind, sym.name, container));

        if include_docs {
            if let Some(doc) = &sym.documentation {
                let doc_lines: Vec<&str> = doc.lines().take(3).collect();
                for doc_line in doc_lines {
                    lines.push(format!("    {}", doc_line));
                }
            }
        }
    }
    if let Some(warning) = &result.warning {
        lines.push(format!("\nWarning: {}", warning));
    }
    lines.join("\n")
}

pub fn format_files_result(result: &FilesResult) -> String {
    fn format_tree(
        files: &HashMap<String, FileInfo>,
        prefix: &str,
        lines: &mut Vec<String>,
        base_path: &str,
    ) {
        let mut entries: Vec<_> = files
            .iter()
            .filter(|(path, _)| {
                let relative = path.strip_prefix(base_path).unwrap_or(path);
                let relative = relative.trim_start_matches('/');
                !relative.contains('/')
            })
            .collect();
        entries.sort_by(|a, b| a.0.cmp(b.0));

        let dirs: std::collections::HashSet<String> = files
            .keys()
            .filter_map(|path| {
                let relative = path.strip_prefix(base_path).unwrap_or(path);
                let relative = relative.trim_start_matches('/');
                relative
                    .split('/')
                    .next()
                    .filter(|_| relative.contains('/'))
            })
            .map(|s| s.to_string())
            .collect();

        let mut all_entries: Vec<(&str, Option<&FileInfo>)> = entries
            .iter()
            .map(|(p, f)| {
                let name = p
                    .strip_prefix(base_path)
                    .unwrap_or(p)
                    .trim_start_matches('/');
                (name, Some(*f))
            })
            .collect();

        for dir in &dirs {
            all_entries.push((dir.as_str(), None));
        }
        all_entries.sort_by(|a, b| a.0.cmp(b.0));
        all_entries.dedup_by(|a, b| a.0 == b.0);

        for (i, (name, file_info)) in all_entries.iter().enumerate() {
            let is_last = i == all_entries.len() - 1;
            let connector = if is_last { "└── " } else { "├── " };
            let child_prefix = if is_last { "    " } else { "│   " };

            if let Some(info) = file_info {
                let size = format_size(info.bytes);
                let symbols: Vec<String> = info
                    .symbols
                    .iter()
                    .filter(|(_, &count)| count > 0)
                    .map(|(kind, count)| format!("{} {}", count, kind))
                    .collect();
                let symbols_str = if symbols.is_empty() {
                    String::new()
                } else {
                    format!(", {}", symbols.join(", "))
                };
                lines.push(format!(
                    "{}{}{} ({}, {} lines{})",
                    prefix, connector, name, size, info.lines, symbols_str
                ));
            } else {
                lines.push(format!("{}{}{}", prefix, connector, name));
                let new_base = if base_path.is_empty() {
                    name.to_string()
                } else {
                    format!("{}/{}", base_path, name)
                };
                let sub_files: HashMap<String, FileInfo> = files
                    .iter()
                    .filter(|(p, _)| p.starts_with(&format!("{}/", new_base)))
                    .map(|(p, f)| (p.clone(), f.clone()))
                    .collect();
                format_tree(
                    &sub_files,
                    &format!("{}{}", prefix, child_prefix),
                    lines,
                    &new_base,
                );
            }
        }
    }

    let mut lines = Vec::new();
    format_tree(&result.files, "", &mut lines, "");

    lines.push(format!(
        "\n{} files, {}, {} lines",
        result.total_files,
        format_size(result.total_bytes),
        result.total_lines
    ));

    lines.join("\n")
}

pub fn format_describe_session_result(
    result: &DescribeSessionResult,
    show_profiling: bool,
) -> String {
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

    let profiling_map: std::collections::HashMap<&str, &leta_types::WorkspaceProfilingData> =
        result
            .profiling
            .as_ref()
            .map(|data| {
                data.iter()
                    .map(|p| (p.workspace_root.as_str(), p))
                    .collect()
            })
            .unwrap_or_default();

    let mut workspace_roots: std::collections::HashSet<&str> = result
        .workspaces
        .iter()
        .map(|ws| ws.root.as_str())
        .collect();

    for root in profiling_map.keys() {
        workspace_roots.insert(root);
    }

    if workspace_roots.is_empty() {
        lines.push("\nNo active workspaces".to_string());
    } else {
        lines.push("\nActive workspaces:".to_string());

        let mut sorted_roots: Vec<_> = workspace_roots.into_iter().collect();
        sorted_roots.sort();

        for root in sorted_roots {
            lines.push(format!("\n  {}", root));

            let workspaces_for_root: Vec<_> = result
                .workspaces
                .iter()
                .filter(|ws| ws.root == root)
                .collect();

            let profiling_data = profiling_map.get(root);

            for ws in &workspaces_for_root {
                let status = if ws.server_pid.is_some() {
                    "running"
                } else {
                    "stopped"
                };
                let pid_str = ws
                    .server_pid
                    .map(|p| format!(", PID {}", p))
                    .unwrap_or_default();

                lines.push(format!(
                    "    {} ({}{}) [{} open files]",
                    ws.language,
                    status,
                    pid_str,
                    ws.open_documents.len()
                ));

                if show_profiling {
                    if let Some(profile) = profiling_data.and_then(|p| {
                        p.server_profiles
                            .iter()
                            .find(|sp| sp.server_name == ws.language)
                    }) {
                        if let Some(startup) = &profile.startup {
                            lines.push(format!(
                                "      Startup: {}ms (init: {}ms, ready: {}ms)",
                                startup.total_time_ms, startup.init_time_ms, startup.ready_time_ms
                            ));
                            for func in startup.functions.iter().take(5) {
                                lines.push(format!(
                                    "        {:50} {:>8}",
                                    func.name,
                                    format_duration_us(func.total_us)
                                ));
                            }
                        }
                        if let Some(indexing) = &profile.indexing {
                            lines.push(format!(
                                "      Indexing: {}ms ({} files)",
                                indexing.total_time_ms, indexing.file_count
                            ));
                            for func in indexing.functions.iter().take(10) {
                                let calls_str = if func.calls > 1 {
                                    format!(
                                        " ({}x, avg {})",
                                        func.calls,
                                        format_duration_us(func.avg_us)
                                    )
                                } else {
                                    String::new()
                                };
                                lines.push(format!(
                                    "        {:50} {:>8}{}",
                                    func.name,
                                    format_duration_us(func.total_us),
                                    calls_str
                                ));
                            }
                        }
                    }
                }
            }

            if show_profiling {
                if let Some(profile) = profiling_data {
                    lines.push(format!(
                        "    Total: {}ms ({} files)",
                        profile.total_time_ms, profile.total_files
                    ));
                }
            }
        }
    }

    lines.join("\n")
}

fn format_duration_us(us: u64) -> String {
    if us >= 1_000_000 {
        format!("{:.2}s", us as f64 / 1_000_000.0)
    } else if us >= 1_000 {
        format!("{:.1}ms", us as f64 / 1_000.0)
    } else {
        format!("{}µs", us)
    }
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
                let path = format!("{}:{}", m.path, m.line);
                lines.push(format!(
                    "  {:<50} {}{}{}{}",
                    path, kind, m.name, container, detail
                ));
            }
        }
        lines.join("\n")
    } else {
        String::new()
    }
}

pub fn format_show_result(result: &ShowResult, path_prefix: Option<&str>) -> String {
    let path = if let Some(prefix) = path_prefix {
        result
            .path
            .strip_prefix(prefix)
            .unwrap_or(&result.path)
            .trim_start_matches('/')
    } else {
        &result.path
    };

    let mut lines = vec![format!(
        "{}:{}-{}",
        path, result.start_line, result.end_line
    )];
    if result.truncated {
        if let Some(total) = result.total_lines {
            lines.push(format!(
                "(truncated, showing {} of {} lines)",
                result.end_line - result.start_line + 1,
                total
            ));
        }
    }
    lines.push(String::new());
    lines.push(result.content.clone());
    lines.join("\n")
}

pub fn format_references_result(result: &ReferencesResult, path_prefix: Option<&str>) -> String {
    format_locations(&result.locations, path_prefix)
}

pub fn format_implementations_result(
    result: &ImplementationsResult,
    path_prefix: Option<&str>,
) -> String {
    if let Some(error) = &result.error {
        return format!("Error: {}", error);
    }
    format_locations(&result.locations, path_prefix)
}

fn format_locations(locations: &[LocationInfo], path_prefix: Option<&str>) -> String {
    let mut lines = Vec::new();
    for loc in locations {
        let path = if let Some(prefix) = path_prefix {
            loc.path
                .strip_prefix(prefix)
                .unwrap_or(&loc.path)
                .trim_start_matches('/')
        } else {
            &loc.path
        };

        lines.push(format!("{}:{}", path, loc.line));
        if let Some(context_lines) = &loc.context_lines {
            for line in context_lines {
                lines.push(line.clone());
            }
            lines.push(String::new());
        }
    }
    if lines.last() == Some(&String::new()) {
        lines.pop();
    }
    lines.join("\n")
}

pub fn format_calls_result(result: &CallsResult, path_prefix: Option<&str>) -> String {
    if let Some(error) = &result.error {
        return format!("Error: {}", error);
    }
    if let Some(message) = &result.message {
        return message.clone();
    }

    let mut lines = Vec::new();

    if let Some(path) = &result.path {
        lines.push("Call path found:".to_string());
        for (i, node) in path.iter().enumerate() {
            let indent = "  ".repeat(i);
            let path = if let Some(prefix) = path_prefix {
                node.path
                    .strip_prefix(prefix)
                    .unwrap_or(&node.path)
                    .trim_start_matches('/')
            } else {
                &node.path
            };
            lines.push(format!("{}{}:{} {}", indent, path, node.line, node.name));
        }
    } else if let Some(root) = &result.root {
        fn format_node(
            node: &CallNode,
            prefix: &str,
            is_last: bool,
            lines: &mut Vec<String>,
            path_prefix: Option<&str>,
        ) {
            let connector = if prefix.is_empty() {
                ""
            } else if is_last {
                "└── "
            } else {
                "├── "
            };

            let path = if let Some(pfx) = path_prefix {
                node.path
                    .strip_prefix(pfx)
                    .unwrap_or(&node.path)
                    .trim_start_matches('/')
            } else {
                &node.path
            };

            lines.push(format!(
                "{}{}{}:{} {}",
                prefix, connector, path, node.line, node.name
            ));

            let child_prefix = if prefix.is_empty() {
                String::new()
            } else if is_last {
                format!("{}    ", prefix)
            } else {
                format!("{}│   ", prefix)
            };

            if let Some(children) = &node.children {
                for (i, child) in children.iter().enumerate() {
                    let is_child_last = i == children.len() - 1;
                    format_node(child, &child_prefix, is_child_last, lines, path_prefix);
                }
            }
        }

        format_node(root, "", true, &mut lines, path_prefix);
    }

    lines.join("\n")
}
