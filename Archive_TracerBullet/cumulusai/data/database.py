"""
Database layer for CumulusAI.
Handles SQLite connection, schema creation, and core CRUD operations.
"""
import sqlite3
import datetime
from pathlib import Path
from typing import List, Optional, Tuple, Any

from cumulusai.utils.logger import logger
from cumulusai.data.models import Reading, DailySummary, Calibration

# Use a consistent date format for storage
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_FORMAT = "%Y-%m-%d"

class DatabaseManager:
    """Manages the SQLite database connection and operations."""
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize database connection."""
        if db_path is None:
            # Default to data folder in app root
            app_dir = Path(__file__).parent.parent.parent
            data_dir = app_dir / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = str(data_dir / "cumulusai.db")
        else:
            self.db_path = db_path
            
        self.initialize_schema()

    def get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Access columns by name
        return conn

    def initialize_schema(self) -> None:
        """Create tables if they don't exist according to the design plan."""
        logger.info(f"Initializing database schema at {self.db_path}")
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Readings table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS readings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME NOT NULL UNIQUE,
                        source TEXT NOT NULL,
                        is_imported BOOLEAN DEFAULT 1,
                        
                        temp_indoor REAL,
                        humidity_indoor INTEGER,
                        temp_outdoor REAL,
                        humidity_outdoor INTEGER,
                        dew_point REAL,
                        pressure REAL,
                        wind_speed REAL,
                        wind_gust REAL,
                        wind_direction INTEGER,
                        
                        rain_rate REAL,
                        rain_today REAL,
                        
                        wind_chill REAL,
                        heat_index REAL,
                        feels_like REAL,
                        apparent_temp REAL,
                        humidex REAL,
                        
                        solar_radiation REAL,
                        uv_index REAL,
                        
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Daily Summary table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS daily_summary (
                        date DATE PRIMARY KEY,
                        
                        temp_min REAL, temp_min_time TEXT,
                        temp_max REAL, temp_max_time TEXT,
                        
                        pressure_min REAL, pressure_min_time TEXT,
                        pressure_max REAL, pressure_max_time TEXT,
                        
                        wind_gust_max REAL, wind_gust_max_time TEXT,
                        wind_avg_max REAL, wind_avg_max_time TEXT,
                        
                        rain_total REAL,
                        rain_rate_max REAL, rain_rate_max_time TEXT,
                        
                        humidity_min INTEGER, humidity_min_time TEXT,
                        humidity_max INTEGER, humidity_max_time TEXT,
                        
                        heat_index_max REAL, heat_index_max_time TEXT,
                        wind_chill_min REAL, wind_chill_min_time TEXT,
                        
                        temp_avg REAL,
                        humidity_avg INTEGER,
                        
                        wind_run REAL,
                        dominant_wind_dir INTEGER
                    )
                """)

                # Monthly Summary
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS monthly_summary (
                        year INTEGER,
                        month INTEGER,

                        temp_min REAL, temp_max REAL, temp_avg REAL,
                        pressure_min REAL, pressure_max REAL,
                        wind_gust_max REAL, wind_avg_max REAL,
                        rain_total REAL,
                        humidity_min INTEGER, humidity_max INTEGER,
                        heat_index_max REAL, wind_chill_min REAL,

                        PRIMARY KEY (year, month)
                    )
                """)

                # Yearly Summary
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS yearly_summary (
                        year INTEGER PRIMARY KEY,
                        
                        temp_min REAL, temp_max REAL, temp_avg REAL,
                        pressure_min REAL, pressure_max REAL,
                        wind_gust_max REAL, wind_avg_max REAL,
                        rain_total REAL,
                        humidity_min INTEGER, humidity_max INTEGER
                    )
                """)

                # Settings
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Weather Diary
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS weather_diary (
                        date DATE PRIMARY KEY,
                        notes TEXT,
                        snow_falling BOOLEAN,
                        snow_depth REAL,
                        snow_lying BOOLEAN,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Calibration
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS calibration (
                        sensor TEXT PRIMARY KEY,
                        offset REAL DEFAULT 0,
                        multiplier REAL DEFAULT 1.0,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Pre-populate default calibrations if empty
                cursor.execute("SELECT COUNT(*) as count FROM calibration")
                if cursor.fetchone()['count'] == 0:
                    default_sensors = [
                        'temp_indoor', 'temp_outdoor', 'humidity_indoor', 
                        'humidity_outdoor', 'pressure', 'wind_speed', 'wind_gust'
                    ]
                    for sensor in default_sensors:
                        cursor.execute(
                            "INSERT INTO calibration (sensor, offset, multiplier) VALUES (?, 0, 1.0)",
                            (sensor,)
                        )
                        
                conn.commit()
                logger.info("Database schema initialized successfully.")
        except sqlite3.Error as e:
            logger.error(f"Error initializing database schema: {e}")
            raise

    def insert_reading(self, reading: Reading) -> Optional[int]:
        """Insert a single reading into the database."""
        sql = """
            INSERT INTO readings (
                timestamp, source, is_imported, temp_indoor, humidity_indoor,
                temp_outdoor, humidity_outdoor, dew_point, pressure, wind_speed,
                wind_gust, wind_direction, rain_rate, rain_today, wind_chill,
                heat_index, feels_like, apparent_temp, humidex, solar_radiation, uv_index
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Format timestamp
                ts_str = reading.timestamp.strftime(DATETIME_FORMAT) if isinstance(reading.timestamp, datetime.datetime) else reading.timestamp
                
                cursor.execute(sql, (
                    ts_str, reading.source, reading.is_imported, reading.temp_indoor,
                    reading.humidity_indoor, reading.temp_outdoor, reading.humidity_outdoor,
                    reading.dew_point, reading.pressure, reading.wind_speed, reading.wind_gust,
                    reading.wind_direction, reading.rain_rate, reading.rain_today, reading.wind_chill,
                    reading.heat_index, reading.feels_like, reading.apparent_temp, reading.humidex,
                    reading.solar_radiation, reading.uv_index
                ))
                conn.commit()
                return cursor.lastrowid
        except sqlite3.IntegrityError:
            # Handle duplicate timestamp by potentially updating based on priority
            logger.warning(f"Duplicate reading timestamp: {reading.timestamp}")
            # TODO: Add conflict resolution logic (API > MDB > Cumulus)
            return None
        except sqlite3.Error as e:
            logger.error(f"Error inserting reading: {e}")
            return None

    def get_latest_reading(self) -> Optional[Reading]:
        """Get the most recent reading from the database."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM readings ORDER BY timestamp DESC LIMIT 1")
                row = cursor.fetchone()
                
                if not row:
                    return None
                    
                # Convert row to dict, then to Reading object
                data = dict(row)
                
                # Parse timestamp back to datetime
                if isinstance(data['timestamp'], str):
                    try:
                        data['timestamp'] = datetime.datetime.strptime(data['timestamp'], DATETIME_FORMAT)
                    except ValueError:
                        pass
                if data.get('created_at') and isinstance(data['created_at'], str):
                    try:
                        data['created_at'] = datetime.datetime.strptime(data['created_at'], DATETIME_FORMAT)
                    except ValueError:
                        pass
                
                return Reading(**data)
        except sqlite3.Error as e:
            logger.error(f"Error fetching latest reading: {e}")
            return None
