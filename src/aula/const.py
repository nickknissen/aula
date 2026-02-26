DOMAIN = "aula"
API_URL = "https://www.aula.dk/api/v"
API_VERSION = "22"
MIN_UDDANNELSE_API = "https://api.minuddannelse.net/aula"
SYSTEMATIC_API = "https://systematic-momo.dk/api/aula"
EASYIQ_API = "https://api.easyiqcloud.dk/api/aula"
MEEBOOK_API = "https://app.meebook.com/aulaapi"
CICERO_API = "https://surf.cicero-suite.com/portal-api/rest/aula"

# Widget IDs for third-party integrations
WIDGET_EASYIQ = "0001"
WIDGET_BIBLIOTEKET = "0019"
WIDGET_MIN_UDDANNELSE_UGEPLAN = "0029"
WIDGET_MIN_UDDANNELSE = "0030"
WIDGET_MEEBOOK = "0004"
WIDGET_HUSKELISTEN = "0062"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"  # noqa: E501

# Auth endpoints (validated against Android app network traffic)
AUTH_BASE_URL = "https://login.aula.dk"
OAUTH_AUTHORIZE_PATH = "/simplesaml/module.php/oidc/authorize.php"
OAUTH_TOKEN_PATH = "/simplesaml/module.php/oidc/token.php"
APP_REDIRECT_URI = "https://app-private.aula.dk"

# OAuth client (Level 3 = full MitID access)
OAUTH_CLIENT_ID = "_99949a54b8b65423862aac1bf629599ed64231607a"
OAUTH_SCOPE = "aula-sensitive"

# CSRF (cookie is PascalCase, header is lowercase — matches Android app)
CSRF_TOKEN_COOKIE = "Csrfp-Token"
CSRF_TOKEN_HEADER = "csrfp-token"

# MitID / SAML broker
BROKER_URL = "https://broker.unilogin.dk"
MITID_BASE_URL = "https://nemlog-in.mitid.dk"
