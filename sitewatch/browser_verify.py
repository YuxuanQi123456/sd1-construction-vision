"""Verify real uploads, CPU results, downloads, and no camera access in native UI."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse
import zipfile


async def native_download(page, context, label, target):
    async with page.expect_download() as event:
        await page.get_by_role("button", name=label, exact=True).click()
    download = await event.value
    assert urlparse(download.url).hostname in ("127.0.0.1", "localhost", "::1")
    response = await context.request.get(download.url)
    assert response.ok
    data = await response.body()
    target.write_bytes(data)
    return data


async def wait_script_idle(page, expect):
    # The filename appears before Streamlit has consumed an upload. Wait for
    # the server-rendered current filename, then its completed script run.
    await expect(page.locator('[data-testid="stApp"]')).to_have_attribute(
        "data-test-script-state", "notRunning", timeout=120000)


async def upload_and_review(page, source, expect):
    await page.locator("input[type=file]").first.set_input_files(
        {"name": source.name, "mimeType": "video/mp4" if source.suffix == '.mp4' else "image/jpeg", "buffer": source.read_bytes()})
    await expect(page.get_by_text(source.name, exact=True)).to_be_visible()
    await expect(page.get_by_text("当前影像：" + source.name, exact=True)).to_be_visible(timeout=60000)
    await expect(page.get_by_role("button", name="下载原始检测 JSON", exact=True)).to_have_count(0, timeout=60000)
    await expect(page.get_by_text("Qwen 区域意见：", exact=False)).to_have_count(0)
    await wait_script_idle(page, expect)
    await page.get_by_role("button", name="开始识别与复核", exact=True).click()
    await expect(page.get_by_text("识别完成：", exact=False)).to_be_visible(timeout=120000)


async def check_regions(page, context, args, record, expect):
    record["region_reviews"] = []
    cases = [("niosh-runway-worker.jpg", "A", "可见工业安全帽"),
             ("plasterer-original.jpg", "B", "头发或头皮可见，未见工业安全帽"),
             ("bricklayer.jpg", "B", "头发或头皮可见，未见工业安全帽")]
    for index, (filename, expected_option, expected_label) in enumerate(cases):
        source = args.project_root / "downloads/vision-samples" / filename
        await upload_and_review(page, source, expect)
        before = await native_download(page, context, "下载原始检测 JSON", args.output / f"region-{source.stem}-before.json")
        raw = json.loads(before)
        assert raw["model"]["id"] == "sitewatch"
        button = page.get_by_role("button", name="复核所选头部", exact=True)
        await expect(button).to_be_enabled(timeout=120000)
        await button.click()
        await expect(page.get_by_text("Qwen 区域意见：" + expected_label, exact=True)).to_be_visible(timeout=180000)
        after = await native_download(page, context, "下载原始检测 JSON", args.output / f"region-{source.stem}-after.json")
        assert after == before, "Second opinion must not rewrite raw detector output"
        zip_path = args.output / f"region-{source.stem}-evidence.zip"
        await native_download(page, context, "下载完整证据（原文件 / 检测框 / JSON）", zip_path)
        with zipfile.ZipFile(zip_path) as archive:
            assert archive.read("detections.json") == before
            latest = [n for n in archive.namelist() if n.startswith("head-reviews/") and n.endswith("/latest.json")]
            assert len(latest) == 1, latest
            region = json.loads(archive.read(latest[0]))
            assert region["status"] == "complete"
            assert region["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
            assert region["opinion"]["option"] == expected_option
            assert region["opinion"]["classification_confidence"] is None
            assert region["opinion"]["fresh_session"] is True
            # class_id indexes the model vocabulary, not the detection list.
            assert region["detector_detection"] in raw["frames"][0]["detections"]
            crop = archive.read(region["crop_file"])
            assert hashlib.sha256(crop).hexdigest() == region["crop_sha256"]
            assert hashlib.sha256(archive.read(region["input_file"])).hexdigest() == region["input_sha256"]
            assert len(region["opinion"]["api_history"]) == 2
            if filename == "bricklayer.jpg":
                assert region["detector_detection"]["class_name"] == "Hardhat"
                assert region["comparison"] == "disagree"
                await expect(page.get_by_text("两模型意见不同，请结合原图人工复核。", exact=True)).to_be_visible()
        (args.output / f"region-{source.stem}-review.json").write_text(json.dumps(region, ensure_ascii=False, indent=2)+"\n")
        await page.screenshot(path=str(args.output / f"region-{index+1:02d}-{source.stem}.png"), full_page=True)
        record["region_reviews"].append({"file": filename, "option": region["opinion"]["option"],
            "detector_class": region["detector_detection"]["class_name"],
            "detector_confidence": region["detector_detection"]["confidence"],
            "comparison": region["comparison"], "crop_sha256": region["crop_sha256"],
            "raw_detector_unchanged": True, "zip_crop_and_answer_verified": True})
    picker = page.locator('[data-testid="stSelectbox"]').filter(has_text="检测模型").get_by_role("combobox")
    await picker.click()
    await page.get_by_role("option", name="Constructelligence 对照（仍有误检）", exact=True).click()
    await expect(page.get_by_role("checkbox", name="显示全部14类（含人员、设备及可能误检）", exact=True)).to_have_count(1)
    await expect(page.get_by_role("button", name="下载原始检测 JSON", exact=True)).to_have_count(0)
    await expect(page.get_by_text("Qwen 区域意见：", exact=False)).to_have_count(0)
    await wait_script_idle(page, expect)
    # Switching back before another inference must not resurrect the stale
    # baseline image or second opinion stored before the model change.
    await picker.click()
    await page.get_by_role("option", name="SiteWatch 基线（默认）", exact=True).click()
    await expect(page.get_by_role("checkbox", name="显示全部25类（含人员、设备及可能误检）", exact=True)).to_have_count(1)
    await wait_script_idle(page, expect)
    await expect(page.get_by_role("button", name="下载原始检测 JSON", exact=True)).to_have_count(0)
    await expect(page.get_by_text("Qwen 区域意见：", exact=False)).to_have_count(0)
    await picker.click()
    await page.get_by_role("option", name="Constructelligence 对照（仍有误检）", exact=True).click()
    await expect(page.get_by_role("checkbox", name="显示全部14类（含人员、设备及可能误检）", exact=True)).to_have_count(1)
    await wait_script_idle(page, expect)
    source = args.project_root / "downloads/vision-samples/working-the-grinder.jpg"
    await upload_and_review(page, source, expect)
    payload = await native_download(page, context, "下载原始检测 JSON", args.output / "candidate-grinder-detections.json")
    candidate = json.loads(payload)
    assert candidate["model"]["id"] == "constructelligence-v03"
    assert candidate["model"]["sha256"] == "ab31a6b2ddcd21a081d6393a11e8062a058c218c333be11481fc0678a9c67e2e"
    assert len(candidate["model"]["names"]) == 14
    assert any(d["class_name"] == "person" and d["source"] == "constructelligence-v03" for d in candidate["frames"][0]["detections"])
    await expect(page.get_by_text("当前帧未检出可复核的头部框，不能据此判断是否戴帽。", exact=True)).to_be_visible()
    await expect(page.get_by_role("button", name="复核所选头部", exact=True)).to_have_count(0)
    await page.get_by_text("显示全部14类（含人员、设备及可能误检）", exact=True).click()
    await expect(page.get_by_role("checkbox", name="显示全部14类（含人员、设备及可能误检）", exact=True)).to_be_checked()
    await page.get_by_text("模型来源与许可", exact=True).click()
    await expect(page.get_by_text("固定版本 79673cff5a8bb249fc8ec9cca3daa19e2ef95191；14 类；CPU 推理", exact=True)).to_be_visible()
    await page.screenshot(path=str(args.output / "region-candidate-grinder.png"), full_page=True)
    record["model_switch"] = {"cleared_old_detection_and_opinion": True,
                              "switch_back_does_not_restore_stale_result": True,
                              "actual_candidate_id": candidate["model"]["id"], "actual_classes": 14,
                              "grinder_person_detected": True, "all_classes_display_enabled": True,
                              "no_head_does_not_imply_safety": True}
    await picker.click()
    await page.get_by_role("option", name="SiteWatch 基线（默认）", exact=True).click()
    await expect(page.get_by_role("checkbox", name="显示全部25类（含人员、设备及可能误检）", exact=True)).to_have_count(1)
    await expect(page.get_by_role("button", name="下载原始检测 JSON", exact=True)).to_have_count(0)


async def check_distant_video(page, context, args, record, expect):
    picker = page.locator('[data-testid="stSelectbox"]').filter(has_text="演示预设").get_by_role('combobox')
    await picker.click()
    await page.get_by_role('option', name='自动（按素材与场景）', exact=True).click()
    source = args.project_root / '.runtime/vision-media/window-hostivar-0-8.0.mp4'
    await upload_and_review(page, source, expect)
    await expect(page.get_by_text('当前识别场景：远景视频 · 人员与防护装备', exact=True)).to_be_visible()
    payload = await native_download(page, context, '下载原始检测 JSON', args.output/'distant-video.json')
    result = json.loads(payload)
    assert result['settings']['profile'] == 'distant'
    assert result['settings']['inference_imgsz'] == 1280
    assert result['model']['person_companion']['sha256'] == '31e20dde3def09e2cf938c7be6fe23d9150bbbe503982af13345706515f2ef95'
    frame = next(f for f in result['frames'] if f['timestamp_seconds'] == 7)
    workers = [d for d in frame['detections'] if d['category'] == 'worker']
    assert any(118 <= (d['bbox'][0]+d['bbox'][2])/2 <= 142 for d in workers)
    assert any(150 <= (d['bbox'][0]+d['bbox'][2])/2 <= 190 for d in workers)
    assert any(d['class_name'] == 'Hardhat' for d in frame['detections'])
    frame_picker = page.locator('[data-testid="stSelectbox"]').filter(has_text='查看采样画面').get_by_role('combobox')
    await frame_picker.click()
    await page.get_by_role('option', name='7.00s / frame 175', exact=True).click()
    await wait_script_idle(page, expect)
    await native_download(page, context, '下载完整证据（原文件 / 检测框 / JSON）', args.output/'distant-video.zip')
    with zipfile.ZipFile(args.output/'distant-video.zip') as archive:
        assert archive.read('detections.json') == payload
        assert frame['review_overlay_file'] in archive.namelist()
    await page.get_by_role('button', name='下载原始检测 JSON', exact=True).scroll_into_view_if_needed()
    await page.screenshot(path=str(args.output/'distant-video-persons-helmet.png'), full_page=True)
    record['distant_video'] = {'automatic_preset_selected': True, 'two_trackside_workers_detected': True,
        'head_candidate_detected': True, 'profile': result['settings']['profile'], 'zip_verified': True}
    await picker.click()
    await page.get_by_role('option', name='照片/近景（标准）', exact=True).click()
    await expect(page.get_by_role('button', name='下载原始检测 JSON', exact=True)).to_have_count(0)
    await picker.click()
    await page.get_by_role('option', name='自动（按素材与场景）', exact=True).click()
    await expect(page.get_by_role('button', name='下载原始检测 JSON', exact=True)).to_have_count(0)


async def run(args, record):
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost,::1"
    from playwright.async_api import async_playwright, expect
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(args.cdp)
        context = await browser.new_context(viewport={"width": 1440, "height": 1100}, locale="zh-CN", accept_downloads=True)
        await context.add_init_script("""window.__cameraCalls=0;
            if(navigator.mediaDevices) navigator.mediaDevices.getUserMedia=async()=>{
                window.__cameraCalls++; throw new Error('Offline review must not request camera'); };""")
        async def local_only(route):
            if urlparse(route.request.url).hostname in ("127.0.0.1", "localhost", "::1"):
                await route.continue_()
            else:
                record["blocked_external"].append(route.request.url)
                await route.abort()
        await context.route("**/*", local_only)
        page = await context.new_page()
        try:
            await page.goto(args.url, wait_until="domcontentloaded")
            await expect(page.get_by_role("heading", name="影像识别与复核")).to_be_visible(timeout=120000)
            await expect(page).to_have_title('水电一局 · 施工视觉AI')
            logo = page.locator('.sd1-logo')
            await expect(logo).to_be_visible()
            assert await logo.evaluate('(img) => img.complete && img.naturalWidth === 344 && img.naturalHeight === 63')
            assert (await logo.get_attribute('src')).startswith('data:image/png;base64,')
            await expect(page.locator('.sd1-step')).to_have_count(3)
            await wait_script_idle(page, expect)
            await page.locator('.sd1-masthead').scroll_into_view_if_needed()
            await page.screenshot(path=str(args.output/'00-branded-desktop.png'))
            record['official_logo_embedded_locally'] = True
            record['chinese_branding_and_workflow'] = True
            await page.get_by_text("自己上传", exact=True).click()
            # The legacy regression is pinned to the unchanged standard profile.
            preset = page.locator('[data-testid="stSelectbox"]').filter(has_text='演示预设').get_by_role('combobox')
            await preset.click()
            await page.get_by_role('option', name='照片/近景（标准）', exact=True).click()
            await expect(page.get_by_text("AI 检测用于辅助人工复核", exact=False)).to_be_visible()
            await page.screenshot(path=str(args.output / "01-initial.png"), full_page=True)
            sources = [args.project_root / "downloads/vision-samples/niosh-runway-worker.jpg",
                       args.project_root / "downloads/vision-samples/working-the-grinder.jpg",
                       args.project_root / ".runtime/vision-media/window-florenc-0-8.0.mp4"]
            if args.additional_image:
                sources.insert(2, args.additional_image)
            all_classes = page.get_by_role("checkbox", name="显示全部25类（含人员、设备及可能误检）", exact=True)
            await expect(all_classes).not_to_be_checked()
            for i, source in enumerate(sources):
                mime = "image/jpeg" if source.suffix == ".jpg" else "video/mp4"
                await page.locator("input[type=file]").first.set_input_files(
                    {"name": source.name, "mimeType": mime, "buffer": source.read_bytes()})
                # Streamlit's upload triggers an asynchronous rerun. Wait for
                # old result/download widgets to disappear before pressing Run.
                await expect(page.get_by_text(source.name, exact=True)).to_be_visible()
                await expect(page.get_by_text("当前影像：" + source.name, exact=True)).to_be_visible(timeout=60000)
                await expect(page.get_by_role("button", name="下载原始检测 JSON", exact=True)).to_have_count(0, timeout=60000)
                await wait_script_idle(page, expect)
                await page.get_by_role("button", name="开始识别与复核", exact=True).click()
                await expect(page.get_by_text("识别完成：", exact=False)).to_be_visible(timeout=120000)
                assert await page.evaluate("window.__cameraCalls") == 0
                async with page.expect_download() as download_event:
                    await page.get_by_role("button", name="下载原始检测 JSON", exact=True).click()
                download = await download_event.value
                target = args.output / f"{source.stem}-ui-detections.json"
                assert urlparse(download.url).hostname in ("127.0.0.1", "localhost", "::1")
                response = await context.request.get(download.url)
                assert response.ok, await response.text()
                target.write_bytes(await response.body())
                result = json.loads(target.read_text())
                assert result["status"] == "complete" and result["model"]["device"] == "cpu"
                assert result["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
                assert result["settings"]["motion_rules"] is False
                assert result["source_provenance"]["registered"] is True
                if args.additional_image and source == args.additional_image and args.expected_additional_class:
                    assert args.expected_additional_class in [d["class_name"] for d in result["frames"][0]["detections"]]
                if i == 0:
                    labels = [d["class_name"] for d in result["frames"][0]["detections"]]
                    assert "Hardhat" in labels and "Safety Vest" in labels
                    async with page.expect_download() as zip_event:
                        await page.get_by_role("button", name="下载完整证据（原文件 / 检测框 / JSON）", exact=True).click()
                    downloaded_zip = await zip_event.value
                    zip_path = args.output / "niosh-ui-evidence.zip"
                    response = await context.request.get(downloaded_zip.url)
                    assert response.ok
                    zip_path.write_bytes(await response.body())
                    with zipfile.ZipFile(zip_path) as archive:
                        assert hashlib.sha256(archive.read("original.jpg")).hexdigest() == result["source_sha256"]
                        assert "detections.json" in archive.namelist()
                        provenance = json.loads(archive.read("source-provenance.json"))
                        assert provenance["sha256"] == result["source_sha256"]
                    await page.get_by_text("显示全部25类（含人员、设备及可能误检）", exact=True).click()
                    await expect(all_classes).to_be_checked()
                    await page.screenshot(path=str(args.output / "02-niosh-all-classes.png"), full_page=True)
                    await page.get_by_text("显示全部25类（含人员、设备及可能误检）", exact=True).click()
                    await expect(all_classes).not_to_be_checked()
                await page.screenshot(path=str(args.output / f"{i+2:02d}-{source.stem}.png"), full_page=True)
                record["uploads"].append({"file": source.name, "frames": len(result["frames"]),
                                          "manual_review_detection_count": result["manual_review_detection_count"],
                                          "source_sha256": result["source_sha256"],
                                          "json_download_verified": True,
                                          "download_method": "clicked native download button, verified its local HTTP response (Windows CDP artifact paths cannot be saved on Linux)",
                                          "model_sha256": result["model"]["sha256"]})
            await page.locator("input[type=file]").first.set_input_files(
                {"name": "invalid.jpg", "mimeType": "image/jpeg", "buffer": b"not a valid image"})
            await expect(page.get_by_text("invalid.jpg", exact=True)).to_be_visible()
            await expect(page.get_by_text("当前影像：invalid.jpg", exact=True)).to_be_visible(timeout=60000)
            await expect(page.get_by_role("button", name="下载原始检测 JSON", exact=True)).to_have_count(0)
            await wait_script_idle(page, expect)
            await page.get_by_role("button", name="开始识别与复核", exact=True).click()
            await expect(page.get_by_text("复核失败：", exact=False)).to_be_visible()
            await expect(page.locator('[data-testid="stException"]')).to_have_count(0)
            await page.screenshot(path=str(args.output / "90-invalid-image.png"), full_page=True)
            record["invalid_image_visible_failure"] = True
            if args.negative_video:
                await page.locator("input[type=file]").first.set_input_files(
                    {"name": "broken-video.mp4", "mimeType": "video/mp4", "buffer": args.negative_video.read_bytes()})
                await expect(page.get_by_text("broken-video.mp4", exact=True)).to_be_visible()
                await expect(page.get_by_text("当前影像：broken-video.mp4", exact=True)).to_be_visible(timeout=60000)
                await expect(page.get_by_text("复核失败：", exact=False)).to_have_count(0)
                await wait_script_idle(page, expect)
                await page.get_by_role("button", name="开始识别与复核", exact=True).click()
                await expect(page.get_by_text("Video decode ended early", exact=False)).to_be_visible(timeout=60000)
                await expect(page.get_by_text("识别完成：", exact=False)).to_have_count(0)
                await page.screenshot(path=str(args.output / "91-premature-video.png"), full_page=True)
                record["premature_video_visible_failure"] = True
            if args.check_region_review:
                await check_regions(page, context, args, record, expect)
            if args.check_distant_video:
                await check_distant_video(page, context, args, record, expect)
            recovery = sources[0]
            await page.locator("input[type=file]").first.set_input_files(
                {"name": recovery.name, "mimeType": "image/jpeg", "buffer": recovery.read_bytes()})
            await expect(page.get_by_text(recovery.name, exact=True)).to_be_visible()
            await expect(page.get_by_text("当前影像：" + recovery.name, exact=True)).to_be_visible(timeout=60000)
            await expect(page.get_by_text("复核失败：", exact=False)).to_have_count(0)
            await wait_script_idle(page, expect)
            await page.get_by_role("button", name="开始识别与复核", exact=True).click()
            await expect(page.get_by_text("识别完成：", exact=False)).to_be_visible(timeout=60000)
            await expect(page.get_by_text("复核失败：", exact=False)).to_have_count(0)
            async with page.expect_download() as recovered_download:
                await page.get_by_role("button", name="下载原始检测 JSON", exact=True).click()
            downloaded = await recovered_download.value
            response = await context.request.get(downloaded.url)
            assert response.ok
            recovered = json.loads(await response.body())
            assert recovered["source_sha256"] == hashlib.sha256(recovery.read_bytes()).hexdigest()
            assert recovered["status"] == "complete" and "error" not in recovered
            (args.output / "recovery-detections.json").write_text(json.dumps(recovered,ensure_ascii=False,indent=2)+"\n")
            await page.screenshot(path=str(args.output / "92-valid-image-recovery.png"), full_page=True)
            record["recovery_after_failure"] = {"passed": True, "source_sha256": recovered["source_sha256"]}
            await page.get_by_role("tab", name="摄像头接入说明", exact=True).click()
            await expect(page.get_by_text("当前演示支持照片与视频文件复核", exact=False)).to_be_visible()
            record["camera_calls"] = await page.evaluate("window.__cameraCalls")
            assert record["camera_calls"] == 0
            await page.screenshot(path=str(args.output / "99-live-disabled.png"), full_page=True)
            await page.get_by_role('tab', name='影像识别与复核', exact=True).click()
            await page.set_viewport_size({'width': 390, 'height': 844})
            collapse = page.locator('[data-testid="stSidebarCollapseButton"] button')
            await page.wait_for_timeout(350)  # Streamlit may already have collapsed offscreen.
            box = await collapse.bounding_box()
            if box and 0 <= box['x'] + box['width']/2 <= 390:
                await collapse.click()
            await page.locator('.sd1-masthead').scroll_into_view_if_needed()
            await expect(logo).to_be_visible()
            layout = await page.locator('.sd1-masthead').evaluate('''(node) => {
                const box = node.getBoundingClientRect();
                return {left: box.left, right: box.right, viewport: innerWidth,
                        pageWidth: document.documentElement.scrollWidth};
            }''')
            assert layout['left'] >= 0 and layout['right'] <= layout['viewport'] + 1, layout
            assert layout['pageWidth'] <= layout['viewport'] + 1, layout
            await page.screenshot(path=str(args.output/'98-branded-mobile.png'))
            record['mobile_layout'] = layout
            record["technical_passed"] = True
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            record["page_text"] = await page.locator("body").inner_text()
            await page.screenshot(path=str(args.output / "failure.png"), full_page=True)
            raise
        finally:
            await context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8767")
    parser.add_argument("--cdp", default="http://127.0.0.1:9226")
    parser.add_argument("--negative-video", type=Path)
    parser.add_argument("--additional-image", type=Path)
    parser.add_argument("--expected-additional-class")
    parser.add_argument("--check-region-review", action="store_true")
    parser.add_argument("--check-distant-video", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    record = {"at": datetime.now(timezone.utc).isoformat(), "url": args.url,
              "isolated_browser_context": True, "blocked_external": [], "uploads": [], "technical_passed": False}
    try:
        asyncio.run(run(args, record))
    finally:
        (args.output / "report.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
