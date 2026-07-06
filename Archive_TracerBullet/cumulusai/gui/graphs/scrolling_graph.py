"""
Scrolling Graph Widget.
Provides a real-time updating graph for weather metrics.
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QGroupBox
from PyQt6.QtCore import Qt, QTimer
import pyqtgraph as pg
from datetime import datetime
import numpy as np

from cumulusai.data.models import Reading

class ScrollingGraphWidget(QGroupBox):
    """A real-time scrolling graph for weather metrics."""
    
    def __init__(self, title: str = "Temperature Graph", metric: str = "temp_outdoor", 
                 unit: str = "°F", max_points: int = 1440): # 1440 mins = 24h
        super().__init__(title)
        self.metric = metric
        self.unit = unit
        self.max_points = max_points
        
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
        
        layout = QVBoxLayout(self)
        
        # Setup PyQtGraph
        pg.setConfigOption('background', 'w')
        pg.setConfigOption('foreground', 'k')
        
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel('left', title, units=unit)
        self.plot_widget.setLabel('bottom', 'Time')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        
        # Data arrays
        self.x_data = [] # Timestamps (unix)
        self.y_data = [] # Values
        
        # Plot curve
        self.curve = self.plot_widget.plot(
            pen=pg.mkPen(color='#e74c3c', width=2)
        )
        
        # Configure X-axis to show time
        self.plot_widget.setAxisItems({'bottom': pg.DateAxisItem()})
        
        layout.addWidget(self.plot_widget)

    def update_graph(self, reading: Reading):
        """Add a new reading to the graph."""
        val = getattr(reading, self.metric, None)
        if val is None or reading.timestamp is None:
            return
            
        ts = reading.timestamp.timestamp()
        
        self.x_data.append(ts)
        self.y_data.append(val)
        
        # Limit data size
        if len(self.x_data) > self.max_points:
            self.x_data = self.x_data[-self.max_points:]
            self.y_data = self.y_data[-self.max_points:]
            
        self.curve.setData(self.x_data, self.y_data)
