"""
The base of the login process has been done by Neuro Assassin (https://github.com/Cog-Creators/Red-Dashboard)!
"""

import datetime
import random
import string

from reddash.app.app import app

import aiohttp
import jwt
from django.utils.http import url_has_allowed_host_and_scheme
from flask import abort, flash, redirect, render_template, request, session, url_for
from flask_babel import _
from flask_login import current_user, login_fresh, login_user, logout_user

from ..utils import User
from . import blueprint

current_user: User


@app.site_mapper.include()
@blueprint.route("/login")
async def login():
    if current_user.is_authenticated and not login_fresh():
        redirecting_to: str = (
            request.args.get("next")
            if not app.config["USE_SESSION_FOR_NEXT"]
            else session.get("next")
        ) or url_for("base_blueprint.index")
        # `url_has_allowed_host_and_scheme`` should check if the url is safe for redirects, meaning it matches the request host.
        if not url_has_allowed_host_and_scheme(redirecting_to, request.host):
            return abort(400)
        return redirect(redirecting_to)
    if app.data["core"]["secret"] is None:
        flash(
            _(
                "Authorization is unavailable for Red-Web-Dashboard until setting a secret Discord oauth key. If you believe this message is delivered in error, please contact the developer for assistance."
            ),
            category="danger",
        )
        return redirect(url_for("base_blueprint.index"))
    return render_template("pages/login/login.html", next=request.args.get("next"))


@blueprint.route("/login/discord")
async def discord_oauth():
    if (redirect_uri := app.data["core"]["redirect_uri"]) is None:
        redirect_uri = (
            f"http://127.0.0.1:{app.port}/callback"
            if app.host in ("0.0.0.0", "127.0.0.1")
            else f"http://{app.host}/callback"
        )
    state = "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(15))
    session["state"] = state
    session["next"] = request.args.get("next")
    return redirect(
        f"https://discordapp.com/api/oauth2/authorize?client_id={app.variables['bot']['application_id']}&redirect_uri={redirect_uri}&response_type=code&scope=identify&state={state}"
    )


@blueprint.route("/callback")
async def callback():
    redirecting_to: str = (request.args.get("next") or session.get("next")) or url_for(
        "base_blueprint.index"
    )
    # `url_has_allowed_host_and_scheme` should check if the url is safe for redirects, meaning it matches the request host.
    if not url_has_allowed_host_and_scheme(redirecting_to, request.host):
        return abort(400)
    if current_user.is_authenticated:
        return redirect(redirecting_to)

    try:
        code = request.args["code"]
    except KeyError:
        flash(
            _(
                "Authorization failed due to cancellation. Click again below if you wish to re-attempt authorizing."
            ),
            category="danger",
        )
        return redirect(url_for("login_blueprint.login", next=redirecting_to))
    if "state" not in session or "state" not in request.args:
        flash(
            _(
                "Authorization must be directed through this login page to ensure protection against CSRF. Please re-authenticate."
            ),
            category="danger",
        )
        return redirect(url_for("login_blueprint.login", next=redirecting_to))
    if session.pop("state") != request.args["state"]:
        flash(
            _(
                "Your authentication request contained a different state than when your authorization process was initiated. Please re-attempt."
            ),
            category="danger",
        )
        return redirect(url_for("login_blueprint.login", next=redirecting_to))

    if (redirect_uri := app.data["core"]["redirect_uri"]) is None:
        redirect_uri = (
            f"http://127.0.0.1:{app.port}/callback"
            if app.host == "0.0.0.0"
            else f"http://{app.host}/callback"
        )
    data = {
        "client_id": app.variables["bot"]["application_id"],
        "client_secret": app.data["core"]["secret"],
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "scope": "identify",
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    async with aiohttp.ClientSession() as aiohttp_session:
        async with aiohttp_session.post(
            "https://discordapp.com/api/v9/oauth2/token", data=data, headers=headers
        ) as r:
            response = await r.json()
            try:
                token = response["access_token"]
            except KeyError as e:
                app.logger.error(f"Failed to log someone in.\n{response}", exc_info=e)
                flash(
                    _(
                        "Authorization failed due to issues on the Discord API. Please re-attempt to authorize below, or contact the developer for assistance if this issue persists."
                    ),
                    category="danger",
                )
                return redirect(url_for("login_blueprint.login", next=request.args.get("next")))

        async with aiohttp_session.get(
            "https://discordapp.com/api/v9/users/@me", headers={"Authorization": f"Bearer {token}"}
        ) as r:
            new_data = await r.json()
            try:
                user: User = User(
                    id=int(new_data["id"]),
                    name=new_data["username"],
                    global_name=new_data["global_name"],
                    avatar_url=f"https://cdn.discordapp.com/avatars/{new_data['id']}/{new_data['avatar']}.png" if new_data["avatar"] is not None else None,
                )
                login_user(
                    user=user,
                    remember=False,
                    duration=datetime.timedelta(weeks=1),
                )
            except KeyError as e:
                app.logger.error(f"Failed to obtain a user's profile.\n{new_data}", exc_info=e)
                flash(
                    _(
                        "Authorization failed due to issues on the Discord API. Please re-attempt to authorize below, or contact the developer for assistance if this issue persists."
                    ),
                    category="danger",
                )
                return redirect(url_for("login_blueprint.login", next=redirecting_to))

        app.logger.info(f"User `{user.display_name}` ({user.id}) connected.")
        flash(
            _("Nice to see you again, {display_name}!").format(display_name=user.display_name),
            category="success",
        )
        return redirect(redirecting_to)


@blueprint.route("/logout")
async def logout():
    if current_user.is_authenticated:
        try:
            current_user.devices.remove(session["_user_id"])
        except (KeyError, ValueError):
            pass
        logout_user()
        flash(_("You have been deconnected with success."), category="success")
    return redirect(url_for("login_blueprint.login"))


@blueprint.route("/blacklisted")
async def blacklisted():
    remote_addr = request.environ.get("HTTP_X_FORWARDED_FOR", request.remote_addr)
    if remote_addr not in app.data["core"]["blacklisted_ips"]:
        return redirect(url_for("base_blueprint.index"))
    return render_template("errors/blacklisted.html")
