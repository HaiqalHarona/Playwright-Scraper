# bot_logic.py
# Launches the browser, detects Lazada session, routes to scraper or sniper.

from playwright.sync_api import sync_playwright, ProxySettings, Route, BrowserContext
from playwright_stealth import Stealth
from captcha_solver import resolve_any_captcha
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


def _is_lazada_logged_in(context: BrowserContext, page) -> bool:
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


def _handle_login(page, context: BrowserContext, email: str = "", password: str = "") -> None:
    """
    Directs the page to the login URL. Attempts auto-login if email and password are provided.
    If it fails (due to wrong credentials, captcha/slider, etc.) or if credentials are empty,
    notifies the operator and falls back to manual human login.
    """
    print("[Traffic Cop] No session found — redirecting to login page.")
    login_url = "https://member.lazada.sg/user/login"
    try:
        page.goto(login_url, wait_until="domcontentloaded", timeout=30_000)
    except Exception as e:
        print(f"[Traffic Cop] Could not navigate directly to login page ({e}). Trying homepage redirect.")
        try:
            page.goto("https://www.lazada.sg", wait_until="domcontentloaded", timeout=30_000)
            login_btn = page.wait_for_selector("#anonLogin, a:has-text('LOGIN')", timeout=10000)
            login_btn.click()
        except Exception as redirect_err:
            print(f"[Traffic Cop] Failed to redirect to login: {redirect_err}")

    # Check if credentials are provided and not default template placeholders
    is_cred_valid = (
        email and 
        password and 
        "your_email" not in email and 
        "your_password" not in password
    )

    if is_cred_valid:
        print(f"[Traffic Cop] Attempting auto-login using email: {email}")
        try:
            # Let the page render a bit to avoid element errors
            time.sleep(1.5)

            # Robust selectors for Lazada's login fields
            user_selectors = [
                "input[name='fm-login-id']",
                "input[placeholder*='Phone Number or Email']",
                "input[placeholder*='phone or email']",
                "input[placeholder*='Email']",
                ".mod-login-input-loginName input",
                "input[type='text']"
            ]
            
            pass_selectors = [
                "input[name='fm-login-password']",
                "input[type='password']",
                "input[placeholder*='Password']",
                ".mod-login-input-password input"
            ]

            submit_selectors = [
                "button[type='submit']",
                "button:has-text('LOGIN')",
                "button:has-text('Login')",
                ".mod-login-btn button"
            ]

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

            if user_el and pass_el and submit_el:
                # Clear, focus and simulate typing
                user_el.click()
                user_el.fill("")
                user_el.type(email, delay=30)
                
                pass_el.click()
                pass_el.fill("")
                pass_el.type(password, delay=30)
                
                # Check for active slide or image captchas and solve them dynamically
                solved_captcha = resolve_any_captcha(page)
                if solved_captcha:
                    print("[Traffic Cop] Captcha solver executed successfully. Bypassing blocker...")
                    time.sleep(1.0)
                
                # Check for slider captcha wrapper before clicking submit
                slider_selectors = [
                    "#nc_1_n1z",
                    ".nc_scale",
                    ".next-slider",
                    "[class*='slider']",
                    "[class*='nc-container']"
                ]
                has_slider = False
                for sel in slider_selectors:
                    try:
                        if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                            has_slider = True
                            break
                    except Exception:
                        pass
                
                if has_slider:
                    print("[Traffic Cop] WARNING: Slider Captcha / Slide-to-verify detected on page. Auto-login cannot bypass sliders automatically.")
                else:
                    time.sleep(0.5)
                    submit_el.click()
                    print("[Traffic Cop] Credentials submitted. Waiting to verify session...")
                    
                    # Wait up to 6 seconds for login to succeed
                    for _ in range(6):
                        time.sleep(1)
                        if _is_lazada_logged_in(context, page):
                            print("[Traffic Cop] Auto-login succeeded! Active session confirmed.")
                            return
                
                # Check for common error elements on failure
                err_selectors = [
                    ".next-feedback-message",
                    ".next-feedback-content",
                    ".mod-login-input-validation",
                    "[class*='alert']",
                    "[class*='error-msg']",
                    "[class*='feedback']"
                ]
                err_msg = ""
                for sel in err_selectors:
                    try:
                        el = page.locator(sel).first
                        if el.count() > 0 and el.is_visible():
                            err_msg = el.inner_text().strip()
                            break
                    except Exception:
                        pass
                
                if err_msg:
                    print(f"[Traffic Cop] Auto-login failed with error message: '{err_msg}'")
                else:
                    print("[Traffic Cop] Auto-login failed or verification slider was triggered.")
            else:
                print("[Traffic Cop] Auto-login failed: Could not locate login form input fields.")
                
        except Exception as e:
            print(f"[Traffic Cop] Auto-login crashed: {e}")
    else:
        if not email:
            print("[Traffic Cop] No email credentials provided in .env.")
        else:
            print("[Traffic Cop] Default placeholder credentials found. Skipping auto-fill.")

    # Fallback to manual human login
    print("[Traffic Cop] >>> PLEASE SIGN IN MANUALLY in this browser window. <<<")
    print("[Traffic Cop] Waiting for manual login...")
    while True:
        if _is_lazada_logged_in(context, page):
            break
        time.sleep(2)
    print("[Traffic Cop] Login confirmed — proceeding.")


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
    """
    proxy_url = os.getenv("PROXY_URL", None)
    proxy_config: ProxySettings | None = (
        ProxySettings(server=proxy_url) if proxy_url else None
    )

    # Buy / Buy_Scrape = headful (user can see & intervene); scrape = headless to save resources.
    headless_mode = action not in ("buy", "buy_scrape")

    print(f"\n[Traffic Cop] Launching browser — {action.upper()} on {store_name}...")
    if proxy_config:
        print(f"[Traffic Cop] Proxy: {proxy_url}")
    print(f"[Traffic Cop] Headless: {headless_mode}")
    print(f"[Traffic Cop] Mode: Fresh browser (no saved sessions)")

    with Stealth().use_sync(sync_playwright()) as p:
        # Always launch fresh browser without saved sessions
        browser = p.chromium.launch(headless=headless_mode, slow_mo=0, channel="chrome")
        context = (
            browser.new_context(proxy=proxy_config)
            if proxy_config
            else browser.new_context()
        )

        page = context.new_page()

        # Block CSS/images only during standalone scrape — checkout needs a full render.
        if action == "scrape":
            page.route("**/*", _block_resources)
            print("[Traffic Cop] Mode: Headless / Bandwidth-Saver")
        else:
            print("[Traffic Cop] Mode: Headful / Full-render")

        # --- Store routing ---
        result = ""
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
        # pyrefly: ignore [bad-return]
        return result