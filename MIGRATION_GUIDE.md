# Migration Guide: UniLogin to MitID Authentication

## Overview

Aula has migrated from the old UniLogin authentication system to the new MitID authentication system. This guide will help you update your code to use the new authentication method.

## What Changed?

### Before (UniLogin - No Longer Works)
```python
client = AulaApiClient(
    username="your_aula_username",
    password="your_aula_password"
)
await client.login()
```

### After (MitID - New System)
```python
client = AulaApiClient(
    mitid_username="your_mitid_username",  # Your MitID username, not Aula username
    token_file=".aula_tokens.json"  # Optional: token cache location
)
await client.login()  # Will prompt for MitID app approval on first login
```

## Key Differences

### 1. Authentication Method
- **Old**: Direct username/password authentication
- **New**: OAuth 2.0 + SAML + MitID app authentication

### 2. Credentials
- **Old**: Aula username and password
- **New**: MitID username + MitID app for approval

### 3. Token Caching
- **Old**: No token caching (login every time)
- **New**: Tokens are cached and reused (faster subsequent logins)

### 4. Python Version
- **Old**: Python >= 3.9
- **New**: Python >= 3.10 (required for `match` statement in auth code)

## Migration Steps

### Step 1: Update Dependencies

The new authentication system requires additional dependencies:

```bash
pip install --upgrade aula
```

Or if installing from source:
```bash
pip install qrcode pycryptodome
```

### Step 2: Find Your MitID Username

Your **MitID username** is different from your Aula username:
- It's the username you use to log into MitID
- Often in the format: "FirstnameLastname" or similar
- **Not** your email address
- **Not** your Aula username

To find it:
1. Try logging into https://mitid.dk/
2. The username you use there is your MitID username

### Step 3: Update Your Code

#### Simple Update
Replace the constructor:

```python
# OLD
client = AulaApiClient(username="aula_user", password="aula_pass")

# NEW
client = AulaApiClient(mitid_username="MitIDUsername")
```

#### Complete Example
```python
import asyncio
from aula import AulaApiClient

async def main():
    client = AulaApiClient(
        mitid_username="YourMitIDUsername",
        token_file=".aula_tokens.json",  # Tokens cached here
        debug=False  # Set True for detailed logs
    )

    try:
        # First login: Will prompt for MitID app approval
        # Subsequent logins: Uses cached tokens (fast!)
        await client.login()

        # Rest of your code remains the same
        profile = await client.get_profile()
        print(f"Logged in as: {profile.display_name}")

    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(main())
```

### Step 4: First Login Experience

On your **first login** or when tokens expire:
1. Run your code
2. You'll see: "Please approve the login request in your MitID app"
3. Open your **MitID app** on your phone
4. You'll see a login request for "Aula"
5. You might need to scan a **QR code** or enter an **OTP code** (displayed in terminal)
6. Approve the login in the app
7. Authentication completes and tokens are saved

On **subsequent logins**:
- Tokens are loaded from cache
- No MitID app interaction needed
- Much faster!

## Token Management

### Token Storage
Tokens are stored in a JSON file (default: `.aula_tokens.json`):
- Contains access token and refresh token
- Valid for several hours
- Automatically reused on next login

### Token File Location
You can customize where tokens are stored:
```python
client = AulaApiClient(
    mitid_username="...",
    token_file="/path/to/my/tokens.json"
)
```

### Security Considerations
- **Keep token files secure** - they provide access to your Aula account
- Add token files to `.gitignore`:
  ```gitignore
  .aula_tokens.json
  *_tokens.json
  ```
- Don't commit token files to version control

### Token Expiration
- Tokens expire after a few hours
- When expired, you'll be prompted to authenticate again with MitID app
- This is automatic - just approve in your app

## Environment Variables

For automation or CI/CD, you can use environment variables:

```python
import os
from aula import AulaApiClient

mitid_username = os.getenv("MITID_USERNAME")
client = AulaApiClient(mitid_username=mitid_username)
```

## Troubleshooting

### "User does not exist" Error
- **Problem**: Your MitID username is incorrect
- **Solution**: Verify your MitID username at https://mitid.dk/

### "Authentication failed" Error
- **Problem**: MitID app not responding or login declined
- **Solution**:
  - Ensure MitID app is installed and up to date
  - Check you're approving the correct login request
  - Try again after a few minutes

### "Token expired" Messages
- **Normal behavior**: Tokens expire periodically
- **Solution**: Just approve the new login request in your MitID app

### "Parallel sessions detected" Error
- **Problem**: You have multiple active MitID login attempts
- **Solution**: Wait 2-3 minutes and try again

### No QR Code/OTP Displayed
- **Check**: Look in your terminal output for QR code or OTP code
- **Alternative**: Some setups might show QR codes as ASCII art
- **Solution**: If neither appears, check your MitID app directly

## Backwards Compatibility

**⚠️ Breaking Change**: The old UniLogin authentication no longer works. You **must** update to MitID authentication.

If you absolutely need the old behavior for some reason, you'll need to:
1. Pin to the last version before MitID migration
2. Note that this version will eventually stop working as Aula has disabled UniLogin

## API Compatibility

All API methods remain the same:
- `get_profile()`
- `get_daily_overview()`
- `get_calendar_events()`
- `get_messages_for_thread()`
- etc.

Only the authentication mechanism has changed.

## Examples

See `example_mitid.py` for a complete working example.

## Need Help?

If you encounter issues:
1. Enable debug logging: `AulaApiClient(mitid_username="...", debug=True)`
2. Check the logs for detailed error messages
3. Verify your MitID username is correct
4. Ensure your MitID app is working
5. Open an issue on GitHub with debug logs (remove sensitive info)

## Summary Checklist

- [ ] Update to Python >= 3.10
- [ ] Install new dependencies (`qrcode`, `pycryptodome`)
- [ ] Find your MitID username
- [ ] Update code to use `AulaApiClient(mitid_username=...)`
- [ ] Remove old username/password references
- [ ] Add token files to `.gitignore`
- [ ] Test first login with MitID app
- [ ] Verify token caching works on second login
