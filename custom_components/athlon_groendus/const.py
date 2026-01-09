DOMAIN = "athlon_groendus"

CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_CHARGEPOINT_ID = "chargepoint_id"
CONF_UPDATE_INTERVAL = "update_interval_seconds"
CONF_MAX_PAGES = "max_pages"

DEFAULT_UPDATE_INTERVAL_SECONDS = 300  # 5 minutes
DEFAULT_MAX_PAGES = 5

# Reverse-engineered AWS config (Athlon Groendus portal)
COGNITO_USER_POOL_ID = "eu-central-1_8IPEVy8kc"
COGNITO_CLIENT_ID = "387nbhei8uvf13f7ck4c5ivaa2"
COGNITO_REGION = "eu-central-1"
APPSYNC_GRAPHQL_URL = "https://kylqo4g6gres3lmw4rtqaoftke.appsync-api.eu-central-1.amazonaws.com/graphql"

STORE_VERSION = 1
STORE_KEY_FMT = f"{DOMAIN}.{{entry_id}}"


