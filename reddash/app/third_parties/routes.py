import base64
import binascii

from django.utils.http import url_has_allowed_host_and_scheme
from flask import (
    abort,
    flash,
    g,
    jsonify,
    make_response,
    redirect,
    render_template,
    render_template_string,
    request,
    session,
    url_for,
)
from flask_babel import _
from flask_login import current_user, login_required
from flask_login import login_url as make_login_url
from flask_wtf.csrf import generate_csrf
from werkzeug.exceptions import HTTPException

from reddash.app.app import app
from reddash.app.base.routes import get_guild, get_third_parties
from reddash.app.pagination import Pagination
from reddash.app.utils import get_result  # , get_user_id

from . import blueprint

# <---------- Third Parties ---------->

_RAW_RESPONSE_ALLOWED_HEADERS = frozenset(
    header.lower()
    for header in (
        "Cache-Control",
        "ETag",
        "Last-Modified",
        "Expires",
        "Vary",
        "Content-Disposition",
        "Content-Language",
    )
)


def _resolve_third_party_name(name: str) -> str | None:
    third_parties = app.variables["third_parties"]
    name = name.strip()
    if name in third_parties:
        return name
    return next((key for key in third_parties if key.lower() == name.lower()), None)


def _is_safe_asset_path(asset_path: str) -> bool:
    # Flask has already URL-decoded the path. Reject Windows drives, UNC
    # paths and alternate data streams as well as POSIX traversal.
    return (
        bool(asset_path)
        and not any(char in asset_path for char in ("\\", ":"))
        and not any(ord(char) < 32 or ord(char) == 127 for char in asset_path)
        and all(part not in ("", ".", "..") for part in asset_path.split("/"))
    )


async def _check_third_party_page_access(
    name: str,
    page_key: str,
    *,
    page: str | None = None,
    guild_id: str | None = None,
    login_redirect: bool = True,
) -> tuple[dict, dict]:
    page_data = app.variables["third_parties"][name][page_key]
    context_ids = {}
    if "user_id" in page_data["context_ids"]:
        if current_user.is_authenticated:
            context_ids["user_id"] = (
                current_user.id
            )  # int(get_user_id(app=app, req=request, ses=session))
        elif login_redirect:
            abort(redirect(make_login_url("login_blueprint.login", next_url=request.url)))
        else:
            abort(401, description=_("You must be logged in to access this page."))
    if page_data["is_owner"] and not (current_user.is_authenticated and current_user.is_owner):
        abort(403, description=_("You must be the owner of the bot to access this page."))
    if "guild_id" in page_data["context_ids"]:
        try:
            context_ids["guild_id"] = int(guild_id)
        except (TypeError, ValueError):
            abort(
                redirect(
                    make_login_url(
                        "base_blueprint.dashboard",
                        next_url=url_for(
                            "third_parties_blueprint.third_party",
                            name=name,
                            page=page,
                            guild_id="GUILD_ID",
                            **request.args,
                        ),
                    ),
                ),
            )
        return_guild = await get_guild(context_ids["guild_id"], for_third_parties=True)
        if return_guild["guild"]["status"] == 1:
            abort(jsonify(return_guild["guild"]))
    else:
        return_guild = {}
    return context_ids, return_guild


def _build_raw_response(raw_response):
    try:
        body = base64.b64decode(raw_response["body_base64"], validate=True)
    except (binascii.Error, KeyError, TypeError, ValueError):
        return abort(500, description=_("Invalid raw third-party response."))

    response = make_response(body, raw_response.get("status", 200))
    response.headers["Content-Type"] = raw_response.get(
        "content_type",
        "application/octet-stream",
    )
    for header, value in raw_response.get("headers", {}).items():
        header, value = str(header), str(value)
        if header.lower() not in _RAW_RESPONSE_ALLOWED_HEADERS or any(
            char in value for char in "\r\n\x00"
        ):
            app.logger.debug(f"Dropping disallowed raw third-party response header `{header}`.")
            continue
        response.headers[header] = value
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Raw documents (including HTML, SVG and XML) must never gain the
    # Dashboard's origin privileges. This does not sandbox embedding pages.
    response.headers["Content-Security-Policy"] = "sandbox"
    g.raw_third_party_response = True
    return response


@blueprint.after_request
def protect_third_party_cache(response):
    if request.endpoint in (
        "third_parties_blueprint.third_party",
        "third_parties_blueprint.third_party_static",
    ):
        response.vary.add("Cookie")
        # Session cookies can also be refreshed after response hooks run.
        # Only successful, anonymous, session-free assets may be shared.
        if (
            not g.get("third_party_public_asset", False)
            or response.status_code != 200
            or request.cookies
            or session.modified
            or "Set-Cookie" in response.headers
        ):
            response.headers["Cache-Control"] = "private, no-store"
    return response


async def _call_third_party_page(
    *,
    method: str,
    name: str,
    page: str | None,
    context_ids=None,
    required_kwargs=None,
    optional_kwargs=None,
    extra_kwargs=None,
    data=None,
    include_csrf=True,
):
    if context_ids is None:
        context_ids = {}
    if required_kwargs is None:
        required_kwargs = {}
    if optional_kwargs is None:
        optional_kwargs = {}
    if extra_kwargs is None:
        extra_kwargs = {}
    if data is None:
        data = {"form": {}, "json": {}}

    # Keep the existing RPC signature compatible without exposing CSRF
    # material or creating a session for read-only asset requests.
    csrf_token = ("", "")
    csrf_secret = ""
    if include_csrf:
        generate_csrf()
        csrf_token = (session["csrf_token"], g.csrf_token)
        csrf_secret = base64.urlsafe_b64encode(app.config["WTF_CSRF_SECRET_KEY"]).decode()
    requeststr = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "DASHBOARDRPC_THIRDPARTIES__DATA_RECEIVE",
        "params": [
            method,
            name,
            page,
            request.url,
            csrf_token,
            csrf_secret,
            context_ids,
            required_kwargs,
            optional_kwargs,
            extra_kwargs,
            data,
            app.extensions["babel"].locale_selector() if include_csrf else "en_US",
        ],
    }
    return await get_result(app, requeststr)


@app.csrf_protect.exempt
@blueprint.route("/api/webhook", methods=("POST",))
async def webhook_route():
    if not request.is_json:
        # Reject any requests that aren't json for now.
        return jsonify(
            {"status": 0, "message": "Invalid formatting. This endpoint receives JSON only."},
        )
    payload = request.get_json()
    payload["origin"] = request.origin
    payload["headers"] = dict(
        request.headers.items(),
    )  # Pass header data here incase there was something else the user needs for filtering.
    payload["user_agent"] = str(
        request.user_agent,
    )  # User agent seems adequate enough for filtering.
    payload["request_args"] = request.args.to_dict()
    try:
        requeststr = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "DASHBOARDRPC_WEBHOOKS__WEBHOOK_RECEIVE",
            "params": [payload],
        }
        return await get_result(app, requeststr)
    except Exception as e:  # noqa: BLE001 - Convert RPC failures to an HTTP response.
        app.logger.error("Error sending webhook data.", exc_info=e)


@blueprint.route("/third_party/callback/<provider>")
@blueprint.route("/oauth/callback/<provider>")
@login_required
async def oauth_route(provider: str):
    args = request.args.copy()
    args["provider"] = provider
    args["url"] = request.url
    requeststr = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "DASHBOARDRPC_THIRDPARTIES__OAUTH_RECEIVE",
        "params": [current_user.id, args],
    }
    await get_result(app, requeststr)
    return render_template("pages/third_parties/oauth.html", provider=provider)


@blueprint.route("/third-parties/<third_party>")
@blueprint.route("/third-parties")
@login_required
async def third_parties(third_party: str | None = None):
    return_third_parties = await get_third_parties()

    return render_template(
        "pages/third_parties/third_parties.html",
        **return_third_parties,
        tab_name=None
        if third_party is None or third_party not in return_third_parties["third_parties"]
        else third_party,
    )


@blueprint.route("/third-party/<name>/static/<path:asset_path>", methods=("GET", "HEAD"))
async def third_party_static(name: str, asset_path: str):
    if not _is_safe_asset_path(asset_path):
        return abort(404)
    third_parties = app.variables["third_parties"]
    name = _resolve_third_party_name(name)
    if name is None:
        return abort(404, description=_("Looks like that third party doesn't exist... Strange..."))
    if name in app.data["disabled_third_parties"]:
        return abort(403, description=_("This third party is disabled."))
    if "static" not in third_parties[name]:
        return abort(404, description=_("Looks like that page doesn't exist... Strange..."))
    if request.method not in third_parties[name]["static"]["methods"]:
        return abort(405, description=_("Method not allowed."))
    if "guild_id" in third_parties[name]["static"]["context_ids"]:
        return abort(400, description=_("Static pages cannot require a guild context."))
    context_ids, _return_guild = await _check_third_party_page_access(
        name,
        "static",
        login_redirect=False,
    )

    try:
        result = await _call_third_party_page(
            method=request.method,
            name=name,
            page="static",
            context_ids=context_ids,
            required_kwargs={"asset_path": asset_path},
            include_csrf=False,
        )
        if "raw_response" in result:
            g.third_party_public_asset = (
                not third_parties[name]["static"]["context_ids"]
                and not third_parties[name]["static"]["is_owner"]
            )
            return _build_raw_response(result["raw_response"])
        if "error_code" in result:
            return abort(result["error_code"], description=result.get("error_message"))
        return abort(500, description=_("Invalid raw third-party response."))
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - Convert RPC failures to an HTTP response.
        app.logger.error(
            f"Error in static asset `{asset_path}` of third party `{name}`.",
            exc_info=e,
        )
        return abort(500, description=_("An error occurred while processing your request."))


@blueprint.route(
    "/api/third-party/<name>/<page>",
    methods=(
        "GET",
        "HEAD",
        "OPTIONS",
        "POST",
        "PATCH",
        "DELETE",
    ),
)
@blueprint.route(
    "/api/third-party/<name>",
    methods=(
        "GET",
        "HEAD",
        "OPTIONS",
        "POST",
        "PATCH",
        "DELETE",
    ),
)
@blueprint.route(
    "/dashboard/<guild_id>/third-party/<name>/<page>",
    methods=(
        "GET",
        "HEAD",
        "OPTIONS",
        "POST",
        "PATCH",
        "DELETE",
    ),
)
@blueprint.route(
    "/dashboard/<guild_id>/third-party/<name>",
    methods=(
        "GET",
        "HEAD",
        "OPTIONS",
        "POST",
        "PATCH",
        "DELETE",
    ),
)
@blueprint.route(
    "/third-party/<name>/<page>",
    methods=(
        "GET",
        "HEAD",
        "OPTIONS",
        "POST",
        "PATCH",
        "DELETE",
    ),
)
@blueprint.route(
    "/third-party/<name>",
    methods=(
        "GET",
        "HEAD",
        "OPTIONS",
        "POST",
        "PATCH",
        "DELETE",
    ),
)
async def third_party(name: str, page: str | None = None, guild_id: str | None = None):
    third_parties = app.variables["third_parties"]
    name = _resolve_third_party_name(name)
    if name is None:
        return abort(
            404,
            description=_("Looks like that third party doesn't exist... Strange..."),
        )
    if name in app.data["disabled_third_parties"]:
        return abort(403, description=_("This third party is disabled."))
    if page is not None:
        page = _page = page.lower()
    else:
        _page = "null"
    if _page not in third_parties[name]:
        # if _page != "null" and page.isdecimal() and "null" in third_parties[name]:
        #     guild_id, page, _page = page, None, "null"
        return abort(404, description=_("Looks like that page doesn't exist... Strange..."))
    if request.method not in third_parties[name][_page]["methods"]:
        return abort(405, description=_("Method not allowed."))

    context_ids, return_guild = await _check_third_party_page_access(
        name,
        _page,
        page=page,
        guild_id=guild_id,
    )

    kwargs = request.args.copy()
    required_kwargs = {}
    optional_kwargs = {}
    for key in third_parties[name][_page]["context_ids"]:
        if key in ("user_id", "guild_id"):
            continue
        try:
            context_ids[key] = int(kwargs.pop(key))
        except KeyError:
            return render_template("errors/custom.html", error_title=f"Missing argument: `{key}`.")
        except ValueError:
            return render_template("errors/custom.html", error_title=f"Invalid argument: `{key}`.")
    for key in third_parties[name][_page]["required_kwargs"]:
        if key not in kwargs:
            return render_template("errors/custom.html", error_title=f"Missing argument: `{key}`.")
        required_kwargs[key] = kwargs.pop(key)
    if page == "static" and not _is_safe_asset_path(required_kwargs.get("asset_path", "")):
        return abort(404)
    for key in kwargs.copy():
        if key in third_parties[name][_page]["optional_kwargs"]:
            optional_kwargs[key] = kwargs.pop(key)
    extra_kwargs = kwargs

    data = {}
    data["form"] = request.form.to_dict(flat=False)
    data["json"] = (
        request.json.to_dict(flat=False)
        if request.method not in ("GET", "HEAD") and request.content_type == "application/json"
        else {}
    )

    try:
        result = await _call_third_party_page(
            method=request.method,
            name=name,
            page=page,
            context_ids=context_ids,
            required_kwargs=required_kwargs,
            optional_kwargs=optional_kwargs,
            extra_kwargs=extra_kwargs,
            data=data,
        )

        if "raw_response" in result:
            return _build_raw_response(result["raw_response"])
        if "data" in result:
            return result["data"]
        if "notifications" in result:
            for notification in result["notifications"]:
                flash(notification["message"], category=notification["category"])
        if "web_content" in result:
            for key, value in result["web_content"].items():
                if isinstance(value, dict) and "items" in value:
                    result["web_content"][key]: Pagination = Pagination(
                        value.pop("items"),
                        **value,
                    )
                    result["web_content"]["source"] += "\n\n" + result["web_content"][key].to_html(
                        key,
                        render_template_string=False,
                    )
            if result["web_content"].get("standalone", False):
                return render_template_string(
                    name=name,
                    page=page,
                    **return_guild,
                    **result["web_content"],
                )
            return render_template(
                "pages/third_parties/third_party.html",
                name=name,
                page=page,
                **return_guild,
                expanded=result["web_content"].get("expanded", False),
                fullscreen=result["web_content"].get("fullscreen", False),
                source_content=render_template_string(
                    result["web_content"].pop("source"),
                    name=name,
                    page=page,
                    **return_guild,
                    **result["web_content"],
                ),
            )
        if "error_code" in result:
            return abort(result["error_code"], description=result.get("error_message"))
        if "error_title" in result:
            return render_template(
                "errors/custom.html",
                error_title=result["error_title"],
                error_message=result.get("error_message"),
            )
        if "redirect_url" in result:
            # Check if the URL is safe for redirects (matches the request host).
            if not url_has_allowed_host_and_scheme(result["redirect_url"], request.host):
                return abort(400)
            return redirect(result["redirect_url"])
        return result
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - Convert RPC failures to an HTTP response.
        app.logger.error(
            f"Error in the page `{page or 'Main Page'}` of the third party `{name}`.",
            exc_info=e,
        )
        return abort(500, description=_("An error occurred while processing your request."))
