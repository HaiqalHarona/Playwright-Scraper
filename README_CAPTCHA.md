# Playwright E-Commerce Captcha Solver

A high-performance, robust CAPTCHA resolution system designed specifically to bypass modern bot-detection and verification walls (e.g., Lazada, Alibaba, Taobao) within a Playwright-driven Python automation browser.

---

## Features

### 1. Frame-Aware reCAPTCHA v2 Solver
* **Cross-Origin Iframe Targeting**: Iterates through all nested frames (`page.frames`) to find the isolated iframe where the reCAPTCHA widget lives (e.g., `baxia.taobao.com`).
* **Token Injection & Dispatching**: Injects the resolved CapMonster token directly into standard hidden textareas (`g-recaptcha-response`) inside the correct iframe's DOM.
* **Framework Events**: Dispatches simulated standard browser events (`input`, `change`) on inputs so that frontend frameworks (React, Vue, Angular) register the value changes.
* **Automatic Callback Triggering**: Evaluates the global `window.___grecaptcha_cfg` configuration object inside the correct context and automatically fires the corresponding callbacks.

### 2. Jigsaw Puzzle Slider Solver
* **Coordinate Extraction**: Identifies and screenshots the background and slide piece elements, converting them to Base64 payloads.
* **CapMonster ComplexImageTask**: Submits both images to the CapMonster API to receive precise alignment coordinates.
* **Human-like Drag Actions**: Uses Playwright mouse movement tools to simulate linear/curved speed offsets and click-and-drag mechanics to simulate natural interaction.

### 3. Slide-to-Verify (Alibaba/Lazada NoCaptcha)
* **Single Container Captures**: Screenshots full slider wrappers when separate background/piece components are missing, using CapMonster OCR to estimate pixel offsets.
* **Fallback Mechanisms**: Automatically falls back to traditional coordinate estimations and sliding.

### 4. Alphanumeric OCR Captcha
* **Multi-Selector Image Detection**: Recognizes dynamic captcha images and input fields using heuristic DOM scanning.
* **SDK & Raw HTTP Parallel Integration**: Utilizes the `capmonster_python` SDK client with automatic fallback to direct HTTP post-requests to guarantee API responsiveness.
* **Automated Failure Refresh**: Clears inputs, submits, evaluates success, and auto-refreshes/retries on incorrect guesses (up to configurable retries limit).

---

## Configuration

Add your CapMonster Cloud API key inside the `.env` file at the project root:

```ini
CAPMONSTER_CLOUD=your_capmonster_api_key_here
```

---

## Usage

### Direct Solver Calls
You can trigger specialized solvers directly inside your automation script:

```python
from playwright.sync_api import sync_playwright
from captcha_solver import solve_recaptcha_v2, solve_alphanumeric_captcha

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto("https://example.com/login")
    
    # Solve any standard reCAPTCHA present on the page
    success = solve_recaptcha_v2(page)
    if success:
        print("reCAPTCHA bypassed successfully.")
```

### Master Orchestrator (Automatic Multi-Captcha Resolution)
Use `resolve_any_captcha` to scan and resolve any known captcha pattern sequentially (OCR, reCAPTCHA, and sliders/jig-saws):

```python
from captcha_solver import resolve_any_captcha

# Scans the active page and attempts solving up to 3 rounds of challenges
resolved = resolve_any_captcha(page, max_rounds=3)
```

### Global Captcha Interceptor Hook
Attach a non-blocking hook to automatically run the master orchestrator every time a new page or navigation load is triggered:

```python
from captcha_solver import attach_global_captcha_hook

# Hook auto-attaches to the page lifecycle
attach_global_captcha_hook(page)

# Subsequent navigations will now auto-bypass captcha walls on load
page.goto("https://www.lazada.sg/")
```

---

## Technical Architecture

```mermaid
graph TD
    A[Page Navigation / Captcha Appears] --> B[Global Navigation Hook / Manual Trigger]
    B --> C{resolve_any_captcha}
    
    C -->|reCAPTCHA v2 Checkbox| D[solve_recaptcha_v2]
    C -->|Alphanumeric OCR| E[solve_alphanumeric_captcha]
    C -->|Sliders / Slideways| F[solve_slide_to_verify / solve_jigsaw_puzzle_official]
    
    D --> D1[Extract sitekey via DOM parsing]
    D1 --> D2[Request Token from CapMonster API]
    D2 --> D3[Loop through all page.frames]
    D3 --> D4[Inject token and fire ___grecaptcha_cfg callbacks in isolated contexts]
    
    E --> E1[Grab Image Base64]
    E1 --> E2[CapMonster OCR API Call]
    E2 --> E3[Fill text field & submit]
    
    F --> F1[Grab background + piece screenshot]
    F1 --> F2[CapMonster ComplexImageTask]
    F2 --> F3[Drag Slider Knobs via Mouse simulation]
```
