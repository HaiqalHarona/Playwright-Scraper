# bot_logic.py
# Launches the browser, detects Lazada session, routes to scraper or sniper.

from playwright.sync_api import sync_playwright, ProxySettings, Route, BrowserContext, Page
from playwright_stealth import Stealth
from captcha_solver import resolve_any_captcha, attach_global_captcha_hook
from stores.scraper.site_lazada import run_lazada, scrape_item_data
from stores.checkout.lazada_site_buy import buy_item
from datetime import datetime
import os
import time


# Block heavy assets during scrape to save bandwidth.
_BLOCKED_RESOURCE_TYPES = {"image", "font", "media", "stylesheet"}

def _block_resources(route: Route) -> None:
    if route.request.resource_type in _BLOCKED_RESOURCE_TYPES:
        route.abort()
    else:
        route.continue_()


def _is_lazada_logged_in(context: BrowserContext, page: Page) -> bool:
    # Check for authenticated session cookies (without domain restrictions)
    cookies = context.cookies()
    session_cookies = {"_lzd_stoken", "login_cookie", "lzd_uid"}
    if any(c["name"] in session_cookies for c in cookies):
        return True
        
    # Fallback: check if the 'My Account' header element is visible
    try:
        if page.locator("#myAccountTrigger, .my-account-trigger, a[href*='/customer/account']").is_visible():
            return True
    except Exception:
        pass
        
    return False


def _handle_login(page: Page, context: BrowserContext, email: str = "", password: str = "") -> None:
    """
    Navigate to the Lazada login page and auto-login using CapMonster to solve
    any captcha / slider that appears. No manual fallback — all challenges are
    routed through CapMonster.
    """
    print("[Traffic Cop] No session found — redirecting to login page.")
    login_url = "https://member.lazada.sg/user/login"
    try:
        page.goto(login_url, wait_until="domcontentloaded", timeout=30_000)
    except Exception as e:
        print(f"[Traffic Cop] Could not navigate to login page ({e}). Trying homepage redirect.")
        try:
            page.goto("https://www.lazada.sg", wait_until="domcontentloaded", timeout=30_000)
            login_btn = page.wait_for_selector("#anonLogin, a:has-text('LOGIN')", timeout=10_000)
            if login_btn:
                login_btn.click()
        except Exception as redirect_err:
            print(f"[Traffic Cop] Redirect to login failed: {redirect_err}")

    is_cred_valid = (
        email
        and password
        and "your_email" not in email
        and "your_password" not in password
    )

    if not is_cred_valid:
        if not email:
            print("[Traffic Cop] No email credentials provided in .env.")
        else:
            print("[Traffic Cop] Default placeholder credentials found. Cannot auto-login.")
        return

    print(f"[Traffic Cop] Attempting auto-login using email: {email}")

    user_selectors = [
        "input[name='fm-login-id']",
        "input[placeholder*='Phone Number or Email']",
        "input[placeholder*='phone or email']",
        "input[placeholder*='Email']",
        ".mod-login-input-loginName input",
        "input[type='text']",
    ]
    pass_selectors = [
        "input[name='fm-login-password']",
        "input[type='password']",
        "input[placeholder*='Password']",
        ".mod-login-input-password input",
    ]
    submit_selectors = [
        "button[type='submit']",
        "button:has-text('LOGIN')",
        "button:has-text('Login')",
        ".mod-login-btn button",
    ]

    # Up to 3 attempts: solve captcha → fill credentials → submit
    for attempt in range(1, 4):
        try:
            time.sleep(1.5)

            # Resolve any pre-form captcha
            resolve_any_captcha(page)
            time.sleep(0.5)

            user_el = None
            for sel in user_selectors:
                try:
                    el = page.locator(sel).first
                    if el.count() > 0 and el.is_visible():
                        user_el = el
                        break
                except Exception:
                    pass

            pass_el = None
            for sel in pass_selectors:
                try:
                    el = page.locator(sel).first
                    if el.count() > 0 and el.is_visible():
                        pass_el = el
                        break
                except Exception:
                    pass

            submit_el = None
            for sel in submit_selectors:
                try:
                    el = page.locator(sel).first
                    if el.count() > 0 and el.is_visible():
                        submit_el = el
                        break
                except Exception:
                    pass

            if not (user_el and pass_el and submit_el):
                print(f"[Traffic Cop] Attempt {attempt}: login form fields not found. Retrying...")
                page.reload(wait_until="domcontentloaded", timeout=30_000)
                continue

            user_el.click()
            user_el.fill("")
            user_el.type(email, delay=30)

            pass_el.click()
            pass_el.fill("")
            pass_el.type(password, delay=30)

            # Solve any captcha that appeared after typing credentials
            resolve_any_captcha(page)
            time.sleep(0.5)

            # Re-check for remaining slider / captcha blocking submit
            blocking_captcha = False
            for sel in ["#nc_1_n1z", ".nc_scale", "[class*='nc-container']",
                        "[class*='next-slider']", "[class*='captcha-slider']"]:
                try:
                    if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                        blocking_captcha = True
                        break
                except Exception:
                    pass

            if blocking_captcha:
                print(f"[Traffic Cop] Attempt {attempt}: captcha still visible after solving — retrying...")
                resolve_any_captcha(page)
                time.sleep(1.0)

            submit_el.click()
            print(f"[Traffic Cop] Attempt {attempt}: credentials submitted. Waiting for session...")

            for _ in range(8):
                time.sleep(1)
                if _is_lazada_logged_in(context, page):
                    print("[Traffic Cop] Auto-login succeeded! Active session confirmed.")
                    return

            # Check for error messages
            err_msg = ""
            for sel in [".next-feedback-message", ".next-feedback-content",
                        ".mod-login-input-validation", "[class*='error-msg']",
                        "[class*='feedback']"]:
                try:
                    el = page.locator(sel).first
                    if el.count() > 0 and el.is_visible():
                        err_msg = el.inner_text().strip()
                        break
                except Exception:
                    pass

            if err_msg:
                print(f"[Traffic Cop] Attempt {attempt} failed — server error: '{err_msg}'")
            else:
                print(f"[Traffic Cop] Attempt {attempt} failed — session not confirmed. Retrying...")
                resolve_any_captcha(page)

        except Exception as e:
            print(f"[Traffic Cop] Auto-login attempt {attempt} crashed: {e}")

    print("[Traffic Cop] All login attempts exhausted — could not establish a session.")


def start_browser_and_route(
    store_name: str,
    action: str,
    target_url: str,
    release_time: datetime | None = None,
    refresh_lead_seconds: int = 5,
    target_quantity: int = 1,
    test_refresh_duration: int = 0,
    email: str = "",
    password: str = "",
    acc_idx: int = 1,
    total_accounts: int = 1,
) -> str:
    """
    Launch browser, detect session, and route to the right store module.
    store_name           — e.g. "Lazada"
    action               — "buy" or "scrape"
    target_url           — direct product/search URL
    release_time         — scheduled drop time (None = immediate)
    refresh_lead_seconds — seconds before release_time to start refreshing
    target_quantity      — number of items to purchase
    test_refresh_duration — seconds to keep refreshing even when in stock (for testing)
    email                — email to auto-fill login
    password             — password to auto-fill login
    acc_idx              — account index for screen placement
    total_accounts       — total parallel accounts for screen placement
    """
    proxy_url = os.getenv("PROXY_URL", None)
    proxy_config: ProxySettings | None = (
        ProxySettings(server=proxy_url) if proxy_url else None
    )

    # Buy / Buy_Scrape = headful (user can see & intervene); scrape = headless to save resources.
    headless_mode = action not in ("buy", "buy_scrape")
    result = ""

    print(f"\n[Traffic Cop] Launching browser — {action.upper()} on {store_name}...")
    if proxy_config:
        print(f"[Traffic Cop] Proxy: {proxy_url}")
    print(f"[Traffic Cop] Headless: {headless_mode}")
    print(f"[Traffic Cop] Mode: Fresh browser (no saved sessions)")

    with Stealth().use_sync(sync_playwright()) as p:
        # Always launch fresh browser without saved sessions
        launch_args = []
        if not headless_mode and total_accounts > 1:
            import math
            # Standard screen dimension estimate
            screen_width = 1920
            screen_height = 1080
            cols = math.ceil(math.sqrt(total_accounts))
            rows = math.ceil(total_accounts / cols)
            
            # Substract small margin for OS panels/docks
            margin_y = 60
            
            win_width = int(screen_width / cols)
            win_height = int((screen_height - margin_y) / rows)
            
            idx = acc_idx - 1
            row = idx // cols
            col = idx % cols
            
            x = col * win_width
            y = row * win_height
            
            launch_args.extend([
                f"--window-position={x},{y}",
                f"--window-size={win_width},{win_height}"
            ])
            print(f"[Traffic Cop] Window Layout: pos=({x},{y}), size={win_width}x{win_height}")

        browser = p.chromium.launch(
            headless=headless_mode, 
            slow_mo=0, 
            channel="chrome", 
            args=launch_args
        )
        
        context = browser.new_context(
            proxy=proxy_config,
            viewport=None if (not headless_mode and total_accounts > 1) else { "width": 1280, "height": 720 }
        )

        page = context.new_page()

        # Attach global captcha hook on headful pages so every navigation is swept.
        if not headless_mode:
            attach_global_captcha_hook(page)

        # Block CSS/images only during standalone scrape — checkout needs a full render.
        if action == "scrape":
            page.route("**/*", _block_resources)
            print("[Traffic Cop] Mode: Headless / Bandwidth-Saver")
        else:
            print("[Traffic Cop] Mode: Headful / Full-render")

        # --- Store routing ---
        try:
            if store_name.lower() == "lazada":
                if action == "scrape":
                    result = run_lazada(page, action, target_url)

                elif action == "buy_scrape":
                    # --- Phase 1: Scrape the target URL for in-stock products ---
                    print("\n[Traffic Cop] ========================================")
                    print("[Traffic Cop]  BUY_SCRAPE: Phase 1 — Scraping products")
                    print("[Traffic Cop] ========================================")
                    # Check for continuous retry mode
                    continuous = os.getenv("SCRAPER_CONTINUOUS_MODE", "false").lower() == "true"
                    try:
                        retry_interval = int(os.getenv("SCRAPER_LOOP_INTERVAL", "60"))
                    except ValueError:
                        retry_interval = 60
                    
                    scrape_attempt = 0
                    in_stock = []
                    while True:
                        scrape_attempt += 1
                        print(f"\n[Traffic Cop] Scrape attempt #{scrape_attempt}...")
                        scraped_products = scrape_item_data(page, target_url)
                        in_stock = [p for p in scraped_products if not p.get('is_out_of_stock', True)]

                        if in_stock:
                            print(f"\n[Traffic Cop] Found {len(in_stock)} in-stock products on attempt #{scrape_attempt}!")
                            break

                        if not continuous:
                            result = "FAILED: No in-stock products found matching your criteria."
                            print(f"[Traffic Cop] {result}")
                            return result

                        print(f"[Traffic Cop] No in-stock products yet. Waiting {retry_interval}s before retry...")
                        page.reload(wait_until="domcontentloaded", timeout=30_000)
                        time.sleep(retry_interval)

                    print(f"\n[Traffic Cop] In-stock products found:")
                    for p in in_stock:
                        print(f"  - {p['name'][:60]} | {p['price']}")

                    # --- Phase 2: Login for purchasing ---
                    print("\n[Traffic Cop] ========================================")
                    print("[Traffic Cop]  BUY_SCRAPE: Phase 2 — Login")
                    print("[Traffic Cop] ========================================")
                    print("[Traffic Cop] Checking Lazada login session...")
                    try:
                        page.goto("https://www.lazada.sg", wait_until="domcontentloaded", timeout=30_000)
                    except Exception as e:
                        result = f"ERROR: Failed to load Lazada homepage: {e}"
                        print(f"[Traffic Cop] {result}")
                        return result

                    if not _is_lazada_logged_in(context, page):
                        _handle_login(page, context, email, password)
                    else:
                        print("[Traffic Cop] Active session found — proceeding.")

                    # --- Phase 3: Buy each in-stock product ---
                    print("\n[Traffic Cop] ========================================")
                    print("[Traffic Cop]  BUY_SCRAPE: Phase 3 — Purchasing")
                    print("[Traffic Cop] ========================================")
                    buy_results = []
                    for i, product in enumerate(in_stock, 1):
                        print(f"\n[Traffic Cop] >>> Buying product {i}/{len(in_stock)}: {product['name'][:60]}")
                        try:
                            buy_result = buy_item(
                                page=page,
                                target_url=product['link'],
                                release_time=None,
                                refresh_lead_seconds=0,
                                target_quantity=target_quantity,
                                test_refresh_duration=0,
                            )
                            buy_results.append(buy_result)
                            print(f"[Traffic Cop] <<< Result: {buy_result}")
                        except Exception as e:
                            err_msg = f"ERROR: buy_item crashed on '{product['name'][:40]}': {e}"
                            buy_results.append(err_msg)
                            print(f"[Traffic Cop] {err_msg}")

                    successes = [r for r in buy_results if r.startswith("SUCCESS")]
                    result = f"DONE: {len(successes)}/{len(in_stock)} products purchased successfully."

                elif action == "buy":
                    # Open Lazada home so cookies are readable, then check session.
                    print("[Traffic Cop] Checking Lazada login session...")
                    try:
                        page.goto("https://www.lazada.sg", wait_until="domcontentloaded", timeout=30_000)
                    except Exception as e:
                        result = f"ERROR: Failed to load Lazada homepage: {e}"
                        return result

                    if not _is_lazada_logged_in(context, page):
                        # No session — take the user to the login page and wait.
                        _handle_login(page, context, email, password)
                    else:
                        print("[Traffic Cop] Active session found — proceeding.")

                    try:
                        result = buy_item(
                            page=page,
                            target_url=target_url,
                            release_time=release_time,
                            refresh_lead_seconds=refresh_lead_seconds,
                            target_quantity=target_quantity,
                            test_refresh_duration=test_refresh_duration,
                        )
                    except Exception as e:
                        result = f"ERROR: buy_item crashed: {e}"
                        print(f"[Traffic Cop] {result}")
                else:
                    result = f"Error: '{action}' is not a supported action for Lazada."

            elif store_name.lower() == "amazon":
                result = "Error: Amazon module not yet implemented."

            else:
                result = f"Error: '{store_name}' is not a supported store."

        except Exception as e:
            result = f"ERROR: Routing crashed: {e}"
            print(f"[Traffic Cop] {result}")
        finally:
            print("[Traffic Cop] Done — closing browser.")
            try:
                if not page.is_closed():
                    page.close()
            except Exception:
                pass
            try:
                if not context.is_closed():
                    context.close()
            except Exception:
                pass
            try:
                if browser:
                    browser.close()
            except Exception:
                pass
    return result or ""