"""Exercise third-party responses with Flask's real request/session machinery.

Run with: python -m unittest discover -s tests -v
"""

import base64
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import quote

from werkzeug.exceptions import InternalServerError

from reddash.app import FlaskApp
from reddash.app.utils import initialize_babel, register_extensions

# Routes use the application's module-level singleton at import time.
app = FlaskApp()
app.config.update(TESTING=True, SECRET_KEY="test-session-key")
app.data = {
    "core": {"allow_unsecure_http_requests": True, "redirect_uri": ""},
    "disabled_third_parties": [],
}
register_extensions(app)
initialize_babel(app)

from reddash.app.third_parties import routes  # noqa: E402

app.register_blueprint(routes.blueprint)


@app.route("/login", endpoint="login_blueprint.login")
def login():
    return "Login"


def raw_response(body=b"asset", content_type="text/javascript", headers=None):
    return {
        "body_base64": base64.b64encode(body).decode("ascii"),
        "content_type": content_type,
        "headers": headers or {},
    }


class AssetPathSecurityTests(unittest.TestCase):
    def test_unsafe_paths_never_reach_rpc(self):
        for asset_path in (
            "C:/Windows/win.ini",
            "C:relative.txt",
            "assets/icon.svg:payload",
            "../secret",
            "assets/../../secret",
            "assets/./secret",
            "assets//secret",
            "\\\\server\\share\\secret",
            "assets\\..\\secret",
            "assets/secret\x00",
            "assets/secret\n",
        ):
            with (
                self.subTest(asset_path=asset_path),
                patch.object(
                    routes,
                    "get_result",
                    new_callable=AsyncMock,
                ) as rpc,
            ):
                response = app.test_client().get(
                    "/third-party/Test/static/" + quote(asset_path, safe="/"),
                )
                self.assertEqual(response.status_code, 404)
                rpc.assert_not_awaited()

    def test_normal_asset_paths_are_allowed(self):
        for asset_path in ("assets/index-a123.js", "fonts/main.woff2", "icons/icon 1.png"):
            with self.subTest(asset_path=asset_path):
                self.assertTrue(routes._is_safe_asset_path(asset_path))


class AssetCacheSecurityTests(unittest.TestCase):
    def setUp(self):
        self.page = {
            "methods": ("GET", "HEAD"),
            "context_ids": [],
            "required_kwargs": ["asset_path"],
            "optional_kwargs": [],
            "is_owner": False,
        }
        app.variables = {"third_parties": {"Test": {"static": self.page}}}
        app.data["disabled_third_parties"] = []
        self.client = app.test_client()
        self.rpc = AsyncMock(
            return_value={
                "raw_response": raw_response(
                    headers={
                        "Cache-Control": "public, max-age=3600, s-maxage=7200",
                    },
                ),
            },
        )
        rpc_patch = patch.object(routes, "get_result", self.rpc)
        self.addCleanup(rpc_patch.stop)
        rpc_patch.start()

    def test_anonymous_static_assets_have_no_session_or_csrf_material(self):
        with patch.object(routes, "generate_csrf") as generate:
            for method in ("GET", "HEAD"):
                with self.subTest(method=method):
                    response = self.client.open(
                        "/third-party/test/static/assets/main.js?lang_code=de-DE",
                        method=method,
                        headers={"Accept-Language": "de-DE"},
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.cache_control.public)
                    self.assertNotIn("Set-Cookie", response.headers)
                    self.assertEqual(response.headers["Content-Security-Policy"], "sandbox")
                    self.assertIn("Cookie", response.vary)
                    params = self.rpc.call_args.args[1]["params"]
                    self.assertEqual(params[4], ("", ""))
                    self.assertEqual(params[5], "")
                    self.assertEqual(params[7], {"asset_path": "assets/main.js"})
                    self.assertEqual(params[11], "en_US")
                    if method == "HEAD":
                        self.assertEqual(response.data, b"")
            generate.assert_not_called()
        self.assertIsNone(self.client.get_cookie("session"))

    def test_cookie_bearing_static_requests_are_private_without_creating_csrf(self):
        with self.client.session_transaction() as saved:
            saved["lang_code"] = "de-DE"
        response = self.client.get("/third-party/Test/static/assets/main.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.assertNotIn("Set-Cookie", response.headers)
        with self.client.session_transaction() as saved:
            self.assertNotIn("csrf_token", saved)
            self.assertEqual(saved["lang_code"], "de-DE")

    def test_refreshing_permanent_sessions_cannot_be_public(self):
        with self.client.session_transaction() as saved:
            saved.permanent = True
            saved["csrf_token"] = "existing-token"
        response = self.client.get("/third-party/Test/static/assets/main.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.assertIn("Set-Cookie", response.headers)

    def test_user_required_assets_reject_anonymous_visitors_before_rpc(self):
        self.page["context_ids"] = ["user_id"]
        response = self.client.get("/third-party/Test/static/assets/main.js")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.rpc.assert_not_awaited()

    def test_personalized_assets_forward_identity_and_are_private(self):
        self.page["context_ids"] = ["user_id"]
        with patch.object(routes, "current_user", SimpleNamespace(is_authenticated=True, id=42)):
            response = self.client.get("/third-party/Test/static/assets/main.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        params = self.rpc.call_args.args[1]["params"]
        self.assertEqual(params[6], {"user_id": 42})
        self.assertEqual(params[5], "")

    def test_owner_required_assets_reject_non_owner_before_rpc(self):
        self.page.update(context_ids=["user_id"], is_owner=True)
        with patch.object(
            routes,
            "current_user",
            SimpleNamespace(is_authenticated=True, is_owner=False, id=42),
        ):
            response = self.client.get("/third-party/Test/static/assets/main.js")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.rpc.assert_not_awaited()

    def test_guild_scoped_assets_are_rejected_before_rpc(self):
        self.page["context_ids"] = ["user_id", "guild_id"]
        response = self.client.get("/third-party/Test/static/assets/main.js")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.rpc.assert_not_awaited()

    def test_owner_assets_are_private_even_when_owner_metadata_has_no_user_context(self):
        self.page["is_owner"] = True
        with patch.object(
            routes,
            "current_user",
            SimpleNamespace(is_authenticated=True, is_owner=True),
        ):
            response = self.client.get("/third-party/Test/static/assets/main.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")

    def test_disabled_third_parties_never_reach_rpc(self):
        app.data["disabled_third_parties"] = ["Test"]
        response = self.client.get("/third-party/Test/static/assets/main.js")
        self.assertEqual(response.status_code, 403)
        self.rpc.assert_not_awaited()

    def test_non_asset_pages_keep_csrf_and_cannot_be_shared(self):
        app.variables["third_parties"]["Test"]["null"] = {**self.page, "required_kwargs": []}
        response = self.client.get("/third-party/Test")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.assertIn("Set-Cookie", response.headers)
        params = self.rpc.call_args.args[1]["params"]
        self.assertTrue(all(params[4]))
        self.assertTrue(params[5])

    def test_json_and_template_responses_are_private(self):
        app.variables["third_parties"]["Test"]["null"] = {**self.page, "required_kwargs": []}
        for result in (
            {"data": {"ticket": "private"}},
            {"web_content": {"standalone": True, "source": "{{ csrf_token() }}"}},
        ):
            with self.subTest(result=result):
                self.rpc.return_value = result
                response = self.client.get("/third-party/Test")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["Cache-Control"], "private, no-store")
                self.assertEqual(
                    response.headers["Content-Security-Policy"],
                    "object-src 'none'; base-uri 'self'",
                )

    def test_mutating_pages_still_require_valid_csrf(self):
        app.variables["third_parties"]["Test"]["null"] = {
            **self.page,
            "required_kwargs": [],
            "methods": ("GET", "POST"),
        }
        response = self.client.post("/third-party/Test")
        self.assertEqual(response.status_code, 400)
        self.rpc.assert_not_awaited()
        self.client.get("/third-party/Test")
        token = self.rpc.call_args.args[1]["params"][4][1]
        response = self.client.post("/third-party/Test", data={"csrf_token": token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.assertEqual(self.rpc.call_args.args[1]["params"][0], "POST")

    def test_errors_and_invalid_raw_responses_are_private(self):
        for result, status in (
            ({"error_code": 404}, 404),
            ({"web_content": {"source": "not an asset"}}, 500),
            ({"raw_response": {"body_base64": "!!!"}}, 500),
            ({"raw_response": {**raw_response(), "status": 404}}, 404),
        ):
            with self.subTest(result=result):
                self.rpc.return_value = result
                response = self.client.get("/third-party/Test/static/assets/main.js")
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.headers["Cache-Control"], "private, no-store")

    def test_unsafe_paths_on_query_based_static_pages_are_rejected(self):
        response = self.client.get("/api/third-party/Test/static?asset_path=C:/Windows/win.ini")
        self.assertEqual(response.status_code, 404)
        self.rpc.assert_not_awaited()


class RawResponseSecurityTests(unittest.TestCase):
    def test_raw_documents_are_sandboxed(self):
        for content_type in (
            "text/html; charset=utf-8",
            "image/svg+xml",
            "text/xml",
            "application/xml",
            "application/xhtml+xml",
            "application/custom+xml",
        ):
            with self.subTest(content_type=content_type), app.test_request_context():
                body = b"<script>parent.compromised = true</script>"
                response = routes._build_raw_response(raw_response(body, content_type))
                self.assertEqual(response.data, body)
                self.assertEqual(response.headers["Content-Type"], content_type)
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(response.headers["Content-Security-Policy"], "sandbox")

    def test_cogs_cannot_override_security_or_set_cookies(self):
        with app.test_request_context():
            response = routes._build_raw_response(
                raw_response(
                    headers={
                        "cOnTeNt-SeCuRiTy-PoLiCy": "sandbox allow-scripts allow-same-origin",
                        "X-Content-Type-Options": "",
                        "Content-Type": "text/html",
                        "Set-Cookie": "session=attacker",
                        "Location": "https://example.com",
                        "Service-Worker-Allowed": "/",
                        "cAcHe-CoNtRoL": "public, max-age=3600",
                        "ETag": '"bundle-v1"',
                    },
                ),
            )
        self.assertEqual(response.headers["Content-Security-Policy"], "sandbox")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.mimetype, "text/javascript")
        self.assertNotIn("Set-Cookie", response.headers)
        self.assertNotIn("Location", response.headers)
        self.assertNotIn("Service-Worker-Allowed", response.headers)
        self.assertEqual(response.headers["Cache-Control"], "public, max-age=3600")
        self.assertEqual(response.headers["ETag"], '"bundle-v1"')

    def test_binary_assets_keep_their_bytes_and_mime_type(self):
        for content_type in ("image/png", "font/woff2", "text/css", "text/javascript"):
            with self.subTest(content_type=content_type), app.test_request_context():
                body = bytes(range(256))
                response = routes._build_raw_response(raw_response(body, content_type))
                self.assertEqual(response.data, body)
                self.assertEqual(response.mimetype, content_type)
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_invalid_body_returns_500(self):
        for payload in ({}, {"body_base64": "!!!"}, {"body_base64": None}):
            with (
                self.subTest(payload=payload),
                app.test_request_context(),
                self.assertRaises(InternalServerError),
            ):
                routes._build_raw_response(payload)


if __name__ == "__main__":
    unittest.main()
