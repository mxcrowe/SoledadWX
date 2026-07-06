"""
Extremes Panel Widget.
Displays the daily minimum and maximum records.
"""
from PyQt6.QtWidgets import QGroupBox, QGridLayout, QLabel, QVBoxLayout
from PyQt6.QtCore import Qt

from cumulusai.data.models import DailySummary

class ExtremeValueWidget(QLabel):
    """Widget to show an extreme value and its time."""
    def __init__(self, color="black"):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"color: {color}; font-size: 16px; font-weight: bold;")
        self.setText("--\n--:--")
        
    def set_extreme(self, val, time, unit=""):
        if val is None:
            self.setText("--\n--:--")
        else:
            time_str = time if time else "--:--"
            self.setText(f"{val:.1f}{unit}\n{time_str}")

class ExtremesPanelWidget(QGroupBox):
    """Panel showing today's weather extremes."""
    def __init__(self):
        super().__init__("Today's Extremes")
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
        
        # Headers
        layout.addWidget(QLabel("<b>High</b>"), 0, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(QLabel("<b>Low</b>"), 0, 2, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # Temp Row
        layout.addWidget(QLabel("<b>Temperature:</b>"), 1, 0)
        self.temp_high = ExtremeValueWidget(color="#c0392b")
        self.temp_low = ExtremeValueWidget(color="#2980b9")
        layout.addWidget(self.temp_high, 1, 1)
        layout.addWidget(self.temp_low, 1, 2)
        
        # Pressure Row
        layout.addWidget(QLabel("<b>Pressure:</b>"), 2, 0)
        self.press_high = ExtremeValueWidget()
        self.press_low = ExtremeValueWidget()
        layout.addWidget(self.press_high, 2, 1)
        layout.addWidget(self.press_low, 2, 2)
        
        # Wind Gust Row
        layout.addWidget(QLabel("<b>Wind Gust:</b>"), 3, 0)
        self.wind_high = ExtremeValueWidget(color="#8e44ad")
        layout.addWidget(self.wind_high, 3, 1)

    def update_extremes(self, summary: DailySummary):
        """Update values from a DailySummary object."""
        self.temp_high.set_extreme(summary.temp_max, summary.temp_max_time, "°F")
        self.temp_low.set_extreme(summary.temp_min, summary.temp_min_time, "°F")
        
        self.press_high.set_extreme(summary.pressure_max, summary.pressure_max_time, "inHg")
        self.press_low.set_extreme(summary.pressure_min, summary.pressure_min_time, "inHg")
        
        self.wind_high.set_extreme(summary.wind_gust_max, summary.wind_gust_max_time, "mph")
