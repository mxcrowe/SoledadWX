"""
Data models for CumulusAI.
Contains dataclasses representing the database records and internal state.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass
class Reading:
    """A single weather reading snapshot."""
    timestamp: datetime
    source: str  # 'cumulus', 'mdb', 'api'
    is_imported: bool = True
    
    # Measurements
    temp_indoor: Optional[float] = None
    humidity_indoor: Optional[int] = None
    temp_outdoor: Optional[float] = None
    humidity_outdoor: Optional[int] = None
    dew_point: Optional[float] = None
    pressure: Optional[float] = None
    wind_speed: Optional[float] = None
    wind_gust: Optional[float] = None
    wind_direction: Optional[int] = None
    
    # Rain
    rain_rate: Optional[float] = None
    rain_today: Optional[float] = None
    
    # Derived values
    wind_chill: Optional[float] = None
    heat_index: Optional[float] = None
    feels_like: Optional[float] = None
    apparent_temp: Optional[float] = None
    humidex: Optional[float] = None
    
    # Solar
    solar_radiation: Optional[float] = None
    uv_index: Optional[float] = None
    
    # DB metadata
    id: Optional[int] = None
    created_at: Optional[datetime] = None


@dataclass
class DailySummary:
    """Summary of weather for a single day."""
    date: datetime.date
    
    # Temperature extremes
    temp_min: Optional[float] = None
    temp_min_time: Optional[str] = None
    temp_max: Optional[float] = None
    temp_max_time: Optional[str] = None
    
    # Pressure extremes
    pressure_min: Optional[float] = None
    pressure_min_time: Optional[str] = None
    pressure_max: Optional[float] = None
    pressure_max_time: Optional[str] = None
    
    # Wind extremes
    wind_gust_max: Optional[float] = None
    wind_gust_max_time: Optional[str] = None
    wind_avg_max: Optional[float] = None
    wind_avg_max_time: Optional[str] = None
    
    # Rain
    rain_total: Optional[float] = None
    rain_rate_max: Optional[float] = None
    rain_rate_max_time: Optional[str] = None
    
    # Humidity extremes
    humidity_min: Optional[int] = None
    humidity_min_time: Optional[str] = None
    humidity_max: Optional[int] = None
    humidity_max_time: Optional[str] = None
    
    # Derived extremes
    heat_index_max: Optional[float] = None
    heat_index_max_time: Optional[str] = None
    wind_chill_min: Optional[float] = None
    wind_chill_min_time: Optional[str] = None
    
    # Averages
    temp_avg: Optional[float] = None
    humidity_avg: Optional[int] = None
    
    # Additional
    wind_run: Optional[float] = None
    dominant_wind_dir: Optional[int] = None


@dataclass
class Calibration:
    """Sensor calibration offsets and multipliers."""
    sensor: str
    offset: float = 0.0
    multiplier: float = 1.0
    updated_at: Optional[datetime] = None
