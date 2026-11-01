"""Optional real-browser check: pip install playwright && playwright install chromium.

Run with: python tests/browser_security_smoke.py
"""

import threading

from playwright.sync_api import sync_playwright
from test_third_party_security import app, raw_response, routes
from werkzeug.serving import make_server

PAYLOAD = b"<script>document.documentElement.dataset.executed = 'yes'; fetch('/executed')</script>"
ASSETS = {
    "document.html": (b"<html>" + PAYLOAD + b"</html>", "text/html"),
    "image.svg": (
        b'<svg xmlns="http://www.w3.org/2000/svg">' + PAYLOAD + b"</svg>",
        "image/svg+xml",
    ),
    "document.xhtml": (
        b'<html xmlns="http://www.w3.org/1999/xhtml">' + PAYLOAD + b"</html>",
        "application/xhtml+xml",
    ),
    "document.xml": (
        b'<html xmlns="http://www.w3.org/1999/xhtml">' + PAYLOAD + b"</html>",
        "application/xml",
    ),
    "trusted.js": (b"window.trustedAssetLoaded = true;", "text/javascript"),
}


async def rpc_result(_app, rpc_request):
    path = rpc_request["params"][7]["asset_path"]
    body, content_type = ASSETS[path]
    return {"raw_response": raw_response(body, content_type)}


@app.route("/browser-parent")
def browser_parent():
    return '<script src="/third-party/Test/static/trusted.js"></script>'


def main():
    app.variables = {
        "third_parties": {
            "Test": {
                "static": {
                    "methods": ("GET", "HEAD"),
                    "context_ids": [],
                    "required_kwargs": ["asset_path"],
                    "optional_kwargs": [],
                    "is_owner": False,
                },
            },
        },
    }
    routes.get_result = rpc_result
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                requests = []
                page.on("request", lambda req: requests.append(req.url))
                page.goto(base + "/browser-parent")
                page.wait_for_function("window.trustedAssetLoaded === true")
                print("PASS: trusted JavaScript still executes when embedded by a page")
                for name in ASSETS:
                    if name == "trusted.js":
                        continue
                    response = page.goto(base + "/third-party/Test/static/" + name)
                    assert response.status == 200
                    assert response.headers["content-security-policy"] == "sandbox"
                    assert response.headers["x-content-type-options"] == "nosniff"
                    assert not page.evaluate("document.documentElement.dataset.executed")
                    assert page.evaluate("""() => {
                        try { document.cookie; return false; }
                        catch (error) { return error.name === 'SecurityError'; }
                    }""")
                    print(f"PASS: {name} script blocked and origin privileges denied")
                assert not any(url.endswith("/executed") for url in requests)
            finally:
                browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
