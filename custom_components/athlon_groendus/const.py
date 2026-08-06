DOMAIN = "athlon_groendus"

CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_CHARGEPOINT_ID = "chargepoint_id"
CONF_UPDATE_INTERVAL = "update_interval_seconds"
CONF_MAX_PAGES = "max_pages"
CONF_PORTAL_URL = "portal_url"
CONF_LABEL = "label"

DEFAULT_UPDATE_INTERVAL_SECONDS = 300  # 5 minutes
DEFAULT_MAX_PAGES = 5

# The Groendus charging portal is a white-label app: one Angular frontend, one
# Cognito user pool and one AppSync API serve several lease companies. Which
# tenant ("label") you belong to is sent to Cognito as ClientMetadata and is
# validated by a PreAuthentication Lambda trigger. A wrong label fails login
# with "User is not part of the <label> label" even when the password is right.
#
# The portal used to live on athlon.groendus.nl (label "athlon") and moved to
# thuisladen.groendus.nl (label "groendus"). Both are configurable in the UI so
# a future move does not require a code change.
DEFAULT_PORTAL_URL = "https://thuisladen.groendus.nl/"
DEFAULT_LABEL = "groendus"

# Labels the portal frontend knows about, in its own priority order. It picks
# the first one that appears anywhere in the page URL, falling back to
# "groendus" — we mirror that so a label can be derived from a portal URL.
KNOWN_LABELS = ("ayvens", "ayvens-ald", "athlon", "groendus")

CLIENT_GROUP = "Portal"

# Runtime AWS config is discovered from <portal_url>api/config (the same
# endpoint the frontend calls on boot). These are the values that endpoint
# returned at the time of writing and are used only if discovery fails.
COGNITO_USER_POOL_ID = "eu-central-1_8IPEVy8kc"
COGNITO_CLIENT_ID = "387nbhei8uvf13f7ck4c5ivaa2"
COGNITO_REGION = "eu-central-1"
APPSYNC_GRAPHQL_URL = "https://kylqo4g6gres3lmw4rtqaoftke.appsync-api.eu-central-1.amazonaws.com/graphql"

STORE_VERSION = 1
STORE_KEY_FMT = f"{DOMAIN}.{{entry_id}}"


def derive_label(portal_url: str) -> str:
    """Derive the tenant label from a portal URL, like the portal frontend does."""
    url = (portal_url or "").lower()
    for label in KNOWN_LABELS:
        if label in url:
            return label
    return DEFAULT_LABEL
