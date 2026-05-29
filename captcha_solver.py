# captcha_solver.py
import base64
import os
import time
from typing import Any
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


def _capmonster_solve_grid(
    image_b64: str,
    task_text: str,
    grid_size: str,
    website_url: str,
) -> list[int]:
    """
    Solve image-click grid captchas via CapMonster ComplexImageTask (recaptcha class).
    Returns 1-based selected cell indices.
    """
    api_key = os.getenv("CAPMONSTER_CLOUD")
    if not api_key:
        return []

    clean_img = image_b64.replace("\n", "").replace("\r", "")
    payload = {
        "clientKey": api_key,
        "task": {
            "type": "ComplexImageTask",
            "class": "recaptcha",
            "imagesBase64": [clean_img],
            "metadata": {
                "Task": task_text or "Select matching images",
                "Grid": grid_size if grid_size in {"3x3", "4x4"} else "3x3",
            },
            "websiteUrl": website_url,
        },
    }

    try:
        create_res = requests.post(
            "https://api.capmonster.cloud/createTask",
            json=payload,
            timeout=15,
        )
        create_data = create_res.json()
        if create_data.get("errorId", 1) != 0:
            print(
                f"[Captcha Solver] Grid createTask error: {create_data.get('errorDescription')}"
            )
            return []

        task_id = create_data.get("taskId")
        for _ in range(30):
            time.sleep(1.2)
            result_res = requests.post(
                "https://api.capmonster.cloud/getTaskResult",
                json={"clientKey": api_key, "taskId": task_id},
                timeout=10,
            )
            result_data = result_res.json()
            if result_data.get("status") != "ready":
                continue

            solution = result_data.get("solution", {})
            answer = solution.get("answer", [])
            if isinstance(answer, list):
                # CapMonster returns booleans by tile order (1-based mapping).
                if answer and isinstance(answer[0], bool):
                    return [idx + 1 for idx, picked in enumerate(answer) if picked]
                # Some integrations may return explicit indices.
                parsed: list[int] = []
                for raw in answer:
                    try:
                        val = int(raw)
                        if val > 0:
                            parsed.append(val)
                    except (TypeError, ValueError):
                        pass
                return parsed
            return []
    except Exception as e:
        print(f"[Captcha Solver] Grid solve exception: {e}")
    return []


def solve_image_grid_captcha(page: Page, max_rounds: int = 5) -> bool:
    """
    Solve click-based image grid captchas:
      - "Select all squares with ..."
      - "Select all images with ..."
    """
    if not os.getenv("CAPMONSTER_CLOUD"):
        return False

    instruction_selectors = [
        ".rc-imageselect-desc-wrapper",
        ".rc-imageselect-desc",
        ".rc-imageselect-instructions",
        "[class*='captcha'] [class*='title']",
        "[class*='captcha'] [class*='prompt']",
        "div:has-text('Select all squares with')",
        "div:has-text('Select all images with')",
    ]
    image_selectors = [
        "img.rc-image-tile-33",
        "img.rc-image-tile-44",
        ".rc-imageselect-target img",
        "[class*='captcha'] img",
        "[class*='captcha'] canvas",
    ]
    challenge_roots = [
        ".rc-imageselect",
        "[class*='captcha']",
        "[class*='baxia']",
        "[class*='verify-dialog']",
    ]

    def _grid_still_visible(frame_obj: Any) -> bool:
        try:
            return bool(
                frame_obj.evaluate(
                    """
                    () => {
                        const prompt = Array.from(document.querySelectorAll('div,span,p'))
                          .some(el => {
                            const t = (el.textContent || '').toLowerCase();
                            return t.includes('select all squares with') || t.includes('select all images with');
                          });
                        const tiles = document.querySelectorAll(
                          '.rc-imageselect-tile, .rc-imageselect-table td, [class*="imageselect"] td, [class*="captcha"] td, [class*="captcha"] [class*="tile"]'
                        ).length;
                        return prompt || tiles >= 9;
                    }
                    """
                )
            )
        except Exception:
            return False

    for round_num in range(1, max_rounds + 1):
        solved_this_round = False

        for frame in list(page.frames):
            try:
                prompt_text = ""
                prompt_el = None
                for sel in instruction_selectors:
                    loc = frame.locator(sel).first
                    if loc.count() > 0 and loc.is_visible():
                        text = (loc.inner_text() or "").strip()
                        if text:
                            prompt_text = text
                            prompt_el = loc
                            break

                if not prompt_text:
                    continue

                lower_prompt = prompt_text.lower()
                if (
                    "select all squares" not in lower_prompt
                    and "select all images" not in lower_prompt
                ):
                    continue

                image_el = None
                for sel in image_selectors:
                    loc = frame.locator(sel).first
                    if loc.count() > 0 and loc.is_visible():
                        image_el = loc
                        break

                if not image_el:
                    for root_sel in challenge_roots:
                        loc = frame.locator(root_sel).first
                        if loc.count() > 0 and loc.is_visible():
                            image_el = loc
                            break

                if not image_el:
                    continue

                # Determine grid shape from tile count; fallback to 3x3.
                grid_size = "3x3"
                try:
                    tile_count = frame.evaluate(
                        """
                        () => {
                          const selectors = [
                            '.rc-imageselect-tile',
                            '.rc-imageselect-table td',
                            '[class*="imageselect"] td'
                          ];
                          for (const sel of selectors) {
                            const n = document.querySelectorAll(sel).length;
                            if (n > 0) return n;
                          }
                          return 0;
                        }
                        """
                    )
                    if tile_count == 16:
                        grid_size = "4x4"
                except Exception:
                    pass

                challenge_box = image_el.bounding_box()
                if not challenge_box:
                    continue

                challenge_b64 = base64.b64encode(
                    image_el.screenshot(timeout=6000)
                ).decode("utf-8")
                print(
                    f"[Captcha Solver] Image-grid captcha detected ({grid_size}): '{prompt_text}'. Sending to CapMonster..."
                )
                picks = _capmonster_solve_grid(
                    image_b64=challenge_b64,
                    task_text=prompt_text,
                    grid_size=grid_size,
                    website_url=page.url,
                )

                cols = 4 if grid_size == "4x4" else 3
                rows = cols
                cell_w = challenge_box["width"] / cols
                cell_h = challenge_box["height"] / rows

                if picks:
                    print(f"[Captcha Solver] Grid picks: {picks}")
                    clicked_indices: set[int] = set()

                    # Prefer clicking tile elements directly to avoid coordinate drift.
                    tile_locator = frame.locator(
                        ".rc-imageselect-tile, .rc-imageselect-table td, [class*='imageselect'] td, [class*='captcha'] td, [class*='captcha'] [class*='tile']"
                    )
                    tile_count = 0
                    try:
                        tile_count = tile_locator.count()
                    except Exception:
                        tile_count = 0

                    for idx in picks:
                        if idx in clicked_indices:
                            continue
                        zero = max(0, idx - 1)
                        col = zero % cols
                        row = zero // cols
                        clicked = False

                        if tile_count >= idx and idx > 0:
                            try:
                                tile = tile_locator.nth(zero)
                                if tile.count() > 0 and tile.is_visible():
                                    tile.click(timeout=2500)
                                    clicked = True
                            except Exception:
                                clicked = False

                        if not clicked:
                            x = int(col * cell_w + (cell_w / 2))
                            y = int(row * cell_h + (cell_h / 2))
                            try:
                                image_el.click(position={"x": x, "y": y}, timeout=2500)
                                clicked = True
                            except Exception:
                                clicked = False

                        if clicked:
                            clicked_indices.add(idx)
                            time.sleep(0.22)
                else:
                    print("[Captcha Solver] Grid solver returned no picks; trying skip/verify.")

                for btn_sel in [
                    "#recaptcha-verify-button",
                    "button:has-text('Verify')",
                    "button:has-text('verify')",
                    "button:has-text('Skip')",
                    "button:has-text('skip')",
                    "button:has-text('Next')",
                    "button:has-text('next')",
                ]:
                    try:
                        btn = frame.locator(btn_sel).first
                        if btn.count() > 0 and btn.is_visible():
                            btn.click(timeout=2500)
                            break
                    except Exception:
                        pass

                time.sleep(1.5)
                still_visible = _grid_still_visible(frame)

                if still_visible:
                    solved_this_round = True
                    print(
                        f"[Captcha Solver] Grid captcha still active after round {round_num}; continuing..."
                    )
                    continue

                print("[Captcha Solver] ✓ Image-grid captcha solved.")
                return True
            except Exception as e:
                print(f"[Captcha Solver] Image-grid solve error: {e}")

        if not solved_this_round:
            break

    return False


def _drag_slider(
    page: Page,
    knob_selector: str,
    offset_x: int,
    challenge_width: float | None = None,
) -> bool:
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
    slider_knob_box = None
    for sel in knob_candidates:
        try:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible():
                box = el.bounding_box()
                if not box:
                    continue
                # Skip track/container-like elements when they are too wide and short.
                if sel != "#nc_1_n1z" and box["width"] > (box["height"] * 4):
                    continue
                slider_knob = el
                slider_knob_box = box
                break
        except Exception:
            pass

    if not slider_knob:
        print("[Captcha Solver] Failed to find the slider drag knob.")
        return False

    box = slider_knob_box or slider_knob.bounding_box()
    if not box:
        return False

    x_start = box["x"] + box["width"] / 2
    y_start = box["y"] + box["height"] / 2

    drag_distance = int(offset_x)

    # CapMonster offset is often based on challenge image width, not track width.
    # Scale to the real track so the drag does not undershoot toward the left side.
    track_selectors = [
        ".nc_scale",
        "[class*='nc_scale']",
        "[class*='slider-track']",
        "[class*='verify-bar']",
    ]
    track_width = None
    for sel in track_selectors:
        try:
            track = page.locator(sel).first
            if track.count() > 0 and track.is_visible():
                track_box = track.bounding_box()
                if track_box and track_box["width"] > 80:
                    track_width = track_box["width"]
                    break
        except Exception:
            pass

    if challenge_width and track_width and challenge_width > 0:
        scaled = int((offset_x / challenge_width) * track_width)
        if scaled > 0:
            drag_distance = scaled

    if track_width:
        drag_distance = max(5, min(drag_distance, int(track_width - 6)))

    page.mouse.move(x_start, y_start)
    page.mouse.down()
    page.mouse.move(x_start + drag_distance, y_start, steps=24)
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

        bg_box = bg_element.bounding_box()
        challenge_width = bg_box["width"] if bg_box else None
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
        return _drag_slider(page, "#nc_1_n1z", offset_x, challenge_width)

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
            bg_box = bg_el.bounding_box()
            challenge_width = bg_box["width"] if bg_box else None
            bg_b64 = base64.b64encode(bg_el.screenshot()).decode("utf-8")
            piece_b64 = base64.b64encode(piece_el.screenshot()).decode("utf-8")
            offset_x = _capmonster_solve_slider(bg_b64, piece_b64)
            if offset_x:
                print(f"[Captcha Solver] Slide offset from CapMonster: {offset_x}px")
                return _drag_slider(page, slider_selector, offset_x, challenge_width)
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

    # ── Step 1: Confirm an ACTIVE, VISIBLE reCAPTCHA iframe or widget actually exists in the DOM ──────────
    recaptcha_detected = False
    for frame in page.frames:
        try:
            # Check frame URL directly and check if the frame element is visible in parent DOM
            if "google.com/recaptcha/api2/anchor" in frame.url or "recaptcha" in frame.url:
                try:
                    el = frame.frame_element()
                    if el and el.is_visible():
                        recaptcha_detected = True
                        break
                except Exception:
                    pass

            # Evaluate visibility inside the frame itself
            has_markers = frame.evaluate("""
                () => {
                    // Check for standard captcha inputs/anchors
                    const selectors = ['.g-recaptcha', '[name="g-recaptcha-response"]', '#recaptcha-anchor'];
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el) {
                            const rect = el.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                return true;
                            }
                        }
                    }
                    return false;
                }
            """)
            if has_markers:
                recaptcha_detected = True
                break
        except Exception:
            pass

    if not recaptcha_detected:
        return False

    print("[Captcha Solver] reCAPTCHA v2 detected (iframe/widget found).")

    # ── Step 2: Click the "I'm not a robot" checkbox ──────────────────────────
    # Must happen before token injection so the widget enters an active state.
    try:
        checkbox_clicked = False
        # Search every frame for the anchor checkbox element to click it directly in its frame context
        for frame in page.frames:
            try:
                anchor = frame.locator("#recaptcha-anchor").first
                if anchor.count() > 0 and anchor.is_visible():
                    anchor.click(timeout=5000)
                    print(f"[Captcha Solver] ✓ reCAPTCHA checkbox clicked in frame: {frame.url[:60]}...")
                    checkbox_clicked = True
                    time.sleep(1.5)
                    break
            except Exception:
                pass
        
        if not checkbox_clicked:
            # Fallback to standard frame locator on main page
            checkbox_frame = page.frame_locator(
                "iframe[src*='recaptcha/api2/anchor'], iframe[src*='recaptcha'][src*='anchor']"
            ).first
            checkbox = checkbox_frame.locator("#recaptcha-anchor")
            checkbox.wait_for(state="visible", timeout=5000)
            checkbox.click(timeout=3000)
            print("[Captcha Solver] ✓ reCAPTCHA checkbox clicked via page locator.")
            time.sleep(1.5)
    except Exception as click_err:
        print(
            f"[Captcha Solver] Checkbox click failed ({click_err}), continuing with token injection..."
        )

    # ── Step 3: Extract sitekey ────────────────────────────────────────────────
    import urllib.parse
    import re
    sitekey = ""
    
    # 1. First, search all frames' execution contexts for sitekey variables
    for frame in page.frames:
        try:
            extracted = frame.evaluate("""
                () => {
                    // 1. data-sitekey attribute (any element)
                    const el = document.querySelector('[data-sitekey]');
                    if (el) return el.getAttribute('data-sitekey');
                    
                    // 2. data-sitekey on div.g-recaptcha
                    const grecaptchaDiv = document.querySelector('div.g-recaptcha, .g-recaptcha');
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
                            if (input.value.length > 20 && input.value.length < 100) {
                                return input.value;
                            }
                        }
                    }
                    
                    return '';
                }
            """)
            if extracted and len(extracted) > 10:
                sitekey = extracted
                break
        except Exception:
            pass

    # 2. If not found, search all frames' URLs directly using Python-based parsing
    if not sitekey:
        for frame in page.frames:
            try:
                # Direct regex search for k= sitekey parameter on frame URLs
                match = re.search(r'[?&]k=([^&]+)', frame.url)
                if match:
                    sitekey = match.group(1)
                    break
                
                # Check for standard URL params
                if "google.com/recaptcha" in frame.url or "recaptcha" in frame.url:
                    parsed = urllib.parse.urlparse(frame.url)
                    params = urllib.parse.parse_qs(parsed.query)
                    if 'k' in params:
                        sitekey = params['k'][0]
                        break
            except Exception:
                pass

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

    # ── Updated Token Injection (Frame-Aware) ──
    print("[Captcha Solver] reCAPTCHA token received. Injecting into all frames...")

    injection_js = """
    (token) => {
        // 1. Set the standard hidden textareas
        document.querySelectorAll('[name="g-recaptcha-response"], #g-recaptcha-response').forEach(el => {
            el.innerHTML = token;
            el.value = token;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        });

        // 2. Trigger the callback using ___grecaptcha_cfg
        try {
            if (window.___grecaptcha_cfg && window.___grecaptcha_cfg.clients) {
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
        
        // 3. Fallback: Check for data-callback attributes
        try {
            const cb = document.querySelector('[data-callback]');
            if (cb) {
                const fn = cb.getAttribute('data-callback');
                if (fn && typeof window[fn] === 'function') {
                    window[fn](token);
                }
            }
        } catch(e) {}
    }
    """

    injection_success = False

    # Iterate through every frame (including the main page and all iframes)
    for frame in page.frames:
        try:
            # Check if this frame contains the recaptcha container or script
            has_recaptcha = frame.evaluate("""
                () => !!document.querySelector('.g-recaptcha, [name="g-recaptcha-response"]') || 
                      !!window.___grecaptcha_cfg
            """)
            
            if has_recaptcha:
                print(f"[Captcha Solver] Injecting token into frame: {frame.url[:60]}...")
                frame.evaluate(injection_js, token)
                injection_success = True
                
        except Exception as e:
            # Ignore cross-origin frame errors if they can't be evaluated, 
            # though Playwright handles this better than raw JS.
            pass

    if not injection_success:
        # Fallback just in case the frame detection failed
        try:
            page.evaluate(injection_js, token)
        except Exception:
            pass

    # ── Step 4: Verification ───────────────────────────────────────────────────
    verified_solved = False
    print("[Captcha Solver] Verifying captcha resolution status...")
    for poll in range(10):
        still_active = False
        try:
            for frame in page.frames:
                if "google.com/recaptcha/api2/anchor" in frame.url or "recaptcha" in frame.url:
                    # Check if the checkbox has successfully transitioned to "checked" state
                    is_checked = frame.evaluate("""
                        () => {
                            const anchor = document.getElementById('recaptcha-anchor');
                            return anchor && anchor.classList.contains('recaptcha-checkbox-checked');
                        }
                    """)
                    if not is_checked:
                        still_active = True
                        break
            
            # Check if baxia overlay is still visible on main page
            overlay = page.locator("[class*='baxia-dialog'], .baxia-dialog").first
            if overlay.count() > 0 and overlay.is_visible():
                still_active = True
        except Exception:
            pass

        if not still_active:
            verified_solved = True
            break
        time.sleep(0.5)

    if verified_solved:
        print("[Captcha Solver] ✓ reCAPTCHA v2 solved and verified successfully.")
        return True
    else:
        print("[Captcha Solver] WARNING: reCAPTCHA v2 token injected, but verification showed captcha is still active.")
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

        # 2. reCAPTCHA / click-grid image challenges
        try:
            if solve_image_grid_captcha(page):
                round_resolved = True
        except Exception as e:
            print(f"[Captcha Solver] Image-grid sweep error: {e}")

        if round_resolved:
            resolved_any = True
            time.sleep(1.5)
            continue

        # 3. reCAPTCHA v2 checkbox ("I'm not a robot")
        try:
            if solve_recaptcha_v2(page):
                round_resolved = True
        except Exception as e:
            print(f"[Captcha Solver] reCAPTCHA v2 sweep error: {e}")

        if round_resolved:
            resolved_any = True
            time.sleep(1.5)
            continue

        # 4. Alphanumeric / image OCR captcha
        try:
            if solve_alphanumeric_captcha(page):
                round_resolved = True
        except Exception as e:
            print(f"[Captcha Solver] OCR sweep error: {e}")

        if round_resolved:
            resolved_any = True
            time.sleep(1.5)
            continue

        # 5. Detect active slider / jigsaw trigger
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

        # 5a. Check if jigsaw (needs both bg + piece)
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