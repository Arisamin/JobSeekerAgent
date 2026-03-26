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
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)

    for sel in ["a.jobs-apply-button", "button.jobs-apply-button", ".jobs-apply-button", "a:has-text('Easy Apply')"]:
        b = page.locator(sel).first
        if b.count() > 0:
            try:
                if b.is_visible(timeout=1000):
                    b.click(timeout=2000)
                    break
            except Exception:
                pass

    page.wait_for_timeout(2000)

    buttons = page.locator("button")
    for i in range(buttons.count()):
        b = buttons.nth(i)
        try:
            if not b.is_visible(timeout=300):
                continue
            text = (b.inner_text(timeout=300) or "").strip()
            aria = (b.get_attribute("aria-label", timeout=300) or "").strip()
            cls = (b.get_attribute("class", timeout=300) or "").strip()
            dcn = (b.get_attribute("data-control-name", timeout=300) or "").strip()
            print(f"[{i}] text={text!r} aria={aria!r} dcn={dcn!r} class={cls!r}")
        except Exception:
            continue

    ctx.close()
