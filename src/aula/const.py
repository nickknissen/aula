DOMAIN = "aula"
API_URL = "https://www.aula.dk/api/v"
API_VERSION = "24"
MIN_UDDANNELSE_API = "https://api.minuddannelse.net/aula"
SYSTEMATIC_API = "https://systematic-momo.dk/api/aula"
EASYIQ_API = "https://api.easyiqcloud.dk/api/aula"
# EasyIQ serves homework and weekplan rows from its school portal, not from the
# aula REST API. ``/api/aula/homeworkinfo`` was removed upstream and now 404s.
# The two data types live on separate controllers: the calendar one never
# returns homework rows.
EASYIQ_PORTAL = "https://skoleportal.easyiqcloud.dk"
EASYIQ_CALENDAR_PATH = "/Calendar/CalendarGetWeekplanEvents"
EASYIQ_HOMEWORK_PATH = "/AulaHuskeliste/GetWeekplanEvents"
EASYIQ_CHILDREN_PATH = "/Aula/GetChildren"
# The portal's controllers need the session cookies this sets; the Aula widget
# token on its own is not enough.
EASYIQ_AUTHENTICATE_PATH = "/Aula/AuthenticateAulaUser"
# The real client's own child selector: a server-side state change (followed
# by a full page reload in the browser) that makes the portal's session treat
# this child as the active one. Takes EasyIQ's own ``Id`` for the child, from
# ``GetChildren``, as ``loginId`` -- not the child's ``Login`` string.
EASYIQ_SWITCHCHILD_PATH = "/Aula/SwitchChild"
MEEBOOK_API = "https://app.meebook.com/aulaapi"
CICERO_API = "https://surf.cicero-suite.com/portal-api/rest/aula"

# Widget IDs for third-party integrations
WIDGET_EASYIQ_WEEKPLAN = "0128"
WIDGET_EASYIQ_HOMEWORK = "0142"
WIDGET_BIBLIOTEKET = "0019"
WIDGET_MIN_UDDANNELSE_UGEPLAN = "0029"
WIDGET_MIN_UDDANNELSE_TASKS = "0030"
WIDGET_MIN_UDDANNELSE_SSO = "0023"
WIDGET_MEEBOOK = "0004"
WIDGET_HUSKELISTEN = "0062"

# Widget IDs that can mint a token for MinUddannelse's opgaveliste endpoint, in
# preference order. Not every school lists 0030, and a school that only has the
# SSO widget still has opgaver: a 0023 token is accepted by the same endpoint
# with the same parameters (scaarup/aula#364, verified live 2026-08-11).
MIN_UDDANNELSE_TASK_WIDGETS = (WIDGET_MIN_UDDANNELSE_TASKS, WIDGET_MIN_UDDANNELSE_SSO)

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

# STIL puts an F5 bot-defence gate in front of the UniLogin broker for some
# clients. It answers on this host, and passing it needs a JavaScript engine,
# so the flow can only be reported, not completed. See nickknissen/aula#43.
STIL_SECURITY_CHECK_HOST = "security-check.stil.dk"
