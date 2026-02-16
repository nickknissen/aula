"""
Example demonstrating MitID authentication with the Aula API client.

This example shows how to use the new MitID authentication system
to access the Aula API.
"""

import asyncio
import logging
from aula import AulaApiClient

# Enable logging to see authentication progress
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


async def main():
    """Main example function."""
    # Replace with your actual MitID username
    # Note: This is your MitID username, NOT your Aula username
    mitid_username = "Nick Nissen"

    # Create the client
    # Tokens will be cached in .aula_tokens.json by default
    client = AulaApiClient(
        mitid_username=mitid_username,
        token_file=".aula_tokens.json",  # Optional: customize token storage location
        debug=False  # Set to True for detailed debug logs
    )

    try:
        # Login using MitID
        # First time: This will prompt you to approve the login in your MitID app
        # Subsequent times: Will use cached tokens (faster)
        print("Logging in with MitID...")
        print("If this is your first login, please check your MitID app")
        await client.login()
        print(f"Successfully logged in! API URL: {client.api_url}")

        # Fetch profile information
        profile = await client.get_profile()
        print(f"\nUser: {profile.display_name} (ID: {profile.profile_id})")

        if profile.children:
            print("\nChildren:")
            for child in profile.children:
                print(f" - {child.name} (ID: {child.id})")

                # Fetch daily overview for the first child
                if child == profile.children[0]:
                    overview = await client.get_daily_overview(child.id)
                    print(f"\n   Overview for {child.name}:")
                    print(f"   - Status: {overview.status_text}")
        else:
            print("\nNo children found.")

        # Example: Fetch calendar events
        from datetime import datetime, timedelta
        start = datetime.now()
        end = start + timedelta(days=7)

        print(f"\nFetching calendar events for the next 7 days...")
        events = await client.get_calendar_events(
            institution_profile_ids=profile.institution_profile_ids,
            start=start,
            end=end
        )

        if events:
            print(f"Found {len(events)} events:")
            for event in events[:5]:  # Show first 5 events
                print(f" - {event.title} on {event.start_datetime.strftime('%Y-%m-%d %H:%M')}")
        else:
            print("No calendar events found")

    except Exception as e:
        print(f"\nAn error occurred: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Important: Close the HTTP client sessions
        await client.close()
        print("\nSession closed.")


if __name__ == "__main__":
    asyncio.run(main())
