# main.py
from bot_logic import start_browser_and_route

def display_menu():
    print("\n" + "="*40)
    print("   UNIVERSAL SHOPPING & SCRAPING BOT v1.1   ")
    print("="*40)
    print("Supported Stores: Lazada")
    print("Type 'exit' to quit.")
    print("="*40)

def main():
    while True:
        display_menu()
        
        # 1. Get store
        store_choice = input("\nEnter the store name: ").strip()
        if store_choice.lower() == 'exit':
            print("Shutting down bot. Goodbye!")
            break
            
        # 2. Get action (NEW!)
        action_choice = input("Do you want to 'buy' or 'scrape'?: ").strip().lower()
        
        # 3. Get URL
        url_input = input("Enter the product URL: ").strip()
        
        # 4. Hand off to the bot logic (Notice we added action_choice here!)
        final_status = start_browser_and_route(store_choice, action_choice, url_input)
        
        print(f"\n>>> FINAL STATUS: {final_status} <<<\n")

if __name__ == "__main__":
    main()