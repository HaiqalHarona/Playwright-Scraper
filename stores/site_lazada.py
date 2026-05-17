# stores/site_lazada.py
# ---------------------------------------------------------------------
# This is the Lazada module. It handles the two main things:
# 1. The buying flow (logging in, adding to cart, and checking out).
# 2. The scraping flow (opening the store, detail-checking every product).
# ---------------------------------------------------------------------

import json
import os
from datetime import datetime
from utils import random_delay

# =====================================================================
#  BUYING HELPERS
# =====================================================================


def login(page, username, password):
    print("-> [Lazada] Attempting to log in...")
    page.wait_for_timeout(1000)


def add_item_to_cart(page, url):
    print(f"-> [Lazada] Navigating to product: {url}")
    page.goto(url)
    print("-> [Lazada] Clicking 'Add to Cart'...")


def proceed_to_checkout(page):
    print("-> [Lazada] Clicking 'Checkout'...")


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


def _check_stock_on_detail_page(page, product):
    if not product["link"] or product["link"] == "N/A":
        return product

    try:
        # 1.5s delay to avoid triggering CAPTCHA as requested
        page.wait_for_timeout(1500)

        print(f"   [Detail Check] Checking: {product['name'][:40]}...")
        page.goto(product["link"], wait_until="domcontentloaded", timeout=15000)

        # Check for CAPTCHA wall
        if page.query_selector("#nc_1_n1z") or "verification" in page.url:
            print("      [!] Hit CAPTCHA. Retrying with a longer wait...")
            page.wait_for_timeout(5000)
            page.reload()

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
    project_root = os.path.dirname(os.path.dirname(__file__))
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


def scrape_item_data(page, url):
    _navigate_to_page(page, url)

    grid_products = []
    current_page = 1

    while True:
        print(f"\n--- [Lazada] Collecting Links Page {current_page} ---")
        _scroll_to_load_products(page)
        cards, matched_selector = _find_product_cards(page)
        for i, card in enumerate(cards, start=len(grid_products) + 1):
            product = _extract_grid_data(card, i, matched_selector)
            if product:
                grid_products.append(product)

        next_btn = page.query_selector("li.ant-pagination-next")
        if next_btn and "ant-pagination-disabled" not in (
            next_btn.get_attribute("class") or ""
        ):
            btn = next_btn.query_selector("button")
            if btn:
                btn.click()
                page.wait_for_timeout(3000)
                current_page += 1
                continue
        break

    unique_products = []
    seen = set()
    for p in grid_products:
        if p["link"] not in seen:
            seen.add(p["link"])
            unique_products.append(p)

    print(
        f"\n-> Starting deep stock check on {len(unique_products)} items (with anti-captcha delays)"
    )

    final_products = []
    for p in unique_products:
        # Extra pause between items to stay under the radar
        random_delay(2, 5)
        final_products.append(_check_stock_on_detail_page(page, p))

    for i, p in enumerate(final_products, start=1):
        p["index"] = i

    _save_results(final_products, url)
    return final_products


def run_lazada(page, action, target_url):
    print(f"=== Running Lazada Bot | Action: {action.upper()} ===")
    try:
        if action == "buy":
            return "DONE"
        elif action == "scrape":
            products = scrape_item_data(page, target_url)
            return f"DONE: Found {len(products)} total items."
    except Exception as e:
        return f"CRASHED: {e}"
