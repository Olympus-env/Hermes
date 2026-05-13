# src-tauri/

Wrapper Tauri (Rust) qui embarque le frontend Vite dans une fenêtre native.

**Pré-requis** : Rust stable installé (https://rustup.rs/) et Visual Studio Build Tools 2022 (Windows).

Une fois Rust en place :

```powershell
cd frontend
npm install @tauri-apps/cli @tauri-apps/api
npm run tauri dev      # mode dev (Vite + fenêtre Tauri)
npm run tauri build    # bundle desktop (installer Windows / .app macOS / .deb Linux)
```

Icônes attendues sous `src-tauri/icons/` :
- `32x32.png`, `128x128.png`, `icon.ico` (Windows), `icon.icns` (macOS).

Ces icônes peuvent être générées plus tard avec `cargo tauri icon mon-logo.png`.
