"""
Basic example using MitID authentication with Aula API.

NOTE: This example uses the NEW MitID authentication system.
You need your MitID username (not Aula username) and the MitID app.
"""

import asyncio
from aula import AulaApiClient


async def main():
    # Replace with your MitID username
    # NOTE: This is your MitID username, NOT your Aula username!
    mitid_username = "your_mitid_username"

    client = AulaApiClient(mitid_username=mitid_username)

    try:
        # Login (required for most operations)
        # First time: Will prompt for MitID app approval
        # Subsequent times: Uses cached tokens (faster)
        print("Logging in with MitID...")
        print("If this is your first login, check your MitID app for approval request")
        await client.login()
        print(f"Successfully logged in. API URL: {client.api_url}")

        # Fetch profile information
        profile = await client.get_profile()
        print(f"User: {profile.display_name} (ID: {profile.profile_id})")

        if profile.children:
            print("Children:")
            for child in profile.children:
                print(f" - {child.name} (ID: {child.id})")

                # Fetch daily overview for the first child
                # Note: Only fetching for one child here as an example
                if child == profile.children[0]:
                    overview = await client.get_daily_overview(child.id)
                    print(f"   Overview for {child.name}:")
                    print(f"   - Status: {overview.status_text}")
                    # Add more overview details as needed
        else:
            print("No children found.")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        # Close the HTTP client sessions (important!)
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
