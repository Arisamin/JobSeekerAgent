from playwright.sync_api import sync_playwright

profile = r"c:\MyData\Git\AI Projects\Job Seeker Agent\.playwright_profile"
url = "https://www.linkedin.com/jobs/view/4299764895/"

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=profile,
        channel="chrome",
        headless=False,
        viewport={"width": 1440, "height": 900},
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.set_default_timeout(20000)
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    for sel in [
        ".jobs-apply-button",
        "a.jobs-apply-button",
        "button.jobs-apply-button",
        "button:has-text('Easy Apply')",
        "a:has-text('Easy Apply')",
    ]:
        btn = page.locator(sel).first
        if btn.count() > 0:
            try:
                if btn.is_visible(timeout=1000):
                    btn.click(timeout=3000)
                    print(f"Clicked Easy Apply with: {sel}")
                    break
            except Exception:
                pass

    page.wait_for_timeout(2500)

    modal_buttons = page.locator(".artdeco-modal button, .jobs-easy-apply-modal button")
    count = modal_buttons.count()
    print(f"Modal button count: {count}")

    for idx in range(count):
        b = modal_buttons.nth(idx)
        try:
            text = (b.inner_text(timeout=500) or "").strip()
        except Exception:
            text = ""
        try:
            cls = b.get_attribute("class", timeout=500) or ""
        except Exception:
            cls = ""
        try:
            aria = b.get_attribute("aria-label", timeout=500) or ""
        except Exception:
            aria = ""
        try:
            enabled = b.is_enabled(timeout=500)
        except Exception:
            enabled = False
        try:
            visible = b.is_visible(timeout=500)
        except Exception:
            visible = False
        print(f"[{idx}] visible={visible} enabled={enabled} text={text!r} aria={aria!r} class={cls!r}")

    page.screenshot(path="diag_modal_buttons.png")
    ctx.close()
