# Mode: `buy_scrape` — Developer Reference

> **Action value**: `ACTION=buy_scrape`
> **Call chain**: `main.py` → `bot_logic.start_browser_and_route()` → `site_lazada.scrape_item_data()` → `lazada_site_buy.buy_item()` × N
>
> `buy_scrape` is a **combined pipeline**. A single browser session first scrapes
> a search/category page for in-stock products, logs in, then purchases every
> in-stock item sequentially — all without opening a new browser window.

---

## 1. Entry — `main.py`

### `load_env()`
Parses `.env` line-by-line and writes every `KEY=VALUE` into `os.environ`.
Comments (`#`) and blank lines are skipped.

### `parse_accounts(require_url=False)`

In `buy_scrape` mode the `main()` function calls:
```python
accounts = parse_accounts(require_url=False)
```

`require_url=False` means accounts only need an **email** to be valid.
The target URL is **shared** across all accounts and comes from `SCRAPER_TARGET_URL`
(not from per-account `ACCOUNT_N_URL` fields).

```python
# Inside main() — buy_scrape URL resolution per thread
if action == "buy_scrape":
    target_url = os.getenv("SCRAPER_TARGET_URL", config.get("url", ""))
```

Returns a `dict[int, dict]` sorted by account index:
```python
{
  1: {"email": "a@b.com", "password": "secret", "url": ""},
  2: {"email": "c@d.com", "password": "secret2", "url": ""},
}
```

### `main()`
- One `threading.Thread` per account, each calling `start_browser_and_route(action="buy_scrape", ...)`.
- All threads use the **same** `SCRAPER_TARGET_URL` but run with independent Playwright browser instances.
- All threads are joined before the summary table is printed.

---

## 2. Router — `bot_logic.py`

### `start_browser_and_route()` — Signature

```python
def start_browser_and_route(
    store_name: str,                    # "Lazada"
    action: str,                        # "buy_scrape"
    target_url: str,                    # SCRAPER_TARGET_URL (search/category page)
    release_time: datetime | None,      # not used in buy_scrape (forced None in Phase 3)
    refresh_lead_seconds: int = 5,      # not used in buy_scrape
    target_quantity: int = 1,           # units to purchase per product
    test_refresh_duration: int = 0,     # not used in buy_scrape
    email: str = "",                    # per-account login email
    password: str = "",                 # per-account login password
) -> str
```

> **Note**: `release_time`, `refresh_lead_seconds`, and `test_refresh_duration` are
> accepted but **not forwarded** to `buy_item()` in this mode. Each purchase is
> triggered immediately after stock is confirmed by the scraper.

### Playwright setup for `buy_scrape`

```python
headless_mode = False   # buy_scrape is headful — user can intervene during login/checkout

with Stealth().use_sync(sync_playwright()) as p:
    browser = p.chromium.launch(
        headless=False,
        slow_mo=0,
        channel="chrome"        # use installed Google Chrome binary
    )
    context = browser.new_context()   # or new_context(proxy=...) if PROXY_URL set
    page = context.new_page()
    # No page.route() — full render needed for checkout phases
```

> The same `page` object is **reused across all three phases** — scrape, login, and purchase.

---

## 3. Phase 1 — Scrape (`scrape_item_data`)

```python
print("[Traffic Cop]  BUY_SCRAPE: Phase 1 — Scraping products")

continuous = os.getenv("SCRAPER_CONTINUOUS_MODE", "false").lower() == "true"
retry_interval = int(os.getenv("SCRAPER_LOOP_INTERVAL", "60"))

scrape_attempt = 0
in_stock = []

while True:
    scrape_attempt += 1
    scraped_products = scrape_item_data(page, target_url)
    in_stock = [p for p in scraped_products if not p.get('is_out_of_stock', True)]

    if in_stock:
        break   # proceed to Phase 2

    if not continuous:
        return "FAILED: No in-stock products found matching your criteria."

    # Continuous retry — reload and wait before next attempt
    page.reload(wait_until="domcontentloaded", timeout=30_000)
    time.sleep(retry_interval)
```

> **`SCRAPER_CONTINUOUS_MODE=false` (default)**: if no in-stock products found on the
> first scrape → immediately return failure. No retries.
>
> **`SCRAPER_CONTINUOUS_MODE=true`**: reload the page and retry every
> `SCRAPER_LOOP_INTERVAL` seconds until at least one in-stock product is found.

### `scrape_item_data(page, url, config=None) -> list[dict]`

Full scraping engine from `stores/scraper/site_lazada.py`. In `buy_scrape` mode it
is called directly (bypassing `run_lazada()`). `config` is auto-loaded from env.

#### Stage 1 — Navigate & paginate

```python
page.goto(url, wait_until="domcontentloaded")
page.wait_for_timeout(3000)   # 3s DOM-settle

# Per listing page:
for i in range(scroll_count):                          # SCRAPER_SCROLL_COUNT (default 5)
    page.evaluate("window.scrollBy(0, window.innerHeight)")
    page.wait_for_timeout(500)
page.evaluate("window.scrollTo(0, 0)")

# Advance to next page:
next_btn = page.query_selector("li.ant-pagination-next")
btn = next_btn.query_selector("button")
btn.click()
page.wait_for_timeout(3000)
```

Stops when `ant-pagination-disabled` class found, no next button, or `SCRAPER_MAX_PAGES` reached.

#### Stage 2 — Find product cards

`_find_product_cards(page)` tries 4 selectors in order:

| Priority | Selector |
|---|---|
| 1 | `[data-qa-locator='product-item']` |
| 2 | `.Bm3ON` |
| 3 | `div[data-tracking='product-card']` |
| 4 | `a[href*='/products/']` |

Per card, `_extract_grid_data()` extracts name, price, link, image using:
```python
card.query_selector(selector)
element.inner_text()
element.get_attribute("href")
```

#### Stage 3 — Deduplication
URLs tracked in a `set`; duplicate product links discarded.

#### Stage 4 — Name filter (optional)
If `SCRAPER_PRODUCT_NAMES` set → case-insensitive substring match per product name.

#### Stage 5 — Deep stock check per product

```python
page.goto(product["link"], wait_until="domcontentloaded", timeout=15000)
page_text_lower = page.inner_text("body").lower()
```

Stock detection:
1. Text check: `"sold out"` or `"out of stock"` in body text.
2. Button check: `page.query_selector("button:has-text('Add to Cart')")` — OOS if `disabled` in class.

CAPTCHA detection:
```python
if page.query_selector("#nc_1_n1z") or "verification" in page.url:
    page.wait_for_timeout(5000)
    page.reload()
```

#### Stage 6 — Save JSON
Writes results to:
- `data/scrapes/run_logs/lazada_scrape-<DD-MM-YYYY_HH-MM>.json`
- `data/scrapes/in_stock/lazada_in_stock-<DD-MM-YYYY_HH-MM>.json`

**Returns** `list[dict]`:
```python
{
  "index": int,
  "name": str,              # ≤200 chars
  "price": str,
  "link": str,              # absolute HTTPS URL — used as target_url in Phase 3
  "image": str,
  "is_out_of_stock": bool
}
```

---

## 4. Phase 2 — Login

```python
print("[Traffic Cop]  BUY_SCRAPE: Phase 2 — Login")

page.goto("https://www.lazada.sg", wait_until="domcontentloaded", timeout=30_000)

if not _is_lazada_logged_in(context, page):
    _handle_login(page, context, email, password)
else:
    print("[Traffic Cop] Active session found — proceeding.")
```

> The same `page` that was used for scraping is reused here. After loading the
> Lazada homepage the session cookies become readable and `_is_lazada_logged_in()`
> can confirm authentication state.

### `_is_lazada_logged_in(context, page) -> bool`

```python
# 1. Cookie check
cookies = context.cookies()
session_cookies = {"_lzd_stoken", "login_cookie", "lzd_uid"}
if any(c["name"] in session_cookies for c in cookies):
    return True

# 2. DOM fallback
page.locator("#myAccountTrigger, .my-account-trigger, a[href*='/customer/account']").is_visible()
```

### `_handle_login(page, context, email, password) -> None`

**Step 1 — Navigate to login page**
```python
page.goto("https://member.lazada.sg/user/login", wait_until="domcontentloaded", timeout=30_000)
```

**Step 2 — Auto-fill credentials**

| Field | Selectors tried (in order) |
|---|---|
| Email | `input[name='fm-login-id']`, `input[placeholder*='Phone Number or Email']`, `input[placeholder*='phone or email']`, `input[placeholder*='Email']`, `.mod-login-input-loginName input`, `input[type='text']` |
| Password | `input[name='fm-login-password']`, `input[type='password']`, `input[placeholder*='Password']`, `.mod-login-input-password input` |
| Submit | `button[type='submit']`, `button:has-text('LOGIN')`, `button:has-text('Login')`, `.mod-login-btn button` |

```python
user_el.click()
user_el.fill("")
user_el.type(email, delay=60)    # ~60ms/char simulating human typing

pass_el.click()
pass_el.fill("")
pass_el.type(password, delay=60)
```

**Step 3 — CAPTCHA guard**
Checks `#nc_1_n1z`, `.nc_scale`, `.next-slider`, `[class*='slider']`, `[class*='nc-container']`.
If found → skip submit, warn operator.

**Step 4 — Session verify loop** (up to 6s)
```python
for _ in range(6):
    time.sleep(1)
    if _is_lazada_logged_in(context, page):
        return
```

**Step 5 — Manual fallback** (blocking)
```python
while True:
    if _is_lazada_logged_in(context, page):
        break
    time.sleep(2)
```

---

## 5. Phase 3 — Purchase Loop

```python
print("[Traffic Cop]  BUY_SCRAPE: Phase 3 — Purchasing")

buy_results = []
for i, product in enumerate(in_stock, 1):
    print(f"[Traffic Cop] >>> Buying product {i}/{len(in_stock)}: {product['name'][:60]}")
    try:
        buy_result = buy_item(
            page=page,
            target_url=product['link'],       # URL from scraper output
            release_time=None,                # no countdown — buy immediately
            refresh_lead_seconds=0,           # no lead time
            target_quantity=target_quantity,  # TARGET_QUANTITY from env
            test_refresh_duration=0,          # no test mode
        )
        buy_results.append(buy_result)
    except Exception as e:
        buy_results.append(f"ERROR: buy_item crashed on '{product['name'][:40]}': {e}")

successes = [r for r in buy_results if r.startswith("SUCCESS")]
result = f"DONE: {len(successes)}/{len(in_stock)} products purchased successfully."
```

Each product is purchased **sequentially** using the same `page`. A crash on one
product is caught and logged; remaining products are still attempted.

### `buy_item()` in `buy_scrape` context

```python
def buy_item(
    page: Page,
    target_url: str,           # product['link'] from scraper
    release_time=None,         # always None — no scheduled drop
    refresh_lead_seconds=0,
    target_quantity=1,
    test_refresh_duration=0,
) -> str
```

The sniper executes Parts 1–7 (same as standalone `buy` mode):

| Part | Action | Key Playwright call |
|---|---|---|
| 1 | Safety check | `datetime.now()` comparison |
| 2 | Open product page | `page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)` |
| 3 | Countdown | Skipped — `release_time=None` |
| 4 | Stock-poll loop | `_page_is_in_stock()` → `page.reload()` if OOS |
| 5 | Set quantity | `input_loc.fill(str(qty))` or `plus_loc.click()` × N |
| 6 | Click Buy Now | `page.wait_for_selector(SEL_BUY_NOW, timeout=30_000)` → `buy_btn.click()` |
| 7 | Checkout | `_handle_checkout(page)` → `page.wait_for_url("**/order/**", timeout=60_000)` |

> **Key difference from standalone `buy`**: In `buy_scrape`, the product was already
> confirmed in-stock by the scraper's deep check. Part 4's refresh loop typically
> exits on the **first attempt** with no reloads needed.

#### Checkout — `_handle_checkout(page)`

```python
page.set_viewport_size({"width": 1920, "height": 1080})
page.wait_for_load_state("domcontentloaded", timeout=5000)
page.evaluate("window.scrollBy(0, 500)")
_click_place_order(page)          # 5-strategy cascade, 3 retries
page.wait_for_url("**/order/**", timeout=60_000)
```

Returns per product:
- `"SUCCESS: Order placed."` — URL matched `**/order/**`
- `"LIKELY_SUCCESS: Final URL = ..."` — URL wait timed out
- `"ERROR: ..."` — Place Order not found or click failed

---

## 6. Final Result

After the purchase loop completes:

```python
successes = [r for r in buy_results if r.startswith("SUCCESS")]
return f"DONE: {len(successes)}/{len(in_stock)} products purchased successfully."
```

This string is stored in `statuses[acc_idx]` in `main.py` and printed in the
final execution summary table.

---

## 7. Environment Variables (`buy_scrape` mode)

| Variable | Default | Description |
|---|---|---|
| `STORE_NAME` | `"Lazada"` | Target store |
| `ACTION` | `"buy"` | Must be `"buy_scrape"` |
| `SCRAPER_TARGET_URL` | — | **Required** — shared search/category URL for Phase 1 |
| `ACCOUNT_<N>_EMAIL` | — | Per-account login email (required per account) |
| `ACCOUNT_<N>_PASSWORD` | — | Per-account login password |
| `TARGET_QUANTITY` | `1` | Units to purchase per product |
| `SCRAPER_CONTINUOUS_MODE` | `false` | Retry Phase 1 until in-stock items found |
| `SCRAPER_LOOP_INTERVAL` | `60` | Seconds between Phase 1 retry attempts |
| `SCRAPER_DELAY` | `1.5` | Seconds between detail page checks in Phase 1 |
| `SCRAPER_RANDOM_DELAY` | `true` | Add random jitter to Phase 1 delays |
| `SCRAPER_SCROLL_COUNT` | `5` | Scroll iterations per listing page in Phase 1 |
| `SCRAPER_MAX_PAGES` | `0` | Max listing pages in Phase 1 (0 = unlimited) |
| `SCRAPER_PRODUCT_NAMES` | `""` | Comma-separated name filters for Phase 1 |
| `PROXY_URL` | `""` | Optional proxy server |

---

## 8. `buy_scrape` Mode Call Graph

```
main()
 └─ start_browser_and_route(action="buy_scrape")
       ├─ p.chromium.launch(headless=False, channel="chrome")
       ├─ context.new_page()
       │
       │  ── PHASE 1: SCRAPE ──────────────────────────────────────
       ├─ [retry loop if SCRAPER_CONTINUOUS_MODE=true]
       │     └─ scrape_item_data(page, SCRAPER_TARGET_URL)
       │           ├─ page.goto(url, wait_until="domcontentloaded")
       │           ├─ [pagination loop]
       │           │     ├─ page.evaluate("window.scrollBy(...)")
       │           │     ├─ page.query_selector_all(selector)
       │           │     └─ card.query_selector() × fields
       │           ├─ deduplication
       │           ├─ _filter_products_by_name()  [optional]
       │           ├─ [per-product deep check]
       │           │     └─ page.goto(product.link)
       │           │           page.inner_text("body")
       │           └─ _save_results()
       │     → in_stock = [products where is_out_of_stock=False]
       │
       │  ── PHASE 2: LOGIN ───────────────────────────────────────
       ├─ page.goto("https://www.lazada.sg")
       ├─ _is_lazada_logged_in(context, page)
       │     ├─ context.cookies()
       │     └─ page.locator(...).is_visible()
       └─ _handle_login()  [if not logged in]
             ├─ page.goto("https://member.lazada.sg/user/login")
             ├─ user_el.type(email, delay=60)
             └─ blocking loop → _is_lazada_logged_in()

       │  ── PHASE 3: PURCHASE LOOP ───────────────────────────────
       └─ for product in in_stock:
             └─ buy_item(page, product['link'], release_time=None, ...)
                   ├─ page.goto(product.link)         Part 2
                   ├─ [stock poll — typically 1 iter] Part 4
                   │     └─ _page_is_in_stock()
                   ├─ _set_quantity()                 Part 5
                   ├─ buy_btn.click()                 Part 6
                   └─ _handle_checkout()              Part 7
                         ├─ page.set_viewport_size()
                         ├─ _click_place_order()
                         └─ page.wait_for_url("**/order/**")
```

---

## 9. Key Differences vs. Standalone Modes

| Aspect | `scrape` | `buy` | `buy_scrape` |
|---|---|---|---|
| Browser | Headless | Headful | Headful |
| Resource blocking | Yes (`image`, `font`, `media`, `stylesheet`) | No | No |
| Login required | No | Yes | Yes (Phase 2) |
| URL source | `ACCOUNT_N_URL` | `ACCOUNT_N_URL` | `SCRAPER_TARGET_URL` (shared) |
| `release_time` honoured | N/A | Yes | No (always immediate) |
| Saves JSON output | Yes | No | Yes (Phase 1) |
| Purchases items | No | Yes | Yes (Phase 3) |
| Account `url` field required | Yes | Yes | No |
| Account `email` field required | Optional | Yes | Yes |
