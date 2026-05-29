# Mode: `scrape` — Developer Reference

> **Action value**: `ACTION=scrape`
> **Call chain**: `main.py` → `bot_logic.start_browser_and_route()` → `site_lazada.run_lazada()` → `site_lazada.scrape_item_data()`

---

## 1. Entry — `main.py`

### `load_env()`
Parses `.env` line-by-line and writes every `KEY=VALUE` into `os.environ`.  
Comments (`#`) and blank lines are skipped.

### `parse_accounts(require_url=True)`
Regex-scans `os.environ` for `ACCOUNT_<N>_(URL|EMAIL|PASSWORD)`.  
In scrape mode `require_url=True`, so only accounts that have a `url` field are returned.  
Returns a `dict[int, dict]` sorted by account index.

### `main()`
Key scrape-specific behaviour:
- Reads `SCRAPER_STORE_NAME` and overrides `store` if set.
- `parse_accounts(require_url=True)` — accounts need `ACCOUNT_N_URL`.
- Falls back to `SCRAPER_TARGET_URL` → `STORE_URL_1` → `STORE_URL` when no accounts configured.
- One `threading.Thread` per account, each calling `start_browser_and_route(action="scrape", ...)`.

---

## 2. Router — `bot_logic.py`

### `start_browser_and_route()` — Signature

```python
def start_browser_and_route(
    store_name: str,            # "Lazada"
    action: str,                # "scrape"
    target_url: str,            # search / category page URL
    release_time: datetime | None = None,
    refresh_lead_seconds: int = 5,
    target_quantity: int = 1,
    test_refresh_duration: int = 0,
    email: str = "",
    password: str = "",
) -> str
```

### Playwright setup for `scrape`

```python
headless_mode = True   # scrape is always headless

with Stealth().use_sync(sync_playwright()) as p:
    browser = p.chromium.launch(
        headless=True,
        slow_mo=0,
        channel="chrome"        # use installed Google Chrome binary
    )
    context = browser.new_context()   # or new_context(proxy=...) if PROXY_URL set
    page = context.new_page()

    # Bandwidth saver — only active for scrape
    page.route("**/*", _block_resources)
```

### `_block_resources(route: Route) -> None`
Registered via `page.route("**/*", _block_resources)`.  
Calls `route.abort()` for resource types in `{"image", "font", "media", "stylesheet"}`.  
Calls `route.continue_()` for everything else (HTML, JS, XHR/fetch).  
**Not applied in `buy` or `buy_scrape` — checkout needs a full render.**

### Scrape route dispatch

```python
if store_name.lower() == "lazada":
    if action == "scrape":
        result = run_lazada(page, action, target_url)
```

No login check is performed. Scraping is done anonymously.

---

## 3. `run_lazada()` — `stores/scraper/site_lazada.py`

```python
def run_lazada(page, action: str, target_url: str) -> str
```

Top-level entry point inside the scraper module.

1. Calls `_get_scraper_config()` to load all env-driven settings.
2. Prints a configuration summary to stdout.
3. Branches on `SCRAPER_CONTINUOUS_MODE`:

### Single-run mode (`SCRAPER_CONTINUOUS_MODE=false`, default)
```python
products = scrape_item_data(page, target_url, config)
in_stock = [p for p in products if not p.get('is_out_of_stock', True)]
return f"DONE: Found {len(products)} total items ({len(in_stock)} in stock)."
```

### Continuous mode (`SCRAPER_CONTINUOUS_MODE=true`)
```python
while True:
    products = scrape_item_data(page, target_url, config)
    in_stock = [p for p in products if not p.get('is_out_of_stock', True)]
    time.sleep(config['loop_interval'])   # SCRAPER_LOOP_INTERVAL seconds
    cycle += 1
```
Runs until the process is killed. Never returns a string.

---

## 4. `scrape_item_data()` — Core Engine

```python
def scrape_item_data(page, url: str, config: dict | None = None) -> list[dict]
```

| Parameter | Type | Description |
|---|---|---|
| `page` | `Page` | Active Playwright page object |
| `url` | `str` | Search or category page URL |
| `config` | `dict \| None` | Auto-loaded from env if `None` |

### Stage 1 — Navigate & paginate

```python
# Navigate & Sweep Captcha
page.goto(url, wait_until="domcontentloaded")
resolve_any_captcha(page)    # Sweep before parsing
page.wait_for_timeout(3000)   # 3s DOM-settle

# Per page — scroll to trigger lazy load
for i in range(scroll_count):            # SCRAPER_SCROLL_COUNT, default 5
    page.evaluate("window.scrollBy(0, window.innerHeight)")
    page.wait_for_timeout(500)
page.evaluate("window.scrollTo(0, 0)")  # scroll back to top

# Advance to next page
next_btn = page.query_selector("li.ant-pagination-next")
btn = next_btn.query_selector("button")
btn.click()
page.wait_for_timeout(3000)
```

Stops when: `ant-pagination-disabled` class found on `li.ant-pagination-next`,
no next button exists, or `SCRAPER_MAX_PAGES` limit reached (0 = unlimited).

### Stage 2 — Extract product cards

`_find_product_cards(page)` tries 4 selectors in order, returns first that yields results:

| Priority | Label | Selector |
|---|---|---|
| 1 | Standard items | `[data-qa-locator='product-item']` |
| 2 | Bm3ON class | `.Bm3ON` |
| 3 | Tracking cards | `div[data-tracking='product-card']` |
| 4 | Link fallback | `a[href*='/products/']` |

Per card, `_extract_grid_data()` extracts:

| Field | Selectors tried |
|---|---|
| `name` | `.RfADt`, `[data-qa-locator='product-item'] span`, `span` |
| `price` | `.ooOxS`, `span[class*='price']` |
| `link` | `a[href]` → `href` attribute (protocol-relative URLs normalised to `https:`) |
| `image` | `img` → `src` then `data-src` |

Returns a `dict`:
```python
{
  "index": int,
  "name": str,           # truncated to 200 chars
  "price": str,
  "link": str,           # absolute HTTPS URL
  "image": str,
  "is_out_of_stock": False   # assumed in-stock at grid level
}
```

### Stage 3 — Deduplication
Product `link` values are tracked in a `set`; duplicate URLs are discarded.

### Stage 4 — Name filter (optional)
If `SCRAPER_PRODUCT_NAMES` is set (comma-separated), `_filter_products_by_name()`
performs a case-insensitive `in` substring check on each product's name.

### Stage 5 — Deep stock check per product

```python
page.goto(product["link"], wait_until="domcontentloaded", timeout=15000)
```

Detection order:
1. **Body text scan**: `"sold out"` or `"out of stock"` in `page.inner_text("body").lower()`.
2. **Button state**: `page.query_selector("button:has-text('Add to Cart')")` — OOS if button has `disabled` or `pdp-button_disabled` class.

CAPTCHA handling:
```python
if page.query_selector("#nc_1_n1z") or "verification" in page.url or page.query_selector("img[src*='captcha']"):
    print("      [!] Hit CAPTCHA. Running automated solver...")
    solved = resolve_any_captcha(page)
    if not solved:
        page.wait_for_timeout(5000)
        page.reload()
```

Between each detail page, applies `config['delay']` ms wait
(`SCRAPER_DELAY` seconds × 1000), plus optional random jitter (`SCRAPER_RANDOM_DELAY`).

### Stage 6 — Save JSON results

Writes to two files inside the project root:

| File | Path pattern | Contents |
|---|---|---|
| Full results | `data/scrapes/run_logs/lazada_scrape-<DD-MM-YYYY_HH-MM>.json` | All products |
| In-stock only | `data/scrapes/in_stock/lazada_in_stock-<DD-MM-YYYY_HH-MM>.json` | Filtered list |

JSON structure:
```json
{
  "scraped_at": "2026-05-23T22:00:00",
  "source": "https://www.lazada.sg/...",
  "products": [ { "index": 1, "name": "...", ... } ]
}
```

**Returns** `list[dict]` — all products with `is_out_of_stock` populated.

---

## 5. Environment Variables (scrape mode)

| Variable | Default | Description |
|---|---|---|
| `STORE_NAME` | `"Lazada"` | Target store |
| `ACTION` | `"buy"` | Set to `"scrape"` |
| `SCRAPER_STORE_NAME` | `""` | Override `STORE_NAME` in scrape mode |
| `ACCOUNT_<N>_URL` | — | Per-account target URL |
| `SCRAPER_TARGET_URL` | — | Fallback URL (single-account / no accounts) |
| `SCRAPER_DELAY` | `1.5` | Seconds between detail page visits |
| `SCRAPER_RANDOM_DELAY` | `true` | Add random jitter to delay |
| `SCRAPER_SCROLL_COUNT` | `5` | Scroll iterations per listing page |
| `SCRAPER_MAX_PAGES` | `0` | Max listing pages (0 = unlimited) |
| `SCRAPER_CONTINUOUS_MODE` | `false` | Loop forever between scrape cycles |
| `SCRAPER_LOOP_INTERVAL` | `300` | Seconds between continuous cycles |
| `SCRAPER_PRODUCT_NAMES` | `""` | Comma-separated name filters |
| `PROXY_URL` | `""` | Optional proxy server (e.g. `http://user:pass@host:port`) |

---

## 6. Scrape Mode Call Graph

```
main()
 └─ start_browser_and_route(action="scrape")
       ├─ p.chromium.launch(headless=True, channel="chrome")
       ├─ page.route("**/*", _block_resources)
       └─ run_lazada(page, "scrape", target_url)
             ├─ _get_scraper_config()
             └─ scrape_item_data(page, url, config)
                   ├─ _navigate_to_page()         → page.goto()
                   ├─ [pagination loop]
                   │     ├─ _scroll_to_load_products() → page.evaluate()
                   │     ├─ _find_product_cards()      → page.query_selector_all()
                   │     └─ _extract_grid_data()       → card.query_selector()
                   ├─ deduplication
                   ├─ _filter_products_by_name()   (if SCRAPER_PRODUCT_NAMES set)
                   ├─ [per-product loop]
                   │     └─ _check_stock_on_detail_page() → page.goto(), page.inner_text()
                   └─ _save_results()              → json.dump() × 2
```
