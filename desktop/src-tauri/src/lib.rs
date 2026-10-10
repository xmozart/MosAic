//! The MosAic desktop shell (M3; ADR 0057, 0060).
//!
//! It starts the Python backend as a sidecar on a free loopback port with a fresh
//! per-launch token (written to its stdin, never on a command line), waits until it is
//! healthy, and shows the backend's own page in a window that may not navigate anywhere
//! else. If the backend exits unexpectedly it is started again (with a new token and port)
//! and the window follows; unfinished jobs resume from the task log. On quit the windows
//! close first (their event streams with them), then the backend gets SIGTERM and time to
//! let its workers finish or checkpoint their current task.

mod backend;

use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tauri::menu::{Menu, MenuBuilder, MenuItem, PredefinedMenuItem, SubmenuBuilder};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, Wry};

use backend::Backend;

/// Window labels are `main-<port>`: a restarted backend gets a new window while the old
/// one is still closing (labels must be unique).
const WINDOW: &str = "main";
const MAX_RESTARTS: usize = 5; // within RESTART_WINDOW, then give up and say so
const RESTART_WINDOW: Duration = Duration::from_secs(120);

#[derive(Default)]
struct State {
    backend: Option<Arc<Backend>>,
    quitting: bool,
    stopped: bool,
    launching: bool, // a backend is starting: a quit waits for it, then stops it

    restarts: Vec<Instant>,
}

type Shared = Arc<Mutex<State>>;

pub fn run() {
    let shared: Shared = Arc::new(Mutex::new(State::default()));
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(shared.clone())
        .menu(app_menu)
        .on_menu_event(|app, event| {
            if event.id().as_ref() == "quit" {
                request_quit(app);
            }
        })
        .setup(move |app| {
            build_tray(app.handle())?;
            quit_on_signals(app.handle().clone());
            supervise(app.handle().clone(), shared.clone());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("the MosAic shell could not start");
    app.run(|handle, event| match event {
        // The last window closed (or was replaced for a restarted backend): MosAic keeps
        // working from the menu bar, as Mac apps do.
        RunEvent::ExitRequested {
            code: None, api, ..
        } => {
            if !shared_state(handle).lock().unwrap().quitting {
                api.prevent_exit();
            }
        }
        // Any other exit request goes through the graceful quit unless it is done.
        RunEvent::ExitRequested { api, .. } => {
            if !shared_state(handle).lock().unwrap().stopped {
                api.prevent_exit();
                request_quit(handle);
            }
        }
        #[cfg(target_os = "macos")]
        RunEvent::Reopen { .. } => show_window(handle),
        _ => {}
    });
}

/// SIGTERM, SIGINT or SIGHUP to the shell (a `kill`, a terminal's Ctrl-C) is a quit too:
/// the same graceful path as ⌘Q.
#[cfg(unix)]
fn quit_on_signals(app: AppHandle) {
    use signal_hook::consts::{SIGHUP, SIGINT, SIGTERM};
    match signal_hook::iterator::Signals::new([SIGTERM, SIGINT, SIGHUP]) {
        Ok(mut signals) => {
            std::thread::spawn(move || {
                if signals.forever().next().is_some() {
                    let handle = app.clone();
                    let _ = app.run_on_main_thread(move || request_quit(&handle));
                }
            });
        }
        Err(e) => log::warn!("no signal handler: {e}"),
    }
}

#[cfg(not(unix))]
fn quit_on_signals(_app: AppHandle) {}

fn shared_state(app: &AppHandle) -> Shared {
    app.state::<Shared>().inner().clone()
}

/// MosAic's own app menu: its Quit (⌘Q) is the graceful quit, independent of how the
/// platform reports a menu quit; Edit keeps copy and paste working in text fields.
fn app_menu(app: &AppHandle) -> tauri::Result<Menu<Wry>> {
    let quit = MenuItem::with_id(app, "quit", "Quit MosAic", true, Some("CmdOrCtrl+Q"))?;
    let app_menu = SubmenuBuilder::new(app, "MosAic")
        .item(&PredefinedMenuItem::about(app, Some("About MosAic"), None)?)
        .separator()
        .item(&PredefinedMenuItem::services(app, None)?)
        .separator()
        .item(&PredefinedMenuItem::hide(app, None)?)
        .item(&PredefinedMenuItem::hide_others(app, None)?)
        .item(&PredefinedMenuItem::show_all(app, None)?)
        .separator()
        .item(&quit)
        .build()?;
    let edit = SubmenuBuilder::new(app, "Edit")
        .undo()
        .redo()
        .separator()
        .cut()
        .copy()
        .paste()
        .select_all()
        .build()?;
    let window = SubmenuBuilder::new(app, "Window")
        .minimize()
        .close_window()
        .build()?;
    MenuBuilder::new(app)
        .items(&[&app_menu, &edit, &window])
        .build()
}

/// Closes the windows (and their event streams), stops the backend off the main thread,
/// then exits for real.
fn request_quit(app: &AppHandle) {
    let shared = shared_state(app);
    {
        let mut s = shared.lock().unwrap();
        if s.quitting {
            return;
        }
        s.quitting = true;
    }
    for (_, w) in app.webview_windows() {
        let _ = w.destroy();
    }
    let handle = app.clone();
    std::thread::spawn(move || {
        // A backend still starting is waited for, so it gets the same graceful stop.
        let backend = loop {
            let mut s = shared.lock().unwrap();
            if !s.launching {
                break s.backend.take();
            }
            drop(s);
            std::thread::sleep(Duration::from_millis(100));
        };
        if let Some(b) = backend {
            b.stop(); // SIGTERM, then a grace period for workers (ADR 0060)
        }
        shared.lock().unwrap().stopped = true;
        handle.exit(0);
    });
}

/// Starts the backend and keeps it running: an unexpected exit or a failed start is
/// retried (the window follows a new port and token), up to the restart budget.
fn supervise(app: AppHandle, shared: Shared) {
    std::thread::spawn(move || loop {
        {
            let mut s = shared.lock().unwrap();
            if s.quitting {
                return;
            }
            s.launching = true;
        }
        let launched = Backend::launch(&app);
        let failure = match launched {
            Ok(b) => {
                let b = Arc::new(b);
                let exited = b.exit_signal();
                let (port, token) = (b.port, b.token.clone());
                {
                    // One lock for the check and the store: a quit sees this backend.
                    let mut s = shared.lock().unwrap();
                    s.launching = false;
                    s.backend = Some(b);
                    if s.quitting {
                        return; // request_quit takes and stops it
                    }
                }
                let handle = app.clone();
                let _ = app.run_on_main_thread(move || open_window(&handle, port, &token));
                let _ = exited.recv();
                {
                    let mut s = shared.lock().unwrap();
                    if s.quitting {
                        return;
                    }
                    s.backend = None;
                }
                "MosAic's engine keeps stopping.".to_string()
            }
            Err(e) => {
                let mut s = shared.lock().unwrap();
                s.launching = false;
                if s.quitting {
                    return;
                }
                format!("MosAic's engine didn't start: {e}")
            }
        };
        let retry = {
            let mut s = shared.lock().unwrap();
            let now = Instant::now();
            s.restarts
                .retain(|t| now.duration_since(*t) < RESTART_WINDOW);
            s.restarts.push(now);
            s.restarts.len() <= MAX_RESTARTS
        };
        if !retry {
            fatal(
                &app,
                &format!("{failure} See backend.log in ~/Library/Logs/com.mosaic.desktop."),
            );
            return;
        }
        log::warn!("{failure} Starting it again.");
        std::thread::sleep(Duration::from_secs(1));
    });
}

fn main_window(app: &AppHandle) -> Option<tauri::WebviewWindow> {
    app.webview_windows()
        .into_iter()
        .find(|(label, _)| label.starts_with(WINDOW))
        .map(|(_, w)| w)
}

fn open_window(app: &AppHandle, port: u16, token: &str) {
    if shared_state(app).lock().unwrap().quitting {
        return;
    }
    // A restarted backend has a new origin and token: a new window replaces the old.
    let old = main_window(app);
    // Development builds may open another page first (MOSAIC_DEV_START_PATH, e.g. a
    // preview) to check media in the real webview; release builds always open "/".
    let start = if cfg!(debug_assertions) {
        std::env::var("MOSAIC_DEV_START_PATH").unwrap_or_else(|_| "/".into())
    } else {
        "/".into()
    };
    let url = format!("http://127.0.0.1:{port}{start}");
    // The token reaches only this webview; the page trades it once for a session cookie
    // and forgets it (ADR 0057). serde_json quotes it safely for JavaScript.
    let script = format!(
        "window.__MOSAIC_DESKTOP__ = {{ token: {} }};",
        serde_json::to_string(token).unwrap()
    );
    let label = format!("{WINDOW}-{port}");
    let result = WebviewWindowBuilder::new(app, &label, WebviewUrl::External(url.parse().unwrap()))
        .title("MosAic")
        .inner_size(1440.0, 900.0)
        .min_inner_size(1280.0, 800.0)
        .initialization_script(&script)
        // Only the backend's own origin: links elsewhere never load in this window.
        .on_navigation(move |u| {
            u.scheme() == "http" && u.host_str() == Some("127.0.0.1") && u.port() == Some(port)
        })
        .build();
    match result {
        Ok(_) => {
            if let Some(old) = old {
                let _ = old.destroy();
            }
        }
        Err(e) => fatal(app, &format!("MosAic's window didn't open: {e}")),
    }
}

/// Brings the window back, opening it again after it was closed.
fn show_window(app: &AppHandle) {
    if let Some(w) = main_window(app) {
        let _ = w.show();
        let _ = w.set_focus();
        return;
    }
    let current = shared_state(app)
        .lock()
        .unwrap()
        .backend
        .as_ref()
        .map(|b| (b.port, b.token.clone()));
    if let Some((port, token)) = current {
        open_window(app, port, &token);
    }
}

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let pause = MenuItem::with_id(app, "pause", "Pause all work", true, None::<&str>)?;
    let resume = MenuItem::with_id(app, "resume", "Resume work", true, None::<&str>)?;
    let show = MenuItem::with_id(app, "show", "Show MosAic", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "tray-quit", "Quit MosAic", true, None::<&str>)?;
    let sep = PredefinedMenuItem::separator(app)?;
    let menu = Menu::with_items(app, &[&show, &sep, &pause, &resume, &sep, &quit])?;
    // A template image: black tiles on transparent, which macOS tints for the menu bar.
    let icon = tauri::image::Image::from_bytes(include_bytes!("../icons/tray-template@2x.png"))?;
    TrayIconBuilder::with_id("mosaic")
        .menu(&menu)
        .tooltip("MosAic")
        .icon(icon)
        .icon_as_template(true)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "pause" | "resume" => {
                let action = event.id.as_ref().to_string();
                // Copy what the call needs; never hold the state lock across it.
                let target = shared_state(app)
                    .lock()
                    .unwrap()
                    .backend
                    .as_ref()
                    .map(|b| (b.port, b.token.clone()));
                if let Some((port, token)) = target {
                    std::thread::spawn(move || {
                        if let Err(e) =
                            backend::post(port, &token, &format!("/api/jobs/{action}-all"))
                        {
                            log::warn!("{action} all: {e}");
                        }
                    });
                }
            }
            "show" => show_window(app),
            "tray-quit" => request_quit(app),
            _ => {}
        })
        .build(app)?;
    Ok(())
}

fn fatal(app: &AppHandle, message: &str) {
    use tauri_plugin_dialog::{DialogExt, MessageDialogKind};
    log::error!("{message}");
    let handle = app.clone();
    app.dialog()
        .message(message)
        .title("MosAic")
        .kind(MessageDialogKind::Error)
        .show(move |_| request_quit(&handle));
}
