//! Entrée Tauri minimaliste — démarre la fenêtre.
//!
//! Le backend Python est lancé séparément (FastAPI sur 127.0.0.1:8000).
//! L'autodémarrage du backend Python par Tauri sera ajouté en Phase 10
//! via `tauri::api::process::Command::new_sidecar(...)`.

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|_app| Ok(()))
        .run(tauri::generate_context!())
        .expect("Erreur au démarrage de HERMES");
}
