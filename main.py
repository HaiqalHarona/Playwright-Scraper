# main.py
from bot_logic import start_browser_and_route

# --- TEST CONFIGURATION ---
# Hardcoded for testing. Change these values to test different scenarios.
TEST_STORE = "Lazada"
TEST_ACTION = "scrape"
TEST_URL = "https://www.lazada.sg/tefal/?from=wangpu&q=All-Products&ppath=120168401:110008744"


def display_menu():
    print("\n" + "="*40)
    print("   UNIVERSAL SHOPPING & SCRAPING BOT v1.1   ")
    print("="*40)
    print("Supported Stores: Lazada")
    print("Type 'exit' to quit.")
    print("="*40)

def main():
    display_menu()

    print(f"\n[Test Mode] Store  : {TEST_STORE}")
    print(f"[Test Mode] Action : {TEST_ACTION}")
    print(f"[Test Mode] URL    : {TEST_URL}")
    print("-" * 40)

    final_status = start_browser_and_route(TEST_STORE, TEST_ACTION, TEST_URL)

    print(f"\n>>> FINAL STATUS: {final_status} <<<\n")

if __name__ == "__main__":
    main()