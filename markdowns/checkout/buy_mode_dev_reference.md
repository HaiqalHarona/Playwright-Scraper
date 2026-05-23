# Mode: `buy` — Developer Reference

> **Action value**: `ACTION=buy`
> **Call chain**: `main.py` → `bot_logic.start_browser_and_route()` → `lazada_site_buy.buy_item()`

---

## 1. Entry — `main.py`

### `load_env()`
Parses `.env` line-by-line and writes every `KEY=VALUE` into `os.environ`.  
Comments (`#`) and blank lines are skipped.

### `parse_accounts(require_url=True)`
Regex-scans `os.environ` for `ACCOUNT_<N>_(URL|EMAIL|PASSWORD)`.  
In buy mode `require_url=True`, so only accounts that have a `url` field are included.  
Returns a `dict[int, dict]` sorted by account index.

```python
{
  1: {"url": "https://www.lazada.sg/products/...", "email": "a@b.com", "password": "secret"},
  2: {"url": "https://www.lazada.sg/products/...", "email": "c@d.com", "password": "secret2"},
}
```

### `main()`
Key buy-specific behaviour:
- `parse_accounts(require_url=True)` — each account must have its own `ACCOUNT_N_URL`.
- Falls back to `STORE_URL_1` → `STORE_URL` when no accounts configured.
- `RELEASE_TIME` is parsed — accepts ISO datetime string or `"test"` (2 mins from now).
- One `threading.Thread` per account, each calling `start_browser_and_route(action="buy", ...)`.
- All threads joined; a summary table printed with per-account result strings.

---

## 2. Router — `bot_logic.py`

### `start_browser_and_route()` — Signature

```python
def start_browser_and_route(
    store_name: str,                    # "Lazada"
    action: str,                        # "buy"
    target_url: str,                    # direct product page URL
    release_time: datetime | None,      # scheduled drop time; None = immediate
    refresh_lead_seconds: int = 5,      # seconds before release to start refreshing
    target_quantity: int = 1,           # units to purchase
    test_refresh_duration: int = 0,     # keep refreshing even in-stock for N seconds
    email: str = "",                    # auto-login credential
    password: str = "",
) -> str
```

### Playwright setup for `buy`

```python
headless_mode = False   # buy is always headful (user-visible)

with Stealth().use_sync(sync_playwright()) as p:
    browser = p.chromium.launch(
        headless=False,
        slow_mo=0,
        channel="chrome"        # use installed Google Chrome binary
    )
    context = browser.new_context()   # or new_context(proxy=...) if PROXY_URL set
    page = context.new_page()
    # No page.route() — full render needed for checkout
```

### Session check & login

```python
page.goto("https://www.lazada.sg", wait_until="domcontentloaded", timeout=30_000)
```
> The homepage is loaded first so that session cookies are readable from the correct domain.

```python
if not _is_lazada_logged_in(context, page):
    _handle_login(page, context, email, password)
else:
    print("[Traffic Cop] Active session found — proceeding.")
```

#### `_is_lazada_logged_in(context, page) -> bool`
1. `context.cookies()` — checks for any cookie named `_lzd_stoken`, `login_cookie`, or `lzd_uid`.
2. DOM fallback: `page.locator("#myAccountTrigger, .my-account-trigger, a[href*='/customer/account']").is_visible()`.

#### `_handle_login(page, context, email, password) -> None`

**Step 1 — Navigate to login page**
```python
page.goto("https://member.lazada.sg/user/login", wait_until="domcontentloaded", timeout=30_000)
```

**Step 2 — Auto-fill** (only if valid credentials; rejects `"your_email"` / `"your_password"` placeholders)

| Field | Selectors tried (in order) |
|---|---|
| Email/Phone | `input[name='fm-login-id']`, `input[placeholder*='Phone Number or Email']`, `input[placeholder*='phone or email']`, `input[placeholder*='Email']`, `.mod-login-input-loginName input`, `input[type='text']` |
| Password | `input[name='fm-login-password']`, `input[type='password']`, `input[placeholder*='Password']`, `.mod-login-input-password input` |
| Submit | `button[type='submit']`, `button:has-text('LOGIN')`, `button:has-text('Login')`, `.mod-login-btn button` |

```python
user_el.click()
user_el.fill("")
user_el.type(email, delay=60)    # human-like typing, ~60ms per character

pass_el.click()
pass_el.fill("")
pass_el.type(password, delay=60)
```

**Step 3 — CAPTCHA check** (before submit)
Checks for `#nc_1_n1z`, `.nc_scale`, `.next-slider`, `[class*='slider']`, `[class*='nc-container']`.
If found, **abort auto-submit** and warn operator.

**Step 4 — Verify session** (up to 6 seconds)
```python
for _ in range(6):
    time.sleep(1)
    if _is_lazada_logged_in(context, page):
        return  # success
```

**Step 5 — Manual fallback** (blocking loop)
```python
while True:
    if _is_lazada_logged_in(context, page):
        break
    time.sleep(2)
```
Operator must complete login manually in the visible browser window.

### Buy route dispatch

```python
result = buy_item(
    page=page,
    target_url=target_url,
    release_time=release_time,
    refresh_lead_seconds=refresh_lead_seconds,
    target_quantity=target_quantity,
    test_refresh_duration=test_refresh_duration,
)
```

---

## 3. `buy_item()` — `stores/checkout/lazada_site_buy.py`

```python
def buy_item(
    page: Page,
    target_url: str,
    release_time: datetime | None = None,
    refresh_lead_seconds: int = 5,
    target_quantity: int = 1,
    test_refresh_duration: int = 0,
) -> str
```

Executes in **7 sequential parts**.

---

### Part 1 — Safety check
```python
if release_time and (release_time - datetime.now()).total_seconds() < 0:
    return "ERROR: Release time has already passed by Xs. Aborting."
```

---

### Part 2 — Open product page
```python
page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
_scroll_for_lazy_load(page)
# → page.evaluate("window.scrollBy(0, 500)") × 2 with short sleeps
```

---

### Part 3 — Pre-release countdown
Only entered if `release_time` is set and time remaining > `refresh_lead_seconds`.

```python
def _wait_until_near_release(release_time: datetime, lead_seconds: int) -> None:
    while True:
        delta = (release_time - datetime.now()).total_seconds()
        if delta <= lead_seconds:
            return
        if int(delta) % 10 == 0:
            print(f"[Sniper] Waiting... T-{int(delta)}s to refresh phase.")
        time.sleep(1)
```

---

### Part 4 — Stock-poll refresh loop

```python
MAX_REFRESH_ATTEMPTS = 300
_RETRY_DELAY = 0.4            # seconds between attempts

while True:
    attempt += 1
    if attempt > MAX_REFRESH_ATTEMPTS:
        return f"ERROR: Gave up after {MAX_REFRESH_ATTEMPTS} refresh attempts."

    in_stock = _page_is_in_stock(page)

    if in_stock:
        # Honour test_refresh_duration if set
        if datetime.now().timestamp() < test_refresh_end_time:
            page.reload(wait_until="domcontentloaded", timeout=60_000)
            continue
        break

    page.reload(wait_until="domcontentloaded", timeout=60_000)
    _scroll_for_lazy_load(page)
    time.sleep(_RETRY_DELAY)
```

#### `_page_is_in_stock(page) -> bool`

```python
# 1. Wait briefly for either signal
page.wait_for_selector(f"{SEL_BUY_NOW}, {SEL_OOS_INDICATORS}", timeout=3000)

# 2. Buy Now visible + enabled → IN STOCK
btn = page.query_selector(SEL_BUY_NOW)
if btn and btn.is_visible() and btn.is_enabled():
    return True

# 3. OOS indicator visible → OUT OF STOCK
oos = page.query_selector(SEL_OOS_INDICATORS)
if oos and oos.is_visible():
    return False

# 4. Neither found → assume OOS, keep refreshing
return False
```

Key selectors:

| Constant | Value |
|---|---|
| `SEL_BUY_NOW` | `button[data-spm='d_buynow'], .btn-buynow, [class*='buynow'], button:has-text('Buy Now'), button:has-text('BUY NOW')` |
| `SEL_OOS_INDICATORS` | `button[disabled][class*='buy'], [class*='soldOut'], [class*='sold-out'], span:has-text('Out of Stock'), span:has-text('Sold Out')` |

---

### Part 5 — Set quantity

```python
qty = _set_quantity(page, target_quantity)
```

`_set_quantity()` reads the max-qty label first:
```python
max_label = page.locator("[class*='quantity-max'], [class*='maxQty'], [class*='Quantity-max']").first
max_qty = _parse_max_qty(max_label.inner_text())  # re.findall(r"\d+", text)
actual_target = min(target_quantity, max_qty)
```

**Primary path — direct text input:**
```python
input_loc = page.locator(SEL_QUANTITY_INPUT).first
# SEL_QUANTITY_INPUT: "input[data-spm='quantity'], input[aria-label*='uantity'],
#   .pdp-mod-product-info-quantity input, .qty-input input, ..."

input_loc.wait_for(state="visible", timeout=30_000)
input_loc.scroll_into_view_if_needed()
input_loc.click(click_count=3)           # select-all
input_loc.fill(str(actual_target))
input_loc.press("Enter")
```

**Fallback — `+` button clicks:**
```python
plus_loc = page.locator(SEL_QTY_PLUS).first
# SEL_QTY_PLUS: "button[data-spm='quantity_increase'],
#   button.pdp-mod-product-info-quantity-plus, ..."

plus_loc.scroll_into_view_if_needed()
for _ in range(actual_target - current):
    if not plus_loc.is_enabled():
        break
    plus_loc.click()
    time.sleep(0.08)
```

---

### Part 6 — Click Buy Now

```python
_ELEMENT_TIMEOUT = 30_000   # ms

buy_btn = page.wait_for_selector(SEL_BUY_NOW, timeout=30_000)
buy_btn.scroll_into_view_if_needed()

# Register new-tab listener BEFORE clicking
context.on("page", handle_popup)
buy_btn.click()
time.sleep(1.5)   # _POST_CLICK_DELAY

# If checkout opened in a new tab, switch to it
if popup_page:
    popup_page.wait_for_load_state("domcontentloaded", timeout=60_000)
    page = popup_page
```

---

### Part 7 — Complete checkout via `_handle_checkout(page)`

```python
def _handle_checkout(page: Page) -> str
```

Steps:
```python
# 1. Expand viewport to reveal sticky Place Order footer
page.set_viewport_size({"width": 1920, "height": 1080})

# 2. Wait for DOM
page.wait_for_load_state("domcontentloaded", timeout=5000)

# 3. Scroll into footer
page.evaluate("window.scrollBy(0, 500)")

# 4. Click Place Order
_click_place_order(page)

# 5. Wait for order confirmation redirect
page.wait_for_url("**/order/**", timeout=60_000)
```

Returns:
- `"SUCCESS: Order placed."` — URL matched `**/order/**`
- `"LIKELY_SUCCESS: Final URL = ..."` — `wait_for_url` timed out
- `"ERROR: Place Order button not found — order NOT placed."`
- `"ERROR: Place Order click failed (exc) — order NOT placed."`

#### `_click_place_order()` — 5-strategy cascade (3 retries)

| Priority | Strategy | Playwright call |
|---|---|---|
| 1 | Exact text | `page.locator("button:has-text('Place Order Now'), ...")` |
| 2 | ARIA role + regex | `page.get_by_role("button", name=re.compile(r"(place\s*order\|proceed...)", re.I))` |
| 3 | CSS selector bank | `page.locator(SEL_PLACE_ORDER)` |
| 4 | Text "pay" | `page.locator("button:has-text('pay'), ...")` |
| 5 | Submit type | `page.locator("button[type='submit']")` |

For each match: normal click → force click on failure:
```python
btn.click(timeout=30_000)
# on exception:
btn.click(force=True, timeout=30_000)
```

---

## 4. Module-level Constants (`lazada_site_buy.py`)

| Constant | Value | Purpose |
|---|---|---|
| `_NAVIGATION_TIMEOUT` | `60_000` ms | `page.goto()`, `page.wait_for_url()` |
| `_ELEMENT_TIMEOUT` | `30_000` ms | `wait_for_selector()`, `btn.click()` |
| `_RETRY_DELAY` | `0.4` s | Between stock-poll refresh attempts |
| `_POST_CLICK_DELAY` | `1.5` s | Breathing room after major clicks |
| `MAX_REFRESH_ATTEMPTS` | `300` | Safety cap on the stock-poll loop |

---

## 5. Environment Variables (buy mode)

| Variable | Default | Description |
|---|---|---|
| `STORE_NAME` | `"Lazada"` | Target store |
| `ACTION` | `"buy"` | Must be `"buy"` |
| `ACCOUNT_<N>_URL` | — | Per-account product page URL |
| `ACCOUNT_<N>_EMAIL` | — | Per-account login email |
| `ACCOUNT_<N>_PASSWORD` | — | Per-account login password |
| `STORE_URL_1` | — | Fallback URL (single account mode) |
| `TARGET_QUANTITY` | `1` | Units to add to cart |
| `RELEASE_TIME` | `""` | ISO datetime or `"test"` (2 mins from now) |
| `REFRESH_LEAD_SECONDS` | `5` | Seconds before release to begin refreshing |
| `TEST_REFRESH_DURATION` | `0` | Keep refreshing even in-stock for N seconds |
| `PROXY_URL` | `""` | Optional proxy server |

---

## 6. Buy Mode Call Graph

```
main()
 └─ start_browser_and_route(action="buy")
       ├─ p.chromium.launch(headless=False, channel="chrome")
       ├─ page.goto("https://www.lazada.sg")
       ├─ _is_lazada_logged_in()
       │     ├─ context.cookies()
       │     └─ page.locator(...).is_visible()
       ├─ _handle_login()  [if not logged in]
       │     ├─ page.goto("https://member.lazada.sg/user/login")
       │     ├─ user_el.type(email, delay=60)
       │     ├─ pass_el.type(password, delay=60)
       │     └─ blocking loop → _is_lazada_logged_in()
       └─ buy_item(page, target_url, ...)
             ├─ page.goto(target_url)            Part 2
             ├─ _wait_until_near_release()        Part 3
             ├─ [refresh loop]                   Part 4
             │     ├─ _page_is_in_stock()
             │     │     ├─ page.wait_for_selector()
             │     │     └─ page.query_selector()
             │     └─ page.reload()
             ├─ _set_quantity()                  Part 5
             │     ├─ input_loc.fill()
             │     └─ plus_loc.click() [fallback]
             ├─ buy_btn.click()                  Part 6
             └─ _handle_checkout()               Part 7
                   ├─ page.set_viewport_size()
                   ├─ _click_place_order()
                   │     └─ btn.click() / btn.click(force=True)
                   └─ page.wait_for_url("**/order/**")
```
