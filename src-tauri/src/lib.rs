use std::sync::Mutex;
use tauri::Manager;

mod sidecar;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            #[cfg(debug_assertions)]
            let exe_path = None;

            #[cfg(not(debug_assertions))]
            let exe_path = Some(app.path().resource_dir()?.join("sidecar.exe"));

            let sc = sidecar::SidecarState::spawn(exe_path)
                .expect("Failed to spawn sidecar");
            app.manage(Mutex::new(sc));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![sidecar::invoke_sidecar])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
