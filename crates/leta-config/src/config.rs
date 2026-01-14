use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs::File;
use std::os::unix::io::AsRawFd;
use std::path::{Path, PathBuf};
use thiserror::Error;

use crate::paths::{get_config_dir, get_config_path};

struct ConfigLock {
    _file: File,
}

impl ConfigLock {
    fn acquire_exclusive() -> Result<Self, std::io::Error> {
        let lock_path = get_config_path().with_extension("lock");
        if let Some(parent) = lock_path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let file = File::options()
            .write(true)
            .create(true)
            .truncate(true)
            .open(&lock_path)?;
        let fd = file.as_raw_fd();
        let result = unsafe { libc::flock(fd, libc::LOCK_EX) };
        if result != 0 {
            return Err(std::io::Error::last_os_error());
        }
        Ok(ConfigLock { _file: file })
    }
}

#[derive(Error, Debug)]
pub enum ConfigError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
    #[error("TOML parse error: {0}")]
    TomlParse(#[from] toml::de::Error),
    #[error("TOML serialize error: {0}")]
    TomlSerialize(#[from] toml::ser::Error),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DaemonConfig {
    #[serde(default = "default_log_level")]
    pub log_level: String,
    #[serde(default = "default_request_timeout")]
    pub request_timeout: u64,
    #[serde(default = "default_cache_size")]
    pub hover_cache_size: u64,
    #[serde(default = "default_cache_size")]
    pub symbol_cache_size: u64,
}

impl Default for DaemonConfig {
    fn default() -> Self {
        Self {
            log_level: default_log_level(),
            request_timeout: default_request_timeout(),
            hover_cache_size: default_cache_size(),
            symbol_cache_size: default_cache_size(),
        }
    }
}

fn default_log_level() -> String {
    "info".to_string()
}

fn default_request_timeout() -> u64 {
    30
}

fn default_cache_size() -> u64 {
    256 * 1024 * 1024 // 256MB
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct WorkspacesConfig {
    #[serde(default)]
    pub roots: Vec<String>,
    #[serde(default)]
    pub excluded_languages: Vec<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct FormattingConfig {
    #[serde(default = "default_tab_size")]
    pub tab_size: u32,
    #[serde(default = "default_insert_spaces")]
    pub insert_spaces: bool,
}

fn default_tab_size() -> u32 {
    4
}

fn default_insert_spaces() -> bool {
    true
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ServerLanguageConfig {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub preferred: Option<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Config {
    #[serde(default)]
    pub daemon: DaemonConfig,
    #[serde(default)]
    pub workspaces: WorkspacesConfig,
    #[serde(default)]
    pub formatting: FormattingConfig,
    #[serde(default)]
    pub servers: HashMap<String, ServerLanguageConfig>,
}

impl Config {
    pub fn load() -> Result<Self, ConfigError> {
        let _lock = ConfigLock::acquire_exclusive()?;
        Self::load_unlocked()
    }

    fn load_unlocked() -> Result<Self, ConfigError> {
        let config_path = get_config_path();
        if !config_path.exists() {
            return Ok(Config::default());
        }
        let content = std::fs::read_to_string(&config_path)?;
        let config: Config = toml::from_str(&content)?;
        Ok(config)
    }

    pub fn save(&self) -> Result<(), ConfigError> {
        let _lock = ConfigLock::acquire_exclusive()?;
        self.save_unlocked()
    }

    fn save_unlocked(&self) -> Result<(), ConfigError> {
        let config_path = get_config_path();
        let config_dir = get_config_dir();
        std::fs::create_dir_all(&config_dir)?;
        let content = toml::to_string_pretty(self)?;
        std::fs::write(&config_path, content)?;
        Ok(())
    }

    pub fn add_workspace_root(root: &Path) -> Result<bool, ConfigError> {
        let _lock = ConfigLock::acquire_exclusive()?;
        let mut config = Config::load_unlocked()?;
        let root_str = root.to_string_lossy().to_string();
        if !config.workspaces.roots.contains(&root_str) {
            config.workspaces.roots.push(root_str);
            config.save_unlocked()?;
            Ok(true)
        } else {
            Ok(false)
        }
    }

    pub fn remove_workspace_root(root: &Path) -> Result<bool, ConfigError> {
        let _lock = ConfigLock::acquire_exclusive()?;
        let mut config = Config::load_unlocked()?;
        let root_str = root.to_string_lossy().to_string();
        let initial_len = config.workspaces.roots.len();
        config.workspaces.roots.retain(|r| r != &root_str);
        if config.workspaces.roots.len() < initial_len {
            config.save_unlocked()?;
            Ok(true)
        } else {
            Ok(false)
        }
    }

    pub fn get_best_workspace_root(&self, path: &Path, cwd: Option<&Path>) -> Option<PathBuf> {
        let path = path.canonicalize().unwrap_or_else(|_| path.to_path_buf());

        let mut best: Option<PathBuf> = None;
        let mut best_len = 0;

        for root_str in &self.workspaces.roots {
            let root = PathBuf::from(root_str);
            let root = root.canonicalize().unwrap_or(root);

            if path.starts_with(&root) {
                let len = root.as_os_str().len();
                if len > best_len {
                    best = Some(root);
                    best_len = len;
                }
            }
        }

        if best.is_some() {
            return best;
        }

        if let Some(cwd) = cwd {
            let cwd = cwd.canonicalize().unwrap_or_else(|_| cwd.to_path_buf());
            for root_str in &self.workspaces.roots {
                let root = PathBuf::from(root_str);
                let root = root.canonicalize().unwrap_or(root);

                if cwd.starts_with(&root) {
                    let len = root.as_os_str().len();
                    if len > best_len {
                        best = Some(root);
                        best_len = len;
                    }
                }
            }
        }

        best
    }

    pub fn cleanup_stale_workspace_roots(&mut self) -> Vec<String> {
        let mut removed = Vec::new();
        let original_roots = self.workspaces.roots.clone();

        self.workspaces.roots.retain(|root| {
            let path = PathBuf::from(root);
            if path.exists() {
                true
            } else {
                removed.push(root.clone());
                false
            }
        });

        if self.workspaces.roots.len() < original_roots.len() {
            let _ = self.save();
        }

        removed
    }
}
