from playwright.sync_api import sync_playwright

fallback = r"c:\MyData\Git\AI Projects\Job Seeker Agent\.playwright_profile"

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=fallback,
        channel="chrome",
        headless=False,
        locale="en-US",
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://www.linkedin.com/jobs/view/4299764895/", wait_until="domcontentloaded", timeout=20000)
    page.wait_for_timeout(5000)
    url = page.url
    title = page.title()
    btn = page.locator("button:has-text('Easy Apply'), a:has-text('Easy Apply')").first
    btn_visible = btn.is_visible(timeout=3000) if btn.count() > 0 else False
    print(f"URL: {url}")
    print(f"Title: {title}")
    print(f"EasyApply visible: {btn_visible}")
    page.screenshot(path="diag_screenshot.png")
    ctx.close()
