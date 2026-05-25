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
            clean_piece = piece_b64.replace("\n", "").replace("\r", "") if piece_b64 else ""
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
            print(f"[Captcha Solver] CapMonster API Error: {create_data.get('errorDescription')}")
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
                    print(f"[Captcha Solver] SDK OCR failed ({sdk_err}), falling back to HTTP...")

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

def solve_jigsaw_puzzle_official(page: Page, bg_selector: str, piece_selector: str) -> bool:
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

        print(f"[Captcha Solver] Jigsaw offset received: {offset_x}px. Performing drag...")
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

        print("[Captcha Solver] Slide-to-verify detected. Capturing challenge images...")

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
            print("[Captcha Solver] Got bg + piece — sending to CapMonster ComplexImageTask...")
            bg_b64 = base64.b64encode(bg_el.screenshot()).decode("utf-8")
            piece_b64 = base64.b64encode(piece_el.screenshot()).decode("utf-8")
            offset_x = _capmonster_solve_slider(bg_b64, piece_b64)
            if offset_x:
                print(f"[Captcha Solver] Slide offset from CapMonster: {offset_x}px")
                return _drag_slider(page, slider_selector, offset_x)
            print("[Captcha Solver] CapMonster returned 0 — cannot solve this slide variant.")
            return False

        # No separate piece found — screenshot full container and try OCR as offset
        print("[Captcha Solver] No separate piece element — screenshotting full container...")
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
        print("[Captcha Solver] WARNING: CAPMONSTER_CLOUD key not set — captcha solving disabled.")
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

        # 2. Alphanumeric / image OCR captcha
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
                if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                    bg_sel = sel
                    break
            except Exception:
                pass
        for sel in _JIGSAW_PIECE_SELECTORS:
            try:
                if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                    piece_sel = sel
                    break
            except Exception:
                pass

        if bg_sel and piece_sel:
            print(f"[Captcha Solver] Jigsaw puzzle detected ({bg_sel} / {piece_sel}). Solving via CapMonster...")
            if solve_jigsaw_puzzle_official(page, bg_sel, piece_sel):
                round_resolved = True
        else:
            print(f"[Captcha Solver] Slide-to-verify detected ({active_slider_sel}). Solving via CapMonster...")
            if solve_slide_to_verify(page, active_slider_sel):
                round_resolved = True

        if round_resolved:
            resolved_any = True
            time.sleep(1.5)
        else:
            print(f"[Captcha Solver] Round {round_num}: CapMonster could not resolve this challenge.")
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
