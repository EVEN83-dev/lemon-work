from .models import SkillResult, SkillDef

METADATA = {
    "name": "browser_automation",
    "version": "2.0.0",
    "category": "automation",
    "description": "Browser automation via requests+BS4 for scrape, Playwright for full automation if available.",
}


def execute(
    url: str = "",
    action: str = "scrape",
    selector: str = "",
    value: str = "",
    **kwargs,
) -> SkillResult:
    if not url.strip():
        return SkillResult.fail("url is required")

    valid_actions = ("screenshot", "scrape", "fill", "click", "extract_links", "extract_text", "page_info")
    if action not in valid_actions:
        return SkillResult.fail(
            "Invalid action '" + str(action) + "'. Must be one of: " + str(valid_actions)
        )

    if action in ("scrape", "extract_links", "extract_text", "page_info"):
        return _web_request(url, action, selector)
    elif action == "screenshot":
        return _screenshot_via_playwright(url)
    elif action in ("fill", "click"):
        return _interact_via_playwright(url, action, selector, value)
    else:
        return SkillResult.fail("Unsupported action: " + str(action))


def _web_request(url: str, action: str, selector: str) -> SkillResult:
    try:
        import requests
    except ImportError:
        return SkillResult.fail("requests is not installed. Install with: pip install requests")

    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 (LemonAgent/2.0)"})
        resp.raise_for_status()
    except Exception as e:
        return SkillResult.fail("HTTP request failed: " + str(e))

    if action == "extract_text" or action == "scrape":
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            title = soup.title.string.strip() if soup.title and soup.title.string else "(no title)"
            text = soup.get_text(separator="\n", strip=True)[:8000]
            import re as _re
            text = _re.sub(r'\n{3,}', '\n\n', text)

            links = []
            if action == "scrape":
                for a in soup.find_all("a", href=True)[:20]:
                    link_text = a.get_text(strip=True)[:80]
                    links.append({"text": link_text, "href": a["href"]})

            output = (
                "=== Page Content ===\n"
                "URL: " + url + "\n"
                "Title: " + title + "\n"
                "Status: " + str(resp.status_code) + "\n"
                "Content Length: " + str(len(text)) + " chars\n\n"
                + text[:3000]
            )
            if links:
                output += "\n\n=== Links ===\n"
                for l in links:
                    output += "  " + l["text"] + " -> " + l["href"] + "\n"

            return SkillResult.ok(
                output=output,
                data={"url": url, "title": title, "text": text, "links": links, "status": resp.status_code},
            )
        except ImportError:
            text = resp.text[:5000]
            return SkillResult.ok(
                output="Raw HTML (install beautifulsoup4 for parsed output):\n" + text[:3000],
                data={"url": url, "raw_html": text[:5000], "status": resp.status_code},
            )

    elif action == "extract_links":
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
            links = []
            for a in soup.find_all("a", href=True)[:50]:
                links.append({"text": a.get_text(strip=True)[:80], "href": a["href"]})
            output = "=== Links from " + url + " ===\n"
            for l in links:
                output += "  " + l["text"] + " -> " + l["href"] + "\n"
            return SkillResult.ok(output=output, data={"url": url, "links": links})
        except ImportError:
            import re as _re
            hrefs = _re.findall(r'href=["\']([^"\']+)["\']', resp.text)[:50]
            return SkillResult.ok(
                output="Links (regex-based, install BS4 for better parsing):\n" + "\n".join(hrefs[:30]),
                data={"url": url, "links": [{"href": h} for h in hrefs]},
            )

    elif action == "page_info":
        content_type = resp.headers.get("Content-Type", "unknown")
        content_length = resp.headers.get("Content-Length", str(len(resp.content)))
        server = resp.headers.get("Server", "unknown")
        import re as _re
        title_match = _re.search(r'<title[^>]*>([^<]+)</title>', resp.text, _re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else "(no title)"

        output = (
            "=== Page Info ===\n"
            "URL: " + url + "\n"
            "Status: " + str(resp.status_code) + "\n"
            "Title: " + title + "\n"
            "Content-Type: " + content_type + "\n"
            "Content-Length: " + content_length + "\n"
            "Server: " + server + "\n"
        )
        return SkillResult.ok(
            output=output,
            data={"url": url, "status": resp.status_code, "title": title,
                  "content_type": content_type, "server": server},
        )

    return SkillResult.fail("Unexpected action state")


def _screenshot_via_playwright(url: str) -> SkillResult:
    try:
        from playwright.sync_api import sync_playwright
        import tempfile
        import os as _os

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            tmp_path = _os.path.join(tempfile.gettempdir(), "screenshot_" + str(int(__import__("time").time())) + ".png")
            page.screenshot(path=tmp_path, full_page=False)
            browser.close()

        return SkillResult.ok(
            output="Screenshot saved to: " + tmp_path,
            data={"path": tmp_path, "url": url},
        )
    except ImportError:
        return SkillResult(
            success=False,
            error="Playwright not installed. Install with: pip install playwright && playwright install chromium",
            output="Screenshot requires Playwright. Falling back to text extraction.\n"
                   "Use action='scrape' for text-only content extraction without Playwright.",
        )
    except Exception as e:
        return SkillResult.fail("Screenshot failed: " + str(e))


def _interact_via_playwright(url: str, action: str, selector: str, value: str) -> SkillResult:
    if not selector.strip():
        return SkillResult.fail("selector is required for " + action + " action")

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30000, wait_until="domcontentloaded")

            if action == "fill":
                if not value.strip():
                    return SkillResult.fail("value is required for fill action")
                page.fill(selector, value)
                result_text = "Filled '" + selector + "' with '" + value + "' on " + url
            elif action == "click":
                page.click(selector)
                result_text = "Clicked '" + selector + "' on " + url
            else:
                result_text = "Action performed on " + url

            page.wait_for_timeout(1000)
            browser.close()

        return SkillResult.ok(output=result_text, data={"url": url, "action": action, "selector": selector})
    except ImportError:
        return SkillResult(
            success=False,
            error="Playwright not installed. Install with: pip install playwright && playwright install chromium",
            output="Browser interaction (fill/click) requires Playwright.\n"
                   "Use action='scrape' for read-only content extraction without Playwright.",
        )
    except Exception as e:
        return SkillResult.fail("Browser interaction failed: " + str(e))


def register(registry) -> None:
    registry.register(SkillDef(
        name="browser_automation",
        description="Browser automation: scrape/extract_text/extract_links/page_info via requests+BS4; screenshot/fill/click via Playwright (graceful fallback).",
        category="automation",
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to navigate to",
                },
                "action": {
                    "type": "string",
                    "enum": ["screenshot", "scrape", "fill", "click", "extract_links", "extract_text", "page_info"],
                    "description": "Browser action to perform",
                },
                "selector": {
                    "type": "string",
                    "description": "CSS selector for the target element (required for fill/click)",
                },
                "value": {
                    "type": "string",
                    "description": "Value to fill in (required for fill action)",
                },
            },
            "required": ["url"],
        },
        handler=execute,
        timeout=30,
        risk_level="medium",
    ))
