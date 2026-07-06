"""
AmbientWeather.net API Client
Handles WebSocket connections for real-time data updates.
"""
import socketio
import traceback
import threading
from datetime import datetime
from typing import Callable, Optional

from cumulusai.utils.logger import logger
from cumulusai.data.models import Reading

class AmbientWeatherClient:
    """Client for AmbientWeather.net real-time WebSocket API."""
    
    def __init__(self, api_key: str, app_key: str, mac_address: Optional[str] = None):
        """
        Initialize the API client.
        
        Args:
            api_key: AmbientWeather API Key
            app_key: AmbientWeather Application Key
            mac_address: Optional specific device MAC address
        """
        self.api_key = api_key
        self.app_key = app_key
        self.mac_address = mac_address
        
        # Use sync client to easily run in a background thread alongside PyQt
        self.sio = socketio.Client(logger=False, engineio_logger=False)
        self.url = f"wss://rt2.ambientweather.net/?api=1&applicationKey={self.app_key}"
        self.on_reading_callback = None
        self._thread = None
        self._running = False
        
        self._setup_events()
        
    def _setup_events(self):
        """Setup socket.io event handlers."""
        @self.sio.event
        def connect():
            logger.info("Connected to AmbientWeather.net WebSocket")
            self._subscribe()

        @self.sio.event
        def disconnect():
            logger.warning("Disconnected from AmbientWeather.net WebSocket")

        @self.sio.event
        def data(data):
            try:
                # logger.debug(f"Received raw data: {data}")
                reading = self._parse_reading(data)
                if reading and self.on_reading_callback:
                    self.on_reading_callback(reading)
            except Exception as e:
                logger.error(f"Error parsing data: {e}")
                logger.debug(traceback.format_exc())

    def _subscribe(self):
        """Send subscription message upon connection."""
        subscribe_data = {'apiKeys': [self.api_key]}
        logger.info(f"Subscribing with API Key: {self.api_key[:8]}...")
        self.sio.emit('subscribe', subscribe_data)
        
    def set_callback(self, callback: Callable[[Reading], None]):
        """Set callback to be executed when new reading arrives."""
        self.on_reading_callback = callback
        
    def _parse_reading(self, data: dict) -> Reading:
        """Parse AmbientWeather JSON to Reading dataclass."""
        # Convert JS timestamp (ms) to datetime
        ts = data.get('dateutc', 0)
        if not ts:
            ts = datetime.utcnow().timestamp() * 1000
            
        dt = datetime.fromtimestamp(ts / 1000.0)
        
        return Reading(
            timestamp=dt,
            source='api',
            is_imported=True,
            temp_outdoor=data.get('tempf'),
            humidity_outdoor=data.get('humidity'),
            temp_indoor=data.get('tempinf'),
            humidity_indoor=data.get('humidityin'),
            pressure=data.get('baromrelin'),
            wind_speed=data.get('windspeedmph'),
            wind_gust=data.get('windgustmph'),
            wind_direction=data.get('winddir'),
            rain_rate=data.get('hourlyrainin'), # Approximation for rate
            rain_today=data.get('dailyrainin'),
            solar_radiation=data.get('solarradiation'),
            uv_index=data.get('uv')
        )

    def start(self):
        """Start the WebSocket client in a background thread."""
        if self._running:
            return
            
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("AmbientWeather API client started")
        
    def _run_loop(self):
        """Inner loop for the background thread."""
        try:
            self.sio.connect(self.url, transports=['websocket'])
            self.sio.wait()
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            self._running = False

    def stop(self):
        """Stop the WebSocket client."""
        if not self._running:
            return
            
        logger.info("Stopping AmbientWeather API client...")
        self._running = False
        try:
            self.sio.disconnect()
        except Exception:
            pass
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
