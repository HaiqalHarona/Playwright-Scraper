# stores/scraper/site_lazada.py
# ---------------------------------------------------------------------
# The scraping flow (opening the store, detail-checking every product).
# ---------------------------------------------------------------------

import json
import os
import time
from datetime import datetime
from utils import random_delay
from captcha_solver import resolve_any_captcha


# =====================================================================
#  CONFIGURATION HELPERS
# =====================================================================


def _get_scraper_config():
    """Load scraper configuration from environment variables."""
    try:
        delay = float(os.getenv('SCRAPER_DELAY', '1.5'))
    except ValueError:
        delay = 1.5
    
    try:
        scroll_count = int(os.getenv('SCRAPER_SCROLL_COUNT', '5'))
    except ValueError:
        scroll_count = 5
    
    try:
        loop_interval = int(os.getenv('SCRAPER_LOOP_INTERVAL', '300'))
    except ValueError:
        loop_interval = 300
    
    try:
        max_pages = int(os.getenv('SCRAPER_MAX_PAGES', '0'))
    except ValueError:
        max_pages = 0
    
    config = {
        'delay': delay,
        'random_delay': os.getenv('SCRAPER_RANDOM_DELAY', 'true').lower() == 'true',
        'scroll_count': scroll_count,
        'continuous_mode': os.getenv('SCRAPER_CONTINUOUS_MODE', 'false').lower() == 'true',
        'loop_interval': loop_interval,
        'max_pages': max_pages,
        'product_names': [
            name.strip()
            for name in os.getenv('SCRAPER_PRODUCT_NAMES', '').split(',')
            if name.strip()
        ],
    }
    return config


# =====================================================================
#  SCRAPING HELPERS
# =====================================================================


def _navigate_to_page(page, url):
    print(f"-> [Lazada] Navigating to: {url}")
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)


def _scroll_to_load_products(page, scroll_count=5):
    print(f"-> [Lazada] Scrolling {scroll_count} times to trigger lazy loading...")
    for i in range(scroll_count):
        page.evaluate("window.scrollBy(0, window.innerHeight)")
        page.wait_for_timeout(500)
    page.evaluate("window.scrollTo(0, 0)")


def _find_product_cards(page):
    possible_selectors = [
        ("standard items", "[data-qa-locator='product-item']"),
        ("Bm3ON class", ".Bm3ON"),
        ("tracking cards", "div[data-tracking='product-card']"),
        ("link fallback", "a[href*='/products/']"),
    ]
    for label, selector in possible_selectors:
        cards = page.query_selector_all(selector)
        if cards:
            return cards, selector
    return [], ""


def _extract_text(card, selectors):
    for selector in selectors:
        element = card.query_selector(selector)
        if element:
            text = element.inner_text().strip()
            if text:
                return text
    return "N/A"


def _extract_attribute(card, selector, attribute):
    element = card.query_selector(selector)
    if element:
        return element.get_attribute(attribute) or ""
    return ""


def _build_full_url(href):
    if not href:
        return "N/A"
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return "https://www.lazada.sg" + href
    return href


def _extract_grid_data(card, index, matched_selector):
    try:
        name = _extract_text(
            card, [".RfADt", "[data-qa-locator='product-item'] span", "span"]
        )
        price = _extract_text(card, [".ooOxS", "span[class*='price']"])

        if matched_selector == "a[href*='/products/']":
            raw_href = card.get_attribute("href") or ""
        else:
            raw_href = _extract_attribute(card, "a[href]", "href")

        link = _build_full_url(raw_href)
        image = _extract_attribute(card, "img", "src") or _extract_attribute(
            card, "img", "data-src"
        )

        return {
            "index": index,
            "name": name[:200],
            "price": price,
            "link": link,
            "image": image,
            "is_out_of_stock": False,
        }
    except:
        return None


def _check_stock_on_detail_page(page, product, config):
    if not product["link"] or product["link"] == "N/A":
        return product

    try:
        # Configurable delay to avoid triggering CAPTCHA
        delay_ms = int(config['delay'] * 1000)
        page.wait_for_timeout(delay_ms)

        print(f"   [Detail Check] Checking: {product['name'][:40]}...")
        page.goto(product["link"], wait_until="domcontentloaded", timeout=15000)

        # Check for CAPTCHA wall
        if page.query_selector("#nc_1_n1z") or "verification" in page.url or page.query_selector("img[src*='captcha']"):
            print("      [!] Hit CAPTCHA. Running automated solver...")
            solved = resolve_any_captcha(page)
            if not solved:
                print("      [!] Automated captcha bypass failed. Retrying with a longer wait...")
                page.wait_for_timeout(5000)
                page.reload()
            else:
                print("      [!] CAPTCHA wall successfully bypassed!")

        page_text_lower = page.inner_text("body").lower()
        is_sold_out = False

        # Keywords check
        if "sold out" in page_text_lower or "out of stock" in page_text_lower:
            is_sold_out = True

        # Button check
        add_to_cart = page.query_selector("button:has-text('Add to Cart')")
        if add_to_cart:
            classes = add_to_cart.get_attribute("class") or ""
            if "disabled" in classes.lower() or "pdp-button_disabled" in classes:
                is_sold_out = True

        product["is_out_of_stock"] = is_sold_out
        status = "[OUT OF STOCK]" if is_sold_out else "[IN STOCK]"
        print(f"      -> Result: {status}")

    except Exception as e:
        print(f"      [!] Skip {product['index']} due to timeout/error.")

    return product


def _save_results(products, url):
    # Get base project directory
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    readable_time = datetime.now().strftime("%d-%m-%Y_%H-%M")

    # 1. Save Full Results
    full_output_dir = os.path.join(project_root, "data", "scrapes", "run_logs")
    os.makedirs(full_output_dir, exist_ok=True)  # Ensure the subfolder exists!

    full_path = os.path.join(full_output_dir, f"lazada_scrape-{readable_time}.json")
    with open(full_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "scraped_at": datetime.now().isoformat(),
                "source": url,
                "products": products,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    # 2. Save Filtered (In Stock Only) Results
    in_stock_products = [p for p in products if p.get("is_out_of_stock") is False]

    # Correctly join the subfolder here too
    in_stock_dir = os.path.join(project_root, "data", "scrapes", "in_stock")
    os.makedirs(in_stock_dir, exist_ok=True)  # Ensure this subfolder exists too!

    in_stock_path = os.path.join(in_stock_dir, f"lazada_in_stock-{readable_time}.json")
    with open(in_stock_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "scraped_at": datetime.now().isoformat(),
                "count": len(in_stock_products),
                "products": in_stock_products,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    print(f"-> [Lazada] Full results saved to: {full_path}")
    print(
        f"-> [Lazada] In-stock results saved to: {in_stock_path} ({len(in_stock_products)} items)"
    )


def _filter_products_by_name(products, target_names):
    """Filter products by matching target product names."""
    if not target_names:
        return products
    
    filtered = []
    for product in products:
        product_name_lower = product['name'].lower()
        for target_name in target_names:
            if target_name.lower() in product_name_lower:
                filtered.append(product)
                break
    
    return filtered


def scrape_item_data(page, url, config=None):
    if config is None:
        config = _get_scraper_config()
    
    _navigate_to_page(page, url)
    resolve_any_captcha(page)  # sweep on initial page load

    grid_products = []
    current_page = 1
    
    # Extract config values with proper type handling
    max_pages_val = config.get('max_pages', 0)
    max_pages_limit = int(max_pages_val) if isinstance(max_pages_val, (int, float, str)) else 0
    
    scroll_count_val = config.get('scroll_count', 5)
    scroll_count = int(scroll_count_val) if isinstance(scroll_count_val, (int, float, str)) else 5

    while True:
        print(f"\n--- [Lazada] Collecting Links Page {current_page} ---")
        _scroll_to_load_products(page, scroll_count)
        cards, matched_selector = _find_product_cards(page)
        for i, card in enumerate(cards, start=len(grid_products) + 1):
            product = _extract_grid_data(card, i, matched_selector)
            if product:
                grid_products.append(product)

        # Check if we've reached max pages limit
        if max_pages_limit > 0 and current_page >= max_pages_limit:
            print(f"-> Reached maximum page limit ({max_pages_limit})")
            break

        next_btn = page.query_selector("li.ant-pagination-next")
        if next_btn and "ant-pagination-disabled" not in (
            next_btn.get_attribute("class") or ""
        ):
            btn = next_btn.query_selector("button")
            if btn:
                btn.click()
                page.wait_for_timeout(3000)
                resolve_any_captcha(page)  # sweep after pagination
                current_page += 1
                continue
        break

    unique_products = []
    seen = set()
    for p in grid_products:
        if p["link"] not in seen:
            seen.add(p["link"])
            unique_products.append(p)

    # Filter by product names if specified
    product_names = config.get('product_names', [])
    if product_names and isinstance(product_names, list):
        product_names_str = ', '.join(product_names)
        print(f"\n-> Filtering for specific products: {product_names_str}")
        unique_products = _filter_products_by_name(unique_products, product_names)
        print(f"-> Found {len(unique_products)} matching products")

    print(
        f"\n-> Starting deep stock check on {len(unique_products)} items (with anti-captcha delays)"
    )

    final_products = []
    for p in unique_products:
        # Use configurable delay or random delay
        if config.get('random_delay', True):
            random_delay()
        final_products.append(_check_stock_on_detail_page(page, p, config))

    for i, p in enumerate(final_products, start=1):
        p["index"] = i

    _save_results(final_products, url)
    return final_products


def run_lazada(page, action, target_url):
    print(f"=== Running Lazada Bot | Action: {action.upper()} ===")
    try:
        if action == "scrape":
            config = _get_scraper_config()
            
            # Print configuration summary
            print(f"\n--- Scraper Configuration ---")
            print(f"Delay: {config['delay']}s")
            print(f"Random Delay: {config['random_delay']}")
            print(f"Scroll Count: {config['scroll_count']}")
            print(f"Max Pages: {config['max_pages']} (0 = unlimited)")
            print(f"Continuous Mode: {config['continuous_mode']}")
            if config['continuous_mode']:
                print(f"Loop Interval: {config['loop_interval']}s")
            if config['product_names']:
                print(f"Target Products: {', '.join(config['product_names'])}")
            print("----------------------------\n")
            
            if config['continuous_mode']:
                # Continuous scraping mode
                cycle = 1
                while True:
                    print(f"\n{'='*60}")
                    print(f"  SCRAPING CYCLE #{cycle}")
                    print(f"{'='*60}")
                    
                    products = scrape_item_data(page, target_url, config)
                    
                    # Check for in-stock products
                    in_stock = [p for p in products if not p.get('is_out_of_stock', True)]
                    print(f"\n>>> Cycle {cycle} Complete: {len(in_stock)} in-stock items found <<<")
                    
                    if in_stock and config['product_names']:
                        print("\n🎯 TARGET PRODUCTS IN STOCK:")
                        for p in in_stock:
                            print(f"  - {p['name'][:60]}")
                            print(f"    Price: {p['price']}")
                            print(f"    Link: {p['link']}")
                    
                    print(f"\n⏳ Waiting {config['loop_interval']}s before next cycle...")
                    time.sleep(config['loop_interval'])
                    cycle += 1
            else:
                # Single scrape mode
                products = scrape_item_data(page, target_url, config)
                in_stock = [p for p in products if not p.get('is_out_of_stock', True)]
                return f"DONE: Found {len(products)} total items ({len(in_stock)} in stock)."
    except Exception as e:
        return f"CRASHED: {e}"
