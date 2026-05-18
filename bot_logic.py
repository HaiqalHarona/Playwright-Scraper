# bot_logic.py
from playwright.sync_api import sync_playwright, ProxySettings, Route
from playwright_stealth import Stealth
from stores.scraper.site_lazada import run_lazada
from stores.checkout.lazada_site_buy import buy_item
import os

# Resource types to always block — never needed for scraping and waste bandwidth.
_BLOCKED_RESOURCE_TYPES = {"image", "font", "media", "stylesheet"}

def _block_resources(route: Route) -> None:
    """Abort requests for non-essential resource types to save bandwidth."""
    if route.request.resource_type in _BLOCKED_RESOURCE_TYPES:
        route.abort()
    else:
        route.continue_()

def start_browser_and_route(store_name, action, target_url):
    # --- PROXY CONFIGURATION ---
    # To use a proxy, set this to your proxy URL (e.g., http://user:pass@host:port)
    # or set the PROXY_URL environment variable.
    proxy_url = os.getenv("PROXY_URL", None)
    proxy_config: ProxySettings | None = ProxySettings(server=proxy_url) if proxy_url else None

    using_proxy = proxy_config is not None

    print(f"\n[Traffic Cop] Launching browser engine for {action.upper()}...")
    if using_proxy:
        print(f"[Traffic Cop] Using Proxy : {proxy_url}")
    print(f"[Traffic Cop] Mode        : Headless / Bandwidth-Saver (images, fonts, media & CSS blocked)")

    # Stealth().use_sync() wraps the playwright context manager and
    # automatically applies all stealth evasions to every page/context.
    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(headless=True, slow_mo=0)

        # Create context — pass proxy only when configured.
        if proxy_config:
            context = browser.new_context(proxy=proxy_config)
        else:
            context = browser.new_context()

        page = context.new_page()

        # Always block non-essential resource types to save bandwidth and speed up scraping.
        page.route("**/*", _block_resources)

        if store_name.lower() == "lazada":
            if action == "scrape":
                result = run_lazada(page, action, target_url)
            elif action == "buy":
                result = buy_item(page, target_url)

        elif store_name.lower() == "amazon":
            result = ""

        else:
            result = f"Error: '{store_name}' is not a supported store."

        print("[Traffic Cop] Task complete. Closing browser...")
        browser.close()

        return result