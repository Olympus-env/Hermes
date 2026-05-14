//! Entrée Tauri — fenêtre desktop + gestion du cycle de vie backend/PYTHIA.
//!
//! En **release**, Tauri devient propriétaire du cycle de vie :
//!   - démarrage : si backend (port 8000) ou Ollama (port 11434) ne répondent
//!     pas, on les lance comme processus enfants ;
//!   - fermeture : on tue ces enfants à la destruction de la fenêtre
//!     principale, garantissant l'arrêt complet de HERMES.
//!
//! En **debug** (`cargo tauri dev`), on ne lance rien — le développeur garde
//! la main via `scripts/start-backend.ps1` etc.

use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::{Duration, Instant};

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

// --------------------------------------------------------------------------- //
// État partagé des sous-processus démarrés par Tauri
// --------------------------------------------------------------------------- //

#[derive(Default)]
struct ServiceState {
    backend: Option<Child>,
    ollama: Option<Child>,
}

impl ServiceState {
    fn shutdown(&mut self) {
        if let Some(mut child) = self.backend.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
        if let Some(mut child) = self.ollama.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

// --------------------------------------------------------------------------- //
// Health checks réseau
// --------------------------------------------------------------------------- //

fn port_listening(host: &str, port: u16) -> bool {
    let Ok(addr) = format!("{host}:{port}").parse() else {
        return false;
    };
    TcpStream::connect_timeout(&addr, Duration::from_millis(500)).is_ok()
}

fn wait_until_listening(host: &str, port: u16, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if port_listening(host, port) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    false
}

// --------------------------------------------------------------------------- //
// Démarrage Ollama + backend
// --------------------------------------------------------------------------- //

fn env_or(key: &str, default: &str) -> String {
    std::env::var(key).unwrap_or_else(|_| default.to_string())
}

#[cfg(target_os = "windows")]
fn hidden_command(exe: &PathBuf) -> Command {
    let mut cmd = Command::new(exe);
    cmd.creation_flags(CREATE_NO_WINDOW);
    cmd
}

#[cfg(not(target_os = "windows"))]
fn hidden_command(exe: &PathBuf) -> Command {
    Command::new(exe)
}

fn start_ollama(state: &mut ServiceState) -> Result<(), String> {
    if port_listening("127.0.0.1", 11434) {
        // Ollama tourne déjà — on ne le possède pas, on ne le tuera pas.
        return Ok(());
    }

    let exe_path = env_or("HERMES_OLLAMA_EXE", r"D:\HermesDeps\ollama\bin\ollama.exe");
    let exe = PathBuf::from(&exe_path);
    if !exe.exists() {
        return Err(format!("PYTHIA/Ollama introuvable : {exe_path}"));
    }

    let models_dir = env_or("OLLAMA_MODELS", r"D:\HermesDeps\ollama\models");

    let child = hidden_command(&exe)
        .arg("serve")
        .env("OLLAMA_MODELS", models_dir)
        .spawn()
        .map_err(|e| format!("Lancement Ollama : {e}"))?;
    state.ollama = Some(child);

    if !wait_until_listening("127.0.0.1", 11434, Duration::from_secs(25)) {
        return Err("PYTHIA/Ollama n'a pas répondu sur 127.0.0.1:11434.".into());
    }
    Ok(())
}

fn start_backend(state: &mut ServiceState) -> Result<(), String> {
    if port_listening("127.0.0.1", 8000) {
        return Ok(());
    }

    let backend_dir = locate_backend_dir()?;
    let python = backend_dir.join(r".venv\Scripts\python.exe");
    if !python.exists() {
        return Err(format!(
            "Python venv backend introuvable : {}",
            python.display()
        ));
    }

    let storage = env_or(
        "HERMES_STORAGE_PATH",
        &backend_dir
            .parent()
            .map(|p| p.join("data").join("storage"))
            .unwrap_or_else(|| PathBuf::from(r"E:\Hermes\data\storage"))
            .display()
            .to_string(),
    );
    let db_path = env_or(
        "HERMES_DB_PATH",
        &backend_dir
            .parent()
            .map(|p| p.join("data").join("hermes.db"))
            .unwrap_or_else(|| PathBuf::from(r"E:\Hermes\data\hermes.db"))
            .display()
            .to_string(),
    );

    let child = hidden_command(&python)
        .args([
            "-m",
            "uvicorn",
            "hermes.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ])
        .current_dir(&backend_dir)
        .env("HERMES_DB_PATH", db_path)
        .env("HERMES_STORAGE_PATH", storage)
        .spawn()
        .map_err(|e| format!("Lancement backend : {e}"))?;
    state.backend = Some(child);

    if !wait_until_listening("127.0.0.1", 8000, Duration::from_secs(35)) {
        return Err("Backend HERMES n'a pas répondu sur 127.0.0.1:8000.".into());
    }
    Ok(())
}

fn locate_backend_dir() -> Result<PathBuf, String> {
    let exe = std::env::current_exe()
        .map_err(|e| format!("Impossible de localiser l'exécutable : {e}"))?;
    let mut dir = exe
        .parent()
        .ok_or_else(|| "Exécutable sans dossier parent".to_string())?
        .to_path_buf();

    for _ in 0..8 {
        let candidate = dir.join("backend");
        if candidate.join("hermes").join("main.py").exists() {
            return Ok(candidate);
        }
        match dir.parent() {
            Some(parent) => dir = parent.to_path_buf(),
            None => break,
        }
    }

    // Fallback codé en dur (env de développement Joshua).
    let fallback = PathBuf::from(r"E:\Hermes\backend");
    if fallback.join("hermes").join("main.py").exists() {
        return Ok(fallback);
    }
    Err("Dossier backend/ introuvable depuis l'exécutable HERMES.".into())
}

// --------------------------------------------------------------------------- //
// Entrée Tauri
// --------------------------------------------------------------------------- //

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(Mutex::<ServiceState>::default())
        .setup(|app| {
            // En dev, on ne touche pas aux services — le développeur les
            // gère lui-même via les scripts PowerShell. En release, on lance
            // tout ce qu'il faut.
            #[cfg(not(debug_assertions))]
            {
                use tauri::Manager;
                if let Some(state) = app.try_state::<Mutex<ServiceState>>() {
                    let mut guard = state.lock().unwrap();
                    if let Err(e) = start_ollama(&mut guard) {
                        eprintln!("[HERMES] PYTHIA : {e}");
                    }
                    if let Err(e) = start_backend(&mut guard) {
                        eprintln!("[HERMES] Backend : {e}");
                    }
                }
            }
            #[cfg(debug_assertions)]
            {
                let _ = app; // évite warning unused
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            // À la destruction de la fenêtre principale, on coupe tout ce
            // que Tauri a démarré. La fenêtre est unique → Destroyed = fin
            // de l'application.
            if matches!(event, tauri::WindowEvent::Destroyed) {
                use tauri::Manager;
                if let Some(state) = window.app_handle().try_state::<Mutex<ServiceState>>() {
                    if let Ok(mut guard) = state.lock() {
                        guard.shutdown();
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("Erreur au démarrage de HERMES");
}
