"""Constants for the XiaoDu (小度) integration."""

DOMAIN = "xiaodu"

# Configuration keys
CONF_COOKIE = "cookie"
CONF_HOUSE_ID = "house_id"
CONF_HOUSE_NAME = "house_name"
CONF_DEVICE_IDS = "device_ids"
CONF_DEVICES = "devices"
CONF_APPLIANCE_TYPES = "appliance_types"

# Default polling interval (seconds)
DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 10

# API endpoints
XIAODU_HOST = "https://xiaodu.baidu.com"
API_GATEWAY = "/appserver/gateway/app/v1"
API_MULTIHOUSE = "/saiya/smarthome/multihouse"
API_APPLIANCE = "/saiya/smarthome/appliance"
API_DEVICE_LIST = "/saiya/smarthome/devicelist"
API_APPLIANCE_DETAILS = "/saiya/smarthome/appliancedetails"
API_DIRECTIVE_SEND = "/saiya/smarthome/directivesend"

# DuerOS control namespace
DUEROS_NAMESPACE = "DuerOS.ConnectedHome.Control"

# Platforms
PLATFORMS = [
    "light",
    "switch",
    "cover",
    "climate",
    "sensor",
    "fan",
    "lock",
    "button",
]

# Error messages
ERROR_INVALID_AUTH = "invalid_auth"
ERROR_CANNOT_CONNECT = "cannot_connect"
ERROR_COOKIE_EXPIRED = "cookie_expired"
ERROR_UNKNOWN = "unknown"
