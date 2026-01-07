use std::fs;
use std::path::Path;

pub fn write_pid(path: &Path, pid: u32) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(path, pid.to_string())
}

pub fn remove_pid(path: &Path) {
    let _ = fs::remove_file(path);
}

pub fn read_pid(path: &Path) -> Option<u32> {
    fs::read_to_string(path)
        .ok()
        .and_then(|s| s.trim().parse().ok())
}

pub fn is_daemon_running(path: &Path) -> bool {
    if let Some(pid) = read_pid(path) {
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
