use std::path::Path;

use fastrace::trace;
use thiserror::Error;

#[derive(Error, Debug)]
pub enum TextError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
    #[error("UTF-8 decoding error: {0}")]
    Utf8(#[from] std::string::FromUtf8Error),
}

#[trace]
pub fn get_language_id(path: &Path) -> &'static str {
    let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("");
    let filename = path.file_name().and_then(|f| f.to_str()).unwrap_or("");

    match ext {
        "py" | "pyi" => "python",
        "rs" => "rust",
        "ts" => "typescript",
        "tsx" => "typescriptreact",
        "js" => "javascript",
        "jsx" => "javascriptreact",
        "go" => "go",
        "c" | "h" => "c",
        "cpp" | "hpp" | "cc" | "cxx" | "hxx" => "cpp",
        "java" => "java",
        "rb" | "rake" => "ruby",
        "php" | "phtml" => "php",
        "ex" | "exs" => "elixir",
        "hs" => "haskell",
        "ml" | "mli" => "ocaml",
        "lua" => "lua",
        "zig" => "zig",
        "yaml" | "yml" => "yaml",
        "json" => "json",
        "html" | "htm" => "html",
        "css" => "css",
        "scss" => "scss",
        "less" => "less",
        "md" | "markdown" => "markdown",
        "toml" => "toml",
        "xml" => "xml",
        "sh" | "bash" => "shellscript",
        "sql" => "sql",
        _ => match filename {
            "Gemfile" | "Rakefile" => "ruby",
            "Makefile" | "makefile" | "GNUmakefile" => "makefile",
            "Dockerfile" => "dockerfile",
            _ => "plaintext",
        },
    }
}

pub fn read_file_content(path: &Path) -> Result<String, TextError> {
    let bytes = std::fs::read(path)?;
    let content = String::from_utf8(bytes)?;
    Ok(content)
}

pub fn file_mtime(path: &Path) -> String {
    match std::fs::metadata(path) {
        Ok(meta) => match meta.modified() {
            Ok(mtime) => match mtime.duration_since(std::time::UNIX_EPOCH) {
                Ok(duration) => format!("{}.{}", duration.as_secs(), duration.subsec_nanos()),
                Err(_) => String::new(),
            },
            Err(_) => String::new(),
        },
        Err(_) => String::new(),
    }
}

#[trace]
pub fn get_lines_around(
    content: &str,
    center_line: usize,
    context: usize,
) -> (Vec<String>, usize, usize) {
    let lines: Vec<&str> = content.lines().collect();
    let total = lines.len();

    if total == 0 {
        return (vec![], 0, 0);
    }

    let center = center_line.min(total.saturating_sub(1));
    let start = center.saturating_sub(context);
    let end = (center + context).min(total.saturating_sub(1));

    let extracted: Vec<String> = lines[start..=end].iter().map(|s| s.to_string()).collect();
    (extracted, start, end)
}

#[trace]
pub fn count_lines(content: &str) -> usize {
    if content.is_empty() {
        0
    } else {
        content.lines().count()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_language_detection() {
        assert_eq!(get_language_id(Path::new("test.py")), "python");
        assert_eq!(get_language_id(Path::new("test.rs")), "rust");
        assert_eq!(get_language_id(Path::new("test.go")), "go");
        assert_eq!(get_language_id(Path::new("test.ts")), "typescript");
        assert_eq!(get_language_id(Path::new("Gemfile")), "ruby");
    }

    #[test]
    fn test_get_lines_around() {
        let content = "line0\nline1\nline2\nline3\nline4";
        let (lines, start, end) = get_lines_around(content, 2, 1);
        assert_eq!(lines, vec!["line1", "line2", "line3"]);
        assert_eq!(start, 1);
        assert_eq!(end, 3);
    }
}
