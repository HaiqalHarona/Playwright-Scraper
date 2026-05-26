# captcha_solver.py
import base64
import os
import time
import requests  # type: ignore[import-untyped]
from playwright.sync_api import Page

# capmonster_python SDK (synchronous client — no asyncio needed)
try:
    from capmonster_python import CapmonsterClient, ImageToTextTask

    SDK_AVAILABLE = True
except ImportError:
    SDK_AVAILABLE = False


# ---------------------------------------------------------------------------
# Internal helpers — CapMonster SDK (OCR only; SDK has no slider task type)
# ---------------------------------------------------------------------------


def _solve_ocr_sdk(img_b64: str) -> str:
    """Solve alphanumeric image captcha via capmonster_python SDK."""
    api_key = os.getenv("CAPMONSTER_CLOUD")
    if not api_key:
        raise ValueError("CAPMONSTER_CLOUD key is missing in .env")
    client = CapmonsterClient(api_key=api_key)
    task = ImageToTextTask(body=img_b64.replace("\n", "").replace("\r", ""))
    result = client.solve(task)
    # SDK returns the solution dict; text captcha result is in "text" key
    if isinstance(result, dict):
        return result.get("text", "")
    return str(result)


# ---------------------------------------------------------------------------
# Raw HTTP fallback — handles both OCR and slider ComplexImageTask
# ---------------------------------------------------------------------------


def _solve_via_raw_http(
    bg_b64: str,
    piece_b64: str | None = None,
    task_type: str = "ImageToTextTask",
) -> str:
    """
    Submit a task to CapMonster Cloud via raw HTTP.
    task_type: "ImageToTextTask" for OCR, "ComplexImageTask" for slider/jigsaw.
    Returns the text result or pixel offset as a string, or "" on failure.
    """
    api_key = os.getenv("CAPMONSTER_CLOUD")
    if not api_key:
        print("[Captcha Solver] Error: CAPMONSTER_CLOUD key is missing in .env")
        return ""

    try:
        clean_bg = bg_b64.replace("\n", "").replace("\r", "")

        if task_type == "ImageToTextTask":
            task_payload: dict = {"type": "ImageToTextTask", "body": clean_bg}
        else:
            # Slider / jigsaw — CapMonster ComplexImageTask with class "slider"
            clean_piece = (
                piece_b64.replace("\n", "").replace("\r", "") if piece_b64 else ""
            )
            task_payload = {
                "type": "ComplexImageTask",
                "class": "slider",
                "imageUrls": [clean_bg],
                "metadata": {"target": clean_piece},
            }

        create_res = requests.post(
            "https://api.capmonster.cloud/createTask",
            json={"clientKey": api_key, "task": task_payload},
            timeout=10,
        )
        create_data = create_res.json()
        if create_data.get("errorId", 1) != 0:
            print(
                f"[Captcha Solver] CapMonster API Error: {create_data.get('errorDescription')}"
            )
            return ""

        task_id = create_data.get("taskId")
        for _ in range(30):
            time.sleep(1.5)
            result_res = requests.post(
                "https://api.capmonster.cloud/getTaskResult",
                json={"clientKey": api_key, "taskId": task_id},
                timeout=10,
            )
            result_data = result_res.json()
            if result_data.get("status") == "ready":
                solution = result_data.get("solution", {})
                if task_type == "ImageToTextTask":
                    return solution.get("text", "")
                else:
                    return str(solution.get("x", 0))
        return ""
    except Exception as e:
        print(f"[Captcha Solver] Raw HTTP error: {e}")
        return ""


# ---------------------------------------------------------------------------
# Shared slider helpers
# ---------------------------------------------------------------------------


def _capmonster_solve_slider(bg_b64: str, piece_b64: str) -> int:
    """
    Submit a slider challenge to CapMonster via raw HTTP ComplexImageTask.
    SDK does not support the slider class, so raw HTTP is always used here.
    Returns pixel offset to drag, or 0 on failure.
    """
    raw = _solve_via_raw_http(bg_b64, piece_b64, task_type="ComplexImageTask")
    try:
        return int(raw) if raw else 0
    except (ValueError, TypeError):
        return 0


def _drag_slider(page: Page, knob_selector: str, offset_x: int) -> bool:
    """Perform the actual mouse drag on the slider knob element."""
    knob_candidates = [
        knob_selector,
        "#nc_1_n1z",
        "[class*='slider-knob']",
        ".slider-button",
        "[class*='btn_slide']",
        ".nc-lang-en-US .nc_scale span",
        "[class*='nc_scale'] span",
        "[class*='slider'] span",
        "[class*='drag-btn']",
        "[class*='slide-btn']",
    ]

    slider_knob = None
    for sel in knob_candidates:
        try:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible():
                slider_knob = el
                break
        except Exception:
            pass

    if not slider_knob:
        print("[Captcha Solver] Failed to find the slider drag knob.")
        return False

    box = slider_knob.bounding_box()
    if not box:
        return False

    x_start = box["x"] + box["width"] / 2
    y_start = box["y"] + box["height"] / 2

    page.mouse.move(x_start, y_start)
    page.mouse.down()
    page.mouse.move(x_start + offset_x, y_start, steps=20)
    time.sleep(0.15)
    page.mouse.up()
    return True


# ---------------------------------------------------------------------------
# Public solver: alphanumeric OCR captcha
# ---------------------------------------------------------------------------


def solve_alphanumeric_captcha(page: Page, max_retries: int = 3) -> bool:
    """Detect and solve standard alphanumeric image captchas via CapMonster."""
    image_selectors = [
        "img[src*='captcha']",
        "img[src*='getCaptcha']",
        "img[src*='code']",
        "img[id*='captcha']",
        ".captcha-img",
        "[class*='captcha-image']",
        "[class*='verify-img'] img",
        "[class*='geetest'] img",
    ]
    input_selectors = [
        "input[placeholder*='code']",
        "input[placeholder*='captcha']",
        "input[name*='captcha']",
        "input[name*='code']",
        ".captcha-input input",
        "input[aria-label*='aptcha']",
        "[class*='verify-input'] input",
    ]

    img_el = None
    for sel in image_selectors:
        try:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible():
                img_el = el
                break
        except Exception:
            pass

    if not img_el:
        return False

    print("[Captcha Solver] Alphanumeric Image Captcha detected! Resolving...")

    input_el = None
    for sel in input_selectors:
        try:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible():
                input_el = el
                break
        except Exception:
            pass

    if not input_el:
        print("[Captcha Solver] Alphanumeric input element not found.")
        return False

    for attempt in range(1, max_retries + 1):
        try:
            print(f"[Captcha Solver] OCR Attempt {attempt}/{max_retries}...")
            time.sleep(1.0)

            img_bytes = img_el.screenshot()
            img_b64 = base64.b64encode(img_bytes).decode("utf-8")

            solved_text = ""
            if SDK_AVAILABLE:
                try:
                    solved_text = _solve_ocr_sdk(img_b64)
                except Exception as sdk_err:
                    print(
                        f"[Captcha Solver] SDK OCR failed ({sdk_err}), falling back to HTTP..."
                    )

            if not solved_text:
                solved_text = _solve_via_raw_http(img_b64, task_type="ImageToTextTask")

            if not solved_text:
                print("[Captcha Solver] CapMonster returned no OCR result.")
                continue

            print(f"[Captcha Solver] Decoded text: '{solved_text}'")
            input_el.click()
            input_el.fill("")
            input_el.type(solved_text, delay=60)
            input_el.press("Enter")
            time.sleep(2.5)

            if not img_el.is_visible():
                print("[Captcha Solver] ✓ OCR Captcha bypassed successfully!")
                return True

            print("[Captcha Solver] OCR answer incorrect. Refreshing captcha...")
            try:
                img_el.click()
            except Exception:
                pass

        except Exception as e:
            print(f"[Captcha Solver] Error during OCR solve: {e}")

    return False


# ---------------------------------------------------------------------------
# Public solver: jigsaw puzzle slider
# ---------------------------------------------------------------------------


def solve_jigsaw_puzzle_official(
    page: Page, bg_selector: str, piece_selector: str
) -> bool:
    """Solve a jigsaw slider captcha using CapMonster ComplexImageTask coordinates."""
    try:
        bg_element = page.locator(bg_selector).first
        piece_element = page.locator(piece_selector).first

        if not bg_element.is_visible() or not piece_element.is_visible():
            return False

        bg_b64 = base64.b64encode(bg_element.screenshot()).decode("utf-8")
        piece_b64 = base64.b64encode(piece_element.screenshot()).decode("utf-8")

        print("[Captcha Solver] Submitting jigsaw challenge to CapMonster Cloud...")
        offset_x = _capmonster_solve_slider(bg_b64, piece_b64)

        if not offset_x:
            print("[Captcha Solver] CapMonster failed to identify jigsaw coordinates.")
            return False

        print(
            f"[Captcha Solver] Jigsaw offset received: {offset_x}px. Performing drag..."
        )
        return _drag_slider(page, "#nc_1_n1z", offset_x)

    except Exception as e:
        print(f"[Captcha Solver] Jigsaw solve exception: {e}")
        return False


# ---------------------------------------------------------------------------
# Public solver: slide-to-verify (NoCaptcha/Alibaba slider) via CapMonster
# ---------------------------------------------------------------------------


def solve_slide_to_verify(page: Page, slider_selector: str = "#nc_1_n1z") -> bool:
    """
    Solve Alibaba/Lazada slide-to-verify (NoCaptcha) using CapMonster ComplexImageTask.
    Screenshots the background + piece, sends to CapMonster, drags to the returned offset.
    """
    try:
        container_selectors = [
            "[class*='nc-container']",
            "[class*='nc_wrapper']",
            "[id*='nc_']",
            ".nc_scale",
            "[class*='next-slider']",
            "[class*='nocaptcha']",
            "[class*='baxia']",
        ]

        container = None
        for sel in container_selectors:
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    container = el
                    break
            except Exception:
                pass

        if not container:
            try:
                el = page.locator(slider_selector).first
                if el.count() > 0 and el.is_visible():
                    container = el
                else:
                    return False
            except Exception:
                return False

        print(
            "[Captcha Solver] Slide-to-verify detected. Capturing challenge images..."
        )

        bg_el = None
        piece_el = None

        bg_candidates = [
            "canvas",
            "img[class*='bg']",
            "img[class*='background']",
            "[class*='nc-bg']",
            "[class*='verify-bg'] img",
            "[class*='slider-bg']",
        ]
        piece_candidates = [
            "[class*='nc-piece']",
            "[class*='verify-piece'] img",
            "[class*='slider-piece']",
            "img[class*='piece']",
            "[class*='drag-slide'] img",
        ]

        for sel in bg_candidates:
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    bg_el = el
                    break
            except Exception:
                pass

        for sel in piece_candidates:
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    piece_el = el
                    break
            except Exception:
                pass

        if bg_el and piece_el:
            print(
                "[Captcha Solver] Got bg + piece — sending to CapMonster ComplexImageTask..."
            )
            bg_b64 = base64.b64encode(bg_el.screenshot()).decode("utf-8")
            piece_b64 = base64.b64encode(piece_el.screenshot()).decode("utf-8")
            offset_x = _capmonster_solve_slider(bg_b64, piece_b64)
            if offset_x:
                print(f"[Captcha Solver] Slide offset from CapMonster: {offset_x}px")
                return _drag_slider(page, slider_selector, offset_x)
            print(
                "[Captcha Solver] CapMonster returned 0 — cannot solve this slide variant."
            )
            return False

        # No separate piece found — screenshot full container and try OCR as offset
        print(
            "[Captcha Solver] No separate piece element — screenshotting full container..."
        )
        try:
            container_b64 = base64.b64encode(container.screenshot()).decode("utf-8")
            offset_str = _solve_via_raw_http(container_b64, task_type="ImageToTextTask")
            if offset_str:
                try:
                    offset_x = int(offset_str.strip())
                    return _drag_slider(page, slider_selector, offset_x)
                except (ValueError, TypeError):
                    pass
        except Exception as ocr_err:
            print(f"[Captcha Solver] Container OCR fallback failed: {ocr_err}")
        return False

    except Exception as e:
        print(f"[Captcha Solver] solve_slide_to_verify exception: {e}")
        return False


# ---------------------------------------------------------------------------
# Public solver: reCAPTCHA v2 checkbox ("I'm not a robot")
# ---------------------------------------------------------------------------


def solve_recaptcha_v2(page: Page, max_wait: int = 120) -> bool:
    """
    Detect and solve a reCAPTCHA v2 checkbox via CapMonster RecaptchaV2TaskProxyless.
    Physically clicks the checkbox first, then injects the token and fires callbacks.
    """
    api_key = os.getenv("CAPMONSTER_CLOUD")
    if not api_key:
        return False

    # ── Step 1: Confirm a reCAPTCHA iframe or widget actually exists in the DOM ──────────
    # Check for multiple indicators of reCAPTCHA presence
    recaptcha_detected = False
    try:
        recaptcha_detected = page.evaluate("""
            () => {
                // 1. Check for recaptcha iframes
                if (document.querySelector('iframe[src*="recaptcha"], iframe[src*="google.com/recaptcha"]')) {
                    return true;
                }
                
                // 2. Check for div.g-recaptcha elements
                if (document.querySelector('div.g-recaptcha')) {
                    return true;
                }
                
                // 3. Check for data-sitekey attributes
                if (document.querySelector('[data-sitekey]')) {
                    return true;
                }
                
                // 4. Check for recaptcha script
                const scripts = document.querySelectorAll('script');
                for (const script of scripts) {
                    const src = script.src || '';
                    if (src.includes('recaptcha') || src.includes('google.com/recaptcha')) {
                        return true;
                    }
                }
                
                // 5. Check for recaptcha text in page
                const bodyText = document.body.innerText || '';
                if (bodyText.includes('recaptcha') || bodyText.includes('g-recaptcha')) {
                    return true;
                }
                
                return false;
            }
        """)
    except Exception:
        pass

    if not recaptcha_detected:
        return False

    print("[Captcha Solver] reCAPTCHA v2 detected (iframe/widget found).")

    # ── Step 2: Click the "I'm not a robot" checkbox ──────────────────────────
    # Must happen before token injection so the widget enters an active state.
    try:
        checkbox_frame = page.frame_locator(
            "iframe[src*='recaptcha/api2/anchor'], iframe[src*='recaptcha'][src*='anchor']"
        ).first
        checkbox = checkbox_frame.locator("#recaptcha-anchor")
        checkbox.wait_for(state="visible", timeout=8000)
        checkbox.click(timeout=5000)
        print("[Captcha Solver] ✓ reCAPTCHA checkbox clicked.")
        time.sleep(1.5)
    except Exception as click_err:
        print(
            f"[Captcha Solver] Checkbox click failed ({click_err}), continuing with token injection..."
        )

    # ── Step 3: Extract sitekey ────────────────────────────────────────────────
    sitekey = ""
    try:
        sitekey = page.evaluate("""
            () => {
                // 1. data-sitekey attribute on host page (any element)
                const el = document.querySelector('[data-sitekey]');
                if (el) return el.getAttribute('data-sitekey');
                
                // 2. data-sitekey on div.g-recaptcha
                const grecaptchaDiv = document.querySelector('div.g-recaptcha');
                if (grecaptchaDiv && grecaptchaDiv.getAttribute('data-sitekey')) {
                    return grecaptchaDiv.getAttribute('data-sitekey');
                }
                
                // 3. Parse k= from any recaptcha iframe src
                const frames = document.querySelectorAll('iframe[src*="recaptcha"]');
                for (const f of frames) {
                    const m = f.src.match(/[?&]k=([^&]+)/);
                    if (m) return m[1];
                }
                
                // 4. Check iframe data-sitekey attribute
                for (const f of frames) {
                    const sitekeyAttr = f.getAttribute('data-sitekey');
                    if (sitekeyAttr) return sitekeyAttr;
                }
                
                // 5. grecaptcha clients object (runtime)
                try {
                    const clients = window.___grecaptcha_cfg && window.___grecaptcha_cfg.clients;
                    if (clients) {
                        for (const c of Object.values(clients)) {
                            for (const w of Object.values(c)) {
                                if (w && w.sitekey) return w.sitekey;
                            }
                        }
                    }
                } catch(e) {}
                
                // 6. Look for sitekey in script tags (common pattern)
                const scripts = document.querySelectorAll('script');
                for (const script of scripts) {
                    const text = script.textContent || script.innerText;
                    const match = text.match(/sitekey\\s*[:=]\\s*['"]([^'"]+)['"]/);
                    if (match) return match[1];
                }
                
                // 7. Check hidden input fields
                const hiddenInputs = document.querySelectorAll('input[type="hidden"]');
                for (const input of hiddenInputs) {
                    if (input.name && input.name.includes('recaptcha') && input.value) {
                        // Some implementations store sitekey in value
                        if (input.value.length > 20 && input.value.length < 100) {
                            return input.value;
                        }
                    }
                }
                
                // 8. Check for recaptcha widget ID and try to get sitekey from window.grecaptcha
                try {
                    if (window.grecaptcha && window.grecaptcha.getResponse) {
                        // Try to find widget ID first
                        const widgetIdMatch = document.body.innerHTML.match(/recaptcha-widget-(\\d+)/);
                        if (widgetIdMatch) {
                            const widgetId = parseInt(widgetIdMatch[1]);
                            const sitekeyFromWidget = window.grecaptcha.getResponse(widgetId);
                            if (sitekeyFromWidget && typeof sitekeyFromWidget === 'string' && sitekeyFromWidget.length > 20) {
                                return sitekeyFromWidget;
                            }
                        }
                    }
                } catch(e) {}
                
                return '';
            }
        """)
    except Exception as e:
        print(f"[Captcha Solver] Could not extract reCAPTCHA sitekey: {e}")
        return False

    if not sitekey:
        print("[Captcha Solver] reCAPTCHA sitekey not found — cannot solve.")
        return False

    page_url = page.url
    print(
        f"[Captcha Solver] reCAPTCHA v2 detected. Sitekey: {sitekey[:20]}... Submitting to CapMonster..."
    )

    # Submit task
    try:
        create_res = requests.post(
            "https://api.capmonster.cloud/createTask",
            json={
                "clientKey": api_key,
                "task": {
                    "type": "RecaptchaV2TaskProxyless",
                    "websiteURL": page_url,
                    "websiteKey": sitekey,
                },
            },
            timeout=15,
        )
        create_data = create_res.json()
        if create_data.get("errorId", 1) != 0:
            print(
                f"[Captcha Solver] CapMonster reCAPTCHA error: {create_data.get('errorDescription')}"
            )
            return False
        task_id = create_data["taskId"]
    except Exception as e:
        print(f"[Captcha Solver] reCAPTCHA task submit failed: {e}")
        return False

    # Poll for result
    token = ""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        time.sleep(3)
        try:
            result_res = requests.post(
                "https://api.capmonster.cloud/getTaskResult",
                json={"clientKey": api_key, "taskId": task_id},
                timeout=10,
            )
            result_data = result_res.json()
            if result_data.get("status") == "ready":
                token = result_data.get("solution", {}).get("gRecaptchaResponse", "")
                break
            if result_data.get("errorId", 0) != 0:
                print(
                    f"[Captcha Solver] CapMonster poll error: {result_data.get('errorDescription')}"
                )
                return False
        except Exception as e:
            print(f"[Captcha Solver] reCAPTCHA poll error: {e}")

    if not token:
        print(
            "[Captcha Solver] reCAPTCHA: CapMonster returned no token within timeout."
        )
        return False

    print("[Captcha Solver] reCAPTCHA token received. Injecting into page...")

    # Inject token and fire callbacks
    try:
        page.evaluate(
            """
            (token) => {
                // Set the hidden textarea value
                const ta = document.getElementById('g-recaptcha-response');
                if (ta) {
                    ta.innerHTML = token;
                    ta.value = token;
                }
                // Also set all g-recaptcha-response textareas (multiple widgets)
                document.querySelectorAll('[name="g-recaptcha-response"]').forEach(el => {
                    el.innerHTML = token;
                    el.value = token;
                });
                // Fire the grecaptcha callback if available
                try {
                    const cb = document.querySelector('[data-callback]');
                    if (cb) {
                        const fn = cb.getAttribute('data-callback');
                        if (fn && window[fn]) window[fn](token);
                    }
                    // Also try to call ___grecaptcha_cfg callbacks
                    if (window.grecaptcha && window.grecaptcha.enterprise) {
                        // enterprise variant
                    } else if (window.___grecaptcha_cfg && window.___grecaptcha_cfg.clients) {
                        const clients = window.___grecaptcha_cfg.clients;
                        Object.values(clients).forEach(client => {
                            Object.values(client).forEach(widget => {
                                if (widget && typeof widget.callback === 'function') {
                                    widget.callback(token);
                                }
                            });
                        });
                    }
                } catch(e) {}
            }
        """,
            token,
        )
        time.sleep(1.5)

        # Try to also click the checkbox in the iframe as a fallback signal
        try:
            checkbox = page.frame_locator("iframe[src*='recaptcha']").first.locator(
                "#recaptcha-anchor"
            )
            if checkbox.count() > 0 and checkbox.is_visible():
                checkbox.click(timeout=3000)
                time.sleep(1)
        except Exception:
            pass

        print("[Captcha Solver] ✓ reCAPTCHA v2 token injected successfully.")
        return True
    except Exception as e:
        print(f"[Captcha Solver] reCAPTCHA token injection failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Master orchestrator
# ---------------------------------------------------------------------------

_CAPTCHA_TRIGGER_SELECTORS = [
    "#nc_1_n1z",
    ".nc_scale",
    "[class*='nc-container']",
    "[class*='nc_wrapper']",
    "[id^='nc_']",
    "[class*='next-slider']",
    "[class*='captcha-slider']",
    "[class*='slide-verify']",
    "[class*='nocaptcha']",
    "[class*='baxia-dialog']",
    "[class*='jigsaw']",
    "img[src*='captcha']",
    "img[src*='getCaptcha']",
    "img[src*='code']",
]

_JIGSAW_BG_SELECTORS = [
    ".captcha-background-img",
    "#captcha-bg",
    "img[class*='captcha-bg']",
    "[class*='jigsaw'] img:first-child",
    "[class*='verify-bg'] img",
    "canvas",
]

_JIGSAW_PIECE_SELECTORS = [
    ".captcha-slider-piece",
    "#captcha-piece",
    "img[class*='captcha-piece']",
    "[class*='jigsaw'] [class*='piece']",
    "[class*='verify-piece'] img",
    "[class*='nc-piece']",
]


def resolve_any_captcha(page: Page, max_rounds: int = 3) -> bool:
    """
    Master captcha orchestrator.
    Scans the DOM for every known Lazada captcha surface and resolves them
    via CapMonster. Loops up to max_rounds in case stacked captchas appear.
    Returns True if at least one challenge was resolved.
    """
    if not os.getenv("CAPMONSTER_CLOUD"):
        print(
            "[Captcha Solver] WARNING: CAPMONSTER_CLOUD key not set — captcha solving disabled."
        )
        return False

    resolved_any = False

    for round_num in range(1, max_rounds + 1):
        round_resolved = False

        # 1. Check for page-level verification redirect
        try:
            url = page.url
            if "verification" in url or "captcha" in url or "baxia" in url:
                print(f"[Captcha Solver] Verification URL detected: {url}")
        except Exception:
            pass

        # 2. reCAPTCHA v2 checkbox ("I'm not a robot")
        try:
            if solve_recaptcha_v2(page):
                round_resolved = True
        except Exception as e:
            print(f"[Captcha Solver] reCAPTCHA v2 sweep error: {e}")

        if round_resolved:
            resolved_any = True
            time.sleep(1.5)
            continue

        # 3. Alphanumeric / image OCR captcha
        try:
            if solve_alphanumeric_captcha(page):
                round_resolved = True
        except Exception as e:
            print(f"[Captcha Solver] OCR sweep error: {e}")

        if round_resolved:
            resolved_any = True
            time.sleep(1.5)
            continue

        # 3. Detect active slider / jigsaw trigger
        active_slider_sel = None
        for sel in _CAPTCHA_TRIGGER_SELECTORS:
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    active_slider_sel = sel
                    break
            except Exception:
                pass

        if not active_slider_sel:
            break

        # 3a. Check if jigsaw (needs both bg + piece)
        bg_sel = None
        piece_sel = None
        for sel in _JIGSAW_BG_SELECTORS:
            try:
                if (
                    page.locator(sel).count() > 0
                    and page.locator(sel).first.is_visible()
                ):
                    bg_sel = sel
                    break
            except Exception:
                pass
        for sel in _JIGSAW_PIECE_SELECTORS:
            try:
                if (
                    page.locator(sel).count() > 0
                    and page.locator(sel).first.is_visible()
                ):
                    piece_sel = sel
                    break
            except Exception:
                pass

        if bg_sel and piece_sel:
            print(
                f"[Captcha Solver] Jigsaw puzzle detected ({bg_sel} / {piece_sel}). Solving via CapMonster..."
            )
            if solve_jigsaw_puzzle_official(page, bg_sel, piece_sel):
                round_resolved = True
        else:
            print(
                f"[Captcha Solver] Slide-to-verify detected ({active_slider_sel}). Solving via CapMonster..."
            )
            if solve_slide_to_verify(page, active_slider_sel):
                round_resolved = True

        if round_resolved:
            resolved_any = True
            time.sleep(1.5)
        else:
            print(
                f"[Captcha Solver] Round {round_num}: CapMonster could not resolve this challenge."
            )
            break

    return resolved_any


# ---------------------------------------------------------------------------
# Global page hook — auto-resolve on every page load
# ---------------------------------------------------------------------------


def attach_global_captcha_hook(page: Page) -> None:
    """
    Attach a Playwright 'load' event listener so resolve_any_captcha() is called
    automatically after every navigation on this page.
    Safe to call once per page object.
    """

    def _on_load(_page: Page) -> None:
        try:
            resolve_any_captcha(page)
        except Exception as e:
            print(f"[Captcha Solver] Global hook error on load: {e}")

    try:
        page.on("load", _on_load)
        print("[Captcha Solver] Global captcha hook attached to page.")
    except Exception as e:
        print(f"[Captcha Solver] Could not attach global hook: {e}")
