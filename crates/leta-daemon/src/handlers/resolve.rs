use std::collections::HashSet;
use std::path::{Path, PathBuf};

use leta_fs::get_language_id;
use leta_lsp::lsp_types::{DocumentSymbolParams, TextDocumentIdentifier};
use leta_servers::get_server_for_language;
use leta_types::{ResolveSymbolParams, ResolveSymbolResult, SymbolInfo};
use regex::Regex;

use super::{flatten_document_symbols, relative_path, HandlerContext};

pub async fn handle_resolve_symbol(
    ctx: &HandlerContext,
    params: ResolveSymbolParams,
) -> Result<ResolveSymbolResult, String> {
    let workspace_root = PathBuf::from(&params.workspace_root);
    let symbol_path = params.symbol_path.clone();

    let (path_filter, line_filter, symbol_name) = parse_symbol_path(&symbol_path)?;
    let parts: Vec<&str> = symbol_name.split('.').collect();

    let all_symbols = collect_all_symbols(ctx, &workspace_root).await?;

    let mut filtered = all_symbols;

    if let Some(ref pf) = path_filter {
        filtered = filtered.into_iter()
            .filter(|s| matches_path(&s.path, pf))
            .collect();
    }

    if let Some(line) = line_filter {
        filtered = filtered.into_iter()
            .filter(|s| s.line == line)
            .collect();
    }

    let target_name = parts.last().unwrap_or(&"");
    
    let matches: Vec<SymbolInfo> = if parts.len() == 1 {
        filtered.into_iter()
            .filter(|s| name_matches(&s.name, target_name))
            .collect()
    } else {
        let container_parts = &parts[..parts.len() - 1];
        let container_str = container_parts.join(".");
        let full_qualified = symbol_name.clone();

        filtered.into_iter()
            .filter(|sym| {
                let sym_name = &sym.name;
                
                let go_style = format!("(*{}).{}", container_str, target_name);
                let go_style_val = format!("({}).{}", container_str, target_name);
                if sym_name == &go_style || sym_name == &go_style_val {
                    return true;
                }

                // Go generics: (*Result[T]).IsOk should match Result.IsOk
                if let Some(go_match) = extract_go_method_parts(sym_name) {
                    if go_match.method == target_name && strip_generics(&go_match.receiver) == container_str {
                        return true;
                    }
                }

                if sym_name == &full_qualified {
                    return true;
                }
                
                let lua_colon = format!("{}:{}", container_str, target_name);
                if sym_name == &lua_colon {
                    return true;
                }

                if !name_matches(sym_name, target_name) {
                    return false;
                }

                let sym_container = sym.container.as_deref().unwrap_or("");
                let normalized_container = normalize_container(sym_container);
                let module_name = get_module_name(&sym.path);

                let full_container = if normalized_container.is_empty() {
                    module_name.clone()
                } else {
                    format!("{}.{}", module_name, normalized_container)
                };

                normalized_container == container_str
                    || sym_container == container_str
                    || strip_generics(&normalized_container) == container_str
                    || strip_generics(sym_container) == container_str
                    || full_container == container_str
                    || full_container.ends_with(&format!(".{}", container_str))
                    || (container_parts.len() == 1 && container_parts[0] == module_name)
            })
            .collect()
    };

    if matches.is_empty() {
        let mut error_msg = format!("Symbol '{}' not found", symbol_name);
        if let Some(pf) = &path_filter {
            error_msg.push_str(&format!(" in files matching '{}'", pf));
        }
        if let Some(line) = line_filter {
            error_msg.push_str(&format!(" on line {}", line));
        }
        return Ok(ResolveSymbolResult {
            error: Some(error_msg),
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
        });
    }

    let preferred_kinds: HashSet<&str> = [
        "Class", "Struct", "Interface", "Enum", "Module", "Namespace", "Package"
    ].into_iter().collect();
    
    let type_matches: Vec<&SymbolInfo> = matches.iter()
        .filter(|m| preferred_kinds.contains(m.kind.as_str()))
        .collect();
    
    let final_matches = if type_matches.len() == 1 && matches.len() > 1 {
        vec![type_matches[0].clone()]
    } else {
        matches.clone()
    };

    if final_matches.len() == 1 {
        let sym = &final_matches[0];
        return Ok(ResolveSymbolResult::success(
            format!("{}/{}", workspace_root.display(), sym.path),
            sym.line,
            sym.column,
            Some(sym.name.clone()),
            Some(sym.kind.clone()),
            sym.container.clone(),
            sym.range_start_line,
            sym.range_end_line,
        ));
    }

    let matches_info: Vec<SymbolInfo> = final_matches.iter()
        .take(10)
        .map(|sym| {
            SymbolInfo {
                name: sym.name.clone(),
                kind: sym.kind.clone(),
                path: sym.path.clone(),
                line: sym.line,
                column: sym.column,
                container: sym.container.clone(),
                detail: None,  // Don't include detail in ambiguous matches
                documentation: None,
                range_start_line: None,
                range_end_line: None,
                reference: Some(generate_unambiguous_ref(sym, &final_matches, target_name)),
            }
        })
        .collect();

    Ok(ResolveSymbolResult::ambiguous(&symbol_name, matches_info, final_matches.len() as u32))
}

fn parse_symbol_path(symbol_path: &str) -> Result<(Option<String>, Option<u32>, String), String> {
    let colon_count = symbol_path.matches(':').count();
    
    match colon_count {
        0 => Ok((None, None, symbol_path.to_string())),
        1 => {
            let parts: Vec<&str> = symbol_path.splitn(2, ':').collect();
            Ok((Some(parts[0].to_string()), None, parts[1].to_string()))
        }
        2 => {
            let parts: Vec<&str> = symbol_path.splitn(3, ':').collect();
            let line: u32 = parts[1].parse()
                .map_err(|_| format!("Invalid line number: '{}'", parts[1]))?;
            Ok((Some(parts[0].to_string()), Some(line), parts[2].to_string()))
        }
        _ => Err(format!("Invalid symbol path format: '{}'", symbol_path)),
    }
}

fn matches_path(rel_path: &str, filter: &str) -> bool {
    if glob_match(rel_path, filter) {
        return true;
    }
    if glob_match(rel_path, &format!("**/{}", filter)) {
        return true;
    }
    if glob_match(rel_path, &format!("{}/**", filter)) {
        return true;
    }
    if !filter.contains('/') {
        let filename = Path::new(rel_path).file_name().and_then(|s| s.to_str()).unwrap_or("");
        if glob_match(filename, filter) {
            return true;
        }
        let parts: Vec<&str> = Path::new(rel_path).iter().filter_map(|s| s.to_str()).collect();
        if parts.contains(&filter) {
            return true;
        }
    }
    false
}

fn glob_match(text: &str, pattern: &str) -> bool {
    let regex_pattern = pattern
        .replace('.', r"\.")
        .replace("**", "§§")
        .replace('*', "[^/]*")
        .replace("§§", ".*")
        .replace('?', ".");
    Regex::new(&format!("^{}$", regex_pattern))
        .map(|r| r.is_match(text))
        .unwrap_or(false)
}

fn name_matches(sym_name: &str, target: &str) -> bool {
    if sym_name == target {
        return true;
    }
    normalize_symbol_name(sym_name) == target
}

fn normalize_symbol_name(name: &str) -> String {
    if let Some(captures) = Regex::new(r"^(\w+)\([^)]*\)$").ok().and_then(|r| r.captures(name)) {
        return captures.get(1).map(|m| m.as_str().to_string()).unwrap_or_else(|| name.to_string());
    }
    // Go method: (*Type).Method or (Type).Method, including generics like (*Result[T]).IsOk
    if let Some(captures) = Regex::new(r"^\(\*?[^)]+\)\.(\w+)$").ok().and_then(|r| r.captures(name)) {
        return captures.get(1).map(|m| m.as_str().to_string()).unwrap_or_else(|| name.to_string());
    }
    if name.contains(':') {
        return name.split(':').last().unwrap_or(name).to_string();
    }
    name.to_string()
}

struct GoMethodParts {
    receiver: String,
    method: String,
}

fn extract_go_method_parts(name: &str) -> Option<GoMethodParts> {
    // Match (*Type).Method or (Type).Method, including generics like (*Result[T]).IsOk
    let re = Regex::new(r"^\(\*?([^)]+)\)\.(\w+)$").ok()?;
    let captures = re.captures(name)?;
    Some(GoMethodParts {
        receiver: captures.get(1)?.as_str().to_string(),
        method: captures.get(2)?.as_str().to_string(),
    })
}

fn strip_generics(name: &str) -> String {
    if let Some(idx) = name.find('[') {
        name[..idx].to_string()
    } else {
        name.to_string()
    }
}

fn normalize_container(container: &str) -> String {
    if let Some(captures) = Regex::new(r"^\(\*?(\w+)\)$").ok().and_then(|r| r.captures(container)) {
        return captures.get(1).map(|m| m.as_str().to_string()).unwrap_or_else(|| container.to_string());
    }
    if let Some(captures) = Regex::new(r"^impl\s+\w+(?:<[^>]+>)?\s+for\s+(\w+)").ok().and_then(|r| r.captures(container)) {
        return captures.get(1).map(|m| m.as_str().to_string()).unwrap_or_else(|| container.to_string());
    }
    if let Some(captures) = Regex::new(r"^impl\s+(\w+)").ok().and_then(|r| r.captures(container)) {
        return captures.get(1).map(|m| m.as_str().to_string()).unwrap_or_else(|| container.to_string());
    }
    container.to_string()
}

fn get_module_name(rel_path: &str) -> String {
    Path::new(rel_path)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_string()
}

fn get_effective_container(sym: &SymbolInfo) -> String {
    if let Some(ref container) = sym.container {
        if !container.is_empty() {
            return normalize_container(container);
        }
    }
    
    if let Some(captures) = Regex::new(r"^\(\*?(\w+)\)\.").ok().and_then(|r| r.captures(&sym.name)) {
        return captures.get(1).map(|m| m.as_str().to_string()).unwrap_or_default();
    }
    
    String::new()
}

fn generate_unambiguous_ref(sym: &SymbolInfo, all_matches: &[SymbolInfo], target_name: &str) -> String {
    let filename = Path::new(&sym.path).file_name().and_then(|s| s.to_str()).unwrap_or("");
    let normalized_name = normalize_symbol_name(target_name);
    let effective_container = get_effective_container(sym);

    if !effective_container.is_empty() {
        let ref_str = format!("{}.{}", effective_container, normalized_name);
        if ref_resolves_uniquely(&ref_str, sym, all_matches) {
            return ref_str;
        }
    }

    let ref_str = format!("{}:{}", filename, normalized_name);
    if ref_resolves_uniquely(&ref_str, sym, all_matches) {
        return ref_str;
    }

    if !effective_container.is_empty() {
        let ref_str = format!("{}:{}.{}", filename, effective_container, normalized_name);
        if ref_resolves_uniquely(&ref_str, sym, all_matches) {
            return ref_str;
        }
    }

    format!("{}:{}:{}", filename, sym.line, normalized_name)
}

fn ref_resolves_uniquely(ref_str: &str, target_sym: &SymbolInfo, all_matches: &[SymbolInfo]) -> bool {
    let (path_filter, line_filter, symbol_part) = match parse_symbol_path(ref_str) {
        Ok(p) => p,
        Err(_) => return false,
    };

    let mut candidates = all_matches.to_vec();

    if let Some(ref pf) = path_filter {
        let filename = pf.clone();
        candidates = candidates.into_iter()
            .filter(|s| {
                Path::new(&s.path).file_name().and_then(|f| f.to_str()) == Some(&filename)
            })
            .collect();
    }

    if let Some(line) = line_filter {
        candidates = candidates.into_iter()
            .filter(|s| s.line == line)
            .collect();
    }

    let parts: Vec<&str> = symbol_part.split('.').collect();
    if parts.len() == 1 {
        candidates = candidates.into_iter()
            .filter(|s| normalize_symbol_name(&s.name) == parts[0])
            .collect();
    } else {
        let container_str = parts[..parts.len() - 1].join(".");
        let target_name = parts.last().unwrap();
        candidates = candidates.into_iter()
            .filter(|s| {
                if normalize_symbol_name(&s.name) != *target_name {
                    return false;
                }
                get_effective_container(s) == container_str
            })
            .collect();
    }

    candidates.len() == 1 && candidates[0].path == target_sym.path && candidates[0].line == target_sym.line
}

async fn collect_all_symbols(ctx: &HandlerContext, workspace_root: &PathBuf) -> Result<Vec<SymbolInfo>, String> {
    let skip_dirs: HashSet<&str> = [
        "node_modules", "__pycache__", ".git", "venv", ".venv",
        "build", "dist", ".tox", ".eggs", "target",
    ].into_iter().collect();

    let config = ctx.session.config().await;
    let excluded_languages: HashSet<String> = config
        .workspaces
        .excluded_languages
        .iter()
        .cloned()
        .collect();

    let mut files_by_lang: std::collections::HashMap<String, Vec<PathBuf>> = std::collections::HashMap::new();

    for entry in walkdir::WalkDir::new(workspace_root)
        .into_iter()
        .filter_entry(|e| {
            let name = e.file_name().to_string_lossy();
            !name.starts_with('.') && !skip_dirs.contains(name.as_ref()) && !name.ends_with(".egg-info")
        })
    {
        let entry = match entry {
            Ok(e) => e,
            Err(_) => continue,
        };

        if !entry.file_type().is_file() {
            continue;
        }

        let path = entry.path();
        let lang = get_language_id(path);
        
        if lang == "plaintext" || excluded_languages.contains(lang) {
            continue;
        }
        
        if get_server_for_language(&lang, None).is_none() {
            continue;
        }

        files_by_lang.entry(lang.to_string()).or_default().push(path.to_path_buf());
    }

    let mut all_symbols = Vec::new();

    for (lang, files) in files_by_lang {
        let workspace = match ctx.session.get_or_create_workspace_for_language(&lang, workspace_root).await {
            Ok(ws) => ws,
            Err(_) => continue,
        };

        workspace.wait_for_ready(30).await;

        let client = match workspace.client().await {
            Some(c) => c,
            None => continue,
        };

        for file_path in files {
            if workspace.ensure_document_open(&file_path).await.is_err() {
                continue;
            }

            let uri = leta_fs::path_to_uri(&file_path);
            let response: Option<leta_lsp::lsp_types::DocumentSymbolResponse> = client
                .send_request(
                    "textDocument/documentSymbol",
                    DocumentSymbolParams {
                        text_document: TextDocumentIdentifier { uri: uri.parse().unwrap() },
                        work_done_progress_params: Default::default(),
                        partial_result_params: Default::default(),
                    },
                )
                .await
                .ok()
                .flatten();

            if let Some(resp) = response {
                let rel_path = relative_path(&file_path, workspace_root);
                let symbols = flatten_document_symbols(&resp, &rel_path);
                all_symbols.extend(symbols);
            }
        }
    }

    Ok(all_symbols)
}
