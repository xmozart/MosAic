//! The backend sidecar: launch with a per-launch token, health wait, graceful stop.

use std::fs::{File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager};

const READY: &str = "MOSAIC_READY port=";
const READY_TIMEOUT: Duration = Duration::from_secs(90); // a first start compiles bytecode
const HEALTH_TIMEOUT: Duration = Duration::from_secs(30);
const PROBE_TIMEOUT: Duration = Duration::from_secs(2);
const COMMAND_TIMEOUT: Duration = Duration::from_secs(10);
/// SIGTERM to the backend, then this long before SIGKILL: its own shutdown (event streams
/// cut after 5 s), the supervisor's wait for the worker (35 s), and some slack (ADR 0060).
const STOP_GRACE: Duration = Duration::from_secs(60);

pub struct Backend {
    pub port: u16,
    pub token: String,
    pid: u32,
    exited: Arc<AtomicBool>,
    exit_rx: Mutex<Option<Receiver<()>>>,
    lifeline: Mutex<Option<ChildStdin>>,
}

fn new_token() -> String {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).expect("no system randomness");
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn agent(timeout: Duration) -> ureq::Agent {
    ureq::Agent::config_builder()
        .timeout_global(Some(timeout))
        .build()
        .into()
}

/// How to run the backend: the bundled Python in a release (step 5), or the repository's
/// environment through `uv` in a development build.
fn command(app: &AppHandle) -> Result<Command, String> {
    let resources = app.path().resource_dir().map_err(|e| e.to_string())?;
    let bundled = resources.join("backend").join("bin").join("python3");
    if bundled.is_file() {
        let mut cmd = Command::new(bundled);
        cmd.args([
            "-m",
            "mosaic.cli.main",
            "serve",
            "--port",
            "0",
            "--token-stdin",
        ]);
        cmd.env("MOSAIC_UI_DIR", resources.join("ui"));
        cmd.env("MOSAIC_FFMPEG_DIR", resources.join("ffmpeg"));
        cmd.env("PYTHONNOUSERSITE", "1");
        return Ok(cmd);
    }
    if cfg!(debug_assertions) {
        let repo = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        let mut cmd = Command::new("uv");
        cmd.current_dir(&repo).args([
            "run",
            "--frozen",
            "mosaic",
            "serve",
            "--port",
            "0",
            "--token-stdin",
        ]);
        return Ok(cmd);
    }
    Err("the bundled backend is missing from the app".into())
}

fn log_file(app: &AppHandle) -> Result<(File, PathBuf), String> {
    // Next to the backend's own logs when MOSAIC_HOME points elsewhere (tests, a second
    // profile); else the Mac's standard place (~/Library/Logs/com.mosaic.desktop).
    let dir = match std::env::var_os("MOSAIC_HOME") {
        Some(home) => PathBuf::from(home).join("logs"),
        None => app.path().app_log_dir().map_err(|e| e.to_string())?,
    };
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let path = dir.join("backend.log");
    let file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .map_err(|e| e.to_string())?;
    Ok((file, path))
}

impl Backend {
    pub fn launch(app: &AppHandle) -> Result<Backend, String> {
        let token = new_token();
        let (log, log_path) = log_file(app)?;
        let mut cmd = command(app)?;
        cmd.env("MOSAIC_MODE", "desktop")
            .env("PYTHONUNBUFFERED", "1")
            .env_remove("MOSAIC_DESKTOP_TOKEN")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::from(log.try_clone().map_err(|e| e.to_string())?));
        let mut child: Child = cmd.spawn().map_err(|e| format!("{e}"))?;
        // The token on stdin: never in argv or this process's environment. Stdin then
        // stays open as a lifeline: if this shell dies, the backend sees end of file and
        // stops instead of running on as an orphan.
        let mut stdin = child.stdin.take().ok_or("no stdin")?;
        stdin
            .write_all(format!("{token}\n").as_bytes())
            .and_then(|_| stdin.flush())
            .map_err(|e| e.to_string())?;
        let stdout = child.stdout.take().ok_or("no stdout")?;
        let (port_tx, port_rx) = mpsc::channel::<u16>();
        let mut out_log = log.try_clone().map_err(|e| e.to_string())?;
        std::thread::spawn(move || {
            let mut sent = false;
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                if !sent {
                    if let Some(p) = line.trim().strip_prefix(READY).and_then(|p| p.parse().ok()) {
                        let _ = port_tx.send(p);
                        sent = true;
                        continue;
                    }
                }
                let _ = writeln!(out_log, "{line}");
            }
        });
        let pid = child.id();
        let exited = Arc::new(AtomicBool::new(false));
        let (exit_tx, exit_rx) = mpsc::channel::<()>();
        {
            let exited = exited.clone();
            std::thread::spawn(move || {
                let status = child.wait();
                log::info!("backend exited: {status:?}");
                exited.store(true, Ordering::SeqCst);
                let _ = exit_tx.send(());
            });
        }
        let backend = Backend {
            port: 0,
            token,
            pid,
            exited,
            exit_rx: Mutex::new(Some(exit_rx)),
            lifeline: Mutex::new(Some(stdin)),
        };
        let port = match port_rx.recv_timeout(READY_TIMEOUT) {
            Ok(p) => p,
            Err(RecvTimeoutError::Disconnected) => {
                return Err(format!(
                    "it stopped while starting (see {})",
                    log_path.display()
                ))
            }
            Err(RecvTimeoutError::Timeout) => {
                backend.stop();
                return Err(format!(
                    "it didn't report ready (see {})",
                    log_path.display()
                ));
            }
        };
        let backend = Backend { port, ..backend };
        if let Err(e) = backend.wait_healthy() {
            backend.stop();
            return Err(e);
        }
        Ok(backend)
    }

    fn wait_healthy(&self) -> Result<(), String> {
        let deadline = Instant::now() + HEALTH_TIMEOUT;
        let url = format!("http://127.0.0.1:{}/api/health", self.port);
        let probe = agent(PROBE_TIMEOUT);
        while Instant::now() < deadline {
            if self.has_exited() {
                return Err("it stopped while starting".into());
            }
            if probe.get(&url).call().is_ok() {
                return Ok(());
            }
            std::thread::sleep(Duration::from_millis(200));
        }
        Err("it didn't answer its health check".into())
    }

    pub fn has_exited(&self) -> bool {
        self.exited.load(Ordering::SeqCst)
    }

    /// Fires once when the process ends (for the restart watcher).
    pub fn exit_signal(&self) -> Receiver<()> {
        self.exit_rx.lock().unwrap().take().expect("one watcher")
    }

    /// Closes the lifeline, sends SIGTERM, and waits up to `STOP_GRACE` for the backend
    /// and its workers to finish or checkpoint; then SIGKILL. Signals go only to a process
    /// that has not been reaped (its PID could belong to another process by then).
    pub fn stop(&self) {
        drop(self.lifeline.lock().unwrap().take()); // end of file: the backend stops
        if !self.has_exited() {
            terminate(self.pid);
        }
        let deadline = Instant::now() + STOP_GRACE;
        while Instant::now() < deadline && !self.has_exited() {
            std::thread::sleep(Duration::from_millis(100));
        }
        if !self.has_exited() {
            kill(self.pid);
        }
    }
}

/// An authorized POST from the shell (the menu bar's Pause / Resume), with a timeout so a
/// hung backend never hangs the shell.
pub fn post(port: u16, token: &str, path: &str) -> Result<(), String> {
    agent(COMMAND_TIMEOUT)
        .post(&format!("http://127.0.0.1:{port}{path}"))
        .header("Authorization", &format!("Bearer {token}"))
        .header("Content-Type", "application/json")
        .send("{}")
        .map(|_| ())
        .map_err(|e| e.to_string())
}

#[cfg(unix)]
fn terminate(pid: u32) {
    unsafe {
        libc::kill(pid as i32, libc::SIGTERM);
    }
}

#[cfg(unix)]
fn kill(pid: u32) {
    unsafe {
        libc::kill(pid as i32, libc::SIGKILL);
    }
}

#[cfg(not(unix))]
fn terminate(_pid: u32) {} // Windows: a later milestone

#[cfg(not(unix))]
fn kill(_pid: u32) {}
