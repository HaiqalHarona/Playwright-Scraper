# E-Commerce Snipe Bot

A powerful automated shopping bot built with Playwright that can monitor product availability and automatically purchase items when they come in stock. Supports scheduled releases and multi-account parallel execution.

<div align="center">
  <img src="data/screenshots/bot-running.png" alt="Bot in Action" width="800"/>
  <p><em>The bot monitoring multiple accounts simultaneously</em></p>
</div>

---

## Documentation

**[User-Friendly Guide](README_USER_FRIENDLY.md)** - Step-by-step setup with detailed explanations of every command (no technical jargon!)

---

## Table of Contents

- [Features](#features)
- [Screenshots](#screenshots)
- [Quick Start](#quick-start)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Bot](#running-the-bot)
- [Understanding the Logs](#understanding-the-logs)
- [Troubleshooting](#troubleshooting)
- [Developer Reference](#developer-reference)

## Features

- **Automated product monitoring and purchasing**
- **Scrape-to-buy pipeline** — scan a category page, find in-stock products, and buy them automatically
- **Multi-account parallel execution**
- **Scheduled release time support**
- **Auto-login with dynamic session recovery fallback**
- **Advanced Captcha Handling** (reCAPTCHA, Slider, and Grid-based Image selections)
- **Stealth mode to avoid detection**
- **Detailed logging and status reporting**

## Screenshots

<table>
  <tr>
    <td width="50%">
      <h3 align="center">Configuration Menu</h3>
      <img src="data/screenshots/config-menu.png" alt="Configuration Menu"/>
      <p align="center"><em>Initial configuration display showing store, action, and account settings</em></p>
    </td>
    <td width="50%">
      <h3 align="center">Bot Execution</h3>
      <img src="data/screenshots/bot-execution.png" alt="Bot Execution"/>
      <p align="center"><em>Browser windows running in parallel for multiple accounts</em></p>
    </td>
  </tr>
</table>

## Quick Start

For complete beginners, see the [User-Friendly Guide](README_USER_FRIENDLY.md) for detailed step-by-step instructions.

1. **Install Python** - [Download here](https://www.python.org/downloads/)
2. **Clone/Download this project**
3. **Open in VSCode** (recommended) or any terminal
4. **Run setup commands** (detailed below)
5. **Configure your `.env` file**
6. **Run the bot:** `python main.py`

## Prerequisites

Before installing the bot, ensure you have:

- Python 3.8 or higher installed
- Internet connection
- Valid account credentials for the e-commerce platform

## Installation

### Step 1: Install Python

If you don't have Python installed:

1. Download Python from [https://www.python.org/downloads/](https://www.python.org/downloads/)
2. During installation, make sure to check "Add Python to PATH"
3. Verify installation by opening a terminal/command prompt and running:
   ```
   python --version
   ```

### Step 2: Install pip

Pip usually comes with Python. To verify:

```
pip --version
```

If pip is not installed:

**Windows:**
```
python -m ensurepip --upgrade
```

**Linux/Mac:**
```
python3 -m ensurepip --upgrade
```

### Step 3: Create Virtual Environment

Navigate to the project directory and create a virtual environment:

**Windows:**
```
cd path\to\E-Commerce_SnipeBot
python -m venv .venv
.venv\Scripts\activate
```

**Linux/Mac:**
```
cd path/to/E-Commerce_SnipeBot
python3 -m venv .venv
source .venv/bin/activate
```

You should see `(.venv)` at the beginning of your command prompt, indicating the virtual environment is active.

### Step 4: Install Requirements

With the virtual environment activated, install all dependencies:

```
pip install -r requirements.txt
```

This will install:
- `playwright` - Browser automation framework
- `playwright-stealth` - Stealth plugin to avoid detection
- `greenlet` - Lightweight concurrent programming
- `pyee` - Event emitter implementation
- `pyrefly` - Additional utilities
- `typing_extensions` - Type hints support

### Step 5: Install Playwright Browsers

After installing the requirements, install the Playwright browser binaries:

```
playwright install chromium
```

This downloads the Chromium browser that Playwright will use for automation.

## Configuration

### Step 1: Create Environment File

Copy the example environment file:

**Windows:**
```
copy .env.example .env
```

**Linux/Mac:**
```
cp .env.example .env
```

### Step 2: Edit Configuration

Open the `.env` file in a text editor and configure the following:

**Basic Settings:**
- `STORE_NAME` - The e-commerce platform (currently supports "Lazada")
- `ACTION` - Set to `buy` for purchasing, `scrape` for monitoring, or `buy_scrape` to scan a category page and auto-buy all matching in-stock products
- `TARGET_QUANTITY` - Number of items to purchase (default: 1)

**Timing Settings:**
- `RELEASE_TIME` - When to start the bot:
  - Leave empty for immediate execution
  - Use "test" or "TEST" for 2 minutes from current time
  - Use specific datetime: `2026-05-20 19:45:00`
- `REFRESH_LEAD_SECONDS` - How many seconds before release time to start refreshing (default: 5)
- `TEST_REFRESH_DURATION` - For testing, keep refreshing even when in stock (default: 0)

**Account Configuration:**

For each account you want to use, configure:
- `ACCOUNT_X_URL` - Product URL to target
- `ACCOUNT_X_EMAIL` - Login email
- `ACCOUNT_X_PASSWORD` - Login password

Replace `X` with account number (1, 2, 3, etc.). You can configure multiple accounts for parallel execution.

> **For `buy_scrape` mode:** `ACCOUNT_X_URL` is optional — the scrape target comes from `SCRAPER_TARGET_URL`. Only `ACCOUNT_X_EMAIL` and `ACCOUNT_X_PASSWORD` are needed for login. Each account independently scrapes and buys from the same `SCRAPER_TARGET_URL`.

**Example:**
```
ACCOUNT_1_URL=https://www.lazada.sg/products/example-product-i1234567890.html
ACCOUNT_1_EMAIL=myemail@example.com
ACCOUNT_1_PASSWORD=mySecurePassword123
```

**Proxy Settings (Optional):**
- `PROXY_URL` - HTTP/HTTPS proxy URL if needed (leave empty if not using proxy)
  - Format: `http://proxy.example.com:8080` or `https://proxy.example.com:8080`
  - For authenticated proxies: `http://username:password@proxy.example.com:8080`
  - The scheme (http://) is optional - if omitted, http:// will be prepended automatically
  - Supports HTTP, HTTPS, and SOCKS5 proxies

### Step 3: Scraper Configuration (Optional)

These settings apply when `ACTION=scrape` or `ACTION=buy_scrape`. They control how the bot monitors products and collects data. All have sensible defaults and none are required — the scraper works out of the box.

In **`buy_scrape` mode**, the scraper runs first to find in-stock products, then the bot logs in and purchases each matching product automatically.

**Basic Scraper Settings:**
- `SCRAPER_STORE_NAME` - Store to scrape (default: uses `STORE_NAME`)
- `SCRAPER_TARGET_URL` - URL of the search/category page to scrape (required for scrape mode)

**Product Filtering:**
- `SCRAPER_PRODUCT_NAMES` - Comma-separated product names to monitor (leave empty to scrape all products). Matching is **case-insensitive, visible text, substring** — not regex. For example, `RTX 4090` will match a product named "ASUS RTX 4090 Gaming OC Edition"

**Delay & Anti-Detection:**
- `SCRAPER_DELAY` - Seconds to wait between each product detail check (default: `1.5`; recommended 1.5–3.0)
- `SCRAPER_RANDOM_DELAY` - Add random variation to delays for human-like behavior (default: `true`)

**Page Loading:**
- `SCRAPER_SCROLL_COUNT` - How many times to scroll down per page to trigger lazy loading (default: `5`)
- `SCRAPER_MAX_PAGES` - Max pagination pages to scrape (default: `0` = unlimited)

**Continuous Monitoring:**
- `SCRAPER_CONTINUOUS_MODE` - Keep scraping in an infinite loop (default: `false`)
- `SCRAPER_LOOP_INTERVAL` - Seconds to wait between cycles when continuous mode is on (default: `300`, i.e. 5 minutes)

**Example `.env` snippet for scrape mode:**
```env
ACTION=scrape
SCRAPER_TARGET_URL=https://www.lazada.sg/shop-gaming-laptops/
SCRAPER_PRODUCT_NAMES=RTX 4090,RTX 4080
SCRAPER_DELAY=2.0
SCRAPER_CONTINUOUS_MODE=true
SCRAPER_LOOP_INTERVAL=300
```

**Example `.env` snippet for buy_scrape mode:**
```env
ACTION=buy_scrape
SCRAPER_TARGET_URL=https://www.lazada.sg/shop-gaming-laptops/
SCRAPER_PRODUCT_NAMES=RTX 4090,RTX 4080
SCRAPER_DELAY=2.0
SCRAPER_MAX_PAGES=3

# Account credentials (URL not needed — bot uses SCRAPER_TARGET_URL)
ACCOUNT_1_EMAIL=myemail@example.com
ACCOUNT_1_PASSWORD=mySecurePassword123

TARGET_QUANTITY=1
```

**How buy_scrape works step by step:**
1. Bot navigates to `SCRAPER_TARGET_URL` (category/search page)
2. Scrolls to load all product cards, extracts name + price + link for each
3. Filters by `SCRAPER_PRODUCT_NAMES` (case-insensitive substring on visible text)
4. Visits each matching product's detail page to check stock status
5. Logs in with `ACCOUNT_X_EMAIL` / `ACCOUNT_X_PASSWORD`
6. Calls `buy_item()` on every in-stock product's link — **buys immediately** (scraper already confirmed stock; no polling/waiting)

> **Accounts vs. products:** One account buys ALL matching in-stock products sequentially. If 3 products match and are in stock, 1 account buys all 3 (not 1 per account). Multiple accounts are for parallel redundancy — each account independently scrapes and attempts to buy all matches, increasing your odds.
>
> **Timing note:** `RELEASE_TIME` and `REFRESH_LEAD_SECONDS` have no effect in `buy_scrape` mode. The scraper runs immediately, and once a product is confirmed in stock, `buy_item()` purchases it right away — no countdown, no polling loop. If you need scheduled execution, launch the bot via Task Scheduler / cron at the desired time.

**Where scraped data is saved:**
- Full results: `data/scrapes/run_logs/lazada_scrape-[timestamp].json`
- In-stock only: `data/scrapes/in_stock/lazada_in_stock-[timestamp].json`

## Running the Bot

### Activate Virtual Environment

Before running, always activate the virtual environment:

**Windows:**
```
.venv\Scripts\activate
```

**Linux/Mac:**
```
source .venv/bin/activate
```

### Start the Bot

Run the main script:

```
python main.py
```

The bot will:
1. Display a menu showing your configuration
2. Launch browser windows for each configured account
3. Attempt auto-login or prompt for manual login
4. Wait until the scheduled release time (if configured)
5. Monitor product availability
6. Automatically purchase when in stock

### Stopping the Bot

To stop the bot:
- Press `Ctrl+C` in the terminal
- Close the browser windows manually

## Understanding the Logs

The bot provides detailed logging to help you understand what's happening. Here's what each log prefix means:

### Main Process Logs

**[Main]** - Main process initialization and configuration
- Example: `[Main] TEST MODE: Release time set to 2026-05-20 19:45:00`
- Indicates: Bot startup, configuration loading, and mode selection

**[Warning]** - Non-critical warnings
- Example: `[Warning] No parallel accounts configured in .env`
- Indicates: Configuration issues that won't stop execution but may affect functionality

### Account-Specific Logs

**[Account-X]** - Logs from specific account threads (X = account number)
- Example: `[Account-1] Launching instance...`
- Indicates: Actions performed by each parallel account instance

### Traffic Cop Logs (Browser Management)

**[Traffic Cop]** - Browser initialization and session management
- `Launching browser — BUY on Lazada...` - Browser starting
- `Checking Lazada login session...` - Verifying if already logged in
- `No session found — redirecting to login page` - Need to login
- `Attempting auto-login using email: xxx` - Trying automatic login
- `Auto-login succeeded! Active session confirmed` - Login successful
- `>>> PLEASE SIGN IN MANUALLY in this browser window <<<` - Manual login required
- `Login confirmed — proceeding` - Ready to continue
- `Done — closing browser` - Browser cleanup

### Sniper Logs (Purchase Module)

**[Sniper]** - Product monitoring and purchase execution
- `=== Lazada Sniper Module ===` - Sniper module started
- `Opening product page...` - Loading target product
- `Release at [time] — idling Xs then refreshing` - Waiting for scheduled time
- `Polling stock (refreshing until OOS clears)...` - Checking availability
- `#X — still OOS, refreshing...` - Product out of stock, attempt X
- `IN STOCK on attempt #X!` - Product available!
- `Qty: X` - Quantity set successfully
- `Clicking Buy Now...` - Initiating purchase
- `Buy Now clicked, waiting for navigation...` - Proceeding to checkout
- `Proceeding to checkout...` - On checkout page
- `Scrolling down to find Place Order button...` - Looking for final button
- `Place Order clicked successfully` - Order submitted
- `Order confirmation page reached` - Purchase complete!
- `ERROR: Place Order button not found — keeping browser open for manual intervention` - Bot cannot find the Place Order button automatically. The browser window will remain open so you can manually complete the order. Press ENTER in the terminal after completing the order to close the browser.
- `ERROR: Place Order click failed ([error]) — keeping browser open for manual intervention` - Bot found the button but clicking failed. The browser window will remain open for manual completion. Press ENTER in the terminal after completing the order to close the browser.
- `>>> Press ENTER to close the browser and continue... <<<` - Waiting for you to confirm manual order completion before closing the browser

### Scraper Logs (Monitoring Module)

**[Lazada]** - Product scraping and monitoring
- `Navigating to: [URL]` - Loading page
- `Scrolling X times to trigger lazy loading...` - Loading all products
- `[Detail Check] Checking: [product name]` - Examining product details
- `Full results saved to: [path]` - Data saved to file

### General Logs

**[*]** - Utility functions
- `Sleeping for X seconds...` - Random delay to appear human-like

### Status Messages

At the end of execution, you'll see:

**EXECUTION SUMMARY** - Final results for all accounts
- `SUCCESS: Order placed` - Purchase completed successfully
- `FAILED: Out of stock after X attempts` - Could not purchase
- `ERROR: [description]` - An error occurred
- `CRASHED: [exception]` - Unexpected failure

## Troubleshooting

### Virtual Environment Issues

**Problem:** Cannot activate virtual environment

**Solution:**
- Windows: Run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` in PowerShell
- Recreate the virtual environment: Delete `.venv` folder and repeat Step 3

### Installation Issues

**Problem:** `pip install` fails

**Solution:**
- Update pip: `python -m pip install --upgrade pip`
- Install packages one by one to identify the problematic package
- Check your internet connection

**Problem:** Playwright installation fails

**Solution:**
- Run: `python -m playwright install chromium`
- If still failing, try: `python -m playwright install --force chromium`

### Login Issues

**Problem:** Auto-login fails

**Solution:**
- Verify credentials in `.env` file are correct
- Check for CAPTCHA or slider verification (requires manual login)
- Ensure account is not locked or requires verification

**Problem:** Manual login prompt appears

**Solution:**
- This is normal if auto-login fails or credentials are not provided
- Simply login manually in the browser window
- The bot will detect successful login and continue automatically

### Execution Issues

**Problem:** Bot says "Out of stock" immediately

**Solution:**
- Verify the product URL is correct
- Check if product is actually available on the website
- Increase `REFRESH_LEAD_SECONDS` to start checking earlier

**Problem:** "Place Order button not found"

**Solution:**
- The checkout page layout may have changed
- When prompted, complete the order manually in the browser
- Report the issue for bot updates

**Problem:** Browser closes immediately

**Solution:**
- Check terminal for error messages
- Verify `.env` configuration is correct
- Ensure virtual environment is activated

### Performance Issues

**Problem:** Bot is too slow

**Solution:**
- Reduce `REFRESH_LEAD_SECONDS` for faster execution
- Ensure good internet connection
- Close other applications using bandwidth

**Problem:** Getting detected/blocked

**Solution:**
- Add delays between actions (already implemented)
- Use proxy if available (configure `PROXY_URL`)
- Avoid running too many parallel accounts

## Developer Reference

This project utilizes `playwright` with a robust traffic cop architecture built in `bot_logic.py`.
- **Session Routing**: The `start_browser_and_route` function initializes Playwright's Stealth plugin, dynamically configures CDP window snapping using `_snap_window_cdp()`, and routes to specific store modules (e.g. `action == "buy_scrape"` vs `"scrape"`).
- **Session Recovery**: `bot_logic.py` exposes `_check_and_recover_login`, a persistent fallback checker used extensively during the checkout loop. If Playwright is unexpectedly redirected to a login challenge (or if a popup appears mid-captcha), this function halts the main sniper loop, invokes `_handle_login`, restores the valid session cookie, and allows the bot to retry the purchase seamlessly.
- **Headless Mode Optimization**: When `action == "scrape"`, the `bot_logic.py` utilizes a custom request interceptor (`_block_resources`) on the Playwright `Route` object to drop heavy assets like CSS, images, and fonts to save bandwidth.

## Support

For issues or questions:
1. Check the logs carefully - they usually indicate the problem
2. Verify your configuration in `.env` file
3. Ensure all installation steps were completed
4. Check that the product URL is valid and accessible

## Legal Disclaimer

This bot is for educational purposes only. Use responsibly and in accordance with the terms of service of the e-commerce platforms you interact with. Automated purchasing may violate platform policies.
