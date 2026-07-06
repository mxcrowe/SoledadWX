import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";
import "./App.css";

interface WeatherReading {
  dateutc: number;
  date?: string;
  tempf?: number;
  humidity?: number;
  windspeedmph?: number;
  windgustmph?: number;
  maxdailygust?: number;
  winddir?: number;
  baromrelin?: number;
  baromabsin?: number;
  hourlyrainin?: number;
  dailyrainin?: number;
  weeklyrainin?: number;
  monthlyrainin?: number;
  yearlyrainin?: number;
  solarradiation?: number;
  uv?: number;
  tempinf?: number;
  humidityin?: number;
  feelsLike?: number;
  dewPoint?: number;
  feelsLikein?: number;
  dewPointin?: number;
  lastRain?: string;
}

interface DbStatus {
  total_observations: number;
  live_rows_today: number;
  last_write_utc: number | null;
  today_high_f: number | null;
  today_low_f: number | null;
  today_max_gust_mph: number | null;
  today_rain_in: number | null;
}

function App() {
  const [reading, setReading] = useState<WeatherReading | null>(null);
  const [status, setStatus] = useState<DbStatus | null>(null);

  useEffect(() => {
    const unlisten = listen<WeatherReading>("weather-reading", (event) => {
      setReading(event.payload);
    });
    return () => {
      unlisten.then((f) => f());
    };
  }, []);

  useEffect(() => {
    const poll = () => invoke<DbStatus>("db_status").then(setStatus).catch(() => {});
    poll();
    const id = setInterval(poll, 30_000);
    return () => clearInterval(id);
  }, []);

  const lastWriteAge =
    status?.last_write_utc != null
      ? Math.round(Date.now() / 1000 - status.last_write_utc)
      : null;
  const recording = lastWriteAge != null && lastWriteAge < 120;

  return (
    <main className="container">
      <h1>SoledadWX</h1>
      <p>Raw Telemetry Firehose</p>

      {status && (
        <div className="status-bar">
          <span className={recording ? "rec-dot rec-on" : "rec-dot rec-off"}>●</span>
          <span>
            {recording ? "Recording" : "Not recording"} — archive:{" "}
            {status.total_observations.toLocaleString()} obs
          </span>
          <span className="extremes">
            Today: {status.today_low_f?.toFixed(1) ?? "--"}°F /{" "}
            {status.today_high_f?.toFixed(1) ?? "--"}°F · gust{" "}
            {status.today_max_gust_mph?.toFixed(1) ?? "--"} mph · rain{" "}
            {status.today_rain_in?.toFixed(2) ?? "--"} in
          </span>
        </div>
      )}

      {reading ? (
        <div className="telemetry-grid">
          {/* Group 1: Outdoor Conditions */}
          <div className="data-box"><span className="label">Temp (Out)</span><span className="val">{reading.tempf}°F</span></div>
          <div className="data-box"><span className="label">Humidity (Out)</span><span className="val">{reading.humidity}%</span></div>
          <div className="data-box"><span className="label">Feels Like</span><span className="val">{reading.feelsLike}°F</span></div>
          <div className="data-box"><span className="label">Dew Point</span><span className="val">{reading.dewPoint}°F</span></div>

          {/* Group 2: Indoor Conditions */}
          <div className="data-box"><span className="label">Temp (In)</span><span className="val">{reading.tempinf}°F</span></div>
          <div className="data-box"><span className="label">Humidity (In)</span><span className="val">{reading.humidityin}%</span></div>
          <div className="data-box"><span className="label">Feels Like (In)</span><span className="val">{reading.feelsLikein}°F</span></div>
          <div className="data-box"><span className="label">Dew Point (In)</span><span className="val">{reading.dewPointin}°F</span></div>

          {/* Group 3: Wind */}
          <div className="data-box"><span className="label">Wind Speed</span><span className="val">{reading.windspeedmph ? (reading.windspeedmph * 0.868976).toFixed(1) : "--"} kts</span></div>
          <div className="data-box"><span className="label">Wind Gust</span><span className="val">{reading.windgustmph ? (reading.windgustmph * 0.868976).toFixed(1) : "--"} kts</span></div>
          <div className="data-box"><span className="label">Max Daily Gust</span><span className="val">{reading.maxdailygust ? (reading.maxdailygust * 0.868976).toFixed(1) : "--"} kts</span></div>
          <div className="data-box"><span className="label">Wind Dir</span><span className="val">{reading.winddir}°</span></div>

          {/* Group 4: Pressure & Sun */}
          <div className="data-box"><span className="label">Pressure (Rel)</span><span className="val">{reading.baromrelin} inHg</span></div>
          <div className="data-box"><span className="label">Pressure (Abs)</span><span className="val">{reading.baromabsin} inHg</span></div>
          <div className="data-box"><span className="label">Solar Rad</span><span className="val">{reading.solarradiation} W/m²</span></div>
          <div className="data-box"><span className="label">UV Index</span><span className="val">{reading.uv}</span></div>

          {/* Group 5: Rain */}
          <div className="data-box"><span className="label">Rain (Hourly)</span><span className="val">{reading.hourlyrainin} in</span></div>
          <div className="data-box"><span className="label">Rain (Daily)</span><span className="val">{reading.dailyrainin} in</span></div>
          <div className="data-box"><span className="label">Rain (Weekly)</span><span className="val">{reading.weeklyrainin} in</span></div>
          <div className="data-box"><span className="label">Rain (Yearly)</span><span className="val">{reading.yearlyrainin} in</span></div>
          
          <div className="data-box span-full"><span className="label">Last Rain:</span><span className="val">{reading.lastRain}</span></div>
          <div className="data-box span-full"><span className="label">Timestamp:</span><span className="val">{reading.date}</span></div>
        </div>
      ) : (
        <div className="loading">Waiting for data from weather station...</div>
      )}
    </main>
  );
}

export default App;


