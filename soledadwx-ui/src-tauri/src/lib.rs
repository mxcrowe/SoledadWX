use futures_util::{SinkExt, StreamExt};
use serde_json::json;
use std::env;
use tauri::{AppHandle, Emitter};
use tokio_tungstenite::{connect_async, tungstenite::protocol::Message};

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
fn query_series(metric: String, start: String, end: String) -> Result<Vec<db::SeriesPoint>, String> {
    db::series_daily(&metric, &start, &end)
}

#[tauri::command]
fn range_stats(metric: String, start: String, end: String) -> Result<db::RangeStats, String> {
    db::range_stats(&metric, &start, &end)
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

            // Listen for incoming packets
            while let Some(msg) = read.next().await {
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
        .setup(|app| {
            println!("Starting SoledadWX pure websocket backend...");
            start_weather_listener(app.handle().clone());
            Ok(())
        })
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![greet, db_status, query_series, range_stats])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}








