fn main() {
    let options = glob::MatchOptions {
        case_sensitive: true,
        require_literal_separator: false,
        require_literal_leading_dot: true, // This should skip hidden files/directories
    };
    
    let matches: Vec<_> = glob::glob_with("**/*.py", options)
        .unwrap()
        .filter_map(|e| e.ok())
        .filter(|p| p.is_file())
        .collect();
    
    let venv_count = matches.iter()
        .filter(|p| p.to_string_lossy().contains(".venv"))
        .count();
    
    println!("Total: {}, In .venv: {}", matches.len(), venv_count);
}
