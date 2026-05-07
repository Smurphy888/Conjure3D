use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, Stdio};
use std::sync::Mutex;

pub struct SidecarState {
    stdin: ChildStdin,
    stdout: BufReader<std::process::ChildStdout>,
    next_id: u64,
    _child: Child,
}

impl SidecarState {
    pub fn spawn() -> Result<Self, String> {
        let script = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../sidecar/main.py");

        // Use arg list, never a shell string, so the apostrophe in the path is safe.
        let mut child = std::process::Command::new("python")
            .arg(&script)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|e| format!("Failed to spawn sidecar: {e}"))?;

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
        let mut state = SidecarState::spawn().expect("failed to spawn sidecar");
        let result = state
            .call_inner("system.ping", serde_json::json!({}))
            .expect("system.ping failed");
        assert_eq!(result["ok"], true);
        assert_eq!(result["msg"], "pong");
    }

    #[test]
    fn test_unknown_method_returns_error() {
        let mut state = SidecarState::spawn().expect("failed to spawn sidecar");
        let result = state.call_inner("does.not.exist", serde_json::json!({}));
        assert!(result.is_err());
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
