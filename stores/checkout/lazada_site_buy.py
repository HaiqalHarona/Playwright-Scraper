# stores/checkout/lazada_site_buy.py
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout
from datetime import datetime
import re
import time


# --- Timeouts (ms) and delays (s) ---
_NAVIGATION_TIMEOUT = 60_000  # full page load
_ELEMENT_TIMEOUT = 30_000     # single element wait (increased from 15s to 30s)
_RETRY_DELAY = 0.4            # between refresh attempts
_POST_CLICK_DELAY = 1.5       # breathing room after major clicks
MAX_REFRESH_ATTEMPTS = 300    # safety cap on the stock-poll loop


# --- Selectors — update if Lazada redesigns their DOM ---

# Product page
SEL_QUANTITY_INPUT = (
    "input[data-spm='quantity'], input[aria-label*='uantity'], "
    ".pdp-mod-product-info-quantity input, .qty-input input, "
    "[class*='quantity'] input[type='text'], [class*='quantity'] input[type='number']"
)
SEL_QTY_PLUS = (
    "button[data-spm='quantity_increase'], button.pdp-mod-product-info-quantity-plus, "
    "button.pdp-btn-quantity-plus, [class*='quantity'] button[class*='plus'], "
    ".pdp-mod-product-info-quantity button:last-of-type"
)
SEL_QTY_MAX_LABEL = "[class*='quantity-max'], [class*='maxQty'], [class*='Quantity-max']"
SEL_BUY_NOW = (
    "button[data-spm='d_buynow'], .btn-buynow, [class*='buynow'], "
    "button:has-text('Buy Now'), button:has-text('BUY NOW')"
)

# Checkout page
SEL_CHECKOUT_ADDR = "[data-spm='address'], .address-list .address-item:first-child"
SEL_PAYMENT_CARD = (
    "label:has-text('Credit'), label:has-text('Debit'), "
    "[data-spm*='credit'], [data-spm*='debit'], "
    "input[value*='CARD'], input[value*='card']"
)
SEL_PLACE_ORDER = (
    # Data attributes (most reliable)
    "button[data-spm*='place_order'], button[data-spm*='placeorder'], "
    "button[data-spm*='checkout'], button[data-spm*='submit'], "
    # Class-based selectors
    "button[class*='checkout-order-total-button'], .checkout-order-total-button button, "
    ".submit-order-btn, .place-order-btn, [class*='place-order'] button, "
    "[class*='checkout-order-total'] button, [class*='submit-order'] button, "
    "[class*='checkout-submit'] button, [class*='order-submit'] button, "
    # Text-based selectors (multiple variations)
    "button:has-text('Place Order Now'), button:has-text('PLACE ORDER NOW'), "
    "button:has-text('PLACE ORDER'), button:has-text('Place Order'), "
    "button:has-text('Proceed to pay'), button:has-text('Proceed to Pay'), "
    "button:has-text('Pay Now'), button:has-text('PAY NOW'), "
    "button:has-text('Pay'), button:has-text('PAY'), "
    "button:has-text('Submit Order'), button:has-text('SUBMIT ORDER'), "
    "button:has-text('Confirm'), button:has-text('CONFIRM'), "
    # Generic checkout buttons
    "form[action*='checkout'] button[type='submit'], "
    "form[action*='order'] button[type='submit'], "
    "[class*='checkout'] button[type='submit'], "
    "[class*='order-total'] button"
)

# OOS indicators — only declared OOS if these are positively visible
SEL_OOS_INDICATORS = (
    "button[disabled][class*='buy'], "
    "[class*='soldOut'], [class*='sold-out'], "
    "span:has-text('Out of Stock'), span:has-text('Sold Out')"
)


# --- Helpers ---

def _wait_until_near_release(release_time: datetime, lead_seconds: int) -> None:
    # Block until LEAD_SECONDS before drop time, printing a heartbeat every 10s.
    while True:
        now = datetime.now()
        delta = (release_time - now).total_seconds()
        if delta <= lead_seconds:
            print(f"[Sniper] T-{delta:.1f}s — starting refresh loop.")
            return
        if int(delta) % 10 == 0:
            print(f"[Sniper] Waiting... T-{int(delta)}s to refresh phase.")
        time.sleep(1)


def _scroll_for_lazy_load(page: Page) -> None:
    # Lazada lazy-loads the Buy Now button
    try:
        page.evaluate("window.scrollBy(0, 500)")
        time.sleep(0.2)
        page.evaluate("window.scrollBy(0, 500)")
        time.sleep(0.3)
    except Exception as e:
        print(f"[Sniper] Scroll error: {e}")


def _scroll_scrollable_containers(page: Page, to_bottom: bool = False) -> None:
    # Checkout sometimes scrolls inside a panel, not the window.
    try:
        if to_bottom:
            page.evaluate(
                """() => {
                    for (const el of document.querySelectorAll(
                        '[class*="checkout"], main, [role="main"], [class*="scroll"]'
                    )) {
                        if (el.scrollHeight > el.clientHeight + 40) {
                            el.scrollTop = el.scrollHeight;
                        }
                    }
                }"""
            )
        else:
            page.evaluate(
                """() => {
                    for (const el of document.querySelectorAll(
                        '[class*="checkout"], main, [role="main"], [class*="scroll"]'
                    )) {
                        if (el.scrollHeight > el.clientHeight + 40) {
                            el.scrollTop += Math.round(el.clientHeight * 0.6);
                        }
                    }
                }"""
            )
    except Exception as e:
        print(f"[Sniper] Container scroll error: {e}")


def _scroll_until_visible(page: Page, locator, max_steps: int = 10) -> bool:
    step_px = "Math.max(window.innerHeight * 0.85, 450)"
    for _ in range(max_steps + 1):
        try:
            if locator.count() > 0 and locator.first.is_visible():
                return True
        except Exception:
            pass
        page.evaluate(f"window.scrollBy(0, {step_px})")
        time.sleep(0.25)
    # Final pass — scroll inner containers without jumping to absolute bottom
    _scroll_scrollable_containers(page)
    time.sleep(0.35)
    try:
        return locator.count() > 0 and locator.first.is_visible()
    except Exception:
        return False


def _parse_max_qty(label_text: str) -> int:
    digits = re.findall(r"\d+", label_text or "")
    return int(digits[-1]) if digits else 99


def _page_is_in_stock(page: Page) -> bool:
    """
    Stock check order:
    1. Wait briefly for either Buy Now or OOS to appear.
    2. Buy Now visible + enabled  → definitely IN stock  (return True)
    3. OOS indicator visible      → definitely OOS       (return False)
    4. Neither found              → assume OOS, keep refreshing (return False)
    """
    try:
        # Give the page a moment to render the buttons
        page.wait_for_selector(f"{SEL_BUY_NOW}, {SEL_OOS_INDICATORS}", timeout=3000)
    except Exception:
        pass

    # Step 1 — Buy Now present and clickable = in stock.
    try:
        btn = page.query_selector(SEL_BUY_NOW)
        if btn and btn.is_visible() and btn.is_enabled():
            return True
    except Exception:
        pass

    # Step 2 — explicit OOS signal visible = out of stock.
    try:
        oos = page.query_selector(SEL_OOS_INDICATORS)
        if oos and oos.is_visible():
            return False
    except Exception:
        pass

    # Step 3 — neither found; return False to keep the refresh loop going.
    return False


def _read_quantity(page: Page) -> int:
    input_loc = page.locator(SEL_QUANTITY_INPUT).first
    if input_loc.count() == 0:
        return 1
    try:
        raw = (input_loc.input_value() or "1").strip()
        return max(1, int(raw))
    except (ValueError, PlaywrightTimeout):
        return 1


def _set_quantity(page: Page, target_quantity: int) -> int:
    # Try to set qty to the target allowed; falls back to 1 on any error.
    qty_set = 1
    if target_quantity < 1:
        target_quantity = 1
    try:
        _scroll_for_lazy_load(page)

        max_qty = 99
        max_label = page.locator(SEL_QTY_MAX_LABEL).first
        if max_label.count() > 0:
            try:
                max_qty = _parse_max_qty(max_label.inner_text())
            except Exception:
                pass
        actual_target = min(target_quantity, max_qty)

        input_loc = page.locator(SEL_QUANTITY_INPUT).first
        if input_loc.count() > 0:
            input_loc.wait_for(state="visible", timeout=_ELEMENT_TIMEOUT)
            input_loc.scroll_into_view_if_needed()
            input_loc.click(click_count=3)
            input_loc.fill(str(actual_target))
            input_loc.press("Enter")
            time.sleep(0.25)
            qty_set = _read_quantity(page)
            print(f"[Sniper] Quantity set to {qty_set} via direct input (target {actual_target}).")
        else:
            plus_loc = page.locator(SEL_QTY_PLUS).first
            if plus_loc.count() == 0:
                raise RuntimeError("No quantity input or '+' button found")
            plus_loc.scroll_into_view_if_needed()
            current = _read_quantity(page)
            for _ in range(actual_target - current):
                if not plus_loc.is_enabled():
                    break
                plus_loc.click()
                time.sleep(0.08)
            qty_set = _read_quantity(page)
            print(f"[Sniper] Quantity incremented to {qty_set} via '+' (target {actual_target}).")

        if qty_set < actual_target:
            print(f"[Sniper] Warning — requested {actual_target} but page shows {qty_set}.")
    except Exception as exc:
        print(f"[Sniper] Could not set quantity ({exc}) — using qty=1.")
    return qty_set


def _dismiss_overlays(page: Page) -> None:
    """Dismiss any popups, modals, or overlays that might block buttons."""
    overlay_selectors = [
        ".modal-close, .popup-close, [class*='close-btn']",
        "button:has-text('Close'), button:has-text('×'), button:has-text('✕')",
        "[class*='overlay'] button, [class*='modal'] button",
        ".next-dialog-close, .next-overlay-backdrop",
    ]
    
    for selector in overlay_selectors:
        try:
            overlay = page.locator(selector).first
            if overlay.count() > 0 and overlay.is_visible():
                print(f"[Sniper] Dismissing overlay: {selector}")
                overlay.click(timeout=2000)
                time.sleep(0.5)
        except Exception:
            pass


def _click_place_order(page: Page, max_retries: int = 3) -> None:
    """Click Place Order button with comprehensive debug logging and retry logic."""
    
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                print(f"[Sniper] Place Order click attempt {attempt + 1}/{max_retries}")
                time.sleep(2)
                page.wait_for_load_state("networkidle", timeout=5000)
            
            print("[Sniper] === DEBUG: Place Order Button Detection ===")
            print(f"[Sniper] Current URL: {page.url}")
            
            # Log all buttons on page for debugging
            try:
                all_buttons = page.locator("button").all()
                print(f"[Sniper] Total buttons found on page: {len(all_buttons)}")
                for i, btn in enumerate(all_buttons[:10]):  # First 10 buttons
                    try:
                        text = btn.inner_text()[:50] if btn.inner_text() else ""
                        classes = btn.get_attribute("class") or ""
                        visible = btn.is_visible()
                        enabled = btn.is_enabled()
                        print(f"[Sniper]   Button {i+1}: '{text}' | visible={visible} | enabled={enabled} | class={classes[:50]}")
                    except Exception:
                        pass
            except Exception as e:
                print(f"[Sniper] Could not enumerate buttons: {e}")
            
            # Try multiple candidate strategies
            candidates = [
                ("Exact Text 'Place Order Now'", page.locator("button:has-text('Place Order Now'), button:has-text('PLACE ORDER NOW'), button:has-text('place order now')")),
                ("Role-based", page.get_by_role("button", name=re.compile(r"(place\s*order|proceed\s*to\s*pay|pay\s*now|pay|checkout|submit|confirm)", re.I))),
                ("CSS Selector", page.locator(SEL_PLACE_ORDER)),
                ("Text Contains 'pay'", page.locator("button:has-text('pay'), button:has-text('Pay'), button:has-text('PAY')")),
                ("Submit Type", page.locator("button[type='submit']")),
            ]
            
            last_error: Exception | None = None
            
            for strategy_name, candidate in candidates:
                print(f"[Sniper] Trying strategy: {strategy_name}")
                count = candidate.count()
                print(f"[Sniper]   Found {count} matches")
                
                if count == 0:
                    continue
                    
                # Try each match
                for i in range(count):
                    try:
                        btn = candidate.nth(i)
                        text = btn.inner_text()[:50] if btn.count() > 0 else "N/A"
                        visible = btn.is_visible() if btn.count() > 0 else False
                        enabled = btn.is_enabled() if btn.count() > 0 else False
                        
                        print(f"[Sniper]   Match {i+1}: '{text}' | visible={visible} | enabled={enabled}")
                        
                        if not visible:
                            print(f"[Sniper]   Attempting to scroll into view...")
                            if not _scroll_until_visible(page, candidate.nth(i)):
                                print(f"[Sniper]   Still not visible after scrolling")
                                continue
                        
                        btn.scroll_into_view_if_needed()
                        time.sleep(0.5)
                        
                        try:
                            print(f"[Sniper]   Attempting normal click...")
                            btn.click(timeout=_ELEMENT_TIMEOUT)
                            print(f"[Sniper] ✓ Place Order clicked successfully using {strategy_name}")
                            return
                        except Exception as exc:
                            print(f"[Sniper]   Normal click failed: {exc}")
                            last_error = exc
                            try:
                                print(f"[Sniper]   Attempting force click...")
                                btn.click(force=True, timeout=_ELEMENT_TIMEOUT)
                                print(f"[Sniper] ✓ Place Order clicked (force) using {strategy_name}")
                                return
                            except Exception as force_exc:
                                print(f"[Sniper]   Force click failed: {force_exc}")
                                last_error = force_exc
                                
                    except Exception as e:
                        print(f"[Sniper]   Error processing match {i+1}: {e}")
                        last_error = e
            
            # If we get here, this attempt failed
            print(f"[Sniper] === Attempt {attempt + 1} failed - all strategies unsuccessful ===")
            if attempt < max_retries - 1:
                print(f"[Sniper] Retrying in 2 seconds...")
            else:
                # Final attempt failed
                if last_error:
                    raise last_error
                raise PlaywrightTimeout("Place Order button not found or not clickable after trying all strategies")
                
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"[Sniper] Attempt {attempt + 1} crashed: {e}. Retrying...")
                continue
            else:
                raise


def _handle_checkout(page: Page) -> str:
    # Skip all checks and go straight to Place Order button
    print("[Sniper] On checkout page, proceeding directly to Place Order...")
    
    # Check if page/context is still alive before proceeding
    try:
        if page.is_closed():
            return "ERROR: Page was closed before checkout could complete."
    except Exception as e:
        return f"ERROR: Cannot access page state: {e}"
    
    # Maximize viewport so the Place Order button is visible without scrolling
    print("[Sniper] Maximizing viewport to reveal Place Order button...")
    try:
        page.set_viewport_size({"width": 1920, "height": 1080})
        time.sleep(0.5)
    except Exception as e:
        print(f"[Sniper] Viewport resize failed (non-critical): {e}")
    
    # Minimal wait - just ensure basic DOM is loaded
    print(f"[Sniper] Current URL: {page.url}")
    try:
        page.wait_for_load_state("domcontentloaded", timeout=5000)
        time.sleep(1.0)  # Longer pause for dynamic content to render
    except Exception as e:
        print(f"[Sniper] Load state wait failed (non-critical): {e}")

    # Single moderate scroll to bring sticky Place Order footer into view
    print("[Sniper] Scrolling slightly to reveal Place Order button...")
    try:
        page.evaluate("window.scrollBy(0, 500)")
        time.sleep(0.3)
    except Exception as e:
        print(f"[Sniper] Scroll error (non-critical): {e}")

    # # Default address is pre-selected by Lazada; just verify it's visible.
    # print("[Sniper] Checking for address element...")
    # try:
    #     # Check if page is still alive before waiting for selector
    #     if page.is_closed():
    #         return "ERROR: Page closed while waiting for address element."
    #
    #     page.wait_for_selector(SEL_CHECKOUT_ADDR, timeout=_ELEMENT_TIMEOUT)
    #     print("[Sniper] Default address confirmed.")
    # except PlaywrightTimeout:
    #     print("[Sniper] Warning — address selector not found, proceeding anyway.")
    # except Exception as e:
    #     print(f"[Sniper] Address check failed: {e}")
    #     # Don't abort, continue to payment selection

    # # Select Credit/Debit Card payment.
    # try:
    #     card = page.wait_for_selector(SEL_PAYMENT_CARD, timeout=_ELEMENT_TIMEOUT)
    #     if card:
    #         card.click()
    #         print("[Sniper] Card payment selected.")
    #         time.sleep(_POST_CLICK_DELAY)
    # except PlaywrightTimeout:
    #     print("[Sniper] Warning — card selector not found (may already be selected).")

    # # Dismiss any overlays before clicking Place Order
    # print("[Sniper] Checking for overlays...")
    # _dismiss_overlays(page)

    # Click Place Order (sticky footer — must scroll into view before click).
    try:
        print("[Sniper] Scrolling down to find Place Order button...")
        _click_place_order(page)
        time.sleep(_POST_CLICK_DELAY * 2)
    except PlaywrightTimeout:
        print("[Sniper] ERROR: Place Order button not found — keeping browser open for manual intervention.")
        input("\n>>> Press ENTER to close the browser and continue... <<<\n")
        return "ERROR: Place Order button not found — order NOT placed."
    except Exception as exc:
        print(f"[Sniper] ERROR: Place Order click failed ({exc}) — keeping browser open for manual intervention.")
        input("\n>>> Press ENTER to close the browser and continue... <<<\n")
        return f"ERROR: Place Order click failed ({exc}) — order NOT placed."

    # Wait for order confirmation redirect.
    try:
        page.wait_for_url("**/order/**", timeout=_NAVIGATION_TIMEOUT)
        print("[Sniper] Order confirmation page reached.")
        return "SUCCESS: Order placed."
    except PlaywrightTimeout:
        return f"LIKELY_SUCCESS: Final URL = {page.url}"


# --- Main entry point ---

def buy_item(
    page: Page,
    target_url: str,
    release_time: datetime | None = None,
    refresh_lead_seconds: int = 5,
    target_quantity: int = 1,
    test_refresh_duration: int = 0,
) -> str:
    """
    Lazada sniper entry point.
    page                 — Playwright Page (launched by bot_logic)
    target_url           — direct product page URL
    release_time         — scheduled drop time; None = attempt immediately
    refresh_lead_seconds — seconds before release_time to begin refreshing
    """
    print("[Sniper] === Lazada Sniper Module ===")
    print(f"[Sniper] Target: {target_url}")

    # part 1 — safety check: abort if release time has already passed
    if release_time:
        now = datetime.now()
        total_wait = (release_time - now).total_seconds()
        if total_wait < 0:
            msg = (
                f"ERROR: Release time {release_time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"has already passed by {abs(total_wait):.0f}s. Aborting."
            )
            print(f"[Sniper] {msg}")
            return msg

    # part 2 — open product page
    print("[Sniper] Opening product page...")
    page.goto(target_url, wait_until="domcontentloaded", timeout=_NAVIGATION_TIMEOUT)
    _scroll_for_lazy_load(page)

    # part 3 — pre-release countdown (skip if no release_time set)
    if release_time:
        now = datetime.now()
        total_wait = (release_time - now).total_seconds()
        if total_wait > refresh_lead_seconds:
            print(f"[Sniper] Release at {release_time} — idling {total_wait - refresh_lead_seconds:.0f}s then refreshing.")
            _wait_until_near_release(release_time, refresh_lead_seconds)
        else:
            print(f"[Sniper] Already within lead window ({total_wait:.1f}s) — refreshing now.")

    # part 4 — refresh until in stock (capped at MAX_REFRESH_ATTEMPTS)
    print("[Sniper] Polling stock (refreshing until OOS clears)...")
    attempt = 0
    test_refresh_end_time = datetime.now().timestamp() + test_refresh_duration if test_refresh_duration > 0 else 0

    while True:
        attempt += 1
        if attempt > MAX_REFRESH_ATTEMPTS:
            return f"ERROR: Gave up after {MAX_REFRESH_ATTEMPTS} refresh attempts — item still OOS."
        
        in_stock = _page_is_in_stock(page)
        
        if in_stock:
            if datetime.now().timestamp() < test_refresh_end_time:
                print(f"[Sniper] IN STOCK but test_refresh_duration active. #{attempt} — refreshing...")
                page.reload(wait_until="domcontentloaded", timeout=_NAVIGATION_TIMEOUT)
                _scroll_for_lazy_load(page)
                time.sleep(_RETRY_DELAY)
                continue
            else:
                print(f"[Sniper] IN STOCK on attempt #{attempt}!")
                break
                
        print(f"[Sniper] #{attempt} — still OOS, refreshing...")
        page.reload(wait_until="domcontentloaded", timeout=_NAVIGATION_TIMEOUT)
        _scroll_for_lazy_load(page)
        time.sleep(_RETRY_DELAY)

    # part 5 — set quantity
    qty = _set_quantity(page, target_quantity)
    print(f"[Sniper] Qty: {qty}")

    # part 6 — click Buy Now
    try:
        print("[Sniper] Clicking Buy Now...")
        buy_btn = page.wait_for_selector(SEL_BUY_NOW, timeout=_ELEMENT_TIMEOUT)
        # pyrefly: ignore [missing-attribute]
        # Scroll the button into view in case it's still off-screen.
        buy_btn.scroll_into_view_if_needed()
        time.sleep(0.3)
        
        # Set up listener for popup/new page (Lazada might open checkout in new tab)
        context = page.context
        popup_page = None
        
        def handle_popup(popup):
            nonlocal popup_page
            popup_page = popup
            print(f"[Sniper] Detected popup/new page: {popup.url}")
        
        context.on("page", handle_popup)
        
        # pyrefly: ignore [missing-attribute]
        buy_btn.click()
        print("[Sniper] Buy Now clicked, waiting for navigation...")
        time.sleep(_POST_CLICK_DELAY)
        
        # Check if checkout opened in a new page/popup
        if popup_page:
            print("[Sniper] Checkout opened in new tab/popup, switching to it...")
            popup_page.wait_for_load_state("domcontentloaded", timeout=_NAVIGATION_TIMEOUT)
            page = popup_page  # Use the popup page for checkout
        
        # Verify page is still alive after Buy Now click
        try:
            if page.is_closed():
                return "ERROR: Page closed immediately after clicking Buy Now."
        except Exception as e:
            return f"ERROR: Cannot verify page state after Buy Now: {e}"
            
    except PlaywrightTimeout:
        return "ERROR: Buy Now button not found — aborted."
    except Exception as e:
        return f"ERROR: Failed to click Buy Now button: {e}"

    # part 7 — complete checkout
    print("[Sniper] Proceeding to checkout...")
    try:
        result = _handle_checkout(page)
        print(f"[Sniper] Result: {result}")
        return result
    except Exception as e:
        return f"ERROR: Checkout handler crashed: {e}"
