# Aula Authentication

This document describes how aula.dk authenticates users and how this library implements it. The findings are based on:
- HAR capture analysis of a real browser login session (February 2026)
- Network traffic analysis of the official Android app (v2.14.4)
- Cross-referencing the library's OAuth implementation

## Overview

Aula supports three authentication paths that share the same MitID identity verification but differ in how the API session is managed:

| | Browser (web login) | Android app (official) | This library |
|---|---|---|---|
| **Entry point** | `www.aula.dk/auth/login.php` | OIDC authorize endpoint with PKCE | OAuth authorize endpoint with PKCE |
| **Identity provider** | MitID via SAML broker | MitID via SAML broker (same) | MitID via SAML broker (same) |
| **Session established by** | SAML redirect chain sets `PHPSESSID` | `access_token` query param on every request | `access_token` query param during `init()` |
| **API authentication** | Cookies only | `access_token` query param + cookies | Cookies only (after init) |
| **access_token in API URLs** | Never | Every request | Only during init, then cleared |

## OAuth Configuration

Observed from the Android app's network traffic:

| Parameter | Value |
|---|---|
| **Authorize URL** | `https://login.aula.dk/simplesaml/module.php/oidc/authorize.php` |
| **Token URL** | `https://login.aula.dk/simplesaml/module.php/oidc/token.php` |
| **Logout URL** | `https://login.aula.dk/auth/logout.php` |
| **Redirect URI** | `https://app-private.aula.dk` |
| **Client ID (Level 3)** | `_99949a54b8b65423862aac1bf629599ed64231607a` |
| **Client ID (Level 2)** | `_742adb5e2759028d86dbadf4af44ef70e8b1f407a6` |
| **Scope (Level 3)** | `aula-sensitive` |
| **Scope (Level 2)** | `aula` |
| **PKCE** | Yes (S256) |
| **API version** | 22 |

**Our library uses the Level 3 client (`_99949a...`, `aula-sensitive`).** Level 2 provides limited access and is used when users authenticate with a lower MitID assurance level.

## Environment Configuration

The production environment uses:

| Host | Value |
|---|---|
| **Backend** | `www.aula.dk` |
| **Auth** | `login.aula.dk` |
| **Private data** | `app-private.aula.dk` |
| **Staff data** | `app-staff.aula.dk` |

## Browser Authentication Flow

Traced from a HAR capture of a real login + API usage session (227 requests, 47 API calls):

```
1. GET  www.aula.dk/auth/login.php
   -> 302 redirect to login.aula.dk

2. GET  login.aula.dk/auth/login.php
   -> 302 redirect to broker.unilogin.dk (SAML request)
   <- Sets: SimpleSAML cookie

3. GET  broker.unilogin.dk/auth/realms/broker/protocol/saml-stil
   -> Renders IdP selection page (UniLogin/MitID)

4. POST broker.unilogin.dk (select MitID as IdP)
   -> 303 redirect chain to nemlog-in.mitid.dk
   <- Sets: RECENTLY_USED_IDP cookie

5. MitID authentication (nemlog-in.mitid.dk)
   -> POST /login/mitid/initialize
   -> MitID app approval (polling)
   -> POST /login/mitid (completion)
   <- Returns SAML response form

6. POST broker.unilogin.dk/broker/nemlogin3/endpoint (SAML response)
   -> Redirect chain through post-broker-login
   -> Returns final SAML response for Aula

7. POST login.aula.dk/simplesaml/.../saml2-acs.php (final SAML assertion)
   -> 303 redirect to login.aula.dk/auth/login.php?type=unilogin
   <- Sets: SimpleSAML, SimpleSAMLAuthToken cookies

8. GET  login.aula.dk/auth/login.php?type=unilogin
   -> 302 redirect to /
   <- Sets: PHPSESSID (domain=.aula.dk)  <-- KEY: session cookie established here

9. GET  login.aula.dk/ -> login.aula.dk/portal/ -> www.aula.dk/portal/
   -> Redirect chain lands on the portal page
   -> Browser already has PHPSESSID + persistent cookies from previous sessions

10. API calls begin (www.aula.dk/api/v23/)
    -> First call: profiles.getProfilesByLogin (server rotates PHPSESSID)
    -> Second call: profiles.getProfileContext
    -> All subsequent API calls use cookies only
```

### Cookies Sent with Every API Request

| Cookie | Purpose | Origin |
|---|---|---|
| `PHPSESSID` | PHP session identifier | Set by `login.aula.dk/auth/login.php` during SAML completion (step 8), rotated on first API call |
| `Csrfp-Token` | CSRF protection token | Persistent cookie from previous sessions, set by Aula backend |
| `initialLogin` | Login state flag (value: `true`) | Persistent cookie from previous sessions |
| `profile_change` | Active profile identifier | Persistent cookie from previous sessions |

### CSRF Protection

- The `csrfp-token` HTTP header is sent **only on POST requests**
- Its value matches the `Csrfp-Token` cookie exactly
- GET requests do not include this header
- The Aula portal page contains `<input type="hidden" id="csrfp_hidden_data_token" value="Csrfp-Token">` to tell JavaScript which cookie to read

## Android App Authentication Flow

Observed from network traffic analysis of the official Android app:

```
1. Configure OIDC client
   -> Authority: https://login.aula.dk/
   -> ClientId: _99949a54b8b65423862aac1bf629599ed64231607a (Level 3)
   -> Scope: aula-sensitive
   -> RedirectUri: https://app-private.aula.dk
   -> PKCE: S256

2. Perform full OIDC login
   -> Opens system browser for MitID authentication
   -> Same SAML broker + MitID flow as browser
   -> Returns: access_token, refresh_token, expiration

3. Tokens persisted locally
   -> access_token, refresh_token, expires_at stored

4. ALL subsequent API requests
   -> access_token ALWAYS appended as query parameter to URL
   -> Cookies also sent automatically (PHPSESSID, Csrfp-Token, etc.)
   -> Both access_token and cookies sent on every request

5. CSRF handling (POST requests only)
   -> Csrfp-Token cookie value read and sent as csrfp-token header
   -> Content-Type: application/json for POST bodies

6. Token refresh
   -> On expired token: OIDC refresh with refresh_token
   -> On failure: retries once, then triggers re-login
   -> On logout: calls auth/logout.php with redirect chain
```

### Key Difference: access_token on Every Request

The Android app **never clears the access_token** — it unconditionally appends `?access_token=...` to every API request URL.

Our library clears the token after `init()` and relies on cookies only. Both approaches work because the Aula server accepts either mechanism. We deliberately clear the token for security — keeping it in every URL risks leaking it through server logs, browser history, referer headers, and proxy logs.

### HTTP Headers

Observed from the Android app's requests:

| Header | Value |
|---|---|
| `user-agent` | `"Android"` (or `"iOS"` on Apple) |
| `App-Version` | Build version string |
| `App-Device-Type` | `"Phone"` / `"Tablet"` |
| `X-Amzn-Trace-Id` | Per-request GUID |
| `Accept` | `application/json, text/plain` |

### Login URLs

The app treats certain API methods as "login URLs" that are allowed before the session is fully established:
- `profiles.getProfileContext`
- `profiles.getProfilesByLogin`
- `profiles.getProfileTypesByLogin`
- `notifications.registerDevice` / `unregisterDevice`
- `session.keepAlive`

Non-login API calls are blocked until the user profile is loaded.

## Library Authentication Flow

This library uses a **mobile app OAuth 2.0 + PKCE flow** matching the Android app's OIDC configuration, but with a session-based optimization:

```
1. Start OAuth flow (login.aula.dk/simplesaml/module.php/oidc/authorize.php)
   -> client_id=_99949a54b8b65423862aac1bf629599ed64231607a
   -> redirect_uri=https://app-private.aula.dk
   -> scope=aula-sensitive
   -> PKCE code_challenge (S256)
   -> Redirects to SAML broker

2-6. Same MitID/SAML flow as browser (steps 3-7 above)

7. Follow OAuth callback redirects
   -> login.aula.dk redirects to app-private.aula.dk?code=...&state=...
   -> PHPSESSID cookie set during this redirect chain (domain=.aula.dk)

8. Exchange OAuth code for tokens (login.aula.dk/.../token.php)
   -> Returns: access_token, refresh_token, expires_in

9. Create AulaApiClient with access_token + cookies from auth flow

10. init() — establish API session
    -> GET profiles.getProfilesByLogin?access_token=...
    -> GET profiles.getProfileContext?access_token=...
    -> Server establishes session, sets/rotates PHPSESSID
    -> Captures Csrfp-Token cookie from response
    -> Clears access_token (no longer needed)

11. All subsequent API calls use session cookies only
```

### Our Approach vs. Android App

| Aspect | Android app | Our library |
|---|---|---|
| **access_token lifetime** | Sent on every request until expiry | Sent during init, then cleared |
| **Primary auth mechanism** | access_token query param | Session cookies (PHPSESSID) |
| **CSRF handling** | `Csrfp-Token` cookie -> `csrfp-token` header (POST) | Same (centralized in `_request_with_version_retry`) |
| **Token refresh** | OIDC refresh flow | Via custom `refresh_access_token()` |
| **User-Agent** | `"Android"` | Desktop Chrome string |
| **Token storage** | Encrypted local storage | FileTokenStorage (JSON file) |

Our session-based approach (clear token after init, use cookies) works because the Aula server establishes a full PHP session during the first API calls. The Android app's approach of always sending the token is simpler but less secure — the token is exposed in every URL, where it can leak via server access logs, HTTP referer headers, proxy logs, and browser history.

### Why access_token Is Needed During init()

The browser gets a fully-established session through the SAML redirect chain — the PHP backend at `login.aula.dk` processes the SAML assertion and creates a session before redirecting to `www.aula.dk`.

Our OAuth flow redirects to `app-private.aula.dk` instead, so the session may not be fully established for API use. The `access_token` query parameter during `init()` tells the API to authenticate and establish a proper session. After that, cookies handle everything.

### Token Lifecycle

```
Fresh login:
  MitID auth -> access_token + refresh_token + cookies -> stored

Cached tokens (not expired):
  Load from storage -> use directly

Expired tokens (refresh available):
  refresh_token -> new access_token -> stored

Session cookies stale:
  create_client() gets 403 -> force_login=True -> full MitID re-auth
```

## Widget Authentication

Third-party widget APIs (Min Uddannelse, EasyIQ, Meebook, Systematic, Cicero) use a separate token mechanism:

1. Fetch widget token: `GET /api/v22/?method=aulaToken.getAulaToken&WidgetId={id}`
2. Use as Bearer token: `Authorization: Bearer <widget_token>`

These widget tokens are **not** the OAuth access_token — they are short-lived tokens issued by the Aula API for specific widget integrations.

### Widget SSO Parameters

Widget URLs include these query parameters:

| Parameter | Description |
|---|---|
| `sessionUuid` | User's profile ID |
| `isMobileApp` | `true` |
| `aulaToken` | Widget-specific token |
| `assuranceLevel` | `"3"` (authentication level) |
| `userProfile` | Profile type (e.g., `"guardian"`) |
| `childFilter` | Selected child ID |
| `institutionFilter` | Selected institution ID |
| `csrfpToken` | Current CSRF token |
| `currentWeekNumber` | Week number |
| `group` | Optional group ID |

## Appendix: API Endpoints

Key API method prefixes:

| Prefix | Module |
|---|---|
| `profiles.` | User profiles, login, master data |
| `messaging.` | Threads, messages, folders, auto-reply |
| `posts.` | News posts |
| `calendar.` | Events, vacations, important dates |
| `presence.` | Check-in/out, templates, daily overview |
| `gallery.` | Albums, media |
| `notifications.` | Settings, device registration |
| `search.` | Recipients, messages, profiles |
| `groups.` | Group membership |
| `documents.` | Secure documents |
| `files.` | Attachments, downloads |
| `comments.` | Post comments |
| `session.` | Keep-alive |
| `aulaToken.` | Widget bearer tokens |
| `centralConfiguration.` | App config, file limits |
| `CalendarFeed.` | Calendar sync |
| `personalReferenceData.` | Reference data |
| `MunicipalConfiguration.` | Municipality settings |
