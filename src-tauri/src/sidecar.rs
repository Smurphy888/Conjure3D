use std::env;
use std::fs::{self, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Stdio};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

pub struct SidecarState {
    stdin: ChildStdin,
    stdout: BufReader<std::process::ChildStdout>,
    next_id: u64,
    log_path: PathBuf,
    _child: Child,
}

/// `%LOCALAPPDATA%\Conjure3D\logs\<unix-secs>.log` — one file per sidecar
/// process. Falls back to the OS temp dir if LOCALAPPDATA is unset (dev /
/// non-Windows) rather than panicking. Directory creation failure is
/// non-fatal: the path is still returned and the OS surfaces the open error.
fn session_log_path() -> PathBuf {
    let base = env::var("LOCALAPPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(|_| env::temp_dir());
    let dir = base.join("Conjure3D").join("logs");
    let _ = fs::create_dir_all(&dir);
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    dir.join(format!("sidecar-{secs}.log"))
}

impl SidecarState {
    /// Spawn the sidecar process.
    /// `exe_path` = `None` in dev (uses `python sidecar/main.py`);
    ///             = `Some(path/to/sidecar.exe)` in release builds.
    pub fn spawn(exe_path: Option<PathBuf>) -> Result<Self, String> {
        // One log file per sidecar process; the child writes its stderr here
        // (create + append) and the Copy-diagnostic command re-opens the path
        // read-only. try_clone() gives the two match arms independent write
        // handles to the same file without consuming `log_file`.
        let log_path = session_log_path();
        let log_file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)
            .map_err(|e| format!("Failed to open sidecar log {log_path:?}: {e}"))?;

        // Use arg list, never a shell string — apostrophe in the path is safe.
        let mut child = match exe_path {
            Some(exe) => std::process::Command::new(exe)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::from(
                    log_file
                        .try_clone()
                        .map_err(|e| format!("log handle clone: {e}"))?,
                ))
                .spawn()
                .map_err(|e| format!("Failed to spawn sidecar exe: {e}"))?,
            None => {
                let script =
                    std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../sidecar/main.py");
                std::process::Command::new("python")
                    .arg(&script)
                    .stdin(Stdio::piped())
                    .stdout(Stdio::piped())
                    .stderr(Stdio::from(
                        log_file
                            .try_clone()
                            .map_err(|e| format!("log handle clone: {e}"))?,
                    ))
                    .spawn()
                    .map_err(|e| format!("Failed to spawn sidecar via python: {e}"))?
            }
        };

        let stdin = child.stdin.take().ok_or("No stdin handle on spawned process")?;
        let stdout = BufReader::new(child.stdout.take().ok_or("No stdout handle on spawned process")?);

        Ok(SidecarState {
            stdin,
            stdout,
            next_id: 1,
            log_path,
            _child: child,
        })
    }

    /// Absolute path of this session's sidecar log file.
    pub fn log_path(&self) -> &Path {
        &self.log_path
    }

    pub(crate) fn call_inner(&mut self, method: &str, params: serde_json::Value) -> Result<serde_json::Value, String> {
        let id = self.next_id;
        self.next_id += 1;

        let req = serde_json::json!({
            "jsonrpc": "2.0",
            "id": id,
            "method": method,
            "params": params,
        });

        writeln!(self.stdin, "{req}").map_err(|e| format!("sidecar write: {e}"))?;
        self.stdin.flush().map_err(|e| format!("sidecar flush: {e}"))?;

        let mut line = String::new();
        self.stdout
            .read_line(&mut line)
            .map_err(|e| format!("sidecar read: {e}"))?;

        let resp: serde_json::Value =
            serde_json::from_str(line.trim()).map_err(|e| format!("sidecar parse: {e}"))?;

        if let Some(err) = resp.get("error") {
            return Err(err.to_string());
        }

        Ok(resp["result"].clone())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_spawn_and_ping() {
        // Dev path: python script (no exe needed)
        let mut state = SidecarState::spawn(None).expect("failed to spawn sidecar");
        let result = state
            .call_inner("system.ping", serde_json::json!({}))
            .expect("system.ping failed");
        assert_eq!(result["ok"], true);
        assert_eq!(result["msg"], "pong");
    }

    #[test]
    fn test_unknown_method_returns_error() {
        let mut state = SidecarState::spawn(None).expect("failed to spawn sidecar");
        let result = state.call_inner("does.not.exist", serde_json::json!({}));
        assert!(result.is_err());
    }

    #[test]
    fn test_spawn_exe_and_ping() {
        let exe = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../sidecar/dist/sidecar.exe");
        if !exe.exists() {
            eprintln!("sidecar.exe not built — run scripts/build-sidecar.ps1 first; skipping");
            return;
        }
        let mut state = SidecarState::spawn(Some(exe)).expect("failed to spawn sidecar.exe");
        let result = state
            .call_inner("system.ping", serde_json::json!({}))
            .expect("system.ping via exe failed");
        assert_eq!(result["ok"], true);
        assert_eq!(result["msg"], "pong");
    }
}

#[tauri::command]
pub fn invoke_sidecar(
    state: tauri::State<'_, Mutex<SidecarState>>,
    method: String,
    params: serde_json::Value,
) -> Result<serde_json::Value, String> {
    state
        .lock()
        .map_err(|e| format!("Sidecar lock poisoned: {e}"))?
        .call_inner(&method, params)
}

/// Issue #29: return this session's log path and the tail of its contents
/// (capped) so the frontend can build a "Copy diagnostic" payload. The file
/// is re-opened read-only (Windows allows reading while the child appends);
/// a missing/unreadable file yields empty contents, never an error, so the
/// diagnostic button still works (it just has no log lines yet). The
/// last-N-lines trim lives in TypeScript (src/lib/diagnostic.ts) where it is
/// unit-tested.
#[tauri::command]
pub fn read_diagnostic_log(
    state: tauri::State<'_, Mutex<SidecarState>>,
) -> Result<serde_json::Value, String> {
    let path = state
        .lock()
        .map_err(|e| format!("Sidecar lock poisoned: {e}"))?
        .log_path()
        .to_path_buf();

    const CAP: usize = 64 * 1024;
    let bytes = fs::read(&path).unwrap_or_default();
    let start = bytes.len().saturating_sub(CAP);
    let contents = String::from_utf8_lossy(&bytes[start..]).into_owned();

    Ok(serde_json::json!({
        "path": path.to_string_lossy(),
        "contents": contents,
    }))
}
