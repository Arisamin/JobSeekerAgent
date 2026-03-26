"""
Diagnostic: open Easy Apply modal, click Next once, then dump all
interactive elements visible inside the modal on step 1.
"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(__file__))

from playwright.sync_api import sync_playwright

JOB_URL = "https://www.linkedin.com/jobs/view/4299764895/"
PROFILE  = os.path.join(os.path.dirname(__file__), ".playwright_profile")

EASY_APPLY_SELS = [
    ".jobs-apply-button",
    "a.jobs-apply-button",
    "button.jobs-apply-button",
    ".jobs-s-apply button",
    "a:has-text('Easy Apply')",
    "button:has-text('Easy Apply')",
]

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        PROFILE,
        channel="chrome",
        headless=False,
        locale="en-US",
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    page = ctx.new_page()
    page.goto(JOB_URL, timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Click Easy Apply
    clicked = False
    for sel in EASY_APPLY_SELS:
        try:
            b = page.locator(sel).first
            if b.count() > 0 and b.is_visible(timeout=1000):
                b.click(timeout=5000)
                clicked = True
                print(f"Clicked Easy Apply via: {sel}")
                break
        except Exception:
            continue
    if not clicked:
        print("ERROR: Could not click Easy Apply"); ctx.close(); sys.exit(1)

    # Wait for modal
    page.wait_for_selector(".artdeco-modal, .jobs-easy-apply-modal", timeout=8000)
    page.wait_for_timeout(1500)

    modal = page.locator(".artdeco-modal").first
    print(f"\n=== STEP 0 MODAL CONTENT ===")

    # Click Next to get to step 1
    advance = None
    for sel in ["button.artdeco-button--primary", "button[aria-label*='التالي']", "button[aria-label*='Next']"]:
        try:
            b = modal.locator(sel).last
            if b.count() > 0 and b.is_visible(timeout=1000) and b.is_enabled(timeout=1000):
                advance = b
                print(f"Found Next button via: {sel} text={b.inner_text(timeout=500)!r}")
                break
        except Exception:
            continue

    if advance:
        advance.click(timeout=5000)
        page.wait_for_timeout(2000)
        print("\n=== STEP 1 MODAL CONTENT ===")
        modal = page.locator(".artdeco-modal").first

        # Dump all interactive elements
        for tag in ["input", "select", "textarea", "fieldset", "[role='radio']", "[role='checkbox']",
                    "[role='combobox']", "[role='listbox']", "[role='option']", "[role='group']",
                    "label", ".jobs-easy-apply-form-element"]:
            try:
                els = modal.locator(tag).all()
                if els:
                    print(f"\n-- {tag}: {len(els)} found --")
                    for i, el in enumerate(els[:10]):
                        try:
                            text = (el.inner_text(timeout=300) or "").strip()[:80]
                            aria = (el.get_attribute("aria-label", timeout=300) or "").strip()[:80]
                            typ  = (el.get_attribute("type", timeout=300) or "").strip()
                            name = (el.get_attribute("name", timeout=300) or "").strip()
                            cls  = (el.get_attribute("class", timeout=300) or "").strip()[:60]
                            vis  = el.is_visible(timeout=200)
                            print(f"  [{i}] vis={vis} type={typ!r} name={name!r} aria={aria!r} text={text!r} class={cls!r}")
                        except Exception as e:
                            print(f"  [{i}] error: {e}")
            except Exception as e:
                print(f"-- {tag}: error: {e}")

        # Also dump raw HTML of first form element
        try:
            form_el = modal.locator(".jobs-easy-apply-form-element").first
            if form_el.count() > 0:
                print("\n-- First .jobs-easy-apply-form-element innerHTML --")
                print(form_el.inner_html(timeout=1000)[:2000])
        except Exception as e:
            print(f"form-element html error: {e}")

        # Dump all paragraph/legend text to see questions
        print("\n-- All visible text nodes (legend, label, p, h3) --")
        for tag in ["legend", "label", "p", "h3", "h4", "span.fb-dash-form-element__label"]:
            try:
                els = modal.locator(tag).all()
                for el in els[:10]:
                    try:
                        t = (el.inner_text(timeout=300) or "").strip()
                        if t:
                            print(f"  <{tag}>: {t[:120]!r}")
                    except Exception:
                        pass
            except Exception:
                pass
    else:
        print("ERROR: No Next button found on step 0")

    input("\nPress Enter to close browser...")
    ctx.close()
