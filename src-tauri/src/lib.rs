mod commands;
mod crypto;
mod db;
mod error;
mod profile;
mod session;

use session::AppState;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(AppState::default())
        .invoke_handler(tauri::generate_handler![
            commands::list_profiles,
            commands::create_profile,
            commands::unlock_profile,
            commands::lock_profile,
            commands::reset_passphrase,
            commands::get_session,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
