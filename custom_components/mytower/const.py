"""Constants for MyTower integration."""

DOMAIN = "mytower"

APP_BASE_URL = "https://app.my-tower.co.il"
API_BASE_URL = "https://api.my-tower.co.il/api"

DEFAULT_SCAN_INTERVAL = 60  # minutes — poll every hour

# Config entry keys
CONF_PHONE = "phone"
CONF_AUTH_TOKEN = "auth_token"
CONF_USER_ID = "user_id"

# Cookie names
COOKIE_AUTH = "CRM_user_users"
COOKIE_DEVICE = "CRM_device"
COOKIE_DEVICE_VALUE = "ANDROID"
COOKIE_LANG = "CRM_siteLang"
COOKIE_PROJECT = "sub_project"
COOKIE_PROJECT_VALUE = "mytower"

# Mobile user-agent (required — server rejects desktop UA)
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 11; Pixel 5) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Mobile Safari/537.36"
)

APP_HEADERS = {
    "User-Agent": MOBILE_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Required for checkPhone — server returns {"data":false} without these
AJAX_HEADERS = {
    "User-Agent": MOBILE_UA,
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://app.my-tower.co.il",
    "Referer": "https://app.my-tower.co.il/",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

# Login uses form submit (NOT XHR) — server returns redirect to /index.php?user_id=XXXX
# X-Requested-With must NOT be set here, or server returns JSON instead of redirect
LOGIN_HEADERS = {
    "User-Agent": MOBILE_UA,
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://app.my-tower.co.il",
    "Referer": "https://app.my-tower.co.il/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Entity unique ID prefixes
ENTITY_MESSAGES = "messages"
ENTITY_MONTHLY_FEE = "monthly_fee"
ENTITY_PAID_MONTHS = "paid_months"
ENTITY_GATE_PREFIX = "gate_"

# Guest entity
ENTITY_GUESTS_COUNT = "guests_count"

# Services
SERVICE_ADD_GUEST = "add_guest"
SERVICE_REMOVE_GUEST = "remove_guest"
SERVICE_SUBMIT_PROBLEM = "submit_problem"

# Guest meeting places
MEETING_PLACE_LOBBY = "1424"
MEETING_PLACE_APARTMENT = "1425"

# Problem category IDs
PROBLEM_CATEGORIES = {
    "cleaning": 34,
    "maintenance": 35,
    "gardening": 37,
    "resident_services": 38,
}

# Problem sub-category IDs
PROBLEM_SUB_CATEGORIES = {
    "management_fee": 6108,
    "elevator_malfunction": 6109,
    "lighting_malfunction": 6110,
    "door_malfunction": 6112,
    "maintenance_other": 6113,
}

# Problem location IDs
PROBLEM_LOCATIONS = {
    "floor_lobby": 15360,
    "resident_parking": 15361,
    "main_lobby": 15362,
    "trash_room": 15363,
    "entrance": 15364,
}
