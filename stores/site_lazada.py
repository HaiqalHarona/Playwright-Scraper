# stores/site_lazada.py
from utils import random_delay

# --- EXISTING BUYING HELPER FUNCTIONS ---
def login(page, username, password):
    print("-> [Lazada] Attempting to log in...")
    random_delay()

def add_item_to_cart(page, url):
    print(f"-> [Lazada] Navigating to product: {url}")
    page.goto(url)
    random_delay()
    print("-> [Lazada] Clicking 'Add to Cart'...")
    random_delay()

def proceed_to_checkout(page):
    print("-> [Lazada] Clicking 'Checkout'...")
    random_delay()

# --- NEW SCRAPING HELPER FUNCTION ---
def scrape_item_data(page, url):
    """Visits the page and reads text instead of clicking buttons."""
    print(f"-> [Lazada] Navigating to scrape: {url}")
    page.goto(url)
    random_delay()
    
    print("-> [Lazada] Extracting Title and Price...")
    # This is where your Playwright scraping code will go!
    # title = page.locator(".product-title-class").inner_text()
    
    random_delay()


# --- MAIN STORE AUTOMATION ---

# Notice we added 'action' to the main function
def run_lazada(page, action, target_url):
    print(f"=== Starting Lazada Module | Task: {action.upper()} ===")
    
    dummy_user = "test@email.com"
    dummy_pass = "securepassword123"
    
    try:
        # THE ROUTER: Decide what to do based on the user's action
        if action == "buy":
            login(page, dummy_user, dummy_pass)
            add_item_to_cart(page, target_url)
            proceed_to_checkout(page)
            return "SUCCESS: Reached Lazada checkout!"
            
        elif action == "scrape":
            # Notice we skip the login step completely for scraping!
            scrape_item_data(page, target_url)
            return "SUCCESS: Data scraped from Lazada!"
            
        else:
            return f"FAILED: Unknown action '{action}'. Please type 'buy' or 'scrape'."
            
    except Exception as e:
        return f"FAILED: Lazada error -> {e}"