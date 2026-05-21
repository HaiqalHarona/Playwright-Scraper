# main.py
import builtins
import os
import re
import sys
import threading
from datetime import datetime, timedelta
from bot_logic import start_browser_and_route

# --- Override global print to prefix logs with thread names ---
_original_print = builtins.print

def custom_print(*args, **kwargs):
    t_name = threading.current_thread().name
    if t_name.startswith("Account-"):
        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        msg = sep.join(str(arg) for arg in args)
        prefix = f"[{t_name}] "
        _original_print(f"{prefix}{msg}", **{k: v for k, v in kwargs.items() if k not in ["sep", "end"]}, end=end)
    else:
        _original_print(*args, **kwargs)

builtins.print = custom_print


def load_env(env_path=".env"):
    """Manually parse .env file to load environment variables."""
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()


def parse_accounts(require_url=True):
    """Extract valid account configurations from environment variables.
    
    require_url — if True, only return accounts that have a URL set.
                   if False, return accounts that have an email set (for buy_scrape).
    """
    accounts = {}
    for key, val in os.environ.items():
        match = re.match(r"ACCOUNT_(\d+)_(URL|EMAIL|PASSWORD)", key)
        if match:
            idx = int(match.group(1))
            field = match.group(2).lower()
            if idx not in accounts:
                accounts[idx] = {}
            accounts[idx][field] = val.strip()

    valid_accounts = {}
    for idx, data in accounts.items():
        if require_url:
            if "url" in data:
                data["email"] = data.get("email", "")
                data["password"] = data.get("password", "")
                valid_accounts[idx] = data
        else:
            # buy_scrape mode: accounts need email, URL comes from SCRAPER_TARGET_URL
            if "email" in data:
                data["url"] = data.get("url", "")
                data["password"] = data.get("password", "")
                valid_accounts[idx] = data
    return dict(sorted(valid_accounts.items()))


def display_menu(store, action, release_time, refresh_lead, num_accounts):
    print("\n" + "=" * 42)
    print("   UNIVERSAL SHOPPING & SCRAPING BOT v1.3  ")
    print("=" * 42)
    print(f"Supported Stores : Lazada")
    print(f"Current Action   : {action.upper()}")
    if release_time:
        print(f"Release Time     : {release_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Refresh Lead     : {refresh_lead}s before release")
    else:
        print("Release Time     : IMMEDIATE (no countdown)")
    print(f"Active Accounts  : {num_accounts}")
    print("=" * 42)


def main():
    # Load configuration
    load_env()

    # Parse common configuration
    store = os.getenv("STORE_NAME", "Lazada")
    action = os.getenv("ACTION", "buy")
    
    # Use scraper-specific store name if in scrape mode
    if action == "scrape":
        scraper_store = os.getenv("SCRAPER_STORE_NAME", "")
        if scraper_store:
            store = scraper_store
    
    try:
        qty = int(os.getenv("TARGET_QUANTITY", "1"))
    except ValueError:
        qty = 1

    try:
        refresh_lead = int(os.getenv("REFRESH_LEAD_SECONDS", "5"))
    except ValueError:
        refresh_lead = 5

    try:
        test_dur = int(os.getenv("TEST_REFRESH_DURATION", "0"))
    except ValueError:
        test_dur = 0

    release_time_str = os.getenv("RELEASE_TIME", "").strip()
    release_time = None
    if release_time_str:
        # Check for test mode
        if release_time_str.lower() == "test":
            release_time = datetime.now() + timedelta(minutes=2)
            print(f"[Main] TEST MODE: Release time set to {release_time.strftime('%Y-%m-%d %H:%M:%S')} (2 minutes from now)")
        else:
            try:
                release_time = datetime.strptime(release_time_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    release_time = datetime.fromisoformat(release_time_str)
                except ValueError:
                    print(f"[Warning] Invalid RELEASE_TIME format '{release_time_str}'. Running immediately.")

    accounts = parse_accounts(require_url=(action != "buy_scrape"))

    display_menu(store, action, release_time, refresh_lead, len(accounts))

    if not accounts:
        # Backwards compatibility / Fallback mode
        print("\n[Warning] No parallel accounts configured in .env.")
        print("          Falling back to single-run mode using default values.")
        
        # Use scraper-specific URL if in scrape or buy_scrape mode
        if action in ("scrape", "buy_scrape"):
            fallback_url = os.getenv("SCRAPER_TARGET_URL", os.getenv("STORE_URL_1", os.getenv("STORE_URL", "https://www.lazada.sg")))
        else:
            fallback_url = os.getenv("STORE_URL_1", os.getenv("STORE_URL", "https://www.lazada.sg"))
        
        fallback_email = os.getenv("ACCOUNT_1_EMAIL", "")
        fallback_password = os.getenv("ACCOUNT_1_PASSWORD", "")
            
        print(f"[Main] Store   : {store}")
        print(f"[Main] Action  : {action}")
        print(f"[Main] URL     : {fallback_url}")
        if fallback_email:
            print(f"[Main] Email   : {fallback_email}")
        print("-" * 42)

        final_status = start_browser_and_route(
            store_name=store,
            action=action,
            target_url=fallback_url,
            release_time=release_time,
            refresh_lead_seconds=refresh_lead,
            target_quantity=qty,
            test_refresh_duration=test_dur,
            email=fallback_email,
            password=fallback_password,
        )
        print(f"\n>>> FINAL STATUS: {final_status} <<<\n")
        return

    # Parallel Execution Mode
    threads = []
    statuses = {}

    def run_account_thread(acc_idx, config):
        thread_name = f"Account-{acc_idx}"
        threading.current_thread().name = thread_name
        
        # For buy_scrape, use SCRAPER_TARGET_URL instead of account-specific URL
        if action == "buy_scrape":
            target_url = os.getenv("SCRAPER_TARGET_URL", config.get("url", ""))
        else:
            target_url = config["url"]
        
        print(f"Launching instance...")
        print(f"Target URL: {target_url}")
        if config.get("email"):
            print(f"Email     : {config['email']}")
        
        try:
            status = start_browser_and_route(
                store_name=store,
                action=action,
                target_url=target_url,
                release_time=release_time,
                refresh_lead_seconds=refresh_lead,
                target_quantity=qty,
                test_refresh_duration=test_dur,
                email=config["email"],
                password=config["password"],
            )
            statuses[acc_idx] = status
        except Exception as e:
            statuses[acc_idx] = f"CRASHED: {e}"
            print(f"Exception raised in execution: {e}")

    print("\nStarting parallel browser windows...")
    for idx, config in accounts.items():
        t = threading.Thread(
            target=run_account_thread,
            args=(idx, config),
            name=f"Account-{idx}"
        )
        threads.append(t)
        t.start()

    # Wait for all threads to finish
    for t in threads:
        t.join()

    # Print a premium, structured results summary
    print("\n" + "=" * 52)
    print("                 EXECUTION SUMMARY                 ")
    print("=" * 52)
    for idx in sorted(accounts.keys()):
        url_short = accounts[idx]["url"][:30] + "..." if len(accounts[idx]["url"]) > 30 else accounts[idx]["url"]
        print(f" Account {idx:02d} | URL: {url_short:<30} | Result: {statuses.get(idx, 'Unknown')}")
    print("=" * 52 + "\n")
                                                                                                                            

if __name__ == "__main__":
    main()