# captcha_solver.py
import base64
import os
import asyncio
import time
import random
import requests
from playwright.sync_api import Page

# Import the official client classes with fallback mechanism
try:
    from capmonstercloudclient import CapMonsterClient, ClientOptions
    from capmonstercloudclient.requests import ImageToTextRequest, RecognitionComplexImageTaskRequest
    SDK_AVAILABLE = True
except ImportError:
    SDK_AVAILABLE = False


async def _solve_ocr_async(bg_b64: str) -> str:
    """Internal helper to solve alphanumeric text captcha using official SDK."""
    api_key = os.getenv("CAPMONSTER_CLOUD")
    if not api_key:
        raise ValueError("CAPMONSTER_CLOUD key is missing in .env")

    client_options = ClientOptions(api_key=api_key)
    client = CapMonsterClient(options=client_options)
    
    # Clean and decode base64 to raw bytes as required by ImageToTextRequest
    clean_b64 = bg_b64.replace("\n", "").replace("\r", "")
    image_bytes = base64.b64decode(clean_b64)
    request = ImageToTextRequest(image_bytes=image_bytes)
    response = await client.solve_captcha(request)
    return response.get("text", "") if isinstance(response, dict) else str(response)


async def _solve_puzzle_async(bg_b64: str, piece_b64: str) -> int:
    """Internal helper to solve jigsaw coordinates using official SDK."""
    api_key = os.getenv("CAPMONSTER_CLOUD")
    if not api_key:
        raise ValueError("CAPMONSTER_CLOUD key is missing in .env")

    client_options = ClientOptions(api_key=api_key)
    client = CapMonsterClient(options=client_options)

    clean_bg = bg_b64.replace("\n", "").replace("\r", "")
    clean_piece = piece_b64.replace("\n", "").replace("\r", "")

    request = RecognitionComplexImageTaskRequest(
        class_name="slider",
        image_urls=[clean_bg],
        metadata={"target": clean_piece},
    )

    result = await client.solve_captcha(request)
    if isinstance(result, dict):
        try:
            return int(result.get("x", 0))
        except (ValueError, TypeError):
            return 0
    try:
        return int(result)
    except (ValueError, TypeError):
        return 0


def _solve_via_raw_http(bg_b64: str, piece_b64: str | None = None, task_type: str = "ImageToTextTask") -> str:
    """
    Fallback method using raw HTTP requests to CapMonster Cloud.
    Guarantees stability even if package import variants mismatch.
    """
    api_key = os.getenv("CAPMONSTER_CLOUD")
    if not api_key:
        print("[Captcha Solver] Error: CAPMONSTER_CLOUD key is missing in .env")
        return ""

    try:
        clean_bg = bg_b64.replace("\n", "").replace("\r", "")
        
        if task_type == "ImageToTextTask":
            task_payload = {
                "type": "ImageToTextTask",
                "body": clean_bg
            }
        else:
            # Jigsaw Slider task
            clean_piece = piece_b64.replace("\n", "").replace("\r", "") if piece_b64 else ""
            task_payload = {
                "type": "ComplexImageTask",
                "class": "slider",
                "imageUrls": [clean_bg],
                "metadata": {"target": clean_piece}
            }

        # Create Task
        create_url = "https://api.capmonster.cloud/createTask"
        create_res = requests.post(create_url, json={"clientKey": api_key, "task": task_payload}, timeout=10)
        create_data = create_res.json()
        
        if create_data.get("errorId", 1) != 0:
            print(f"[Captcha Solver] CapMonster API Error: {create_data.get('errorDescription')}")
            return ""

        task_id = create_data.get("taskId")
        
        # Poll Task Result
        result_url = "https://api.capmonster.cloud/getTaskResult"
        for _ in range(30):
            time.sleep(1.5)
            result_res = requests.post(result_url, json={"clientKey": api_key, "taskId": task_id}, timeout=10)
            result_data = result_res.json()
            
            if result_data.get("status") == "ready":
                solution = result_data.get("solution", {})
                if task_type == "ImageToTextTask":
                    return solution.get("text", "")
                else:
                    return str(solution.get("x", 0))
        return ""
    except Exception as e:
        print(f"[Captcha Solver] Raw HTTP solving encountered error: {e}")
        return ""


def solve_alphanumeric_captcha(page: Page, max_retries: int = 3) -> bool:
    """
    Detects and solves standard alphanumeric text captchas.
    """
    image_selectors = [
        "img[src*='captcha']",
        "img[src*='getCaptcha']",
        "img[src*='code']",
        "img[id*='captcha']",
        ".captcha-img",
        "[class*='captcha-image']"
    ]
    input_selectors = [
        "input[placeholder*='code']",
        "input[placeholder*='captcha']",
        "input[name*='captcha']",
        "input[name*='code']",
        ".captcha-input input",
        "input[aria-label*='aptcha']"
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
            time.sleep(1.0) # breathing room for source update
            
            img_bytes = img_el.screenshot()
            img_b64 = base64.b64encode(img_bytes).decode("utf-8")

            # Try SDK first, fall back to Raw HTTP
            # We use a fresh event loop to avoid clashing with Playwright's
            # internal sync wrapper event loop.
            solved_text = ""
            if SDK_AVAILABLE:
                try:
                    _loop = asyncio.new_event_loop()
                    try:
                        solved_text = _loop.run_until_complete(_solve_ocr_async(img_b64))
                    finally:
                        _loop.close()
                except Exception as sdk_err:
                    print(f"[Captcha Solver] SDK solve failed ({sdk_err}), falling back to HTTP...")
            
            if not solved_text:
                solved_text = _solve_via_raw_http(img_b64, task_type="ImageToTextTask")

            if not solved_text:
                print("[Captcha Solver] CapMonster returned no solver results.")
                continue

            print(f"[Captcha Solver] Decoded text: '{solved_text}'")

            input_el.click()
            input_el.fill("")
            input_el.type(solved_text, delay=60)
            input_el.press("Enter")
            
            time.sleep(2.5) # Wait for page reaction
            
            if not img_el.is_visible():
                print("[Captcha Solver] ✓ OCR Captcha bypassed successfully!")
                return True

            print("[Captcha Solver] OCR answer incorrect. Refreshing captcha and retrying...")
            img_el.click()

        except Exception as e:
            print(f"[Captcha Solver] Error during OCR solve: {e}")

    return False


def solve_jigsaw_puzzle_official(page: Page, bg_selector: str, piece_selector: str) -> bool:
    """
    Solves jigsaw slider captchas using coordinates from CapMonster.
    """
    try:
        bg_element = page.locator(bg_selector).first
        piece_element = page.locator(piece_selector).first

        if not bg_element.is_visible() or not piece_element.is_visible():
            return False

        # Capture element screenshots
        bg_bytes = bg_element.screenshot()
        piece_bytes = piece_element.screenshot()

        bg_b64 = base64.b64encode(bg_bytes).decode("utf-8")
        piece_b64 = base64.b64encode(piece_bytes).decode("utf-8")

        print("[Captcha Solver] Submitting jigsaw challenge to CapMonster Cloud...")

        offset_x = 0
        if SDK_AVAILABLE:
            try:
                _loop = asyncio.new_event_loop()
                try:
                    offset_x = _loop.run_until_complete(_solve_puzzle_async(bg_b64, piece_b64))
                finally:
                    _loop.close()
            except Exception as sdk_err:
                print(f"[Captcha Solver] SDK jigsaw solve failed ({sdk_err}), falling back to HTTP...")

        if not offset_x:
            raw_res = _solve_via_raw_http(bg_b64, piece_b64, task_type="ComplexImageTask")
            try:
                offset_x = int(raw_res) if raw_res else 0
            except ValueError:
                offset_x = 0

        if not offset_x:
            print("[Captcha Solver] CapMonster failed to identify puzzle coordinates.")
            return False

        print(f"[Captcha Solver] Jigsaw coordinate received: {offset_x}px. Performing slide...")

        # Locate slider bar button/knob
        slider_knobs = [
            "[class*='slider-knob']",
            ".slider-button",
            "#nc_1_n1z",
            "[class*='btn_slide']",
            ".nc-lang-en-US .nc_scale span"
        ]
        
        slider_knob = None
        for sel in slider_knobs:
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    slider_knob = el
                    break
            except Exception:
                pass

        if not slider_knob:
            print("[Captcha Solver] Failed to find the drag knob element.")
            return False

        box = slider_knob.bounding_box()
        if not box:
            return False

        x_start = box["x"] + box["width"] / 2
        y_start = box["y"] + box["height"] / 2

        # Emulate drag
        page.mouse.move(x_start, y_start)
        page.mouse.down()
        page.mouse.move(x_start + offset_x, y_start, steps=12)
        time.sleep(0.1)
        page.mouse.up()

        return True
    except Exception as e:
        print(f"[Captcha Solver] Coordinate drag process hit exception: {e}")
        return False


def solve_slide_to_verify(page: Page, slider_selector: str = "#nc_1_n1z") -> bool:
    """
    Simulates human-like drag-and-drop mouse movements to solve standard slide bars.
    """
    try:
        slider = page.locator(slider_selector).first
        if not slider.is_visible():
            return False
            
        print("[Captcha Solver] Slide-to-verify detected. Simulating drag...")
        
        box = slider.bounding_box()
        if not box:
            return False
            
        x_start = box["x"] + box["width"] / 2
        y_start = box["y"] + box["height"] / 2
        
        page.mouse.move(x_start, y_start)
        page.mouse.down()
        
        slide_distance = 320 
        steps = random.randint(15, 25)
        
        for i in range(steps):
            fraction = (i + 1) / steps
            delta_x = slide_distance * (1 - (1 - fraction) ** 2)
            jitter_y = random.uniform(-1, 1)
            
            page.mouse.move(x_start + delta_x, y_start + jitter_y)
            time.sleep(random.uniform(0.01, 0.03))
            
        time.sleep(0.2)
        page.mouse.up()
        print("[Captcha Solver] Drag complete.")
        return True
    except Exception as e:
        print(f"[Captcha Solver] Error solving simple slide: {e}")
        return False


def resolve_any_captcha(page: Page) -> bool:
    """
    Master Captcha orchestrator sweep.
    Scans the DOM for any active alphanumeric text captcha or slider captcha,
    resolves them dynamically, and returns True if a challenge was resolved.
    """
    resolved = False
    
    # 1. Sweep for Alphanumeric Image Captcha
    try:
        ocr_result = solve_alphanumeric_captcha(page)
        if ocr_result:
            resolved = True
    except Exception as e:
        print(f"[Captcha Solver] Master scan alphanumeric bypass error: {e}")

    # 2. Sweep for Slide / Jigsaw Captcha
    if not resolved:
        slider_selectors = [
            "#nc_1_n1z",
            ".nc_scale",
            ".next-slider",
            "[class*='slider']",
            "[class*='nc-container']",
            "[class*='captcha-slider']"
        ]
        
        active_slider = None
        for sel in slider_selectors:
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    active_slider = sel
                    break
            except Exception:
                pass
                
        if active_slider:
            # Check if jigsaw selectors are visible on page (indicating Jigsaw instead of simple slider)
            jigsaw_bg_sels = [".captcha-background-img", "#captcha-bg", "img[class*='captcha-bg']", "[class*='jigsaw'] img"]
            jigsaw_piece_sels = [".captcha-slider-piece", "#captcha-piece", "img[class*='captcha-piece']", "[class*='jigsaw'] [class*='piece']"]
            
            bg_sel = None
            piece_sel = None
            
            for sel in jigsaw_bg_sels:
                try:
                    if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                        bg_sel = sel
                        break
                except Exception:
                    pass
            for sel in jigsaw_piece_sels:
                try:
                    if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                        piece_sel = sel
                        break
                except Exception:
                    pass

            if bg_sel and piece_sel:
                print(f"[Captcha Solver] Jigsaw puzzle slider detected ({bg_sel} / {piece_sel}). Solving...")
                resolved = solve_jigsaw_puzzle_official(page, bg_sel, piece_sel)
            else:
                print(f"[Captcha Solver] Standard slide-to-verify detected ({active_slider}). Solving...")
                resolved = solve_slide_to_verify(page, active_slider)

    return resolved
