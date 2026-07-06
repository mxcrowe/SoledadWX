use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct AmbientReading {
    pub dateutc: i64,
    pub date: Option<String>,
    pub tempf: Option<f64>,
    pub humidity: Option<i32>,
    pub windspeedmph: Option<f64>,
    pub windgustmph: Option<f64>,
    pub maxdailygust: Option<f64>,
    pub winddir: Option<i32>,
    pub baromrelin: Option<f64>,
    pub baromabsin: Option<f64>,
    pub hourlyrainin: Option<f64>,
    pub dailyrainin: Option<f64>,
    pub weeklyrainin: Option<f64>,
    pub monthlyrainin: Option<f64>,
    pub yearlyrainin: Option<f64>,
    pub solarradiation: Option<f64>,
    pub uv: Option<i32>,
    pub tempinf: Option<f64>,
    pub humidityin: Option<i32>,
    pub feelsLike: Option<f64>,
    pub dewPoint: Option<f64>,
    pub feelsLikein: Option<f64>,
    pub dewPointin: Option<f64>,
    pub lastRain: Option<String>,
}

