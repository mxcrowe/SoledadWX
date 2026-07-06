# SoledadWX - Desktop Weather Station Application

A comprehensive desktop weather station application inspired by Cumulus, providing real-time data display, historical data management, and advanced weather analysis.

## 🔨 Project Status

**⚠️ Under Active Development - Phase 0 (Data Archaeology)**

This is a greenfield project currently in the design and data analysis phase. The architecture is being discovered through intentional co-development with Claude Code and CCV3.

**Not ready for production use.** Expect significant changes to structure and APIs as we progress through phases.

For development notes, architecture decisions, and CCV3 learnings, see [CLAUDE_CODE_GUIDE.md](CLAUDE_CODE_GUIDE.md) and [.claude/handoffs/soledadwx-session-1.md](.claude/handoffs/soledadwx-session-1.md).

## Overview

SoledadWX unifies weather data from multiple sources:
- **AmbientWeather.net API** - Real-time data from WS-1002-WiFi weather station
- **HP2000.mdb Database** - Historical data from EasyWeatherIP
- **Cumulus Legacy Data** - 8+ years of historical weather data (April 2010 - January 2018)

## Features

### Current Implementation Status
- [x] Project structure and setup
- [x] Virtual environment configuration
- [ ] Database layer (SQLite)
- [ ] Data importers (Cumulus, MDB, API)
- [ ] Dashboard GUI with real-time updates
- [ ] Scrollable interactive graphs
- [ ] Records and extremes display
- [ ] NOAA report generation
- [ ] Data export functionality

## System Requirements

- **OS**: Windows 11 (64-bit or 32-bit)
- **Python**: 3.11 or later
- **RAM**: 4GB minimum
- **Disk Space**: 500MB for application and data

## Quick Start

### 1. Create Virtual Environment

```bash
# Navigate to project directory
cd G:\Dev\SoledadWX

# Create virtual environment
python -m venv soledadwx_env

# Activate environment (Windows Command Prompt)
soledadwx_env\Scripts\activate

# Or if using Git Bash/PowerShell
source soledadwx_env/Scripts/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Run Application

```bash
python main.py
```

## Project Structure

```
SoledadWX/
├── soledadwx/                   # Main application package
│   ├── config/                  # Configuration and settings
│   │   ├── settings.py         # Application settings management
│   │   ├── calibration.py      # Sensor calibration
│   │   └── constants.py        # Application constants
│   ├── data/                    # Data layer
│   │   ├── database.py         # SQLite operations
│   │   ├── models.py           # Data model classes
│   │   ├── calculations.py     # Derived value calculations
│   │   ├── validators.py       # Data validation
│   │   ├── api_client.py       # AmbientWeather API client
│   │   └── importers/          # Data import modules
│   │       ├── base_importer.py
│   │       ├── cumulus_importer.py
│   │       ├── mdb_importer.py
│   │       └── api_importer.py
│   ├── gui/                     # User interface
│   │   ├── main_window.py      # Main application window
│   │   ├── dialogs/            # Dialog windows
│   │   ├── graphs/             # Graph widgets
│   │   ├── widgets/            # Custom widgets
│   │   └── resources/          # Icons and stylesheets
│   ├── export/                  # Export functionality
│   │   ├── csv_export.py
│   │   └── noaa_reports.py
│   └── utils/                   # Utilities
│       ├── logger.py
│       ├── alarms.py
│       └── backup.py
├── main.py                      # Application entry point
├── requirements.txt             # Python dependencies
├── README.md                    # This file
└── .gitignore                  # Git ignore rules
```

## Configuration

### API Setup

**AmbientWeather.net Configuration:**

1. Obtain your API Key from `SoledadWX_Implementation_Plan.md`
2. Generate an Application Key at https://ambientweather.net/account
3. Configure in the application settings

### Database

The application uses SQLite for data storage. The database is automatically created on first run with the schema defined in `SoledadWX_Implementation_Plan.md`.

## Development Phases

### Phase 1: Project Setup (Complete)
- Project structure created
- Virtual environment configured
- Dependencies installed
- Basic application entry point ready

### Phase 2: Database Layer (Next)
- SQLite database schema implementation
- CRUD operations for all tables
- Database connection management
- Backup/restore functionality

### Phase 3: Data Import Engine
- Cumulus historical data importer
- HP2000.mdb database importer
- AmbientWeather API client
- Data conflict resolution

### Phase 4-9: GUI, Features, and Polish
See `SoledadWX_Implementation_Plan.md` for detailed phase breakdown

## Minimal Viable Product (MVP)

The MVP will include:
1. Real-time data display from AmbientWeather API
2. Basic dashboard with current conditions
3. 24-hour scrolling temperature graph
4. Today's extremes display
5. Basic settings dialog

**Estimated MVP completion**: 4 weeks

## Installation from Source

### Prerequisites
- Git (for version control)
- Python 3.11+ (https://www.python.org/downloads/)
- pip (included with Python)

### Setup Steps

```bash
# Clone or download the repository
cd G:\Dev\SoledadWX

# Create and activate virtual environment
python -m venv soledadwx_env
soledadwx_env\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

## Building Windows Installer

When ready for distribution:

```bash
pip install pyinstaller
pyinstaller --windowed --onefile --icon=soledadwx/gui/resources/icons/icon.ico main.py
```

This creates a standalone executable in the `dist/` folder.

## Data Sources

### Source 1: Cumulus Historical Data
- **Location**: `G:\Dev\SoledadWX\Legacy\Cumulus-Historical-Data`
- **Date Range**: April 2010 - January 2018
- **Files**: Monthly logs and daily summaries
- **Status**: Legacy, high-priority data source

### Source 2: HP2000.mdb Database
- **Location**: `C:\Users\Public\HP2000\HP2000.mdb`
- **Date Range**: ~2018-present
- **Status**: Current, medium-priority data source

### Source 3: AmbientWeather.net API
- **Type**: WebSocket (real-time) + REST API (historical)
- **Status**: Active, highest-priority data source

## Station Configuration

**Current Weather Station**: Ambient Weather WS-1002-WiFi
- **Location**: 32.8191666666667° N, -117.240555555556° W
- **Altitude**: 522 feet (159 meters)
- **Units**: °F, inHg, inches, mph
- **Log Interval**: 3 minutes (with API, real-time available)

**Original Station**: Zephyr PWS-1000TD (Model 4)
- **Historical Data**: April 2010 - January 2018
- **Location**: Same as above
- **Data Logger**: Enabled

## Known Issues and Considerations

1. **MDB File Access**: Requires Microsoft Access ODBC driver (included on Windows)
2. **Date Format Handling**: Supports both dd/mm/yy and dd-mm-yy formats
3. **Data Gaps**: Import tools include gap detection and reporting
4. **Large Datasets**: Database indexes optimize queries for 100K+ readings

## Documentation

- **Implementation Plan**: `SoledadWX_Implementation_Plan.md`
- **Field Reference**: See Appendix A in implementation plan
- **API Configuration**: See Appendix B in implementation plan
- **Calibration Data**: See Appendix C in implementation plan

## Technology Stack

### Core Framework
- **PyQt6** (6.6.0) - Modern Windows 11 compatible GUI
- **PyQtGraph** (0.13.3) - Fast, interactive plotting

### Data Processing
- **numpy** - Array operations
- **python-dateutil** - Date/time handling
- **pyodbc** - Access .mdb databases

### Networking
- **python-socketio** - WebSocket connectivity for real-time API

### Database
- **SQLite3** - Lightweight, serverless database (stdlib)

### Distribution
- **PyInstaller** - Create Windows executable

## Development Workflow

### Daily Development Cycle

1. **Review** the current phase requirements
2. **Implement** the required modules
3. **Test** components individually
4. **Integrate** into main application
5. **Commit** with descriptive message

### Code Style

- Type hints throughout
- PEP 8 naming conventions
- Try/except error handling
- Logging at info/warning/error levels
- Dataclasses for data models

## Resources

### Cumulus Documentation
- https://cumuluswiki.org/a/About_Cumulus
- https://github.com/cumulusmx/CumulusMX
- https://www.wxforum.net/

### Weather Station Resources
- https://ambientweather.com/
- https://www.weewx.com/
- https://www.weather-display.com/

### PyQt6 Documentation
- https://doc.qt.io/qt-6/
- https://pypi.org/project/PyQt6/

## License

To be determined

## Contributing

Development is currently focused on MVP completion. See `SoledadWX_Implementation_Plan.md` for phase breakdown and task assignments.

## Support

For issues or questions:
1. Check `SoledadWX_Implementation_Plan.md` for technical details
2. Review existing GitHub issues (when repository is created)
3. Contact the development team

---

**Last Updated**: January 11, 2025
**Current Phase**: Phase 1 - Project Setup (Complete)
**Next Phase**: Phase 2 - Database Layer Implementation
