use std::sync::Mutex;
use tauri::menu::{MenuBuilder, MenuItemBuilder, SubmenuBuilder};
use tauri::{Emitter, Manager};

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

            let run_wizard = MenuItemBuilder::with_id("run-wizard", "Re-run Setup Wizard")
                .build(app)?;
            let view_menu = SubmenuBuilder::new(app, "View")
                .item(&run_wizard)
                .build()?;
            let menu = MenuBuilder::new(app).item(&view_menu).build()?;
            app.set_menu(menu)?;

            Ok(())
        })
        .on_menu_event(|app, event| {
            if event.id().0 == "run-wizard" {
                app.emit("run-wizard", ()).ok();
            }
        })
        .invoke_handler(tauri::generate_handler![sidecar::invoke_sidecar])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
