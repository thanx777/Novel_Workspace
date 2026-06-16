from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto('http://localhost:5173')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(2000)

    # Click project 2
    items = page.locator('.wb-project-item')
    if items.count() >= 2:
        items.nth(1).click()
    page.wait_for_timeout(3000)

    # Check chapter display
    result = page.evaluate("""() => {
        const spans = document.querySelectorAll('span');
        const chapterSpans = [];
        spans.forEach(s => {
            const t = s.textContent.trim();
            if (t.includes('章') && !t.includes('章节') && t.length < 20) {
                chapterSpans.push(t);
            }
        });
        return [...new Set(chapterSpans)];
    }""")
    print("Chapter displays:", result)

    page.screenshot(path='/tmp/verify_refresh.png', full_page=True)
    browser.close()
