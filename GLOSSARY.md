# Aula

A client for the Danish school platform aula.dk, which guardians use to read and act on their
children's school and daycare information, including data that third-party widgets show inside
Aula.

## Language

### Sessions and credentials

**Aula session**:
A guardian's logged-in state with Aula itself, opened through MitID.
_Avoid_: login, auth, connection

**Refresh token**:
The long-lived credential that renews an Aula session. Aula replaces it on every use, so only one
process can hold it.
_Avoid_: token (unqualified)

### Widgets

**Widget**:
A third-party feature embedded in Aula and identified by a four-digit widget ID, such as `0029`
for the MinUddannelse week plan.
_Avoid_: plugin, integration, app

**Provider**:
The third-party system that serves a widget's data, such as MinUddannelse, Meebook, EasyIQ,
Docendo, Momo or Cicero. One provider can sit behind several widgets.
_Avoid_: vendor, widget API, third party

**Widget token**:
A credential Aula issues for one widget, which that widget's provider accepts in place of an Aula
session.
_Avoid_: bearer token, Aula token, JWT

**SSO widget**:
A widget whose provider is opened by posting the widget token to the provider's login form,
which hands off through SAML to a portal session. SFOweb is one.
_Avoid_: SAML widget, login widget

**Portal session**:
A provider-side session kept by the provider's own cookies and tied to one child at a time.
EasyIQ opens one directly with a widget token. SFOweb opens one through SAML, as an SSO widget.
_Avoid_: EasyIQ login, SFOweb login, widget session
