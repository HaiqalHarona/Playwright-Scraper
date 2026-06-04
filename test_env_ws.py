import os
import asyncio
import websockets
from dotenv import load_dotenv

async def test_env_connection():
    print("Loading variables from .env file...")
    # This automatically finds and reads the .env file in the same folder
    load_dotenv()

    # Read the variables (matching your image exactly)
    wss_enabled = os.getenv("WSS_ENABLED", "false").lower() == "true"
    wss_url = os.getenv("WSS_URL")
    wss_auth_token = os.getenv("WSS_AUTH_TOKEN")

    print("-" * 50)
    print(f"WSS_ENABLED: {wss_enabled}")
    print(f"WSS_URL:     {wss_url}")
    print(f"TOKEN LOADED: {'Yes' if wss_auth_token else 'No'}")
    print("-" * 50)

    # Pre-flight checks
    if not wss_enabled:
        print("✗ WSS_ENABLED is set to false or missing. Exiting.")
        return

    if not wss_url:
        print("✗ Error: WSS_URL is missing from .env")
        return

    # Browserless requires the token to be in the URL query string
    connection_url = wss_url
    if wss_auth_token and "token=" not in connection_url:
        separator = "&" if "?" in connection_url else "?"
        connection_url = f"{connection_url}{separator}token={wss_auth_token}"

    # Mask token for printing
    display_url = connection_url
    if wss_auth_token:
        display_url = connection_url.replace(wss_auth_token, "***[HIDDEN]***")

    print(f"\nAttempting to connect...")
    print(f"Target: {display_url}")
    
    try:
        # Attempt the raw WebSocket connection
        async with websockets.connect(connection_url) as websocket:
            print("\n✓ SUCCESS! Connected to the WebSocket server.")
            print("✓ Connection accepted by Browserless.")
            
            # Hold the connection open for 3 seconds to ensure it's stable
            print("Holding connection open for 3 seconds to test stability...")
            await asyncio.sleep(3)
            
            print("✓ Connection is stable. Test complete!")
            
    except Exception as e:
        if hasattr(e, 'status_code'):
            print(f"\n✗ FAILED: Server rejected the connection (Status Code: {getattr(e, 'status_code')}).")
            print("This usually means your token is incorrect or formatting is wrong.")
        else:
            print(f"\n✗ FAILED to connect!")
            print(f"Error details: {e}")

if __name__ == "__main__":
    asyncio.run(test_env_connection())