# Scraper Configuration Guide

This guide explains the new scraper-specific configuration options added to the E-Commerce SnipeBot.

## Overview

The scraper now supports advanced configuration options that allow you to:
- Target specific products by name
- Control scraping speed and delays
- Enable continuous monitoring mode
- Limit pagination depth
- Customize scroll behavior

## Configuration Options

All scraper configurations are set in the `.env` file. These settings apply when `ACTION=scrape` or `ACTION=buy_scrape`.

### Basic Configuration

#### SCRAPER_STORE_NAME
- **Description**: The store to scrape (can be different from STORE_NAME for buy mode)
- **Default**: Uses `STORE_NAME` if not specified
- **Example**: `SCRAPER_STORE_NAME=Lazada`

#### SCRAPER_TARGET_URL
- **Description**: The URL to scrape for products (e.g., category page, search results)
- **Required**: Yes (when using scrape mode)
- **Example**: `SCRAPER_TARGET_URL=https://www.lazada.sg/shop-laptops/`

### Product Filtering

#### SCRAPER_PRODUCT_NAMES
- **Description**: Comma-separated list of product names to continuously monitor for stock
- **Default**: Empty (scrapes all products)
- **Format**: Comma-separated values
- **Example**: `SCRAPER_PRODUCT_NAMES=iPhone 15 Pro,Samsung Galaxy S24,MacBook Pro M3`
- **Behavior**: The scraper will filter products containing any of these names (case-insensitive partial matching)

### Performance & Rate Limiting

#### SCRAPER_DELAY
- **Description**: Delay in seconds between each product detail page check
- **Default**: `1.5`
- **Recommended**: 1.5-3 seconds
- **Purpose**: Prevents rate limiting and CAPTCHA triggers
- **Example**: `SCRAPER_DELAY=2.0`

#### SCRAPER_RANDOM_DELAY
- **Description**: Add random variation to scraper delay to appear more human-like
- **Default**: `true`
- **Options**: `true` or `false`
- **Example**: `SCRAPER_RANDOM_DELAY=true`

#### SCRAPER_SCROLL_COUNT
- **Description**: Number of times to scroll down on listing pages to load lazy-loaded products
- **Default**: `5`
- **Range**: 1-20 (higher values load more products but take longer)
- **Example**: `SCRAPER_SCROLL_COUNT=10`

### Pagination Control

#### SCRAPER_MAX_PAGES
- **Description**: Maximum number of pagination pages to scrape
- **Default**: `0` (unlimited - scrape all pages)
- **Example**: `SCRAPER_MAX_PAGES=5`
- **Use Case**: Limit scraping to first N pages for faster results

### Continuous Monitoring

#### SCRAPER_CONTINUOUS_MODE
- **Description**: Keep scraping continuously in a loop
- **Default**: `false` (scrape once and exit)
- **Options**: `true` or `false`
- **Example**: `SCRAPER_CONTINUOUS_MODE=true`
- **Use Case**: Monitor products for stock changes over time

#### SCRAPER_LOOP_INTERVAL
- **Description**: Time in seconds to wait between scraping cycles when continuous mode is enabled
- **Default**: `300` (5 minutes)
- **Recommended**: 300-600 seconds (5-10 minutes)
- **Example**: `SCRAPER_LOOP_INTERVAL=600`

## Example Configurations

### Example 1: Quick Single Scrape
```env
ACTION=scrape
SCRAPER_TARGET_URL=https://www.lazada.sg/shop-laptops/
SCRAPER_DELAY=1.5
SCRAPER_MAX_PAGES=3
SCRAPER_CONTINUOUS_MODE=false
```

### Example 2: Monitor Specific Products
```env
ACTION=scrape
SCRAPER_TARGET_URL=https://www.lazada.sg/shop-smartphones/
SCRAPER_PRODUCT_NAMES=iPhone 15 Pro,Samsung Galaxy S24 Ultra
SCRAPER_DELAY=2.0
SCRAPER_CONTINUOUS_MODE=true
SCRAPER_LOOP_INTERVAL=300
```

### Example 3: Deep Scrape All Pages
```env
ACTION=scrape
SCRAPER_TARGET_URL=https://www.lazada.sg/shop-gaming-laptops/
SCRAPER_DELAY=2.5
SCRAPER_SCROLL_COUNT=10
SCRAPER_MAX_PAGES=0
SCRAPER_CONTINUOUS_MODE=false
```

### Example 4: Fast Monitoring with Limits
```env
ACTION=scrape
SCRAPER_TARGET_URL=https://www.lazada.sg/shop-graphics-cards/
SCRAPER_PRODUCT_NAMES=RTX 4090,RTX 4080
SCRAPER_DELAY=1.5
SCRAPER_MAX_PAGES=2
SCRAPER_CONTINUOUS_MODE=true
SCRAPER_LOOP_INTERVAL=180
```

## How It Works

### Product Name Filtering
When you specify product names in `SCRAPER_PRODUCT_NAMES`:
1. The scraper collects all products from the listing pages
2. Filters products whose names contain any of the specified keywords (case-insensitive)
3. Only checks stock status for matching products
4. Saves filtered results separately

### Continuous Mode
When `SCRAPER_CONTINUOUS_MODE=true`:
1. The scraper runs in an infinite loop
2. After each cycle, it waits for `SCRAPER_LOOP_INTERVAL` seconds
3. Displays cycle number and in-stock count
4. Highlights target products that are in stock
5. Continues until manually stopped (Ctrl+C)

> **Developer Syntax Note:** These settings directly interact with `bot_logic.py`'s `start_browser_and_route()` function. For `action == 'buy_scrape'`, the continuous mode wraps around Phase 1 (Scraping), repeating until an in-stock item is found, upon which it proceeds to Phase 2 (Login) and Phase 3 (Purchasing).

### Delay Strategy
- **Fixed Delay**: Set by `SCRAPER_DELAY`
- **Random Delay**: When `SCRAPER_RANDOM_DELAY=true`, adds random variation (uses `utils.random_delay()`)
- **Purpose**: Mimics human browsing behavior to avoid detection

## Output Files

The scraper saves two types of files in the `data/scrapes/` directory:

### Full Results
- **Location**: `data/scrapes/run_logs/`
- **Format**: `lazada_scrape-DD-MM-YYYY_HH-MM.json`
- **Contains**: All scraped products with stock status

### In-Stock Only
- **Location**: `data/scrapes/in_stock/`
- **Format**: `lazada_in_stock-DD-MM-YYYY_HH-MM.json`
- **Contains**: Only products that are currently in stock

## Best Practices

1. **Start Conservative**: Begin with higher delays (2-3 seconds) to avoid CAPTCHA
2. **Use Product Filtering**: When monitoring specific items, use `SCRAPER_PRODUCT_NAMES` to reduce load
3. **Limit Pages**: Use `SCRAPER_MAX_PAGES` for faster results when you don't need all products
4. **Continuous Monitoring**: Set reasonable intervals (5-10 minutes) to avoid excessive requests
5. **Random Delays**: Keep `SCRAPER_RANDOM_DELAY=true` for more human-like behavior

## Troubleshooting

### CAPTCHA Issues
- **Solution**: Increase `SCRAPER_DELAY` to 2.5-3.0 seconds
- **Enable**: `SCRAPER_RANDOM_DELAY=true`

### Slow Scraping
- **Solution**: Reduce `SCRAPER_SCROLL_COUNT` to 3-5
- **Limit**: Set `SCRAPER_MAX_PAGES` to a lower number
- **Filter**: Use `SCRAPER_PRODUCT_NAMES` to target specific products

### Missing Products
- **Solution**: Increase `SCRAPER_SCROLL_COUNT` to 8-10
- **Check**: Ensure `SCRAPER_MAX_PAGES=0` for unlimited pagination

### High Resource Usage
- **Solution**: Increase `SCRAPER_LOOP_INTERVAL` in continuous mode
- **Limit**: Set `SCRAPER_MAX_PAGES` to reduce scope

## Notes

- All scraper settings are optional and have sensible defaults
- Settings only apply when `ACTION=scrape`
- The scraper respects rate limits and includes anti-CAPTCHA delays
- Continuous mode runs indefinitely until manually stopped
- Product name matching is case-insensitive and uses partial matching
