use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Stdio};
use std::sync::Mutex;

pub struct SidecarState {
    stdin: ChildStdin,
    stdout: BufReader<std::process::ChildStdout>,
    next_id: u64,
    _child: Child,
}

impl SidecarState {
    /// Spawn the sidecar process.
    /// `exe_path` = `None` in dev (uses `python sidecar/main.py`);
    ///             = `Some(path/to/sidecar.exe)` in release builds.
    pub fn spawn(exe_path: Option<PathBuf>) -> Result<Self, String> {
        // Use arg list, never a shell string — apostrophe in the path is safe.
        let mut child = match exe_path {
            Some(exe) => std::process::Command::new(exe)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::inherit())
                .spawn()
                .map_err(|e| format!("Failed to spawn sidecar exe: {e}"))?,
            None => {
                let script =
                    std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../sidecar/main.py");
                std::process::Command::new("python")
                    .arg(&script)
                    .stdin(Stdio::piped())
                    .stdout(Stdio::piped())
                    .stderr(Stdio::inherit())
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
            _child: child,
        })
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
