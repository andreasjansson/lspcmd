use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

use anyhow::{anyhow, Result};
use clap::{Parser, Subcommand};
use leta_config::{get_log_dir, get_socket_path, is_daemon_running, Config};
use leta_output::*;
use leta_types::{DEFAULT_HEAD_LIMIT, *};
use serde_json::{json, Value};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::UnixStream;

fn default_head_str() -> String {
    DEFAULT_HEAD_LIMIT.to_string()
}

static PROFILING_ENABLED: AtomicBool = AtomicBool::new(false);

fn profile_start(name: &str) -> (Instant, &str) {
    (Instant::now(), name)
}

fn profile_end((start, name): (Instant, &str)) {
    if PROFILING_ENABLED.load(Ordering::Relaxed) {
        let elapsed = start.elapsed();
        eprintln!(
            "[profile] {:>8.2}ms  {}",
            elapsed.as_secs_f64() * 1000.0,
            name
        );
    }
}

const MAIN_HELP: &str = r#"Leta (LSP Enabled Tools for Agents) is a command line LSP client. It can
quickly search for symbols across large code bases with regular expressions,
print full function and method bodies, find references, implementations,
subtypes, etc. It also has refactoring tools, like renaming symbols across the
entire code base.

`leta grep` can be much better than naive text search tools when you want to
understand a code base. Note that `leta grep` only exposes symbols that are
declared in its workspace, so use (rip)grep or other search tools when you're
looking for specific multi-symbol strings, puncuation, or library functions.
`leta grep PATTERN [PATH] --docs` prints function and method documentation for
all matching symbols.

`leta files` is a good starting point when starting work on a project.

Use `leta show SYMBOL` to print the full body of a symbol. Use `leta refs
SYMBOL` to find all uses of a symbol. These two (and other) commands accept
`--context N` for surrounding lines.

See `leta COMMAND --help` for more documentation and command-specific options."#;

#[derive(Parser)]
#[command(name = "leta")]
#[command(about = MAIN_HELP)]
#[command(version)]
struct Cli {
    #[arg(long, global = true, help = "Output as JSON")]
    json: bool,

    #[arg(long, global = true, help = "Print timing information for profiling")]
    profile: bool,

    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    #[command(about = "Search for symbols matching a regex pattern.")]
    Grep {
        #[arg(help = "Regex pattern to match against symbol names")]
        pattern: String,
        #[arg(help = "Regex to filter file paths (e.g. '\\.py$', 'models/', 'test')")]
        path: Option<String>,
        #[arg(short = 'k', long, help = "Filter by kind (comma-separated)")]
        kind: Option<String>,
        #[arg(short = 'x', long, action = clap::ArgAction::Append, help = "Exclude pattern")]
        exclude: Vec<String>,
        #[arg(short = 'd', long, help = "Include documentation")]
        docs: bool,
        #[arg(short = 'C', long, help = "Case-sensitive matching")]
        case_sensitive: bool,
        #[arg(long, default_value_t = DEFAULT_HEAD_LIMIT, help = "Maximum results to return")]
        head: u32,
    },

    #[command(about = "Show source file tree with symbol and line counts.")]
    Files {
        #[arg(help = "Path to list")]
        path: Option<String>,
        #[arg(short = 'x', long, action = clap::ArgAction::Append, help = "Exclude pattern")]
        exclude: Vec<String>,
        #[arg(short = 'i', long, action = clap::ArgAction::Append, help = "Include default-excluded dirs")]
        include: Vec<String>,
        #[arg(short = 'f', long, help = "Filter files by regex pattern")]
        filter: Option<String>,
        #[arg(long, default_value_t = DEFAULT_HEAD_LIMIT, help = "Maximum files to show")]
        head: u32,
    },

    #[command(about = "Print the definition of a symbol.")]
    Show {
        #[arg(help = "Symbol to show")]
        symbol: String,
        #[arg(short = 'n', long, default_value = "0", help = "Lines of context")]
        context: u32,
        #[arg(long, default_value_t = DEFAULT_HEAD_LIMIT, help = "Maximum lines to show")]
        head: u32,
    },

    #[command(about = "Find all references to a symbol.")]
    Refs {
        #[arg(help = "Symbol to find references for")]
        symbol: String,
        #[arg(short = 'n', long, default_value = "0", help = "Lines of context")]
        context: u32,
        #[arg(long, default_value_t = DEFAULT_HEAD_LIMIT, help = "Maximum results to return")]
        head: u32,
    },

    #[command(about = "Show call hierarchy for a symbol.")]
    Calls {
        #[arg(long, help = "Starting symbol (outgoing calls)")]
        from: Option<String>,
        #[arg(long, help = "Target symbol (incoming calls)")]
        to: Option<String>,
        #[arg(long, default_value = "3", help = "Maximum recursion depth")]
        max_depth: u32,
        #[arg(long, help = "Include stdlib/dependency calls")]
        include_non_workspace: bool,
        #[arg(long, default_value_t = DEFAULT_HEAD_LIMIT, help = "Maximum results to return")]
        head: u32,
    },

    #[command(about = "Find implementations of an interface or abstract method.")]
    Implementations {
        #[arg(help = "Symbol to find implementations for")]
        symbol: String,
        #[arg(short = 'n', long, default_value = "0", help = "Lines of context")]
        context: u32,
        #[arg(long, default_value_t = DEFAULT_HEAD_LIMIT, help = "Maximum results to return")]
        head: u32,
    },

    #[command(about = "Find direct supertypes of a type.")]
    Supertypes {
        #[arg(help = "Symbol to find supertypes for")]
        symbol: String,
        #[arg(short = 'n', long, default_value = "0", help = "Lines of context")]
        context: u32,
        #[arg(long, default_value_t = DEFAULT_HEAD_LIMIT, help = "Maximum results to return")]
        head: u32,
    },

    #[command(about = "Find direct subtypes of a type.")]
    Subtypes {
        #[arg(help = "Symbol to find subtypes for")]
        symbol: String,
        #[arg(short = 'n', long, default_value = "0", help = "Lines of context")]
        context: u32,
        #[arg(long, default_value_t = DEFAULT_HEAD_LIMIT, help = "Maximum results to return")]
        head: u32,
    },

    #[command(about = "Find declaration of a symbol.")]
    Declaration {
        #[arg(help = "Symbol to find declaration for")]
        symbol: String,
        #[arg(short = 'n', long, default_value = "0", help = "Lines of context")]
        context: u32,
        #[arg(long, default_value_t = DEFAULT_HEAD_LIMIT, help = "Maximum results to return")]
        head: u32,
    },

    #[command(about = "Rename a symbol across the workspace.")]
    Rename {
        #[arg(help = "Symbol to rename")]
        symbol: String,
        #[arg(help = "New name")]
        new_name: String,
    },

    #[command(about = "Move/rename a file and update all imports.")]
    Mv {
        #[arg(help = "Old path")]
        old_path: String,
        #[arg(help = "New path")]
        new_path: String,
    },

    #[command(about = "Manage workspaces.")]
    Workspace {
        #[command(subcommand)]
        command: WorkspaceCommands,
    },

    #[command(about = "Manage the leta daemon.")]
    Daemon {
        #[command(subcommand)]
        command: DaemonCommands,
    },

    #[command(about = "Print config file location and contents.")]
    Config,

    #[command(about = "Print help for all commands.")]
    HelpAll,
}

#[derive(Subcommand)]
enum DaemonCommands {
    #[command(about = "Show current daemon state.")]
    Info {
        #[arg(long, help = "Show startup and indexing profiling data")]
        profile: bool,
    },
    #[command(about = "Restart the leta daemon.")]
    Restart,
    #[command(about = "Start the leta daemon.")]
    Start,
    #[command(about = "Stop the leta daemon.")]
    Stop,
}

#[derive(Subcommand)]
enum WorkspaceCommands {
    #[command(about = "Add a workspace for LSP operations.")]
    Add {
        #[arg(help = "Workspace root directory (default: current directory)")]
        path: Option<String>,
    },
    #[command(about = "Remove a workspace and stop its language servers.")]
    Remove {
        #[arg(help = "Workspace path (default: current directory)")]
        path: Option<String>,
    },
    #[command(about = "Restart the language server for a workspace.")]
    Restart {
        #[arg(help = "Workspace path (default: current directory)")]
        path: Option<String>,
    },
    #[command(about = "Show workspace info for current directory.")]
    Info,
}

#[tokio::main]
async fn main() -> Result<()> {
    let total_start = profile_start("total");
    let cli = Cli::parse();

    if cli.profile {
        PROFILING_ENABLED.store(true, Ordering::Relaxed);
    }

    let result = match cli.command {
        Commands::Daemon { command } => handle_daemon_command(command).await,
        Commands::Workspace { command } => handle_workspace_command(command).await,
        Commands::Config => handle_config(),
        Commands::HelpAll => handle_help_all(),
        _ => {
            ensure_daemon_running().await?;
            let config = Config::load()?;

            match cli.command {
                Commands::Grep {
                    pattern,
                    path,
                    kind,
                    exclude,
                    docs,
                    case_sensitive,
                    head,
                } => {
                    handle_grep(
                        &config,
                        cli.json,
                        cli.profile,
                        pattern,
                        path,
                        kind,
                        exclude,
                        head,
                        docs,
                        case_sensitive,
                    )
                    .await
                }
                Commands::Files {
                    path,
                    exclude,
                    include,
                    filter,
                    head,
                } => {
                    handle_files(
                        &config,
                        cli.json,
                        cli.profile,
                        path,
                        exclude,
                        include,
                        filter,
                        head,
                    )
                    .await
                }
                Commands::Show {
                    symbol,
                    context,
                    head,
                } => handle_show(&config, cli.json, cli.profile, symbol, context, head).await,
                Commands::Refs {
                    symbol,
                    context,
                    head,
                } => handle_refs(&config, cli.json, symbol, context, head).await,
                Commands::Declaration {
                    symbol,
                    context,
                    head,
                } => handle_declaration(&config, cli.json, symbol, context, head).await,
                Commands::Implementations {
                    symbol,
                    context,
                    head,
                } => handle_implementations(&config, cli.json, symbol, context, head).await,
                Commands::Subtypes {
                    symbol,
                    context,
                    head,
                } => handle_subtypes(&config, cli.json, symbol, context, head).await,
                Commands::Supertypes {
                    symbol,
                    context,
                    head,
                } => handle_supertypes(&config, cli.json, symbol, context, head).await,
                Commands::Calls {
                    from,
                    to,
                    max_depth,
                    include_non_workspace,
                    head,
                } => {
                    handle_calls(
                        &config,
                        cli.json,
                        from,
                        to,
                        max_depth,
                        include_non_workspace,
                        head,
                    )
                    .await
                }
                Commands::Rename { symbol, new_name } => {
                    handle_rename(&config, cli.json, symbol, new_name).await
                }
                Commands::Mv { old_path, new_path } => {
                    handle_mv(&config, cli.json, old_path, new_path).await
                }
                _ => unreachable!(),
            }
        }
    };

    profile_end(total_start);
    result
}

fn handle_help_all() -> Result<()> {
    use clap::CommandFactory;

    let mut cmd = Cli::command();

    // Print main help
    cmd.write_long_help(&mut std::io::stdout())?;
    println!("\n");

    // Print help for each subcommand
    let subcommands: Vec<_> = cmd
        .get_subcommands()
        .map(|c| c.get_name().to_string())
        .collect();
    for name in subcommands {
        if name == "help-all" || name == "help" {
            continue;
        }
        let mut subcmd = Cli::command();
        if let Some(sub) = subcmd.find_subcommand_mut(&name) {
            println!(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            );
            println!("leta {}", name);
            println!("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n");
            sub.write_long_help(&mut std::io::stdout())?;
            println!("\n");
        }
    }

    Ok(())
}

async fn ensure_daemon_running() -> Result<()> {
    let socket_path = get_socket_path();

    if can_connect_to_daemon(&socket_path).await {
        return Ok(());
    }

    let exe = std::env::current_exe()?;
    let daemon_exe = exe.parent().unwrap().join("leta-daemon");

    Command::new(&daemon_exe)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .envs(std::env::vars())
        .spawn()?;

    for _ in 0..100 {
        if can_connect_to_daemon(&socket_path).await {
            return Ok(());
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }

    Err(anyhow!("Failed to start daemon"))
}

async fn can_connect_to_daemon(socket_path: &std::path::Path) -> bool {
    if !socket_path.exists() {
        return false;
    }
    tokio::net::UnixStream::connect(socket_path).await.is_ok()
}

struct DaemonResponse {
    result: Value,
    profiling: Option<ProfilingData>,
}

async fn send_request(method: &str, params: Value) -> Result<Value> {
    send_request_with_profile(method, params, false)
        .await
        .map(|r| r.result)
}

fn display_profiling(profiling: Option<ProfilingData>) {
    if let Some(data) = profiling {
        eprintln!("\n{}", format_profiling(&data));
    }
}

fn merge_profiling(a: Option<ProfilingData>, b: Option<ProfilingData>) -> Option<ProfilingData> {
    match (a, b) {
        (None, None) => None,
        (Some(a), None) => Some(a),
        (None, Some(b)) => Some(b),
        (Some(mut a), Some(b)) => {
            a.functions.extend(b.functions);
            a.cache.symbol_hits += b.cache.symbol_hits;
            a.cache.symbol_misses += b.cache.symbol_misses;
            a.cache.hover_hits += b.cache.hover_hits;
            a.cache.hover_misses += b.cache.hover_misses;
            Some(a)
        }
    }
}

async fn send_request_with_profile(
    method: &str,
    params: Value,
    profile: bool,
) -> Result<DaemonResponse> {
    let socket_path = get_socket_path();

    let stream = tokio::time::timeout(Duration::from_secs(5), UnixStream::connect(&socket_path))
        .await
        .map_err(|_| anyhow!("Timeout connecting to daemon"))??;

    let (mut read_half, mut write_half) = stream.into_split();

    let request = json!({
        "method": method,
        "params": params,
        "profile": profile,
    });

    write_half
        .write_all(serde_json::to_vec(&request)?.as_slice())
        .await?;
    write_half.shutdown().await?;

    let mut response_data = Vec::new();
    tokio::time::timeout(
        Duration::from_secs(30),
        read_half.read_to_end(&mut response_data),
    )
    .await
    .map_err(|_| anyhow!("Timeout waiting for daemon response (method: {})", method))??;

    let response: Value = serde_json::from_slice(&response_data)?;

    if let Some(error) = response.get("error").and_then(|e| e.as_str()) {
        if error.contains("Internal error") || error.to_lowercase().contains("internal error") {
            let log_dir = get_log_dir();
            let log_path = log_dir.join("daemon.log");
            let mut msg = error.to_string();

            if log_path.exists() {
                if let Ok(content) = std::fs::read_to_string(&log_path) {
                    let lines: Vec<&str> = content.lines().collect();
                    let tail: Vec<&str> = lines.iter().rev().take(15).rev().copied().collect();
                    msg.push_str("\n\nRecent daemon log:\n");
                    msg.push_str(&tail.join("\n"));
                }
            }
            msg.push_str(&format!("\n\nFull logs: {}", log_path.display()));
            return Err(anyhow!(msg));
        }
        return Err(anyhow!("{}", error));
    }

    let result = response.get("result").cloned().unwrap_or(Value::Null);
    let profiling: Option<ProfilingData> = response
        .get("profiling")
        .and_then(|p| serde_json::from_value(p.clone()).ok());

    Ok(DaemonResponse { result, profiling })
}

fn get_workspace_root(config: &Config) -> Result<PathBuf> {
    let cwd = std::env::current_dir()?;
    config
        .get_best_workspace_root(&cwd, Some(&cwd))
        .ok_or_else(|| anyhow!("No workspace found for current directory\nRun: leta workspace add"))
}

fn get_workspace_root_for_path(config: &Config, path: &Path) -> Result<PathBuf> {
    let cwd = std::env::current_dir()?;
    let path = path.canonicalize().unwrap_or_else(|_| path.to_path_buf());
    config
        .get_best_workspace_root(&path, Some(&cwd))
        .ok_or_else(|| {
            anyhow!(
                "No workspace found for {}\nRun: leta workspace add",
                path.display()
            )
        })
}

struct ResolveResult {
    resolved: ResolveSymbolResult,
    profiling: Option<ProfilingData>,
}

async fn resolve_symbol(
    symbol: &str,
    workspace_root: &Path,
    profile: bool,
) -> Result<ResolveResult> {
    let response = send_request_with_profile(
        "resolve-symbol",
        json!({
            "workspace_root": workspace_root.to_string_lossy(),
            "symbol_path": symbol,
        }),
        profile,
    )
    .await?;

    let resolved: ResolveSymbolResult = serde_json::from_value(response.result)?;

    if let Some(error) = &resolved.error {
        let mut msg = error.clone();
        if let Some(matches) = &resolved.matches {
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
                msg.push_str(&format!("\n  {}", ref_str));
                msg.push_str(&format!(
                    "\n    {}:{} {}{}{}{}",
                    m.path, m.line, kind, m.name, detail, container
                ));
            }
            if let Some(total) = resolved.total_matches {
                let shown = matches.len() as u32;
                if total > shown {
                    msg.push_str(&format!("\n  ... and {} more", total - shown));
                }
            }
        }
        return Err(anyhow!("{}", msg));
    }

    Ok(ResolveResult {
        resolved,
        profiling: response.profiling,
    })
}

async fn handle_daemon_command(command: DaemonCommands) -> Result<()> {
    match command {
        DaemonCommands::Start => {
            if is_daemon_running() {
                println!("Daemon already running");
            } else {
                ensure_daemon_running().await?;
                println!("Daemon started");
            }
        }
        DaemonCommands::Stop => {
            if !is_daemon_running() {
                println!("Daemon is not running");
            } else {
                send_request("shutdown", json!({})).await?;
                println!("Daemon stopped");
            }
        }
        DaemonCommands::Restart => {
            if is_daemon_running() {
                send_request("shutdown", json!({})).await?;
                for _ in 0..50 {
                    if !get_socket_path().exists() {
                        break;
                    }
                    tokio::time::sleep(Duration::from_millis(100)).await;
                }
            }
            ensure_daemon_running().await?;
            println!("Daemon restarted");
        }
        DaemonCommands::Info { profile } => {
            ensure_daemon_running().await?;
            let result = send_request(
                "describe-session",
                json!({
                    "include_profiling": profile,
                }),
            )
            .await?;
            let session: DescribeSessionResult = serde_json::from_value(result)?;
            println!("{}", format_describe_session_result(&session, profile));
        }
    }
    Ok(())
}

async fn handle_workspace_command(command: WorkspaceCommands) -> Result<()> {
    let config = Config::load()?;

    match command {
        WorkspaceCommands::Add { path } => {
            let workspace_root = if let Some(path) = path {
                PathBuf::from(path).canonicalize()?
            } else {
                let cwd = std::env::current_dir()?;
                let detected = leta_config::detect_workspace_root(&cwd);
                detected.unwrap_or(cwd)
            };

            ensure_daemon_running().await?;

            let result = send_request(
                "add-workspace",
                json!({
                    "workspace_root": workspace_root.to_string_lossy(),
                }),
            )
            .await?;

            let add_result: AddWorkspaceResult = serde_json::from_value(result)?;
            if add_result.added {
                println!("Added workspace: {}", add_result.workspace_root);
            } else {
                println!("Workspace already added: {}", add_result.workspace_root);
            }
        }
        WorkspaceCommands::Remove { path } => {
            let workspace_root = if let Some(path) = path {
                PathBuf::from(path).canonicalize()?
            } else {
                get_workspace_root(&config)?
            };

            ensure_daemon_running().await?;

            let result = send_request(
                "remove-workspace",
                json!({
                    "workspace_root": workspace_root.to_string_lossy(),
                }),
            )
            .await?;

            let _remove_result: RemoveWorkspaceResult = serde_json::from_value(result)?;
            println!("Removed workspace: {}", workspace_root.display());
        }
        WorkspaceCommands::Restart { path } => {
            let workspace_root = if let Some(path) = path {
                PathBuf::from(path).canonicalize()?
            } else {
                get_workspace_root(&config)?
            };

            ensure_daemon_running().await?;
            let result = send_request(
                "restart-workspace",
                json!({
                    "workspace_root": workspace_root.to_string_lossy(),
                }),
            )
            .await?;
            let restart: RestartWorkspaceResult = serde_json::from_value(result)?;
            println!("{}", format_restart_workspace_result(&restart));
        }
        WorkspaceCommands::Info => {
            let cwd = std::env::current_dir()?;
            match get_workspace_root(&config) {
                Ok(root) => {
                    println!("{}", root.display());
                }
                Err(_) => {
                    return Err(anyhow!(
                        "No workspace found for {}\nRun: leta workspace add",
                        cwd.display()
                    ));
                }
            }
        }
    }
    Ok(())
}

fn handle_config() -> Result<()> {
    let config_path = leta_config::get_config_path();
    println!("Config file: {}", config_path.display());
    println!();

    if config_path.exists() {
        println!("{}", std::fs::read_to_string(&config_path)?);
    } else {
        println!("(file does not exist, using defaults)");
    }
    Ok(())
}

async fn handle_grep(
    config: &Config,
    json_output: bool,
    profile: bool,
    pattern: String,
    path: Option<String>,
    kind: Option<String>,
    exclude: Vec<String>,
    head: u32,
    docs: bool,
    case_sensitive: bool,
) -> Result<()> {
    if pattern.contains(' ') {
        eprintln!("Warning: Pattern contains a space. leta grep searches symbol names, not file contents.");
        eprintln!("  Use ripgrep for text search, or --kind/-k to filter by symbol type (e.g. -k function,class)");
    }

    let kinds: Option<Vec<String>> = kind
        .clone()
        .map(|k| k.split(',').map(|s| s.trim().to_string()).collect());

    let workspace_root = get_workspace_root(config)?;

    let response = send_request_with_profile(
        "grep",
        json!({
            "workspace_root": workspace_root.to_string_lossy(),
            "pattern": pattern,
            "kinds": kinds,
            "case_sensitive": case_sensitive,
            "include_docs": docs,
            "path_pattern": path,
            "exclude_patterns": exclude,
            "limit": head,
        }),
        profile,
    )
    .await?;

    let grep_result: GrepResult = serde_json::from_value(response.result)?;

    if json_output {
        println!("{}", serde_json::to_string_pretty(&grep_result)?);
    } else {
        let mut cmd_parts = vec![format!("leta grep \"{}\"", pattern)];
        if let Some(p) = &path {
            cmd_parts.push(format!("\"{}\"", p));
        }
        if let Some(k) = &kind {
            cmd_parts.push(format!("-k {}", k));
        }
        for ex in &exclude {
            cmd_parts.push(format!("-x \"{}\"", ex));
        }
        if docs {
            cmd_parts.push("-d".to_string());
        }
        if case_sensitive {
            cmd_parts.push("-C".to_string());
        }
        let command_base = cmd_parts.join(" ");
        println!("{}", format_grep_result(&grep_result, head, &command_base));
    }

    display_profiling(response.profiling);
    Ok(())
}

async fn handle_files(
    config: &Config,
    json_output: bool,
    profile: bool,
    path: Option<String>,
    exclude: Vec<String>,
    include: Vec<String>,
    filter: Option<String>,
) -> Result<()> {
    let (workspace_root, subpath) = if let Some(path) = path {
        let target = PathBuf::from(&path).canonicalize()?;
        let workspace_root = get_workspace_root_for_path(config, &target)?;
        (workspace_root, Some(target.to_string_lossy().to_string()))
    } else {
        (get_workspace_root(config)?, None)
    };

    let response = send_request_with_profile(
        "files",
        json!({
            "workspace_root": workspace_root.to_string_lossy(),
            "subpath": subpath,
            "exclude_patterns": exclude,
            "include_patterns": include,
            "filter_pattern": filter,
        }),
        profile,
    )
    .await?;

    let files_result: FilesResult = serde_json::from_value(response.result)?;

    if json_output {
        println!("{}", serde_json::to_string_pretty(&files_result)?);
    } else {
        println!("{}", format_files_result(&files_result));
    }

    display_profiling(response.profiling);
    Ok(())
}

fn format_profiling(data: &ProfilingData) -> String {
    let mut lines = Vec::new();

    let cache = &data.cache;
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
                "  hover:   {}/{} hits ({:.1}%)",
                cache.hover_hits,
                hover_total,
                cache.hover_hit_rate()
            ));
        }
        lines.push(String::new());
    }

    if !data.functions.is_empty() {
        lines.push("TIMING".to_string());
        lines.extend(format_function_stats(&data.functions, "", usize::MAX));
    }

    lines.join("\n")
}

async fn handle_show(
    config: &Config,
    json_output: bool,
    profile: bool,
    symbol: String,
    context: u32,
    head: u32,
) -> Result<()> {
    let workspace_root = get_workspace_root(config)?;
    let resolve_result = resolve_symbol(&symbol, &workspace_root, profile).await?;
    let resolved = resolve_result.resolved;

    let response = send_request_with_profile(
        "show",
        json!({
            "path": resolved.path,
            "workspace_root": workspace_root.to_string_lossy(),
            "line": resolved.line,
            "column": resolved.column.unwrap_or(0),
            "context": context,
            "direct_location": true,
            "range_start_line": resolved.range_start_line,
            "range_end_line": resolved.range_end_line,
            "head": head,
            "symbol": symbol,
            "kind": resolved.kind,
        }),
        profile,
    )
    .await?;

    let show_result: ShowResult = serde_json::from_value(response.result)?;

    if json_output {
        println!("{}", serde_json::to_string_pretty(&show_result)?);
    } else {
        println!("{}", format_show_result(&show_result));
    }

    display_profiling(merge_profiling(
        resolve_result.profiling,
        response.profiling,
    ));
    Ok(())
}

async fn handle_refs(
    config: &Config,
    json_output: bool,
    symbol: String,
    context: u32,
) -> Result<()> {
    let workspace_root = get_workspace_root(config)?;
    let resolved = resolve_symbol(&symbol, &workspace_root, false).await?;

    let result = send_request(
        "references",
        json!({
            "path": resolved.resolved.path,
            "workspace_root": workspace_root.to_string_lossy(),
            "line": resolved.resolved.line,
            "column": resolved.resolved.column.unwrap_or(0),
            "context": context,
        }),
    )
    .await?;

    let refs_result: ReferencesResult = serde_json::from_value(result)?;

    if json_output {
        println!("{}", serde_json::to_string_pretty(&refs_result)?);
    } else {
        println!("{}", format_references_result(&refs_result));
    }
    Ok(())
}

async fn handle_declaration(
    config: &Config,
    json_output: bool,
    symbol: String,
    context: u32,
) -> Result<()> {
    let workspace_root = get_workspace_root(config)?;
    let resolved = resolve_symbol(&symbol, &workspace_root, false).await?;

    let result = send_request(
        "declaration",
        json!({
            "path": resolved.resolved.path,
            "workspace_root": workspace_root.to_string_lossy(),
            "line": resolved.resolved.line,
            "column": resolved.resolved.column.unwrap_or(0),
            "context": context,
        }),
    )
    .await?;

    let decl_result: DeclarationResult = serde_json::from_value(result)?;

    if json_output {
        println!("{}", serde_json::to_string_pretty(&decl_result)?);
    } else {
        println!("{}", format_declaration_result(&decl_result));
    }
    Ok(())
}

async fn handle_implementations(
    config: &Config,
    json_output: bool,
    symbol: String,
    context: u32,
) -> Result<()> {
    let workspace_root = get_workspace_root(config)?;
    let resolved = resolve_symbol(&symbol, &workspace_root, false).await?;

    let result = send_request(
        "implementations",
        json!({
            "path": resolved.resolved.path,
            "workspace_root": workspace_root.to_string_lossy(),
            "line": resolved.resolved.line,
            "column": resolved.resolved.column.unwrap_or(0),
            "context": context,
        }),
    )
    .await?;

    let impl_result: ImplementationsResult = serde_json::from_value(result)?;

    if json_output {
        println!("{}", serde_json::to_string_pretty(&impl_result)?);
    } else {
        println!("{}", format_implementations_result(&impl_result));
    }
    Ok(())
}

async fn handle_subtypes(
    config: &Config,
    json_output: bool,
    symbol: String,
    context: u32,
) -> Result<()> {
    let workspace_root = get_workspace_root(config)?;
    let resolved = resolve_symbol(&symbol, &workspace_root, false).await?;

    let result = send_request(
        "subtypes",
        json!({
            "path": resolved.resolved.path,
            "workspace_root": workspace_root.to_string_lossy(),
            "line": resolved.resolved.line,
            "column": resolved.resolved.column.unwrap_or(0),
            "context": context,
        }),
    )
    .await?;

    let subtypes_result: SubtypesResult = serde_json::from_value(result)?;

    if json_output {
        println!("{}", serde_json::to_string_pretty(&subtypes_result)?);
    } else {
        println!("{}", format_subtypes_result(&subtypes_result));
    }
    Ok(())
}

async fn handle_supertypes(
    config: &Config,
    json_output: bool,
    symbol: String,
    context: u32,
) -> Result<()> {
    let workspace_root = get_workspace_root(config)?;
    let resolved = resolve_symbol(&symbol, &workspace_root, false).await?;

    let result = send_request(
        "supertypes",
        json!({
            "path": resolved.resolved.path,
            "workspace_root": workspace_root.to_string_lossy(),
            "line": resolved.resolved.line,
            "column": resolved.resolved.column.unwrap_or(0),
            "context": context,
        }),
    )
    .await?;

    let supertypes_result: SupertypesResult = serde_json::from_value(result)?;

    if json_output {
        println!("{}", serde_json::to_string_pretty(&supertypes_result)?);
    } else {
        println!("{}", format_supertypes_result(&supertypes_result));
    }
    Ok(())
}

async fn handle_calls(
    config: &Config,
    json_output: bool,
    from: Option<String>,
    to: Option<String>,
    max_depth: u32,
    include_non_workspace: bool,
) -> Result<()> {
    if from.is_none() && to.is_none() {
        return Err(anyhow!("At least one of --from or --to must be specified"));
    }

    let workspace_root = get_workspace_root(config)?;

    let mut params = json!({
        "workspace_root": workspace_root.to_string_lossy(),
        "max_depth": max_depth,
        "include_non_workspace": include_non_workspace,
    });

    if let (Some(from_sym), Some(to_sym)) = (&from, &to) {
        let from_resolved = resolve_symbol(from_sym, &workspace_root, false).await?;
        let to_resolved = resolve_symbol(to_sym, &workspace_root, false).await?;

        params["from_path"] = json!(from_resolved.resolved.path);
        params["from_line"] = json!(from_resolved.resolved.line);
        params["from_column"] = json!(from_resolved.resolved.column.unwrap_or(0));
        params["from_symbol"] = json!(from_sym);
        params["to_path"] = json!(to_resolved.resolved.path);
        params["to_line"] = json!(to_resolved.resolved.line);
        params["to_column"] = json!(to_resolved.resolved.column.unwrap_or(0));
        params["to_symbol"] = json!(to_sym);
        params["mode"] = json!("path");
    } else if let Some(from_sym) = &from {
        let resolved = resolve_symbol(from_sym, &workspace_root, false).await?;
        params["from_path"] = json!(resolved.resolved.path);
        params["from_line"] = json!(resolved.resolved.line);
        params["from_column"] = json!(resolved.resolved.column.unwrap_or(0));
        params["from_symbol"] = json!(from_sym);
        params["mode"] = json!("outgoing");
    } else if let Some(to_sym) = &to {
        let resolved = resolve_symbol(to_sym, &workspace_root, false).await?;
        params["to_path"] = json!(resolved.resolved.path);
        params["to_line"] = json!(resolved.resolved.line);
        params["to_column"] = json!(resolved.resolved.column.unwrap_or(0));
        params["to_symbol"] = json!(to_sym);
        params["mode"] = json!("incoming");
    }

    let result = send_request("calls", params).await?;
    let calls_result: CallsResult = serde_json::from_value(result)?;

    if json_output {
        println!("{}", serde_json::to_string_pretty(&calls_result)?);
    } else {
        println!("{}", format_calls_result(&calls_result));
    }
    Ok(())
}

async fn handle_rename(
    config: &Config,
    json_output: bool,
    symbol: String,
    new_name: String,
) -> Result<()> {
    let workspace_root = get_workspace_root(config)?;
    let resolved = resolve_symbol(&symbol, &workspace_root, false).await?;

    let result = send_request(
        "rename",
        json!({
            "path": resolved.resolved.path,
            "workspace_root": workspace_root.to_string_lossy(),
            "line": resolved.resolved.line,
            "column": resolved.resolved.column.unwrap_or(0),
            "new_name": new_name,
        }),
    )
    .await?;

    let rename_result: RenameResult = serde_json::from_value(result)?;

    if json_output {
        println!("{}", serde_json::to_string_pretty(&rename_result)?);
    } else {
        println!("{}", format_rename_result(&rename_result));
    }
    Ok(())
}

async fn handle_mv(
    config: &Config,
    json_output: bool,
    old_path: String,
    new_path: String,
) -> Result<()> {
    let old_path = PathBuf::from(&old_path).canonicalize()?;
    // new_path doesn't exist yet, so we resolve it relative to current dir
    let new_path = std::env::current_dir()?.join(&new_path);
    let workspace_root = get_workspace_root_for_path(config, &old_path)?;

    let result = send_request(
        "move-file",
        json!({
            "old_path": old_path.to_string_lossy(),
            "new_path": new_path.to_string_lossy(),
            "workspace_root": workspace_root.to_string_lossy(),
        }),
    )
    .await?;

    let mv_result: MoveFileResult = serde_json::from_value(result)?;

    if json_output {
        println!("{}", serde_json::to_string_pretty(&mv_result)?);
    } else {
        println!("{}", format_move_file_result(&mv_result));
    }
    Ok(())
}
