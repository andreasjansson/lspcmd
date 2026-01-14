use std::collections::HashMap;
use std::path::PathBuf;

use leta_types::*;

pub fn format_truncation_with_count(
    command_with_larger_head: &str,
    displayed_count: u32,
    total_count: u32,
    command_base: &str,
) -> String {
    format!(
        "[showing {} of {} results, use `{}` to show more, or `{} -N0` to show all]",
        displayed_count, total_count, command_with_larger_head, command_base
    )
}

pub fn format_truncation_unknown_total(
    command_with_larger_head: &str,
    displayed_count: u32,
    command_base: &str,
) -> String {
    format!(
        "[showing first {} results, use `{}` to show more, or `{} -N0` to show all]",
        displayed_count, command_with_larger_head, command_base
    )
}

pub fn format_grep_result(result: &GrepResult, head: u32, command_base: &str) -> String {
    if let Some(warning) = &result.warning {
        return format!("Warning: {}", warning);
    }
    let mut output = format_symbols(&result.symbols);

    if result.truncated {
        if !output.is_empty() {
            output.push_str("\n\n");
        }
        let next_head = head * 2;
        let cmd = format!("{} --head {}", command_base, next_head);
        if let Some(total) = result.total_count {
            output.push_str(&format_truncation_with_count(
                &cmd,
                result.symbols.len() as u32,
                total,
                command_base,
            ));
        } else {
            output.push_str(&format_truncation_unknown_total(
                &cmd,
                result.symbols.len() as u32,
                command_base,
            ));
        }
    }

    output
}

pub fn format_references_result(
    result: &ReferencesResult,
    head: u32,
    command_base: &str,
) -> String {
    let mut output = format_locations(&result.locations);

    if result.truncated {
        if !output.is_empty() {
            output.push('\n');
        }
        let next_head = head * 2;
        let cmd = format!("{} --head {}", command_base, next_head);
        if let Some(total) = result.total_count {
            output.push_str(&format_truncation_with_count(
                &cmd,
                result.locations.len() as u32,
                total,
                command_base,
            ));
        } else {
            output.push_str(&format_truncation_unknown_total(
                &cmd,
                result.locations.len() as u32,
                command_base,
            ));
        }
    }

    output
}

pub fn format_declaration_result(
    result: &DeclarationResult,
    head: u32,
    command_base: &str,
) -> String {
    let mut output = format_locations(&result.locations);

    if result.truncated {
        if !output.is_empty() {
            output.push('\n');
        }
        let next_head = head * 2;
        let cmd = format!("{} --head {}", command_base, next_head);
        if let Some(total) = result.total_count {
            output.push_str(&format_truncation_with_count(
                &cmd,
                result.locations.len() as u32,
                total,
                command_base,
            ));
        } else {
            output.push_str(&format_truncation_unknown_total(
                &cmd,
                result.locations.len() as u32,
                command_base,
            ));
        }
    }

    output
}

pub fn format_implementations_result(
    result: &ImplementationsResult,
    head: u32,
    command_base: &str,
) -> String {
    if let Some(error) = &result.error {
        return format!("Error: {}", error);
    }
    let mut output = format_locations(&result.locations);

    if result.truncated {
        if !output.is_empty() {
            output.push('\n');
        }
        let next_head = head * 2;
        let cmd = format!("{} --head {}", command_base, next_head);
        if let Some(total) = result.total_count {
            output.push_str(&format_truncation_with_count(
                &cmd,
                result.locations.len() as u32,
                total,
                command_base,
            ));
        } else {
            output.push_str(&format_truncation_unknown_total(
                &cmd,
                result.locations.len() as u32,
                command_base,
            ));
        }
    }

    output
}

pub fn format_subtypes_result(result: &SubtypesResult, head: u32, command_base: &str) -> String {
    let mut output = format_locations(&result.locations);

    if result.truncated {
        if !output.is_empty() {
            output.push('\n');
        }
        let next_head = head * 2;
        let cmd = format!("{} --head {}", command_base, next_head);
        if let Some(total) = result.total_count {
            output.push_str(&format_truncation_with_count(
                &cmd,
                result.locations.len() as u32,
                total,
                command_base,
            ));
        } else {
            output.push_str(&format_truncation_unknown_total(
                &cmd,
                result.locations.len() as u32,
                command_base,
            ));
        }
    }

    output
}

pub fn format_supertypes_result(
    result: &SupertypesResult,
    head: u32,
    command_base: &str,
) -> String {
    let mut output = format_locations(&result.locations);

    if result.truncated {
        if !output.is_empty() {
            output.push('\n');
        }
        let next_head = head * 2;
        let cmd = format!("{} --head {}", command_base, next_head);
        if let Some(total) = result.total_count {
            output.push_str(&format_truncation_with_count(
                &cmd,
                result.locations.len() as u32,
                total,
                command_base,
            ));
        } else {
            output.push_str(&format_truncation_unknown_total(
                &cmd,
                result.locations.len() as u32,
                command_base,
            ));
        }
    }

    output
}

pub fn format_show_result(result: &ShowResult, head: u32) -> String {
    let location = if result.start_line == result.end_line {
        format!("{}:{}", result.path, result.start_line)
    } else {
        format!("{}:{}-{}", result.path, result.start_line, result.end_line)
    };

    let mut lines = vec![location, String::new(), result.content.clone()];

    if result.truncated {
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

pub fn format_files_result(result: &FilesResult, head: u32, command_base: &str) -> String {
    if result.files.is_empty() && result.excluded_dirs.is_empty() {
        return String::new();
    }

    let tree = build_tree(&result.files, &result.excluded_dirs);
    let mut lines = Vec::new();
    render_tree(&tree, &mut lines, 0);

    if result.truncated {
        lines.push(String::new());
        let next_head = head * 2;
        let cmd = format!("{} --head {}", command_base, next_head);
        lines.push(format_truncation_unknown_total(
            &cmd,
            result.files.len() as u32,
            command_base,
        ));
    }

    lines.join("\n")
}

pub fn format_calls_result(result: &CallsResult, head: u32, command_base: &str) -> String {
    if let Some(error) = &result.error {
        return format!("Error: {}", error);
    }
    if let Some(message) = &result.message {
        return message.clone();
    }
    let mut output = String::new();
    if let Some(root) = &result.root {
        output = format_call_tree(root);
    } else if let Some(path) = &result.path {
        output = format_call_path(path);
    }

    if result.truncated {
        if !output.is_empty() {
            output.push_str("\n\n");
        }
        let next_head = head * 2;
        let cmd = format!("{} --head {}", command_base, next_head);
        output.push_str(&format_truncation_unknown_total(&cmd, head, command_base));
    }

    output
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

    let profiling_map: HashMap<&str, &WorkspaceProfilingData> = result
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
                            lines.extend(format_function_stats(&startup.functions, "        ", 5));
                        }
                        if let Some(indexing) = &profile.indexing {
                            let cache = &indexing.cache;
                            let symbol_total = cache.symbol_hits + cache.symbol_misses;
                            let cache_str = if symbol_total > 0 {
                                format!(
                                    ", cache {}/{} ({:.0}%)",
                                    cache.symbol_hits,
                                    symbol_total,
                                    cache.symbol_hit_rate()
                                )
                            } else {
                                String::new()
                            };
                            lines.push(format!(
                                "      Indexing: {}ms ({} files{})",
                                indexing.total_time_ms, indexing.file_count, cache_str
                            ));
                            lines.extend(format_function_stats(
                                &indexing.functions,
                                "        ",
                                10,
                            ));
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

pub fn format_function_name(name: &str) -> &str {
    name.strip_prefix("leta_daemon::handlers::")
        .or_else(|| name.strip_prefix("leta_daemon::"))
        .or_else(|| name.strip_prefix("leta_lsp::"))
        .or_else(|| name.strip_prefix("leta_"))
        .unwrap_or(name)
        .trim_end_matches("::{{closure}}")
}

pub fn format_function_stats(
    functions: &[FunctionStats],
    indent: &str,
    max_lines: usize,
) -> Vec<String> {
    let mut lines = Vec::new();
    if functions.is_empty() {
        return lines;
    }
    lines.push(format!(
        "{}{:<50} {:>6} {:>10} {:>10} {:>10}",
        indent, "Function", "Calls", "Avg", "P90", "Total"
    ));
    for func in functions.iter().take(max_lines) {
        let name = format_function_name(&func.name);
        lines.push(format!(
            "{}{:<50} {:>6} {:>10} {:>10} {:>10}",
            indent,
            name,
            func.calls,
            format_duration_us(func.avg_us),
            format_duration_us(func.p90_us),
            format_duration_us(func.total_us),
        ));
    }
    lines
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
                let ref_str = m.reference.as_deref().unwrap_or("");
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
                if !detail.is_empty() && detail != "()" {
                    parts.push(format!("({})", detail));
                }
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

pub fn format_file_line(file: &FileInfo) -> String {
    format!(
        "{} ({}, {} lines)",
        file.path,
        format_size(file.bytes),
        file.lines
    )
}

/// Stateful printer for streaming file output with proper indentation.
/// Tracks the current directory path and emits directory headers when needed.
pub struct FileTreePrinter {
    current_path: Vec<String>,
}

impl FileTreePrinter {
    pub fn new() -> Self {
        Self {
            current_path: Vec::new(),
        }
    }

    /// Format a file with proper indentation, emitting directory headers as needed.
    /// Returns a string that may contain multiple lines (directory headers + file).
    pub fn format_file(&mut self, file: &FileInfo) -> String {
        let parts: Vec<&str> = file.path.split('/').collect();
        let (dirs, filename) = parts.split_at(parts.len().saturating_sub(1));

        let mut output = String::new();

        // Find where current path diverges from file path
        let mut common_depth = 0;
        for (i, dir) in dirs.iter().enumerate() {
            if i < self.current_path.len() && self.current_path[i] == *dir {
                common_depth = i + 1;
            } else {
                break;
            }
        }

        // Truncate current path to common prefix
        self.current_path.truncate(common_depth);

        // Add new directory headers
        for (i, dir) in dirs.iter().enumerate().skip(common_depth) {
            let indent = "  ".repeat(i);
            output.push_str(&format!("{}{}/\n", indent, dir));
            self.current_path.push(dir.to_string());
        }

        // Add the file
        let indent = "  ".repeat(dirs.len());
        let info_str = format!("{}, {} lines", format_size(file.bytes), file.lines);
        if let Some(name) = filename.first() {
            output.push_str(&format!("{}{} ({})", indent, name, info_str));
        }

        output
    }
}

impl Default for FileTreePrinter {
    fn default() -> Self {
        Self::new()
    }
}

pub fn format_symbol_line(sym: &SymbolInfo) -> String {
    let location = format!("{}:{}", sym.path, sym.line);
    let mut parts = vec![location, format!("[{}]", sym.kind), sym.name.clone()];
    if let Some(detail) = &sym.detail {
        if !detail.is_empty() && detail != "()" {
            parts.push(format!("({})", detail));
        }
    }
    if let Some(container) = &sym.container {
        parts.push(format!("in {}", container));
    }
    let mut output = parts.join(" ");

    if let Some(doc) = &sym.documentation {
        for doc_line in doc.trim().lines() {
            output.push_str(&format!("\n    {}", doc_line));
        }
    }
    output
}

fn format_symbols(symbols: &[SymbolInfo]) -> String {
    let mut lines = Vec::new();
    for sym in symbols {
        lines.push(format_symbol_line(sym));
        if sym.documentation.is_some() {
            lines.push(String::new());
        }
    }
    lines.join("\n")
}

pub fn format_size(size: u64) -> String {
    if size < 1024 {
        format!("{}B", size)
    } else if size < 1024 * 1024 {
        format!("{:.1}KB", size as f64 / 1024.0)
    } else {
        format!("{:.1}MB", size as f64 / (1024.0 * 1024.0))
    }
}

pub fn format_profiling(profiling: &ProfilingData) -> String {
    let mut lines = Vec::new();

    let cache = &profiling.cache;
    let symbol_total = cache.symbol_hits + cache.symbol_misses;
    let hover_total = cache.hover_hits + cache.hover_misses;

    if symbol_total > 0 || hover_total > 0 {
        lines.push("CACHE".to_string());
        if symbol_total > 0 {
            lines.push(format!(
                "  symbols: {}/{} hits ({:.1}%)",
                cache.symbol_hits,
                symbol_total,
                cache.symbol_hit_rate()
            ));
        }
        if hover_total > 0 {
            lines.push(format!(
                "  hover: {}/{} hits ({:.1}%)",
                cache.hover_hits,
                hover_total,
                cache.hover_hit_rate()
            ));
        }
        lines.push(String::new());
    }

    if let Some(tree) = &profiling.span_tree {
        lines.push(format!(
            "{:<55} {:>7} {:>9} {:>9} {:>9}",
            "Function", "Calls", "Avg", "P90", "Total"
        ));
        lines.push("-".repeat(90));

        for root in &tree.roots {
            format_span_node(root, &mut lines, 0, &tree.functions);
        }

        lines.push("-".repeat(90));
        lines.push(format!(
            "{:<55} {:>7} {:>9} {:>9} {:>9}",
            "TOTAL",
            "",
            "",
            "",
            format_duration_us(tree.total_us)
        ));
    }

    lines.join("\n")
}

fn get_func_stats<'a>(name: &str, functions: &'a [FunctionStats]) -> Option<&'a FunctionStats> {
    functions.iter().find(|f| f.name == name)
}

fn format_span_node(
    node: &SpanNode,
    lines: &mut Vec<String>,
    depth: usize,
    functions: &[FunctionStats],
) {
    let indent = " ".repeat(depth);
    let parallel_marker = if node.is_parallel { " ||" } else { "" };

    let stats = get_func_stats(&node.name, functions);
    let (calls, avg, p90) = if let Some(s) = stats {
        (s.calls, s.avg_us, s.p90_us)
    } else {
        (
            node.calls,
            if node.calls > 0 {
                node.total_us / node.calls as u64
            } else {
                0
            },
            0,
        )
    };

    let name_with_indent = format!("{}{}{}", indent, node.name, parallel_marker);

    lines.push(format!(
        "{:<55} {:>7} {:>9} {:>9} {:>9}",
        truncate_left(&name_with_indent, 55),
        calls,
        format_duration_us(avg),
        format_duration_us(p90),
        format_duration_us(node.total_us)
    ));

    // Show properties if any - extract timing info from properties
    let mut property_time_ms = 0.0f64;
    if !node.properties.is_empty() {
        let props_indent = " ".repeat(depth + 1);

        // Aggregate properties by key, summing numeric values for _ms keys
        let mut aggregated: std::collections::HashMap<&str, (f64, u32)> =
            std::collections::HashMap::new();
        for (k, v) in &node.properties {
            if k.ends_with("_ms") {
                if let Ok(ms) = v.parse::<f64>() {
                    property_time_ms += ms;
                    let entry = aggregated.entry(k.as_str()).or_insert((0.0, 0));
                    entry.0 += ms;
                    entry.1 += 1;
                }
            } else if let Ok(num) = v.parse::<f64>() {
                let entry = aggregated.entry(k.as_str()).or_insert((0.0, 0));
                entry.0 += num;
                entry.1 += 1;
            } else {
                // Non-numeric properties just count occurrences
                let entry = aggregated.entry(k.as_str()).or_insert((0.0, 0));
                entry.1 += 1;
            }
        }

        // Format aggregated properties
        let mut props_str: Vec<String> = aggregated
            .iter()
            .map(|(k, (sum, count))| {
                if *count > 1 {
                    if k.ends_with("_ms") {
                        format!(
                            "{}={:.1}ms total ({} calls)",
                            k.trim_end_matches("_ms"),
                            sum,
                            count
                        )
                    } else {
                        format!("{}={:.0} total", k, sum)
                    }
                } else if k.ends_with("_ms") {
                    format!("{}={:.1}ms", k.trim_end_matches("_ms"), sum)
                } else {
                    format!("{}={:.0}", k, sum)
                }
            })
            .collect();
        props_str.sort();

        lines.push(format!("{}  [{}]", props_indent, props_str.join(", ")));
    }

    for child in &node.children {
        format_span_node(child, lines, depth + 1, functions);
    }

    // Only show unaccounted if:
    // 1. There's significant unaccounted time (> 1ms)
    // 2. There are children (otherwise all time is "self")
    // 3. Properties don't already explain most of the time
    let property_time_us = (property_time_ms * 1000.0) as u64;
    let truly_unaccounted = node.self_us.saturating_sub(property_time_us);

    if truly_unaccounted > 1000 && !node.children.is_empty() {
        let unaccounted_name = format!("{}[unaccounted]", " ".repeat(depth + 1));
        lines.push(format!(
            "{:<55} {:>7} {:>9} {:>9} {:>9}",
            unaccounted_name,
            "",
            "",
            "",
            format_duration_us(truly_unaccounted)
        ));
    }
}

fn truncate_left(s: &str, max_len: usize) -> String {
    if s.len() <= max_len {
        s.to_string()
    } else {
        format!("…{}", &s[s.len() - max_len + 1..])
    }
}

enum TreeNode {
    File(FileInfo),
    Dir(HashMap<String, TreeNode>),
    ExcludedDir,
}

fn build_tree(
    files: &HashMap<String, FileInfo>,
    excluded_dirs: &[String],
) -> HashMap<String, TreeNode> {
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

    for excluded_path in excluded_dirs {
        let parts: Vec<&str> = excluded_path.split('/').collect();
        let mut current = &mut tree;

        for (i, part) in parts.iter().enumerate() {
            if i == parts.len() - 1 {
                current
                    .entry(part.to_string())
                    .or_insert(TreeNode::ExcludedDir);
            } else {
                current = match current
                    .entry(part.to_string())
                    .or_insert_with(|| TreeNode::Dir(HashMap::new()))
                {
                    TreeNode::Dir(map) => map,
                    _ => break,
                };
            }
        }
    }

    tree
}

fn render_tree(node: &HashMap<String, TreeNode>, lines: &mut Vec<String>, indent: usize) {
    let mut entries: Vec<_> = node.keys().collect();
    entries.sort();

    let prefix = "  ".repeat(indent);

    for name in entries {
        let child = node.get(name).unwrap();

        match child {
            TreeNode::File(info) => {
                let info_str = format_file_info(info);
                lines.push(format!("{}{} ({})", prefix, name, info_str));
            }
            TreeNode::Dir(children) => {
                lines.push(format!("{}{}/", prefix, name));
                render_tree(children, lines, indent + 1);
            }
            TreeNode::ExcludedDir => {
                lines.push(format!("{}{} (excluded)", prefix, name));
            }
        }
    }
}

fn format_file_info(info: &FileInfo) -> String {
    format!("{}, {} lines", format_size(info.bytes), info.lines)
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

fn should_show_detail(detail: &Option<String>) -> bool {
    detail
        .as_ref()
        .map(|d| !d.is_empty() && d != "()")
        .unwrap_or(false)
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
    if should_show_detail(&node.detail) {
        parts.push(format!("({})", node.detail.as_ref().unwrap()));
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
        if should_show_detail(&item.detail) {
            parts.push(format!("({})", item.detail.as_ref().unwrap()));
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
        if should_show_detail(&item.detail) {
            parts.push(format!("({})", item.detail.as_ref().unwrap()));
        }

        let arrow = if i == 0 { "" } else { "  → " };
        lines.push(format!("{}{}", arrow, parts.join(" ")));
    }

    lines.join("\n")
}
