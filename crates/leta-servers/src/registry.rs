use std::collections::HashMap;
use std::path::Path;
use std::process::Command;

use fastrace::trace;
use leta_config::Config;
use leta_fs::get_language_id;

#[derive(Debug, Clone)]
pub struct ServerConfig {
    pub name: &'static str,
    pub command: &'static [&'static str],
    pub languages: &'static [&'static str],
    pub file_patterns: &'static [&'static str],
    pub install_cmd: Option<&'static str>,
    pub root_markers: &'static [&'static str],
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

static BASEDPYRIGHT: ServerConfig = ServerConfig {
    name: "basedpyright",
    command: &["basedpyright-langserver", "--stdio"],
    languages: &["python"],
    file_patterns: &["*.py", "*.pyi"],
    install_cmd: Some("npm install -g @anthropic/basedpyright"),
    root_markers: &[
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "pyrightconfig.json",
    ],
};

static PYLSP: ServerConfig = ServerConfig {
    name: "pylsp",
    command: &["pylsp"],
    languages: &["python"],
    file_patterns: &["*.py", "*.pyi"],
    install_cmd: Some("pip install python-lsp-server"),
    root_markers: &["pyproject.toml", "setup.py", "setup.cfg"],
};

static RUST_ANALYZER: ServerConfig = ServerConfig {
    name: "rust-analyzer",
    command: &["rust-analyzer"],
    languages: &["rust"],
    file_patterns: &["*.rs"],
    install_cmd: Some("rustup component add rust-analyzer"),
    root_markers: &["Cargo.toml"],
};

static TYPESCRIPT_LANGUAGE_SERVER: ServerConfig = ServerConfig {
    name: "typescript-language-server",
    command: &["typescript-language-server", "--stdio"],
    languages: &[
        "typescript",
        "typescriptreact",
        "javascript",
        "javascriptreact",
    ],
    file_patterns: &["*.ts", "*.tsx", "*.js", "*.jsx"],
    install_cmd: Some("npm install -g typescript-language-server typescript"),
    root_markers: &["package.json", "tsconfig.json", "jsconfig.json"],
};

static GOPLS: ServerConfig = ServerConfig {
    name: "gopls",
    command: &["gopls"],
    languages: &["go"],
    file_patterns: &["*.go"],
    install_cmd: Some("go install golang.org/x/tools/gopls@latest"),
    root_markers: &["go.mod", "go.sum"],
};

static CLANGD: ServerConfig = ServerConfig {
    name: "clangd",
    command: &["clangd"],
    languages: &["c", "cpp"],
    file_patterns: &["*.c", "*.h", "*.cpp", "*.hpp", "*.cc", "*.cxx"],
    install_cmd: Some("brew install llvm (macOS) or apt install clangd (Ubuntu)"),
    root_markers: &["compile_commands.json", "CMakeLists.txt", "Makefile"],
};

static JDTLS: ServerConfig = ServerConfig {
    name: "jdtls",
    command: &["jdtls"],
    languages: &["java"],
    file_patterns: &["*.java"],
    install_cmd: None,
    root_markers: &["pom.xml", "build.gradle", ".project"],
};

static RUBY_LSP: ServerConfig = ServerConfig {
    name: "ruby-lsp",
    command: &["ruby-lsp"],
    languages: &["ruby"],
    file_patterns: &["*.rb", "*.rake", "Gemfile", "Rakefile"],
    install_cmd: Some("gem install ruby-lsp"),
    root_markers: &["Gemfile", ".ruby-version", "Rakefile"],
};

static INTELEPHENSE: ServerConfig = ServerConfig {
    name: "intelephense",
    command: &["intelephense", "--stdio"],
    languages: &["php"],
    file_patterns: &["*.php", "*.phtml"],
    install_cmd: Some("npm install -g intelephense"),
    root_markers: &["composer.json", "composer.lock", "index.php"],
};

static LUA_LANGUAGE_SERVER: ServerConfig = ServerConfig {
    name: "lua-language-server",
    command: &["lua-language-server"],
    languages: &["lua"],
    file_patterns: &["*.lua"],
    install_cmd: Some("brew install lua-language-server"),
    root_markers: &[".luarc.json", ".luarc.jsonc"],
};

static ZLS: ServerConfig = ServerConfig {
    name: "zls",
    command: &["zls"],
    languages: &["zig"],
    file_patterns: &["*.zig"],
    install_cmd: Some("brew install zls"),
    root_markers: &["build.zig"],
};

static PYTHON_SERVERS: &[&ServerConfig] = &[&BASEDPYRIGHT, &PYLSP];
static RUST_SERVERS: &[&ServerConfig] = &[&RUST_ANALYZER];
static TYPESCRIPT_SERVERS: &[&ServerConfig] = &[&TYPESCRIPT_LANGUAGE_SERVER];
static GO_SERVERS: &[&ServerConfig] = &[&GOPLS];
static C_SERVERS: &[&ServerConfig] = &[&CLANGD];
static JAVA_SERVERS: &[&ServerConfig] = &[&JDTLS];
static RUBY_SERVERS: &[&ServerConfig] = &[&RUBY_LSP];
static PHP_SERVERS: &[&ServerConfig] = &[&INTELEPHENSE];
static LUA_SERVERS: &[&ServerConfig] = &[&LUA_LANGUAGE_SERVER];
static ZIG_SERVERS: &[&ServerConfig] = &[&ZLS];

fn language_to_servers(language_id: &str) -> Option<&'static [&'static ServerConfig]> {
    match language_id {
        "python" => Some(PYTHON_SERVERS),
        "rust" => Some(RUST_SERVERS),
        "typescript" | "typescriptreact" | "javascript" | "javascriptreact" => {
            Some(TYPESCRIPT_SERVERS)
        }
        "go" => Some(GO_SERVERS),
        "c" | "cpp" => Some(C_SERVERS),
        "java" => Some(JAVA_SERVERS),
        "ruby" => Some(RUBY_SERVERS),
        "php" => Some(PHP_SERVERS),
        "lua" => Some(LUA_SERVERS),
        "zig" => Some(ZIG_SERVERS),
        _ => None,
    }
}

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
    let servers = language_to_servers(language_id)?;

    if servers.is_empty() {
        return None;
    }

    let key = language_to_key(language_id)?;
    let preferred = config
        .and_then(|c| c.servers.get(key))
        .and_then(|s| s.preferred.as_deref());

    if let Some(preferred_name) = preferred {
        for server in servers.iter() {
            if server.name == preferred_name && is_server_installed(server) {
                return Some(server);
            }
        }
    }

    for server in servers.iter() {
        if is_server_installed(server) {
            return Some(server);
        }
    }

    Some(servers[0])
}

pub fn get_server_for_file(path: &Path, config: Option<&Config>) -> Option<&'static ServerConfig> {
    let language_id = get_language_id(path);
    get_server_for_language(language_id, config)
}
