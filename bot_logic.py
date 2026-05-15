# bot_logic.py
from playwright.sync_api import sync_playwright
from stores.site_lazada import run_lazada

# Notice we added 'action' as a parameter here
def start_browser_and_route(store_name, action, target_url):
    print(f"\n[Traffic Cop] Launching browser engine for {action.upper()}...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=50)
        context = browser.new_context()
        page = context.new_page()
        
        if store_name.lower() == "lazada":
            # Pass the action down to Lazada!
            result = run_lazada(page, action, target_url)
            
        elif store_name.lower() == "amazon":
            result = "Amazon module not built yet!"
            
        else:
            result = f"Error: '{store_name}' is not a supported store."
            
        print("[Traffic Cop] Task complete. Closing browser...")
        browser.close()
        
        return result