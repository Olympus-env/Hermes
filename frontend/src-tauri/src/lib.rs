//! Entrée Tauri — fenêtre desktop + gestion du cycle de vie backend/PYTHIA.
//!
//! En **release**, Tauri devient propriétaire du cycle de vie :
//!   - démarrage : dans un thread dédié (la fenêtre reste réactive), si backend
//!     (port 8000) ou Ollama (port 11434) ne répondent pas, on les lance comme
//!     processus enfants et on émet l'événement `hermes-services-etat` ;
//!   - fermeture : on tue ces enfants à la destruction de la fenêtre
//!     principale, garantissant l'arrêt complet de HERMES ;
//!   - crash : sous Windows, les enfants sont rattachés à un Job Object
//!     « kill-on-close » et meurent aussi si hermes.exe est tué brutalement.
//!
//! En **debug** (`cargo tauri dev`), on ne lance rien — le développeur garde
//! la main via `scripts/start-backend.ps1` etc.

use std::fs;
use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::Serialize;

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

// --------------------------------------------------------------------------- //
// État partagé des sous-processus démarrés par Tauri
// --------------------------------------------------------------------------- //

/// Job Object Windows « kill-on-close » : tant que hermes.exe vit, il détient le
/// handle ; s'il est tué brutalement, Windows ferme le handle et tue tous les
/// processus assignés (backend, Ollama et leurs enfants).
#[cfg(windows)]
struct JobGuard(win32job::Job);

#[cfg(windows)]
fn create_kill_on_close_job() -> Option<JobGuard> {
    let job = win32job::Job::create().ok()?;
    let mut info = job.query_extended_limit_info().ok()?;
    info.limit_kill_on_job_close();
    job.set_extended_limit_info(&mut info).ok()?;
    Some(JobGuard(job))
}

#[derive(Default)]
struct ServiceState {
    backend: Option<Child>,
    ollama: Option<Child>,
    /// Vrai une fois la fenêtre détruite : un démarrage encore en cours ne doit
    /// plus laisser d'enfant vivant derrière lui.
    arret: bool,
    #[cfg(windows)]
    job: Option<JobGuard>,
}

impl ServiceState {
    fn shutdown(&mut self) {
        self.arret = true;
        if let Some(mut child) = self.backend.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
        if let Some(mut child) = self.ollama.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }

    /// Rattache un enfant au Job Object (Windows) pour qu'il ne survive pas à
    /// hermes.exe. Renvoie `false` (et tue l'enfant) si l'arrêt est déjà demandé.
    fn adopter(&mut self, child: &mut Child) -> bool {
        #[cfg(windows)]
        {
            use std::os::windows::io::AsRawHandle;
            if self.job.is_none() {
                self.job = create_kill_on_close_job();
            }
            if let Some(job) = &self.job {
                if let Err(e) = job.0.assign_process(child.as_raw_handle() as isize) {
                    eprintln!("[HERMES] Job Object : rattachement impossible ({e})");
                }
            }
        }
        if self.arret {
            let _ = child.kill();
            let _ = child.wait();
            return false;
        }
        true
    }
}

type SharedState = Mutex<ServiceState>;

// --------------------------------------------------------------------------- //
// Événement d'état pour le frontend
// --------------------------------------------------------------------------- //

/// Émis à chaque changement d'état d'un service, pour que le frontend puisse
/// afficher « démarrage… » plutôt qu'une fenêtre figée.
const EVENT_ETAT: &str = "hermes-services-etat";

#[derive(Clone, Serialize)]
struct EtatService {
    /// "pythia" ou "backend"
    service: &'static str,
    /// "demarrage", "pret" ou "erreur"
    etat: &'static str,
    message: Option<String>,
}

fn emettre(
    app: &tauri::AppHandle,
    service: &'static str,
    etat: &'static str,
    message: Option<String>,
) {
    use tauri::Emitter;
    let _ = app.emit(
        EVENT_ETAT,
        EtatService {
            service,
            etat,
            message,
        },
    );
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

/// Vrai si un HERMES répond sur `/health` (`"app": "HERMES"`). Distingue notre
/// backend d'un autre service qui occuperait le port.
fn is_hermes_backend(port: u16) -> bool {
    let Ok(addr) = format!("127.0.0.1:{port}").parse() else {
        return false;
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_millis(500)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
    let requete = "GET /health HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
    if stream.write_all(requete.as_bytes()).is_err() {
        return false;
    }
    let mut reponse = String::new();
    // Une erreur de lecture (timeout) après réception partielle reste exploitable.
    let _ = stream.take(16 * 1024).read_to_string(&mut reponse);
    let compact: String = reponse.split_whitespace().collect();
    compact.contains("\"app\":\"HERMES\"")
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

fn existing_path_from_env(key: &str) -> Option<PathBuf> {
    std::env::var(key)
        .ok()
        .map(PathBuf::from)
        .filter(|p| p.exists())
}

fn local_app_data_dir() -> PathBuf {
    if let Ok(base) = std::env::var("LOCALAPPDATA") {
        return PathBuf::from(base).join("HERMES");
    }
    std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(Path::to_path_buf))
        .unwrap_or_else(|| PathBuf::from("."))
        .join("data")
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

/// Enregistre l'enfant dans l'état partagé (verrou pris brièvement : la fenêtre
/// peut se fermer pendant que l'attente de disponibilité continue).
fn enregistrer(state: &SharedState, mut child: Child, ollama: bool) -> Result<(), String> {
    let mut guard = state
        .lock()
        .map_err(|_| "État des services indisponible.".to_string())?;
    if !guard.adopter(&mut child) {
        return Err("Arrêt de HERMES demandé pendant le démarrage.".into());
    }
    if ollama {
        guard.ollama = Some(child);
    } else {
        guard.backend = Some(child);
    }
    Ok(())
}

fn start_ollama(state: &SharedState) -> Result<(), String> {
    if port_listening("127.0.0.1", 11434) {
        // Ollama tourne déjà — on ne le possède pas, on ne le tuera pas.
        return Ok(());
    }

    let exe = locate_ollama_exe()
        .ok_or_else(|| "PYTHIA/Ollama introuvable sur cette machine.".to_string())?;

    let models_dir = env_or(
        "OLLAMA_MODELS",
        &local_app_data_dir()
            .join("ollama")
            .join("models")
            .display()
            .to_string(),
    );
    fs::create_dir_all(&models_dir)
        .map_err(|e| format!("Création dossier modèles Ollama : {e}"))?;

    let child = hidden_command(&exe)
        .arg("serve")
        .env("OLLAMA_MODELS", models_dir)
        .spawn()
        .map_err(|e| format!("Lancement Ollama : {e}"))?;
    enregistrer(state, child, true)?;

    if !wait_until_listening("127.0.0.1", 11434, Duration::from_secs(25)) {
        return Err("PYTHIA/Ollama n'a pas répondu sur 127.0.0.1:11434.".into());
    }
    Ok(())
}

fn start_backend(state: &SharedState) -> Result<(), String> {
    if port_listening("127.0.0.1", 8000) {
        // Le port est pris : on ne réutilise que si c'est bien un backend HERMES.
        if is_hermes_backend(8000) {
            return Ok(());
        }
        return Err(
            "Le port 8000 est occupé par un autre service que HERMES. \
             Libère-le puis relance HERMES."
                .into(),
        );
    }

    let backend_dir = locate_backend_dir().ok();
    let data_dir = env_or(
        "HERMES_DATA_DIR",
        &local_app_data_dir().display().to_string(),
    );
    let data_dir = PathBuf::from(data_dir);
    let storage = env_or(
        "HERMES_STORAGE_PATH",
        &data_dir.join("storage").display().to_string(),
    );
    let db_path = env_or(
        "HERMES_DB_PATH",
        &data_dir.join("hermes.db").display().to_string(),
    );
    let log_path = env_or(
        "HERMES_LOG_PATH",
        &data_dir.join("logs").display().to_string(),
    );
    let master_key_path = env_or(
        "HERMES_MASTER_KEY_PATH",
        &data_dir.join("master.key").display().to_string(),
    );

    // 1) Mode bundle final : backend.exe autonome (PyInstaller).
    if let Some(backend_exe) = locate_backend_exe() {
        let child = hidden_command(&backend_exe)
            .env("HERMES_DB_PATH", &db_path)
            .env("HERMES_STORAGE_PATH", &storage)
            .env("HERMES_LOG_PATH", &log_path)
            .env("HERMES_MASTER_KEY_PATH", &master_key_path)
            .spawn()
            .map_err(|e| format!("Lancement backend.exe : {e}"))?;
        enregistrer(state, child, false)?;
    } else {
        // 2) Fallback dev : python.exe du venv local.
        let backend_dir = backend_dir
            .ok_or_else(|| "Backend introuvable (ni backend.exe ni venv Python).".to_string())?;
        let python = backend_dir.join(r".venv\Scripts\python.exe");
        if !python.exists() {
            return Err(format!(
                "Python venv backend introuvable : {}",
                python.display()
            ));
        }

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
            .env("HERMES_LOG_PATH", log_path)
            .env("HERMES_MASTER_KEY_PATH", master_key_path)
            .spawn()
            .map_err(|e| format!("Lancement backend (python) : {e}"))?;
        enregistrer(state, child, false)?;
    }

    if !wait_until_listening("127.0.0.1", 8000, Duration::from_secs(35)) {
        return Err("Backend HERMES n'a pas répondu sur 127.0.0.1:8000.".into());
    }
    Ok(())
}

fn locate_ollama_exe() -> Option<PathBuf> {
    if let Some(path) = existing_path_from_env("HERMES_OLLAMA_EXE") {
        return Some(path);
    }

    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            let bundled = parent.join("ollama").join("ollama.exe");
            if bundled.exists() {
                return Some(bundled);
            }
        }
    }

    let mut candidates = Vec::new();
    if let Ok(program_files) = std::env::var("ProgramFiles") {
        candidates.push(
            PathBuf::from(&program_files)
                .join("Ollama")
                .join("ollama.exe"),
        );
    }
    if let Ok(program_files_x86) = std::env::var("ProgramFiles(x86)") {
        candidates.push(
            PathBuf::from(&program_files_x86)
                .join("Ollama")
                .join("ollama.exe"),
        );
    }
    if let Ok(local_app_data) = std::env::var("LOCALAPPDATA") {
        candidates.push(
            PathBuf::from(local_app_data)
                .join("Programs")
                .join("Ollama")
                .join("ollama.exe"),
        );
    }
    candidates.into_iter().find(|p| p.exists())
}

fn locate_backend_exe() -> Option<PathBuf> {
    // Priorités, du plus officiel au moins :
    //   1. variable d'environnement HERMES_BACKEND_EXE
    //   2. backend\backend.exe à côté de hermes.exe (cas bundle final)
    //   3. backend\backend.exe découvert depuis le dossier courant.

    if let Some(path) = existing_path_from_env("HERMES_BACKEND_EXE") {
        return Some(path);
    }

    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            let bundled = parent.join("backend").join("backend.exe");
            if bundled.exists() {
                return Some(bundled);
            }
        }
    }

    None
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

    Err("Dossier backend/ introuvable depuis l'exécutable HERMES.".into())
}

/// Démarre PYTHIA puis le backend en émettant l'état de chaque service.
#[cfg(not(debug_assertions))]
fn start_services(app: &tauri::AppHandle) {
    use tauri::Manager;
    let Some(state) = app.try_state::<SharedState>() else {
        return;
    };

    emettre(app, "pythia", "demarrage", None);
    match start_ollama(&state) {
        Ok(()) => emettre(app, "pythia", "pret", None),
        Err(e) => {
            eprintln!("[HERMES] PYTHIA : {e}");
            emettre(app, "pythia", "erreur", Some(e));
        }
    }

    emettre(app, "backend", "demarrage", None);
    match start_backend(&state) {
        Ok(()) => emettre(app, "backend", "pret", None),
        Err(e) => {
            eprintln!("[HERMES] Backend : {e}");
            emettre(app, "backend", "erreur", Some(e));
        }
    }
}

// --------------------------------------------------------------------------- //
// Intégration système : zone de notification (tray) et commandes frontend
// --------------------------------------------------------------------------- //

/// Réglage « fermer la fenêtre = réduire dans la zone de notification ».
/// Faux par défaut : tant que le frontend n'a rien synchronisé, fermer la
/// fenêtre quitte réellement HERMES (et arrête backend + PYTHIA).
#[derive(Default)]
struct ReglageTray {
    reduire_a_la_fermeture: AtomicBool,
}

/// Événements émis vers le frontend par le menu du tray.
const EVENT_TRAY_VEILLE: &str = "hermes-tray-veille";
const EVENT_TRAY_PAUSE: &str = "hermes-tray-pause";

/// Vraie sortie : arrête backend + PYTHIA puis quitte le processus.
fn quitter_hermes(app: &tauri::AppHandle) {
    use tauri::Manager;
    if let Some(state) = app.try_state::<SharedState>() {
        if let Ok(mut guard) = state.lock() {
            guard.shutdown();
        }
    }
    app.exit(0);
}

fn afficher_fenetre(app: &tauri::AppHandle) {
    use tauri::Manager;
    if let Some(fenetre) = app.get_webview_window("main") {
        let _ = fenetre.show();
        let _ = fenetre.unminimize();
        let _ = fenetre.set_focus();
    }
}

fn construire_tray(app: &tauri::App) -> tauri::Result<()> {
    use tauri::menu::{MenuBuilder, MenuItemBuilder};
    use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
    use tauri::Emitter;

    let menu = MenuBuilder::new(app)
        .item(&MenuItemBuilder::with_id("ouvrir", "Ouvrir HERMES").build(app)?)
        .item(&MenuItemBuilder::with_id("veille", "Lancer une veille maintenant").build(app)?)
        .item(&MenuItemBuilder::with_id("pause", "Mettre en pause / reprendre").build(app)?)
        .separator()
        .item(&MenuItemBuilder::with_id("quitter", "Quitter").build(app)?)
        .build()?;

    let mut tray = TrayIconBuilder::with_id("hermes")
        .tooltip("HERMES")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "ouvrir" => afficher_fenetre(app),
            "veille" => {
                afficher_fenetre(app);
                let _ = app.emit(EVENT_TRAY_VEILLE, ());
            }
            "pause" => {
                let _ = app.emit(EVENT_TRAY_PAUSE, ());
            }
            "quitter" => quitter_hermes(app),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                afficher_fenetre(tray.app_handle());
            }
        });
    if let Some(icone) = app.default_window_icon() {
        tray = tray.icon(icone.clone());
    }
    tray.build(app)?;
    Ok(())
}

/// Synchronisé par le frontend (réglage Paramètres) au démarrage et à chaque changement.
#[tauri::command]
fn definir_reduire_dans_tray(actif: bool, reglage: tauri::State<'_, ReglageTray>) {
    reglage
        .reduire_a_la_fermeture
        .store(actif, Ordering::Relaxed);
}

/// Écrit un export PDF à l'emplacement choisi via le dialogue natif « Enregistrer sous ».
/// Corps brut = octets du fichier ; chemin en en-tête `chemin` (encodeURIComponent).
#[tauri::command]
fn enregistrer_fichier(request: tauri::ipc::Request<'_>) -> Result<(), String> {
    let tauri::ipc::InvokeBody::Raw(octets) = request.body() else {
        return Err("Contenu du fichier manquant.".into());
    };
    let brut = request
        .headers()
        .get("chemin")
        .and_then(|v| v.to_str().ok())
        .ok_or_else(|| "Chemin de destination manquant.".to_string())?;
    let chemin = PathBuf::from(decoder_url(brut));
    let extension = chemin
        .extension()
        .and_then(|e| e.to_str())
        .map(str::to_ascii_lowercase);
    if extension.as_deref() != Some("pdf") {
        return Err("Seuls les exports PDF peuvent être enregistrés.".into());
    }
    fs::write(&chemin, octets).map_err(|e| format!("Écriture de {} : {e}", chemin.display()))
}

/// Décodage « percent-encoding » minimal (en-tête produit par encodeURIComponent).
fn decoder_url(s: &str) -> String {
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' && i + 2 < b.len() {
            if let Some(v) = s
                .get(i + 1..i + 3)
                .and_then(|h| u8::from_str_radix(h, 16).ok())
            {
                out.push(v);
                i += 3;
                continue;
            }
        }
        out.push(b[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

// --------------------------------------------------------------------------- //
// Entrée Tauri
// --------------------------------------------------------------------------- //

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_dialog::init())
        // Mémorise taille, position et état maximisé. VISIBLE est exclu : une fenêtre
        // réduite dans le tray à la fermeture doit réapparaître au prochain lancement.
        .plugin(
            tauri_plugin_window_state::Builder::default()
                .with_state_flags(
                    tauri_plugin_window_state::StateFlags::all()
                        - tauri_plugin_window_state::StateFlags::VISIBLE,
                )
                .build(),
        )
        .manage(Mutex::<ServiceState>::default())
        .manage(ReglageTray::default())
        .invoke_handler(tauri::generate_handler![
            definir_reduire_dans_tray,
            enregistrer_fichier
        ])
        .setup(|app| {
            if let Err(e) = construire_tray(app) {
                // Le tray est un confort : sans lui, l'app reste pleinement utilisable.
                eprintln!("[HERMES] Zone de notification indisponible : {e}");
            }
            // En dev, on ne touche pas aux services — le développeur les
            // gère lui-même via les scripts PowerShell. En release, on lance
            // tout ce qu'il faut, hors du thread UI (jusqu'à ~60 s d'attente).
            #[cfg(not(debug_assertions))]
            {
                let handle = app.handle().clone();
                std::thread::spawn(move || start_services(&handle));
            }
            #[cfg(debug_assertions)]
            {
                let _ = app; // évite warning unused
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            use tauri::Manager;
            match event {
                // Fermer la fenêtre : réduction dans le tray si le réglage est actif,
                // sinon c'est la vraie sortie (Destroyed, ci-dessous).
                tauri::WindowEvent::CloseRequested { api, .. } => {
                    let reduire = window
                        .app_handle()
                        .try_state::<ReglageTray>()
                        .is_some_and(|r| r.reduire_a_la_fermeture.load(Ordering::Relaxed));
                    if reduire {
                        api.prevent_close();
                        let _ = window.hide();
                    }
                }
                // À la destruction de la fenêtre principale, on coupe tout ce
                // que Tauri a démarré. La fenêtre est unique → Destroyed = fin
                // de l'application.
                tauri::WindowEvent::Destroyed => {
                    if let Some(state) = window.app_handle().try_state::<SharedState>() {
                        if let Ok(mut guard) = state.lock() {
                            guard.shutdown();
                        }
                    }
                }
                _ => {}
            }
        })
        .build(tauri::generate_context!())
        .expect("Erreur au démarrage de HERMES")
        .run(|app, event| {
            // Filet de sécurité : quelle que soit la voie de sortie (menu Quitter,
            // app.exit), backend et PYTHIA sont arrêtés.
            if matches!(event, tauri::RunEvent::Exit) {
                use tauri::Manager;
                if let Some(state) = app.try_state::<SharedState>() {
                    if let Ok(mut guard) = state.lock() {
                        guard.shutdown();
                    }
                }
            }
        });
}
