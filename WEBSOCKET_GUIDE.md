# WebSocket Connection Guide for Webtop Virtual Desktop

This guide explains how to set up the WebSocket (WSS) connection to your webtop virtual desktop.

## Where to Plug In Your URL

1. **Edit your `.env` file** (create one if it doesn't exist):
   ```
   WSS_ENABLED=true
   WSS_URL=wss://your-webtop-server.tailscale-name.ts.net:8080/ws
   WSS_AUTH_TOKEN=your_secret_token_here  # Optional
   WSS_RECONNECT_INTERVAL=10
   WSS_HEARTBEAT_INTERVAL=30
   ```

2. **Using Tailscale DNS IPs**:
   - Your webtop virtual desktop should have Tailscale installed
   - Use the Tailscale MagicDNS name: `your-server-name.tailscale-name.ts.net`
   - Example: If your webtop server's Tailscale name is `webtop-desktop`, use:
     ```
     WSS_URL=wss://webtop-desktop.tailscale-name.ts.net:8080/ws
     ```

3. **Port and Path**:
   - Default WebSocket port is often 8080 or 443
   - Path depends on your webtop software (e.g., `/ws`, `/socket.io`, `/api/ws`)
   - Check your webtop virtual desktop documentation for the correct WebSocket endpoint

## Setting Up Your Webtop Virtual Desktop WebSocket Server

### Option 1: Using Existing Webtop Software
Most webtop virtual desktop solutions (like noVNC, Guacamole, Apache Guacamole) already have WebSocket endpoints. Find the WebSocket URL in your webtop software configuration.

### Option 2: Creating a Simple WebSocket Server
If you need to create a custom WebSocket server to receive bot status updates:

```python
# simple_websocket_server.py
import asyncio
import websockets
import json

async def handler(websocket):
    print("Client connected")
    try:
        async for message in websocket:
            data = json.loads(message)
            print(f"Received: {data}")
            
            # Send acknowledgment
            await websocket.send(json.dumps({
                "type": "ack",
                "message": "Received",
                "timestamp": time.time()
            }))
    except websockets.exceptions.ConnectionClosed:
        print("Client disconnected")

async def main():
    async with websockets.serve(handler, "0.0.0.0", 8080):
        print("WebSocket server running on ws://0.0.0.0:8080")
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    asyncio.run(main())
```

## Testing the Connection

1. **Run the test script**:
   ```
   python test_websocket.py
   ```

2. **Check the bot logs**:
   When you run `python main.py`, look for:
   ```
   [Main] WebSocket client initialized for webtop virtual desktop
   ```

3. **Verify connection**:
   The bot will send status updates:
   - `bot_starting` when the bot starts
   - `accounts_parsed` when accounts are loaded
   - `threads_starting` when browser windows launch
   - `execution_complete` when all threads finish

## Troubleshooting

### Problem: "Cannot find module `websockets`"
**Solution**: The module is installed but pyrefly (type checker) can't find it. This is not a runtime error. The bot will work fine.

To verify websockets is installed:
```
python -c "import websockets; print('OK')"
```

### Problem: Connection refused
**Solution**:
1. Ensure your webtop server is running and accessible via Tailscale
2. Check firewall settings on your webtop server
3. Verify the port is open: `telnet your-server.tailscale-name.ts.net 8080`
4. Make sure the WebSocket server is running on the correct endpoint

### Problem: SSL/TLS errors with WSS
**Solution**:
- Use `ws://` instead of `wss://` if your server doesn't have TLS
- For Tailscale, WSS is recommended for extra security

## Example Configuration

### Complete `.env` example with WebSocket:
```env
# Basic bot configuration
STORE_NAME=Lazada
ACTION=buy_scrape
TARGET_QUANTITY=1
RELEASE_TIME=
REFRESH_LEAD_SECONDS=5

# Account configuration
ACCOUNT_1_EMAIL=your_email@example.com
ACCOUNT_1_PASSWORD=your_password
ACCOUNT_2_EMAIL=another_email@example.com
ACCOUNT_2_PASSWORD=another_password

# Scraper configuration
SCRAPER_TARGET_URL=https://www.lazada.sg/shop-laptops/
SCRAPER_PRODUCT_NAMES=RTX 4090,MacBook Pro
SCRAPER_DELAY=2.0
SCRAPER_CONTINUOUS_MODE=true

# WebSocket configuration for webtop virtual desktop
WSS_ENABLED=true
WSS_URL=wss://webtop-desktop.tailscale-name.ts.net:8080/ws
WSS_AUTH_TOKEN=my_secret_token
WSS_RECONNECT_INTERVAL=10
WSS_HEARTBEAT_INTERVAL=30
```

## Next Steps

1. Configure your `.env` file with your WebSocket URL
2. Start your webtop virtual desktop WebSocket server
3. Run the bot: `python main.py`
4. Monitor status updates on your webtop virtual desktop

The bot will now connect to your webtop virtual desktop and send real-time status updates, allowing you to monitor and control it remotely.