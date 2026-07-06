"""
Current Conditions Widget.
Displays real-time weather metrics on the dashboard.
"""
from PyQt6.QtWidgets import QWidget, QGridLayout, QLabel, QVBoxLayout, QGroupBox, QHBoxLayout
from PyQt6.QtCore import Qt

from cumulusai.data.models import Reading

class MetricWidget(QWidget):
    """A small widget to display a single weather metric."""
    def __init__(self, title: str, unit: str = ""):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        self.title_label = QLabel(title)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("color: #666; font-size: 12px; font-weight: bold;")
        
        self.value_label = QLabel("--")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setStyleSheet("font-size: 24px; font-weight: bold;")
        
        self.unit = unit
        
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        
    def set_value(self, value):
        if value is None:
            self.value_label.setText("--")
        else:
            if isinstance(value, float):
                self.value_label.setText(f"{value:.1f}{self.unit}")
            else:
                self.value_label.setText(f"{value}{self.unit}")


class CurrentConditionsWidget(QGroupBox):
    """Panel displaying current weather conditions."""
    
    def __init__(self):
        super().__init__("Current Conditions")
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #ccc;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px 0 3px;
            }
        """)
        
        layout = QGridLayout(self)
        
        # Initialize metrics
        self.temp_out = MetricWidget("Outdoor Temp", "°F")
        self.humidity_out = MetricWidget("Outdoor Humidity", "%")
        self.dew_point = MetricWidget("Dew Point", "°F")
        self.pressure = MetricWidget("Pressure", " inHg")
        
        self.wind_speed = MetricWidget("Wind Speed", " mph")
        self.wind_gust = MetricWidget("Wind Gust", " mph")
        self.wind_dir = MetricWidget("Wind Dir", "°")
        
        self.rain_today = MetricWidget("Rain Today", " in")
        self.rain_rate = MetricWidget("Rain Rate", " in/hr")
        
        self.temp_in = MetricWidget("Indoor Temp", "°F")
        self.humidity_in = MetricWidget("Indoor Humidity", "%")
        
        # Add to layout
        layout.addWidget(self.temp_out, 0, 0)
        layout.addWidget(self.humidity_out, 0, 1)
        layout.addWidget(self.dew_point, 0, 2)
        layout.addWidget(self.pressure, 0, 3)
        
        layout.addWidget(self.wind_speed, 1, 0)
        layout.addWidget(self.wind_gust, 1, 1)
        layout.addWidget(self.wind_dir, 1, 2)
        
        layout.addWidget(self.rain_today, 2, 0)
        layout.addWidget(self.rain_rate, 2, 1)
        
        layout.addWidget(self.temp_in, 3, 0)
        layout.addWidget(self.humidity_in, 3, 1)
        
        # Time updated
        self.update_time_label = QLabel("Last Updated: Never")
        self.update_time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.update_time_label.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(self.update_time_label, 4, 0, 1, 4)

    def update_conditions(self, reading: Reading):
        """Update UI with a new reading."""
        self.temp_out.set_value(reading.temp_outdoor)
        self.humidity_out.set_value(reading.humidity_outdoor)
        self.dew_point.set_value(reading.dew_point)
        self.pressure.set_value(reading.pressure)
        
        self.wind_speed.set_value(reading.wind_speed)
        self.wind_gust.set_value(reading.wind_gust)
        self.wind_dir.set_value(reading.wind_direction)
        
        self.rain_today.set_value(reading.rain_today)
        self.rain_rate.set_value(reading.rain_rate)
        
        self.temp_in.set_value(reading.temp_indoor)
        self.humidity_in.set_value(reading.humidity_indoor)
        
        if reading.timestamp:
            ts_str = reading.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            self.update_time_label.setText(f"Last Updated: {ts_str}")
