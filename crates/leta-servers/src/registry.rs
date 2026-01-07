use std::collections::HashMap;
use std::path::Path;
use std::process::Command;

use leta_config::Config;
use leta_fs::get_language_id;

#[derive(Debug, Clone)]
pub struct ServerConfig {
    pub name: &'static str,
    pub command: Vec<&'static str>,
    pub languages: Vec<&'static str>,
    pub file_patterns: Vec<&'static str>,
    pub install_cmd: Option<&'static str>,
    pub root_markers: Vec<&'static str>,
}

fn get_extended_path() -> String {
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
    let extra_paths = [
        format!("{}/.gem/bin", home),
        format!("{}/go/bin", home),
        format!("{}/.cargo/bin", home),
        format!("{}/.local/bin", home),
        "/usr/local/bin".to_string(),
        "/opt/homebrew/bin".to_string(),
    ];
    let current_path = std::env::var("PATH").unwrap_or_default();
    format!("{}:{}", extra_paths.join(":"), current_path)
}

pub fn get_server_env() -> HashMap<String, String> {
    let mut env: HashMap<String, String> = std::env::vars().collect();
    env.insert("PATH".to_string(), get_extended_path());
    env
}

fn is_server_installed(server: &ServerConfig) -> bool {
    let path = get_extended_path();
    let cmd = server.command[0];

    for dir in path.split(':') {
        let full_path = Path::new(dir).join(cmd);
        if full_path.exists() && full_path.is_file() {
            return true;
        }
    }

    Command::new("which")
        .arg(cmd)
        .env("PATH", &path)
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

static SERVERS: &[(&str, &[ServerConfig])] = &[
    (
        "python",
        &[
            ServerConfig {
                name: "basedpyright",
                command: vec!["basedpyright-langserver", "--stdio"],
                languages: vec!["python"],
                file_patterns: vec!["*.py", "*.pyi"],
                install_cmd: Some("npm install -g @anthropic/basedpyright"),
                root_markers: vec![
                    "pyproject.toml",
                    "setup.py",
                    "setup.cfg",
                    "requirements.txt",
                    "pyrightconfig.json",
                ],
            },
            ServerConfig {
                name: "pylsp",
                command: vec!["pylsp"],
                languages: vec!["python"],
                file_patterns: vec!["*.py", "*.pyi"],
                install_cmd: Some("pip install python-lsp-server"),
                root_markers: vec!["pyproject.toml", "setup.py", "setup.cfg"],
            },
        ],
    ),
    (
        "rust",
        &[ServerConfig {
            name: "rust-analyzer",
            command: vec!["rust-analyzer"],
            languages: vec!["rust"],
            file_patterns: vec!["*.rs"],
            install_cmd: Some("rustup component add rust-analyzer"),
            root_markers: vec!["Cargo.toml"],
        }],
    ),
    (
        "typescript",
        &[ServerConfig {
            name: "typescript-language-server",
            command: vec!["typescript-language-server", "--stdio"],
            languages: vec![
                "typescript",
                "typescriptreact",
                "javascript",
                "javascriptreact",
            ],
            file_patterns: vec!["*.ts", "*.tsx", "*.js", "*.jsx"],
            install_cmd: Some("npm install -g typescript-language-server typescript"),
            root_markers: vec!["package.json", "tsconfig.json", "jsconfig.json"],
        }],
    ),
    (
        "go",
        &[ServerConfig {
            name: "gopls",
            command: vec!["gopls"],
            languages: vec!["go"],
            file_patterns: vec!["*.go"],
            install_cmd: Some("go install golang.org/x/tools/gopls@latest"),
            root_markers: vec!["go.mod", "go.sum"],
        }],
    ),
    (
        "c",
        &[ServerConfig {
            name: "clangd",
            command: vec!["clangd"],
            languages: vec!["c", "cpp"],
            file_patterns: vec!["*.c", "*.h", "*.cpp", "*.hpp", "*.cc", "*.cxx"],
            install_cmd: Some("brew install llvm (macOS) or apt install clangd (Ubuntu)"),
            root_markers: vec!["compile_commands.json", "CMakeLists.txt", "Makefile"],
        }],
    ),
    (
        "java",
        &[ServerConfig {
            name: "jdtls",
            command: vec!["jdtls"],
            languages: vec!["java"],
            file_patterns: vec!["*.java"],
            install_cmd: None,
            root_markers: vec!["pom.xml", "build.gradle", ".project"],
        }],
    ),
    (
        "ruby",
        &[ServerConfig {
            name: "ruby-lsp",
            command: vec!["ruby-lsp"],
            languages: vec!["ruby"],
            file_patterns: vec!["*.rb", "*.rake", "Gemfile", "Rakefile"],
            install_cmd: Some("gem install ruby-lsp"),
            root_markers: vec!["Gemfile", ".ruby-version", "Rakefile"],
        }],
    ),
    (
        "php",
        &[ServerConfig {
            name: "intelephense",
            command: vec!["intelephense", "--stdio"],
            languages: vec!["php"],
            file_patterns: vec!["*.php", "*.phtml"],
            install_cmd: Some("npm install -g intelephense"),
            root_markers: vec!["composer.json", "composer.lock", "index.php"],
        }],
    ),
    (
        "lua",
        &[ServerConfig {
            name: "lua-language-server",
            command: vec!["lua-language-server"],
            languages: vec!["lua"],
            file_patterns: vec!["*.lua"],
            install_cmd: Some("brew install lua-language-server"),
            root_markers: vec![".luarc.json", ".luarc.jsonc"],
        }],
    ),
    (
        "zig",
        &[ServerConfig {
            name: "zls",
            command: vec!["zls"],
            languages: vec!["zig"],
            file_patterns: vec!["*.zig"],
            install_cmd: Some("brew install zls"),
            root_markers: vec!["build.zig"],
        }],
    ),
];

fn language_to_key(language_id: &str) -> Option<&'static str> {
    match language_id {
        "python" => Some("python"),
        "rust" => Some("rust"),
        "typescript" | "typescriptreact" | "javascript" | "javascriptreact" => Some("typescript"),
        "go" => Some("go"),
        "c" | "cpp" => Some("c"),
        "java" => Some("java"),
        "ruby" => Some("ruby"),
        "php" => Some("php"),
        "lua" => Some("lua"),
        "zig" => Some("zig"),
        _ => None,
    }
}

pub fn get_server_for_language(
    language_id: &str,
    config: Option<&Config>,
) -> Option<&'static ServerConfig> {
    let key = language_to_key(language_id)?;

    let servers = SERVERS.iter().find(|(k, _)| *k == key).map(|(_, s)| *s)?;

    if servers.is_empty() {
        return None;
    }

    let preferred = config
        .and_then(|c| c.servers.get(key))
        .and_then(|s| s.preferred.as_deref());

    if let Some(preferred_name) = preferred {
        for server in servers {
            if server.name == preferred_name && is_server_installed(server) {
                return Some(server);
            }
        }
    }

    for server in servers {
        if is_server_installed(server) {
            return Some(server);
        }
    }

    Some(&servers[0])
}

pub fn get_server_for_file(path: &Path, config: Option<&Config>) -> Option<&'static ServerConfig> {
    let language_id = get_language_id(path);
    get_server_for_language(language_id, config)
}
