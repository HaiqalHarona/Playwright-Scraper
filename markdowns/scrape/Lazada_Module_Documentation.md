# Lazada Module Logic Breakdown

This document explains the structure and functions within `stores/site_lazada.py`.

## Main Entry Point
The primary function called by the bot is **`run_lazada`**.

- **Location**: Bottom of `stores/site_lazada.py`
- **Role**: It acts as the "Traffic Controller." It checks if the user wants to `buy` or `scrape` and routes the request to the correct sub-pipeline.

---

## Scraping Pipeline
The scraping logic is split into small, modular functions to make it resilient to website changes.

### 1. The Coordinator
**`scrape_item_data`**
This is the "Main" function for scraping. It coordinates the following helpers in order:
1. Opens the page.
2. Scrolls to load content.
3. Extracts the data.
4. Cleans up duplicates.
5. Saves the final file.

### 2. The Helpers (Internal)
These functions handle the heavy lifting:

| Function | Role |
| :--- | :--- |
| `_navigate_to_page` | Opens the URL and waits for the product grid to render in JavaScript. |
| `_scroll_to_load_products` | Scrolls the page multiple times to trigger "lazy loading" so all products appear. |
| `_find_product_cards` | Searches the HTML for product containers using multiple backup selectors. |
| `_extract_one_product` | The logic used to pull Name, Price, Link, Image, and Stock Status (Sold Out) from a single card. |
| `_extract_text` | Safely grabs text from inside a card. |
| `_extract_attribute` | Safely grabs HTML attributes (like `src` for images or `href` for links). |
| `_build_full_url` | Ensures all product links are full `https://` URLs. |
| `_deduplicate_products` | Removes any items that might have been picked up twice. |
| `_save_results` | Writes the final structured data to `data/lazada_scrape.json`. |

---

## Buying Pipeline (Placeholders)
These functions are currently placeholders for future automation:
- **`login`**: Will handle account authentication.
- **`add_item_to_cart`**: Will handle selecting a product and adding it to the bag.
- **`proceed_to_checkout`**: Will handle the transition to the final payment screen.
