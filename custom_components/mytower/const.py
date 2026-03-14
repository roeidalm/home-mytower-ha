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

# Entity unique ID prefixes
ENTITY_MESSAGES = "messages"
ENTITY_MONTHLY_FEE = "monthly_fee"
ENTITY_PAID_MONTHS = "paid_months"
ENTITY_GATE_PREFIX = "gate_"
