# Provider errors never refresh the Aula session

Aula replaces the refresh token on every use, so each Aula session refresh carries a cost. If it
fails, the guardian has to approve a new MitID login. A provider's 401 or 403 says the provider
refused this widget token, usually because the account does not have that widget. It does not
say that the Aula session is dead. So a provider refusal raises `ProviderAuthenticationError`,
which is not an `AulaAuthenticationError`. The provider transport never retries and never
refreshes the Aula session. A provider module may reopen its own portal session once, using a
new widget token from the same Aula session. Examples are SFOweb restarting its SSO login and
EasyIQ rerunning its bootstrap. A widget token is minted for each request and never cached.

The one exception is Meebook. It reports an expired widget token as HTTP 200 with
`{"message": "JWT-Token expired, please renew."}`. The Meebook reader alone refreshes the Aula
session, mints a new token and retries once.

## Considered options

- **Refresh the Aula session and retry on any provider 401.** This is what happened before. It
  rotated the refresh token for refusals that a refresh cannot fix, and it resent the same stale
  widget token anyway.
- **Mint a new widget token and retry on 401** (scaarup/aula does this for Docendo). It does not
  help here: a token minted from the same session gets the same answer, and the known 401s
  (Cicero with no library widget) mean the account has no access.
- **Cache widget tokens** (scaarup/aula caches them for one minute). This saves one small Aula
  call per provider request, but a cache needs clearing whenever the session changes, because
  tokens are tied to the session.

## Consequences

Consumers that rebuild their client on `AulaAuthenticationError`, such as hass-aula, no longer
do that for widget calls. They should treat `ProviderAuthenticationError` as "this widget is
unavailable".
