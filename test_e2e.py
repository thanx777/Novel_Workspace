"""Test: check stage state after outline completion and test confirm + writing"""
from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1400, "height": 900})

    page.goto("http://localhost:5173")
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    # Select the test project
    proj_item = page.locator(".wb-project-item:has-text('e2e_test'), .wb-project-item:has-text('E2E测试小说')")
    if proj_item.count() > 0:
        proj_item.first.click()
        time.sleep(2)
        print("✅ Project selected")
    else:
        print("❌ Project not found")
        browser.close()
        exit(1)

    # Click on "阶段" tab
    tabs = page.locator(".wb-sidebar-tab")
    for tab in tabs.all():
        text = tab.text_content()
        if "阶段" in text or "Stages" in text or "🚀" in text:
            tab.click()
            time.sleep(1)
            break

    # Check stage state
    stage_items = page.locator(".wb-stage-item")
    for i, item in enumerate(stage_items.all()):
        header = item.locator(".wb-stage-header").text_content().strip()
        btns = [b.text_content().strip() for b in item.locator("button").all()]
        print(f"  Stage {i}: '{header}' buttons={btns}")

    # ====== Confirm Outline ======
    print("\n====== Confirming Outline ======")
    confirm_btn = page.locator("button:has-text('确认大纲'), button:has-text('Confirm Outline')")
    if confirm_btn.count() > 0:
        confirm_btn.first.click()
        time.sleep(2)
        print("✅ Outline confirmed")

        # Check stage state
        stage_items = page.locator(".wb-stage-item")
        for i, item in enumerate(stage_items.all()):
            header = item.locator(".wb-stage-header").text_content().strip()
            btns = [b.text_content().strip() for b in item.locator("button").all()]
            print(f"  Stage {i}: '{header}' buttons={btns}")
    else:
        print("❌ No confirm outline button found")

    # ====== Start Writing ======
    print("\n====== Starting Writing ======")
    writing_btn = page.locator("button:has-text('继续生成'), button:has-text('开始写作'), button:has-text('Continue'), button:has-text('Start Writing')")
    if writing_btn.count() > 0:
        writing_btn.first.click()
        time.sleep(0.5)

        # Check STOP button
        stop_btn = page.locator(".wb-stage-item button:has-text('停止'), .wb-stage-item button:has-text('Stop')")
        if stop_btn.count() > 0:
            print("✅ Writing button changed to STOP")
        else:
            print("❌ Writing button did NOT change to STOP")

        # Wait for writing (max 300s)
        print("  Waiting for writing (max 300s)...")
        for i in range(300):
            time.sleep(1)
            stop_btns = page.locator(".wb-stage-item button:has-text('停止'), .wb-stage-item button:has-text('Stop')")
            if stop_btns.count() == 0:
                print(f"  ✅ Writing finished after {i+1}s")
                break
            if i % 30 == 29:
                print(f"  ... still running ({i+1}s)")
        else:
            print("  ⚠️ Writing timed out")
    else:
        print("❌ No writing button found")

    # Check stage state after writing
    stage_items = page.locator(".wb-stage-item")
    for i, item in enumerate(stage_items.all()):
        header = item.locator(".wb-stage-header").text_content().strip()
        btns = [b.text_content().strip() for b in item.locator("button").all()]
        print(f"  Stage {i}: '{header}' buttons={btns}")

    # ====== Confirm Writing ======
    print("\n====== Confirming Writing ======")
    confirm_writing_btn = page.locator("button:has-text('确认写作'), button:has-text('Confirm Writing')")
    if confirm_writing_btn.count() > 0:
        confirm_writing_btn.first.click()
        time.sleep(2)
        print("✅ Writing confirmed")
    else:
        print("❌ No confirm writing button found")

    # ====== Start Review ======
    print("\n====== Starting Review ======")
    review_btn = page.locator("button:has-text('继续生成'), button:has-text('全局审校'), button:has-text('Continue'), button:has-text('Global Review')")
    if review_btn.count() > 0:
        review_btn.first.click()
        time.sleep(0.5)

        stop_btn = page.locator(".wb-stage-item button:has-text('停止'), .wb-stage-item button:has-text('Stop')")
        if stop_btn.count() > 0:
            print("✅ Review button changed to STOP")
        else:
            print("❌ Review button did NOT change to STOP")

        print("  Waiting for review (max 120s)...")
        for i in range(120):
            time.sleep(1)
            stop_btns = page.locator(".wb-stage-item button:has-text('停止'), .wb-stage-item button:has-text('Stop')")
            if stop_btns.count() == 0:
                print(f"  ✅ Review finished after {i+1}s")
                break
            if i % 15 == 14:
                print(f"  ... still running ({i+1}s)")
        else:
            print("  ⚠️ Review timed out")
    else:
        print("❌ No review button found")

    page.screenshot(path="/tmp/test_full_e2e_final.png")

    # Final stage state
    stage_items = page.locator(".wb-stage-item")
    for i, item in enumerate(stage_items.all()):
        header = item.locator(".wb-stage-header").text_content().strip()
        btns = [b.text_content().strip() for b in item.locator("button").all()]
        print(f"  Stage {i}: '{header}' buttons={btns}")

    browser.close()
    print("\n✅ Full E2E test completed")
