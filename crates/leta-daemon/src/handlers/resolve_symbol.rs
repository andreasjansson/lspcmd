use std::path::{Path, PathBuf};

use regex::Regex;
use serde_json::{json, Value};

use super::{collect_all_workspace_symbols, HandlerContext, SymbolDict};

pub async fn handle_resolve_symbol(ctx: &HandlerContext, params: Value) -> Result<Value, String> {
    let workspace_root = PathBuf::from(
        params.get("workspace_root")
            .and_then(|v| v.as_str())
            .ok_or("Missing workspace_root")?
    );
    let symbol_path = params.get("symbol_path")
        .and_then(|v| v.as_str())
        .ok_or("Missing symbol_path")?
        .to_string();

    let mut path_filter: Option<String> = None;
    let mut line_filter: Option<u32> = None;
    let mut symbol_name = symbol_path.clone();

    let colon_count = symbol_path.matches(':').count();
    if colon_count == 2 {
        let parts: Vec<&str> = symbol_path.splitn(3, ':').collect();
        path_filter = Some(parts[0].to_string());
        line_filter = parts[1].parse().ok();
        if line_filter.is_none() {
            return Ok(json!({"error": format!("Invalid line number: '{}'", parts[1])}));
        }
        symbol_name = parts[2].to_string();
    } else if colon_count == 1 {
        let parts: Vec<&str> = symbol_path.splitn(2, ':').collect();
        path_filter = Some(parts[0].to_string());
        symbol_name = parts[1].to_string();
    }

    let parts: Vec<&str> = symbol_name.split('.').collect();
    let target_name = parts.last().unwrap_or(&"").to_string();

    let mut all_symbols = collect_all_workspace_symbols(ctx, &workspace_root).await?;

    if let Some(ref filter) = path_filter {
        all_symbols.retain(|s| matches_path(&s.path, filter));
    }

    if let Some(line) = line_filter {
        all_symbols.retain(|s| s.line == line);
    }

    let matches: Vec<SymbolDict> = if parts.len() == 1 {
        all_symbols.into_iter().filter(|s| {
            name_matches(&s.name, &target_name) || s.name.ends_with(&format!(").{}", target_name))
        }).collect()
    } else {
        let container_parts = &parts[..parts.len() - 1];
        let container_str = container_parts.join(".");
        let full_qualified = &symbol_name;

        all_symbols.into_iter().filter(|sym| {
            let sym_name = &sym.name;

            let go_style_name = format!("(*{}).{}", container_str, target_name);
            let go_style_name_val = format!("({}).{}", container_str, target_name);
            if sym_name == &go_style_name || sym_name == &go_style_name_val {
                return true;
            }

            if sym_name == full_qualified {
                return true;
            }

            let lua_colon_name = format!("{}:{}", container_str, target_name);
            if sym_name == &lua_colon_name {
                return true;
            }

            if !name_matches(sym_name, &target_name) {
                return false;
            }

            let sym_container = sym.container.as_deref().unwrap_or("");
            let sym_container_normalized = normalize_container(sym_container);
            let module_name = get_module_name(&sym.path);
            
            let full_container = if sym_container_normalized.is_empty() {
                module_name.clone()
            } else {
                format!("{}.{}", module_name, sym_container_normalized)
            };

            sym_container_normalized == container_str
                || sym_container == container_str
                || full_container == container_str
                || full_container.ends_with(&format!(".{}", container_str))
                || (container_parts.len() == 1 && container_parts[0] == module_name)
        }).collect()
    };

    if matches.is_empty() {
        let mut error_parts = Vec::new();
        if let Some(ref filter) = path_filter {
            error_parts.push(format!("in files matching '{}'", filter));
        }
        if let Some(line) = line_filter {
            error_parts.push(format!("on line {}", line));
        }
        let suffix = if error_parts.is_empty() {
            String::new()
        } else {
            format!(" {}", error_parts.join(" "))
        };
        return Ok(json!({"error": format!("Symbol '{}' not found{}", symbol_name, suffix)}));
    }

    let preferred_kinds = ["Class", "Struct", "Interface", "Enum", "Module", "Namespace", "Package"];
    let type_matches: Vec<&SymbolDict> = matches.iter()
        .filter(|m| preferred_kinds.contains(&m.kind.as_str()))
        .collect();
    
    let final_matches = if type_matches.len() == 1 && matches.len() > 1 {
        vec![type_matches[0].clone()]
    } else {
        matches
    };

    if final_matches.len() == 1 {
        let sym = &final_matches[0];
        return Ok(json!({
            "path": format!("{}/{}", workspace_root.display(), sym.path),
            "line": sym.line,
            "column": sym.column,
            "name": sym.name,
            "kind": sym.kind,
            "container": sym.container,
            "range_start_line": sym.range_start_line,
            "range_end_line": sym.range_end_line,
        }));
    }

    let matches_info: Vec<Value> = final_matches.iter().take(10).map(|sym| {
        let ref_str = generate_unambiguous_ref(sym, &final_matches, &target_name);
        json!({
            "name": sym.name,
            "kind": sym.kind,
            "path": sym.path,
            "line": sym.line,
            "column": sym.column,
            "container": sym.container,
            "ref": ref_str,
        })
    }).collect();

    Ok(json!({
        "error": format!("Symbol '{}' is ambiguous ({} matches)", symbol_name, final_matches.len()),
        "matches": matches_info,
        "total_matches": final_matches.len(),
    }))
}

fn name_matches(sym_name: &str, target: &str) -> bool {
    if sym_name == target {
        return true;
    }
    normalize_symbol_name(sym_name) == target
}

fn normalize_symbol_name(name: &str) -> String {
    let func_pattern = Regex::new(r"^(\w+)\([^)]*\)$").unwrap();
    if let Some(caps) = func_pattern.captures(name) {
        return caps.get(1).map(|m| m.as_str().to_string()).unwrap_or_default();
    }

    let go_pattern = Regex::new(r"^\(\*?\w+\)\.(\w+)$").unwrap();
    if let Some(caps) = go_pattern.captures(name) {
        return caps.get(1).map(|m| m.as_str().to_string()).unwrap_or_default();
    }

    if name.contains(':') {
        return name.split(':').last().unwrap_or("").to_string();
    }

    name.to_string()
}

fn normalize_container(container: &str) -> String {
    let go_pattern = Regex::new(r"^\(\*?(\w+)\)$").unwrap();
    if let Some(caps) = go_pattern.captures(container) {
        return caps.get(1).map(|m| m.as_str().to_string()).unwrap_or_default();
    }

    let impl_for_pattern = Regex::new(r"^impl\s+\w+(?:<[^>]+>)?\s+for\s+(\w+)").unwrap();
    if let Some(caps) = impl_for_pattern.captures(container) {
        return caps.get(1).map(|m| m.as_str().to_string()).unwrap_or_default();
    }

    let impl_pattern = Regex::new(r"^impl\s+(\w+)").unwrap();
    if let Some(caps) = impl_pattern.captures(container) {
        return caps.get(1).map(|m| m.as_str().to_string()).unwrap_or_default();
    }

    container.to_string()
}

fn get_effective_container(sym: &SymbolDict) -> String {
    if let Some(ref container) = sym.container {
        if !container.is_empty() {
            return normalize_container(container);
        }
    }

    let go_pattern = Regex::new(r"^\(\*?(\w+)\)\.").unwrap();
    if let Some(caps) = go_pattern.captures(&sym.name) {
        return caps.get(1).map(|m| m.as_str().to_string()).unwrap_or_default();
    }

    String::new()
}

fn get_module_name(rel_path: &str) -> String {
    Path::new(rel_path)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_string()
}

fn matches_path(rel_path: &str, filter: &str) -> bool {
    if glob_match(filter, rel_path) {
        return true;
    }
    if glob_match(&format!("**/{}", filter), rel_path) {
        return true;
    }
    if glob_match(&format!("{}/**", filter), rel_path) {
        return true;
    }
    if !filter.contains('/') {
        let filename = Path::new(rel_path).file_name().and_then(|f| f.to_str()).unwrap_or("");
        if glob_match(filter, filename) {
            return true;
        }
        let parts: Vec<&str> = Path::new(rel_path).iter().filter_map(|s| s.to_str()).collect();
        if parts.contains(&filter) {
            return true;
        }
    }
    false
}

fn glob_match(pattern: &str, text: &str) -> bool {
    if let Ok(glob) = globset::Glob::new(pattern) {
        glob.compile_matcher().is_match(text)
    } else {
        false
    }
}

fn generate_unambiguous_ref(sym: &SymbolDict, all_matches: &[SymbolDict], target_name: &str) -> String {
    let filename = Path::new(&sym.path).file_name().and_then(|f| f.to_str()).unwrap_or("");
    let sym_container = get_effective_container(sym);
    let normalized_name = normalize_symbol_name(target_name);

    if !sym_container.is_empty() {
        let ref_str = format!("{}.{}", sym_container, normalized_name);
        if ref_resolves_uniquely(&ref_str, sym, all_matches) {
            return ref_str;
        }
    }

    let ref_str = format!("{}:{}", filename, normalized_name);
    if ref_resolves_uniquely(&ref_str, sym, all_matches) {
        return ref_str;
    }

    if !sym_container.is_empty() {
        let ref_str = format!("{}:{}.{}", filename, sym_container, normalized_name);
        if ref_resolves_uniquely(&ref_str, sym, all_matches) {
            return ref_str;
        }
    }

    format!("{}:{}:{}", filename, sym.line, normalized_name)
}

fn ref_resolves_uniquely(ref_str: &str, target_sym: &SymbolDict, all_matches: &[SymbolDict]) -> bool {
    let mut path_filter: Option<&str> = None;
    let mut symbol_path = ref_str;

    let colon_count = ref_str.matches(':').count();
    if colon_count >= 1 {
        let parts: Vec<&str> = ref_str.splitn(3, ':').collect();
        if colon_count == 1 {
            path_filter = Some(parts[0]);
            symbol_path = parts[1];
        } else if colon_count == 2 {
            path_filter = Some(parts[0]);
            if let Ok(line) = parts[1].parse::<u32>() {
                let matching: Vec<&SymbolDict> = all_matches.iter()
                    .filter(|s| {
                        let filename = Path::new(&s.path).file_name().and_then(|f| f.to_str()).unwrap_or("");
                        filename == path_filter.unwrap_or("") && s.line == line
                    })
                    .collect();
                return matching.len() == 1 && std::ptr::eq(matching[0], target_sym);
            }
            symbol_path = if parts.len() > 2 { parts[2] } else { parts[1] };
        }
    }

    let candidates: Vec<&SymbolDict> = if let Some(filter) = path_filter {
        all_matches.iter()
            .filter(|s| {
                let filename = Path::new(&s.path).file_name().and_then(|f| f.to_str()).unwrap_or("");
                filename == filter
            })
            .collect()
    } else {
        all_matches.iter().collect()
    };

    let sym_parts: Vec<&str> = symbol_path.split('.').collect();
    let matching: Vec<&SymbolDict> = if sym_parts.len() == 1 {
        candidates.iter()
            .filter(|s| normalize_symbol_name(&s.name) == sym_parts[0])
            .copied()
            .collect()
    } else {
        let container_str = sym_parts[..sym_parts.len() - 1].join(".");
        let name = sym_parts.last().unwrap_or(&"");

        candidates.iter().filter(|s| {
            if normalize_symbol_name(&s.name) != *name {
                return false;
            }

            let s_container = s.container.as_deref().unwrap_or("");
            let s_container_normalized = normalize_container(s_container);
            let s_module = get_module_name(&s.path);
            let full_container = if s_container_normalized.is_empty() {
                s_module.clone()
            } else {
                format!("{}.{}", s_module, s_container_normalized)
            };
            let s_effective_container = get_effective_container(s);

            s_container_normalized == container_str
                || s_container == container_str
                || s_effective_container == container_str
                || full_container == container_str
                || full_container.ends_with(&format!(".{}", container_str))
                || (sym_parts.len() == 2 && sym_parts[0] == s_module)
        }).copied().collect()
    };

    matching.len() == 1 && std::ptr::eq(matching[0], target_sym)
}
