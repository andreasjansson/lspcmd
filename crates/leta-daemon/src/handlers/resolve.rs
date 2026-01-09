use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

use fastrace::trace;
use leta_types::{ResolveSymbolParams, ResolveSymbolResult, SymbolInfo};
use regex::Regex;

use super::{collect_all_workspace_symbols, relative_path, HandlerContext};

static RE_FUNC_WITH_PARAMS: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^(\w+)\([^)]*\)$").unwrap());
static RE_GO_METHOD: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^\(\*?[^)]+\)\.(\w+)$").unwrap());
static RE_GO_METHOD_PARTS: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^\(\*?([^)]+)\)\.(\w+)$").unwrap());
static RE_CONTAINER_PTR: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^\(\*?(\w+)\)$").unwrap());
static RE_IMPL_FOR: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^impl\s+\w+(?:<[^>]+>)?\s+for\s+(\w+)").unwrap());
static RE_IMPL: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^impl\s+(\w+)").unwrap());
static RE_EFFECTIVE_CONTAINER: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^\(\*?(\w+)\)\.").unwrap());

#[trace]
pub async fn handle_resolve_symbol(
    ctx: &HandlerContext,
    params: ResolveSymbolParams,
) -> Result<ResolveSymbolResult, String> {
    let workspace_root = PathBuf::from(&params.workspace_root);
    let symbol_path = params.symbol_path.clone();

    let all_symbols = collect_all_workspace_symbols(ctx, &workspace_root).await?;

    if looks_like_lua_method(&symbol_path) {
        let matches: Vec<SymbolInfo> = all_symbols
            .iter()
            .filter(|s| s.name == symbol_path)
            .cloned()
            .collect();
        if matches.len() == 1 {
            let sym = &matches[0];
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
    }

    let (path_filter, line_filter, symbol_name) = parse_symbol_path(&symbol_path)?;
    let matches = filter_symbols(
        &all_symbols,
        path_filter.as_deref(),
        line_filter,
        &symbol_name,
    );

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
        "Class",
        "Struct",
        "Interface",
        "Enum",
        "Module",
        "Namespace",
        "Package",
    ]
    .into_iter()
    .collect();

    let type_matches: Vec<&SymbolInfo> = matches
        .iter()
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

    let parts: Vec<&str> = symbol_name.split('.').collect();
    let target_name = parts.last().unwrap_or(&"");

    let matches_info: Vec<SymbolInfo> = final_matches
        .iter()
        .take(10)
        .map(|sym| SymbolInfo {
            name: sym.name.clone(),
            kind: sym.kind.clone(),
            path: sym.path.clone(),
            line: sym.line,
            column: sym.column,
            container: sym.container.clone(),
            detail: None,
            documentation: None,
            range_start_line: None,
            range_end_line: None,
            reference: Some(generate_unambiguous_ref(sym, &final_matches, target_name)),
        })
        .collect();

    Ok(ResolveSymbolResult::ambiguous(
        &symbol_name,
        matches_info,
        final_matches.len() as u32,
    ))
}

#[trace]
fn filter_symbols(
    all_symbols: &[SymbolInfo],
    path_filter: Option<&str>,
    line_filter: Option<u32>,
    symbol_name: &str,
) -> Vec<SymbolInfo> {
    let parts: Vec<&str> = symbol_name.split('.').collect();
    let target_name = parts.last().unwrap_or(&"");

    let mut filtered: Vec<&SymbolInfo> = if let Some(pf) = path_filter {
        all_symbols
            .iter()
            .filter(|s| matches_path(&s.path, pf))
            .collect()
    } else {
        all_symbols.iter().collect()
    };

    if let Some(line) = line_filter {
        filtered = filtered.into_iter().filter(|s| s.line == line).collect();
    }

    if parts.len() == 1 {
        filtered
            .into_iter()
            .filter(|s| name_matches(&s.name, target_name))
            .cloned()
            .collect()
    } else {
        let container_parts = &parts[..parts.len() - 1];
        let container_str = container_parts.join(".");
        let full_qualified = symbol_name.to_string();

        filtered
            .into_iter()
            .filter(|sym| {
                symbol_matches_qualified(sym, target_name, &container_str, &full_qualified)
            })
            .cloned()
            .collect()
    }
}

#[trace]
fn symbol_matches_qualified(
    sym: &SymbolInfo,
    target_name: &str,
    container_str: &str,
    full_qualified: &str,
) -> bool {
    let sym_name = &sym.name;

    let go_style = format!("(*{}).{}", container_str, target_name);
    let go_style_val = format!("({}).{}", container_str, target_name);
    if sym_name == &go_style || sym_name == &go_style_val {
        return true;
    }

    if let Some(go_match) = extract_go_method_parts(sym_name) {
        if go_match.method == target_name && strip_generics(&go_match.receiver) == container_str {
            return true;
        }
    }

    if sym_name == full_qualified {
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

    let container_parts: Vec<&str> = container_str.split('.').collect();

    normalized_container == container_str
        || sym_container == container_str
        || strip_generics(&normalized_container) == container_str
        || strip_generics(sym_container) == container_str
        || full_container == container_str
        || full_container.ends_with(&format!(".{}", container_str))
        || (container_parts.len() == 1 && container_parts[0] == module_name)
}

fn looks_like_lua_method(s: &str) -> bool {
    if s.matches(':').count() != 1 {
        return false;
    }
    let parts: Vec<&str> = s.split(':').collect();
    if parts.len() != 2 {
        return false;
    }
    let is_ident = |p: &str| {
        !p.is_empty()
            && !p.chars().next().unwrap().is_numeric()
            && p.chars().all(|c| c.is_alphanumeric() || c == '_')
    };
    !parts[0].contains('.') && is_ident(parts[0]) && is_ident(parts[1])
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
            let line: u32 = parts[1]
                .parse()
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
        let filename = Path::new(rel_path)
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("");
        if glob_match(filename, filter) {
            return true;
        }
        let parts: Vec<&str> = Path::new(rel_path)
            .iter()
            .filter_map(|s| s.to_str())
            .collect();
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
    if let Some(captures) = RE_FUNC_WITH_PARAMS.captures(name) {
        return captures
            .get(1)
            .map(|m| m.as_str().to_string())
            .unwrap_or_else(|| name.to_string());
    }
    if let Some(captures) = RE_GO_METHOD.captures(name) {
        return captures
            .get(1)
            .map(|m| m.as_str().to_string())
            .unwrap_or_else(|| name.to_string());
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
    let captures = RE_GO_METHOD_PARTS.captures(name)?;
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
    if let Some(captures) = RE_CONTAINER_PTR.captures(container) {
        return captures
            .get(1)
            .map(|m| m.as_str().to_string())
            .unwrap_or_else(|| container.to_string());
    }
    if let Some(captures) = RE_IMPL_FOR.captures(container) {
        return captures
            .get(1)
            .map(|m| m.as_str().to_string())
            .unwrap_or_else(|| container.to_string());
    }
    if let Some(captures) = RE_IMPL.captures(container) {
        return captures
            .get(1)
            .map(|m| m.as_str().to_string())
            .unwrap_or_else(|| container.to_string());
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

    if let Some(captures) = RE_EFFECTIVE_CONTAINER.captures(&sym.name) {
        return captures
            .get(1)
            .map(|m| m.as_str().to_string())
            .unwrap_or_default();
    }

    String::new()
}

fn generate_unambiguous_ref(
    sym: &SymbolInfo,
    all_matches: &[SymbolInfo],
    target_name: &str,
) -> String {
    let filename = Path::new(&sym.path)
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("");
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

fn ref_resolves_uniquely(
    ref_str: &str,
    target_sym: &SymbolInfo,
    all_matches: &[SymbolInfo],
) -> bool {
    let (path_filter, line_filter, symbol_part) = match parse_symbol_path(ref_str) {
        Ok(p) => p,
        Err(_) => return false,
    };

    let mut candidates = all_matches.to_vec();

    if let Some(ref pf) = path_filter {
        let filename = pf.clone();
        candidates = candidates
            .into_iter()
            .filter(|s| Path::new(&s.path).file_name().and_then(|f| f.to_str()) == Some(&filename))
            .collect();
    }

    if let Some(line) = line_filter {
        candidates = candidates.into_iter().filter(|s| s.line == line).collect();
    }

    let parts: Vec<&str> = symbol_part.split('.').collect();
    if parts.len() == 1 {
        candidates = candidates
            .into_iter()
            .filter(|s| normalize_symbol_name(&s.name) == parts[0])
            .collect();
    } else {
        let container_str = parts[..parts.len() - 1].join(".");
        let target_name = parts.last().unwrap();
        candidates = candidates
            .into_iter()
            .filter(|s| {
                if normalize_symbol_name(&s.name) != *target_name {
                    return false;
                }
                get_effective_container(s) == container_str
            })
            .collect();
    }

    candidates.len() == 1
        && candidates[0].path == target_sym.path
        && candidates[0].line == target_sym.line
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_go_method_parts_simple() {
        let parts = extract_go_method_parts("(*User).Save").unwrap();
        assert_eq!(parts.receiver, "User");
        assert_eq!(parts.method, "Save");
    }

    #[test]
    fn test_extract_go_method_parts_value_receiver() {
        let parts = extract_go_method_parts("(User).Save").unwrap();
        assert_eq!(parts.receiver, "User");
        assert_eq!(parts.method, "Save");
    }

    #[test]
    fn test_extract_go_method_parts_generic() {
        let parts = extract_go_method_parts("(*Result[T]).IsOk").unwrap();
        assert_eq!(parts.receiver, "Result[T]");
        assert_eq!(parts.method, "IsOk");
    }

    #[test]
    fn test_extract_go_method_parts_not_go_style() {
        assert!(extract_go_method_parts("User.Save").is_none());
        assert!(extract_go_method_parts("Save").is_none());
    }

    #[test]
    fn test_strip_generics() {
        assert_eq!(strip_generics("Result[T]"), "Result");
        assert_eq!(strip_generics("Map[K, V]"), "Map");
        assert_eq!(strip_generics("User"), "User");
    }

    #[test]
    fn test_normalize_symbol_name_go_method() {
        assert_eq!(normalize_symbol_name("(*User).Save"), "Save");
        assert_eq!(normalize_symbol_name("(User).Save"), "Save");
        assert_eq!(normalize_symbol_name("(*Result[T]).IsOk"), "IsOk");
    }

    #[test]
    fn test_name_matches_go_generic_method() {
        assert!(name_matches("(*Result[T]).IsOk", "IsOk"));
        assert!(name_matches("(*Result[T]).UnwrapOr", "UnwrapOr"));
        assert!(!name_matches("(*Result[T]).IsOk", "IsErr"));
    }

    #[test]
    fn test_looks_like_lua_method() {
        assert!(looks_like_lua_method("User:isAdult"));
        assert!(looks_like_lua_method("Storage:save"));
        assert!(looks_like_lua_method("MemoryStorage:load"));
        assert!(!looks_like_lua_method("User.isAdult"));
        assert!(!looks_like_lua_method("file.lua:User"));
        assert!(!looks_like_lua_method("main.go:123:func"));
        assert!(!looks_like_lua_method("User"));
    }
}
