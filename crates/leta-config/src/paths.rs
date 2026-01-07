use std::path::PathBuf;

pub fn get_config_dir() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
    PathBuf::from(home).join(".config").join("leta")
}

pub fn get_config_path() -> PathBuf {
    get_config_dir().join("config.toml")
}

pub fn get_cache_dir() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
    PathBuf::from(home).join(".cache").join("leta")
}

pub fn get_log_dir() -> PathBuf {
    get_cache_dir().join("log")
}

pub fn get_socket_path() -> PathBuf {
    get_cache_dir().join("daemon.sock")
}

pub fn get_pid_path() -> PathBuf {
    get_cache_dir().join("daemon.pid")
}

pub fn write_pid(path: &std::path::Path, pid: u32) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(path, pid.to_string())
}

pub fn remove_pid(path: &std::path::Path) {
    let _ = std::fs::remove_file(path);
}

pub fn read_pid(path: &std::path::Path) -> Option<u32> {
    std::fs::read_to_string(path)
        .ok()
        .and_then(|s| s.trim().parse().ok())
}

pub fn is_daemon_running() -> bool {
    let pid_path = get_pid_path();
    if let Some(pid) = read_pid(&pid_path) {
        is_process_running(pid)
    } else {
        false
    }
}

#[cfg(unix)]
fn is_process_running(pid: u32) -> bool {
    unsafe { libc::kill(pid as i32, 0) == 0 }
}

#[cfg(not(unix))]
fn is_process_running(_pid: u32) -> bool {
    false
}

pub fn detect_workspace_root(path: &std::path::Path) -> Option<PathBuf> {
    let markers = [
        ".git",
        "pyproject.toml",
        "setup.py",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "Gemfile",
        "composer.json",
        "mix.exs",
        "dune-project",
    ];

    let mut current = path.to_path_buf();
    loop {
        for marker in &markers {
            if current.join(marker).exists() {
                return Some(current);
            }
        }
        if !current.pop() {
            break;
        }
    }
    None
}
