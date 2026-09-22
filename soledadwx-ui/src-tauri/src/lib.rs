use futures_util::{SinkExt, StreamExt};
use serde_json::json;
use std::env;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::Duration;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager};
use tokio_tungstenite::{connect_async, tungstenite::protocol::Message};

const MPH_TO_KT: f64 = 0.868_976_241_900_647_9;

/// If the socket is alive but the station has sent no DATA for this long, the
/// connection is a zombie: it will never error, so the outer reconnect loop
/// would wait forever. Ambient pushes roughly once a minute, so ten minutes of
/// silence means something is wrong, not quiet weather. This is the failure
/// that produced two multi-week holes in the archive.
const DATA_STALL_SECS: u64 = 600;

/// Set only by the tray's Quit item. Everything else that looks like an exit —
/// notably closing the dashboard window — must NOT stop the recorder.
static QUITTING: AtomicBool = AtomicBool::new(false);

/// What the tray tooltip reports. Deliberately small and lock-light: the
/// websocket task writes it, a timer task reads it.
struct LiveState {
    last_data_epoch: Option<i64>,
    tempf: Option<f64>,
    humidity: Option<f64>,
    wind_mph: Option<f64>,
    recorded: u64,
    connected: bool,
}

static LIVE: Mutex<LiveState> = Mutex::new(LiveState {
    last_data_epoch: None,
    tempf: None,
    humidity: None,
    wind_mph: None,
    recorded: 0,
    connected: false,
});

/// Windows tray tooltips are capped at **64 UTF-16 code units** including the
/// null terminator (`NOTIFYICONDATA.szTip`), and the shell truncates silently
/// rather than complaining. The first version of this ran to 93 characters and
/// lost its last line mid-word. Everything below is written to fit 63, and
/// `clamp_tip` enforces it so a long value can never quietly eat a line again.
const TIP_MAX: usize = 63;

fn clamp_tip(s: String) -> String {
    // Count UTF-16 units, which is what the shell counts — '°' and '⚠' are one
    // unit each but two and three UTF-8 bytes, so byte length would mislead.
    if s.encode_utf16().count() <= TIP_MAX {
        return s;
    }
    let mut out = String::new();
    let mut n = 0usize;
    for ch in s.chars() {
        let w = ch.len_utf16();
        if n + w > TIP_MAX - 1 {
            break;
        }
        out.push(ch);
        n += w;
    }
    out.push('…');
    out
}

fn tooltip_text() -> String {
    let st = match LIVE.lock() {
        Ok(g) => g,
        Err(p) => p.into_inner(),
    };

    // Line 1: the conditions, compactly. No units spelled out — the numbers
    // and suffixes carry it, and every character is contended.
    let mut line1 = String::from("SoledadWX");
    if let Some(t) = st.tempf {
        line1.push_str(&format!(" {:.1}°F", t));
    }
    if let Some(h) = st.humidity {
        line1.push_str(&format!(" {:.0}%", h));
    }
    if let Some(w) = st.wind_mph {
        line1.push_str(&format!(" {:.1}kt", w * MPH_TO_KT));
    }

    // Line 2: the line that actually matters — proof the archive is being fed.
    // "running" and "recording" are different things, and this is the only
    // place the difference is visible without opening anything.
    let line2 = match st.last_data_epoch {
        Some(ts) => {
            let age = (chrono::Utc::now().timestamp() - ts).max(0);
            let ago = if age < 90 {
                format!("{}s", age)
            } else if age < 5400 {
                format!("{}m", age / 60)
            } else if age < 172_800 {
                format!("{:.1}h", age as f64 / 3600.0)
            } else {
                format!("{}d", age / 86_400)
            };
            let warn = if age > DATA_STALL_SECS as i64 { " ⚠" } else { "" };
            format!("Last {} ago{} · {} rec", ago, warn, st.recorded)
        }
        None => String::from(if st.connected {
            "Connected — no reading yet"
        } else {
            "NOT CONNECTED ⚠"
        }),
    };

    clamp_tip(format!("{}
{}", line1, line2))
}

/// Build the dashboard window on demand, or focus it if it already exists.
///
/// `tauri.conf.json` declares NO windows on purpose (the JSON schema forbids
/// comments, so the reason lives here): the app starts as a tray-resident
/// recorder with no webview at all — about 20 MB — and the ~490 MB of
/// WebView2 processes measured on 2026-09-21 are only paid while someone is
/// actually looking at the dashboard.
///
/// The window is genuinely destroyed when closed rather than hidden, so the
/// WebView2 processes (~490 MB, measured) exist only while the dashboard is
/// open. The recorder runs in its own task and is untouched either way.
fn open_dashboard(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.unminimize();
        let _ = w.show();
        let _ = w.set_focus();
        return;
    }
    match tauri::WebviewWindowBuilder::new(app, "main", tauri::WebviewUrl::App("index.html".into()))
        .title("SoledadWX")
        .inner_size(1800.0, 1150.0)
        .maximized(true)
        .build()
    {
        Ok(_) => println!("Dashboard window opened."),
        Err(e) => println!("Could not open dashboard: {:?}", e),
    }
}

pub mod db;
pub mod models;
use models::AmbientReading;

#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! You've been greeted from Rust!", name)
}

#[tauri::command]
fn db_status() -> Result<db::DbStatus, String> {
    db::status().map_err(|e| e.to_string())
}

#[tauri::command]
fn series_window(
    metric: String,
    start_ts: i64,
    end_ts: i64,
    max_points: i64,
) -> Result<Vec<db::SeriesPoint>, String> {
    db::series_window(&metric, start_ts, end_ts, max_points)
}

#[tauri::command]
fn query_series(metric: String, start: String, end: String) -> Result<Vec<db::SeriesPoint>, String> {
    db::series_daily(&metric, &start, &end)
}

#[tauri::command]
fn range_stats(metric: String, start: String, end: String) -> Result<db::RangeStats, String> {
    db::range_stats(&metric, &start, &end)
}

#[tauri::command]
fn console_stats() -> Result<db::ConsoleStats, String> {
    db::console_stats().map_err(|e| e.to_string())
}

#[tauri::command]
fn wind_rose(hours: i64) -> Result<db::WindRose, String> {
    db::wind_rose(hours).map_err(|e| e.to_string())
}

#[tauri::command]
fn series_hours(metric: String, hours: i64) -> Result<Vec<db::SeriesPoint>, String> {
    db::series_hours(&metric, hours)
}

#[tauri::command]
fn records() -> Result<Vec<db::RecordCategory>, String> {
    db::records().map_err(|e| e.to_string())
}

#[tauri::command]
fn day_compare() -> Result<db::DayCompare, String> {
    db::day_compare().map_err(|e| e.to_string())
}

async fn run_websocket(app_handle: AppHandle, recorder: &mut Option<db::Recorder>) {
    dotenvy::dotenv().ok();
    let api_key = env::var("AMBIENT_API_KEY").expect("AMBIENT_API_KEY must be set");
    let app_key = env::var("AMBIENT_APP_KEY").expect("AMBIENT_APP_KEY must be set");

    let ws_url = format!(
        "wss://rt2.ambientweather.net/?api=1&applicationKey={}&EIO=4&transport=websocket",
        app_key
    );

    println!("Attempting direct WebSocket connection to: {}", ws_url);

    match connect_async(&ws_url).await {
        Ok((ws_stream, _response)) => {
            println!("WebSocket Handshake successful!");
            if let Ok(mut g) = LIVE.lock() {
                g.connected = true;
            }
            let (mut write, mut read) = ws_stream.split();

            println!("Sending Socket.IO connect packet (40)...");
            if let Err(e) = write.send(Message::Text("40".into())).await {
                println!("Error sending 40 connect: {}", e);
                return;
            }

            let sub_payload = json!(["subscribe", { "apiKeys": [api_key] }]);
            let sub_msg = format!("42{}", sub_payload);
            println!("Sending subscription packet...");
            
            if let Err(e) = write.send(Message::Text(sub_msg.into())).await {
                println!("Error sending subscription: {}", e);
                return;
            }

            // Listen for incoming packets.
            //
            // Two independent stall guards, because a dead Ambient socket does
            // not error — it simply goes quiet, and the outer reconnect loop
            // never fires. (1) a hard timeout on ANY frame catches a severed
            // socket; (2) `last_data` catches the nastier case where the server
            // keeps answering pings but the station has stopped reporting.
            let mut last_data = std::time::Instant::now();
            loop {
                let next = tokio::time::timeout(
                    Duration::from_secs(DATA_STALL_SECS),
                    read.next(),
                )
                .await;
                let msg = match next {
                    Err(_) => {
                        println!("No frames for {}s — socket is a zombie, reconnecting.", DATA_STALL_SECS);
                        break;
                    }
                    Ok(None) => break,
                    Ok(Some(m)) => m,
                };
                if last_data.elapsed() > Duration::from_secs(DATA_STALL_SECS) {
                    println!(
                        "Socket alive but no station data for {}s — reconnecting.",
                        DATA_STALL_SECS
                    );
                    break;
                }
                match msg {
                    Ok(Message::Text(text)) => {
                        if text == "2" {
                            // println!("Received Ping (2), sending Pong (3)...");
                            let _ = write.send(Message::Text("3".into())).await;
                        } 
                        else if text.starts_with("42") {
                            // The payload is 42["data", { ... }]
                            // Strip the "42" so we have a valid JSON array
                            let json_str = &text[2..];
                            
                            // Parse into a generic JSON Value first
                            if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(json_str) {
                                // The Ambient API sends an array: ["data", { actual_reading }]
                                if parsed.is_array() && parsed[0] == "data" {
                                    // Extract the inner object
                                    let reading_data = &parsed[1];
                                    
                                    // Deserialize exactly into our Rust struct
                                    if let Ok(reading) = serde_json::from_value::<AmbientReading>(reading_data.clone()) {
                                        println!("Successfully parsed weather reading! Temp: {:?}", reading.tempf);

                                        // Persist to the archive. A DB error must
                                        // never take down the live stream: log and
                                        // carry on; INSERT OR IGNORE makes retries
                                        // safe after reconnects.
                                        if let Some(rec) = recorder.as_mut() {
                                            match rec.record(&reading) {
                                                Ok(n) => println!("Recorded {} metrics to archive.", n),
                                                Err(e) => println!("Archive write failed: {:?}", e),
                                            }
                                        }

                                        // Feed the tray tooltip and reset the
                                        // data-stall clock.
                                        last_data = std::time::Instant::now();
                                        if let Ok(mut g) = LIVE.lock() {
                                            g.last_data_epoch = Some(chrono::Utc::now().timestamp());
                                            g.tempf = reading.tempf;
                                            g.humidity = reading.humidity.map(f64::from);
                                            g.wind_mph = reading.windspeedmph;
                                            g.recorded += 1;
                                        }

                                        // Emit it over the bridge to React!
                                        if let Err(e) = app_handle.emit("weather-reading", reading) {
                                            println!("Failed to emit to frontend: {:?}", e);
                                        }
                                    } else {
                                        println!("Failed to map JSON to AmbientReading struct.");
                                    }
                                }
                            }
                        }
                    }
                    Ok(_) => {} // Ignore non-text messages
                    Err(e) => {
                        println!("WebSocket read error: {:?}", e);
                        break;
                    }
                }
            }
        }
        Err(e) => {
            println!("Failed to connect: {:?}", e);
        }
    }
    if let Ok(mut g) = LIVE.lock() {
        g.connected = false;
    }
}

fn start_weather_listener(app_handle: AppHandle) {
    tauri::async_runtime::spawn(async move {
        let mut recorder = match db::Recorder::open() {
            Ok(r) => {
                println!("Archive recorder ready at {:?}", db::db_path());
                Some(r)
            }
            Err(e) => {
                println!("Archive recorder unavailable ({:?}) — streaming without persistence.", e);
                None
            }
        };
        loop {
            run_websocket(app_handle.clone(), &mut recorder).await;
            println!("Connection dropped. Reconnecting in 5 seconds...");
            tokio::time::sleep(std::time::Duration::from_secs(5)).await;
        }
    });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // MUST be registered first. Once the app autostarts at login it is
        // easy to launch a second copy from a shortcut; both would open the
        // archive and both would subscribe to the Ambient socket. INSERT OR
        // IGNORE keeps the data clean, but two tray icons and two recorders
        // make the next fault much harder to read. A second launch now just
        // opens the dashboard on the instance already running.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            open_dashboard(app);
        }))
        .setup(|app| {
            println!("Starting SoledadWX backend...");

            // ---- Tray: the app's actual face. There is no window at startup.
            let open_i = MenuItem::with_id(app, "open", "Open Dashboard", true, None::<&str>)?;
            let sep = PredefinedMenuItem::separator(app)?;
            let quit_i = MenuItem::with_id(app, "quit", "Quit SoledadWX", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open_i, &sep, &quit_i])?;

            let tray = TrayIconBuilder::with_id("main")
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip("SoledadWX — starting…")
                .menu(&menu)
                // Left click opens the dashboard; the menu is right-click only,
                // which is the Windows convention.
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "open" => open_dashboard(app),
                    "quit" => {
                        // The ONLY path that is allowed to stop the recorder.
                        QUITTING.store(true, Ordering::SeqCst);
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        open_dashboard(tray.app_handle());
                    }
                })
                .build(app)?;

            // Refresh the tooltip on a slow timer — the data arrives about once
            // a minute, and the "last reading" age needs to keep ticking even
            // when nothing arrives at all. That is the whole point of it.
            tauri::async_runtime::spawn(async move {
                loop {
                    let _ = tray.set_tooltip(Some(tooltip_text()));
                    tokio::time::sleep(Duration::from_secs(20)).await;
                }
            });

            // Catch the archive up from the cloud for any time the app wasn't
            // running, concurrently with starting the live stream.
            let bf_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                db::backfill(bf_handle).await;
            });
            start_weather_listener(app.handle().clone());
            Ok(())
        })
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            greet, db_status, query_series, series_window, range_stats, console_stats, wind_rose, series_hours,
            records, day_compare
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|_app, event| {
            // Closing the dashboard destroys the last window, which Tauri would
            // normally treat as "quit". It is not: the recorder is the point of
            // this program and the window is just a viewer. Only the tray's
            // Quit item is allowed through.
            if let tauri::RunEvent::ExitRequested { api, .. } = event {
                if !QUITTING.load(Ordering::SeqCst) {
                    api.prevent_exit();
                }
            }
        });
}








