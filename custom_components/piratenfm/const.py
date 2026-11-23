"""Constants for the Piraten.FM integration."""

from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "piratenfm"
LOGGER = logging.getLogger(__package__)

# Config entry data
CONF_MA_URL: Final = "url"
CONF_MA_TOKEN: Final = "token"

# Config entry options
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_AUTO_SYNC: Final = "auto_sync"
CONF_AUTO_REMOVE: Final = "auto_remove"
CONF_MISSING_THRESHOLD: Final = "missing_threshold"
CONF_INCLUDE_FREQUENCY: Final = "include_frequency"
CONF_INCLUDE_LOCATION: Final = "include_location"

DEFAULT_MA_URL: Final = "http://homeassistant.local:8095"
DEFAULT_SCAN_INTERVAL: Final = 300
MIN_SCAN_INTERVAL: Final = 60
MAX_SCAN_INTERVAL: Final = 86400
DEFAULT_AUTO_SYNC: Final = True
DEFAULT_AUTO_REMOVE: Final = True
DEFAULT_MISSING_THRESHOLD: Final = 3
MAX_MISSING_THRESHOLD: Final = 50
DEFAULT_INCLUDE_FREQUENCY: Final = True
DEFAULT_INCLUDE_LOCATION: Final = True

DEFAULT_OPTIONS: Final = {
    CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
    CONF_AUTO_SYNC: DEFAULT_AUTO_SYNC,
    CONF_AUTO_REMOVE: DEFAULT_AUTO_REMOVE,
    CONF_MISSING_THRESHOLD: DEFAULT_MISSING_THRESHOLD,
    CONF_INCLUDE_FREQUENCY: DEFAULT_INCLUDE_FREQUENCY,
    CONF_INCLUDE_LOCATION: DEFAULT_INCLUDE_LOCATION,
}

NAME_SEPARATOR: Final = " • "

SERVICE_REMOVE_MANAGED_STATIONS: Final = "remove_managed_stations"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
