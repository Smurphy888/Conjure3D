use std::sync::Mutex;
use tauri::Manager;

mod sidecar;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let sc = sidecar::SidecarState::spawn().expect("Failed to spawn Python sidecar");
            app.manage(Mutex::new(sc));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![sidecar::invoke_sidecar])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
