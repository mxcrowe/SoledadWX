"""Main application window for CumulusAI."""

from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, QObject, pyqtSignal

from cumulusai.gui.widgets.current_conditions import CurrentConditionsWidget
from cumulusai.gui.widgets.extremes_panel import ExtremesPanelWidget
from cumulusai.gui.graphs.scrolling_graph import ScrollingGraphWidget
from cumulusai.data.models import Reading, DailySummary
from cumulusai.data.database import DatabaseManager
from cumulusai.data.api_client import AmbientWeatherClient
from cumulusai.utils.logger import logger

class DataBridge(QObject):
    """Bridge for passing data from background threads to main GUI thread."""
    new_reading = pyqtSignal(Reading)


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        """Initialize the main window."""
        super().__init__()

        self.setWindowTitle("CumulusAI - Weather Station")
        self.setGeometry(100, 100, 1000, 700)

        # Initialize data bridge
        self.bridge = DataBridge()
        self.bridge.new_reading.connect(self.on_new_reading)

        # Initialize core components
        self.db = DatabaseManager()
        self.api_client = None

        # Setup UI
        self.setup_ui()
        
        # Load latest from DB
        self.load_initial_data()
        
        # Setup API client
        self.setup_api_client()

    def setup_ui(self):
        """Setup the user interface."""
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setSpacing(15)

        # Title
        title_label = QLabel("CumulusAI Dashboard")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 24px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title_label)

        # Current Conditions Widget
        self.current_conditions = CurrentConditionsWidget()
        layout.addWidget(self.current_conditions)
        
        # Extremes Panel Widget
        self.extremes_panel = ExtremesPanelWidget()
        layout.addWidget(self.extremes_panel)
        
        # Temperature Graph Widget
        self.temp_graph = ScrollingGraphWidget(title="Temperature (24h)", metric="temp_outdoor", unit="°F")
        layout.addWidget(self.temp_graph)

        # Add a stretch to push everything up
        layout.addStretch()

        # Setup menu and status bar
        self.setup_menu_bar()
        self.statusBar().showMessage("Initializing...")

    def setup_menu_bar(self):
        """Setup the application menu bar."""
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")
        file_menu.addAction("Exit", self.close)

        view_menu = menubar.addMenu("View")
        view_menu.addAction("Dashboard")
        view_menu.addAction("Graphs")
        view_menu.addAction("Records")

        tools_menu = menubar.addMenu("Tools")
        tools_menu.addAction("Settings")
        tools_menu.addAction("Import Data")

        help_menu = menubar.addMenu("Help")
        help_menu.addAction("About")

    def load_initial_data(self):
        """Load the most recent reading from database on startup."""
        latest = self.db.get_latest_reading()
        if latest:
            self.current_conditions.update_conditions(latest)
            self.statusBar().showMessage("Loaded offline data. Waiting for live updates...")
        else:
            self.statusBar().showMessage("No historical data found. Waiting for live updates...")

    def setup_api_client(self):
        """Setup the real-time API client."""
        # TODO: Move to settings dialog. Hardcoding for MVP based on Implementation Plan
        API_KEY = "REDACTED_SEE_ENV_FILE"
        # AmbientWeather requires a registered application key. We'll use a placeholder
        # and document that it needs real generation if it fails to connect.
        APP_KEY = "REDACTED_SEE_ENV_FILE" 

        try:
            self.api_client = AmbientWeatherClient(api_key=API_KEY, app_key=APP_KEY)
            
            # The callback runs in a background thread, so we use the bridge to safely emit it
            def background_callback(reading: Reading):
                self.bridge.new_reading.emit(reading)
                
            self.api_client.set_callback(background_callback)
            self.api_client.start()
            logger.info("API Client setup completed")
        except Exception as e:
            logger.error(f"Failed to setup API Client: {e}")
            self.statusBar().showMessage("API Connection Failed - Check Logs")

    def on_new_reading(self, reading: Reading):
        """Handle a new reading from the API."""
        # Save to DB
        self.db.insert_reading(reading)
        
        # Update UI
        self.current_conditions.update_conditions(reading)
        self.temp_graph.update_graph(reading)
        self.statusBar().showMessage("Live Data Connected")
        
    def closeEvent(self, event):
        """Handle application close."""
        if self.api_client:
            self.api_client.stop()
        super().closeEvent(event)
