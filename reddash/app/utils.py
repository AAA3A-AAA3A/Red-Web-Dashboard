import typing  # isort:skip

import base64
import datetime
import json
import os
import time
from copy import deepcopy
from importlib import import_module
from urllib.parse import parse_qs, quote_plus, urlencode, urlparse, urlunparse

import jwt
import websocket
from django.conf import settings
from fernet import Fernet
from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from flask_babel import Locale, _
from flask_bootstrap import Bootstrap
from flask_login import LoginManager, UserMixin, current_user
from flask_login import login_url as make_login_url
from flask_moment import Moment
from flask_sitemapper import Sitemapper
from flask_talisman import Talisman
from flask_wtf.csrf import CSRFProtect
from flask_wtf.file import FileAllowed, FileField, MultipleFileField
from wtforms import Field, SelectFieldBase, FormField
from fuzzywuzzy import process
from markdown import Markdown
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import Python3TracebackLexer, get_lexer_by_name
import bleach
from markupsafe import Markup

settings.configure()
from django_user_agents.utils import get_user_agent

AVAILABLE_COLORS: typing.List[str] = [
    "success",
    "warning",
    "danger",
    "info",
    "primary",
    "dark",
]

app: Flask = None

WS_URL = "ws://localhost:"
WS_EXCEPTIONS = (
    ConnectionRefusedError,
    websocket._exceptions.WebSocketConnectionClosedException,
    ConnectionResetError,
    ConnectionAbortedError,
    BrokenPipeError,
    AttributeError,  # If the connection is reset.
)


class User(UserMixin):
    USERS: typing.Dict[str, "User"] = {}

    def __init__(
        self,
        id: int,
        name: str,
        global_name: typing.Optional[str] = None,
        avatar_url: typing.Optional[str] = None,
    ) -> None:
        self.id: int = id
        self.name: str = name
        self.global_name: typing.Optional[str] = global_name
        self.avatar_url: typing.Optional[str] = avatar_url

        self.devices: typing.List[str] = []

        self.__class__.USERS[self.id] = self

    def get_id(self) -> str:
        token = self.generate_token(
            action="login", expiration_timedelta=datetime.timedelta(days=1)
        )
        self.devices.append(token)
        try:
            self.devices.remove(session["_user_id"])
        except (KeyError, ValueError):
            pass
        return token

    def __repr__(self) -> str:
        return f"<User id={self.id!r} name={self.name!r} global_name={self.global_name!r} avatar_url={self.avatar_url!r}>"

    @property
    def display_name(self) -> str:
        return self.global_name or self.name

    @property
    def display_avatar(self) -> str:
        return self.avatar_url or f"https://cdn.discordapp.com/embed/avatars/{(self.id >> 22) % 6}.png"

    @property
    def is_owner(self) -> bool:
        return self.id in app.variables["bot"]["owner_ids"]

    @property
    def is_active(self) -> bool:
        return not self.is_blacklisted

    @property
    def is_blacklisted(self) -> bool:
        return self.id in app.variables["bot"]["blacklisted_users"]

    def generate_token(
        self,
        action: typing.Optional[str] = None,
        expiration_timedelta: datetime.timedelta = datetime.timedelta(minutes=15),
        data: typing.Dict[str, typing.Any] = {},
    ) -> str:
        secret_key = app.config["SECRET_KEY"]
        expiration_time = datetime.datetime.now(tz=datetime.timezone.utc) + expiration_timedelta
        payload = {
            "user_id": self.id,
            "action": action,
            "exp": expiration_time,
        }
        payload.update(**data)
        return jwt.encode(payload, secret_key, algorithm="HS256")

    @classmethod
    def get_user_from_token(
        cls,
        token: str,
        action: typing.Optional[str] = None,
        unique: bool = True,
        return_data: bool = False,
    ) -> typing.Union["User", typing.Tuple["User", typing.Dict[str, typing.Any]]]:
        secret_key = app.config["SECRET_KEY"]
        try:
            data = jwt.decode(token, secret_key, algorithms=["HS256"])
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            raise
        if action is not None and data.get("action") != action:
            raise jwt.InvalidTokenError()
        if token in app.already_used_tokens:
            raise jwt.ExpiredSignatureError()
        if unique:
            app.already_used_tokens.add(token)
        user_id = data.get("user_id")
        user: User = cls.USERS.get(user_id)
        if user is None:
            raise jwt.ExpiredSignatureError()
        return user if not return_data else (user, data)


current_user: User


def register_extensions(_app: Flask) -> None:
    global app
    app = _app
    app.login_manager: LoginManager = LoginManager()
    app.login_manager.session_protection: str = "strong"
    app.config["USE_SESSION_FOR_NEXT"]: bool = False
    app.login_manager.login_view: str = "login_blueprint.login"
    app.login_manager.login_message: str = _(
        "Please log in to access this page."
    )  # Just to have the string in the translation files...
    app.login_manager.login_message_category: str = "info"
    app.login_manager.refresh_view: str = "login_blueprint.login"
    app.login_manager.needs_refresh_message: str = _(
        "To protect your account, please reauthenticate to access this page."
    )  # Just to have the string in the translation files...
    app.login_manager.needs_refresh_message_category: str = "info"
    app.login_manager.localize_callback: typing.Any = _
    app.login_manager.init_app(app)

    @app.login_manager.user_loader
    def user_loader(token: str) -> None:
        try:
            user: User = User.get_user_from_token(token=token, action="login", unique=False)
        except jwt.ExpiredSignatureError:
            return
        except jwt.InvalidTokenError:
            remote_addr = request.environ.get("HTTP_X_FORWARDED_FOR", request.remote_addr)
            if remote_addr in app.data["core"]["blacklisted_ips"]:
                return
            # app.data["core"]["blacklisted_ips"].append(remote_addr)
            return
        if not user.is_active or token not in user.devices:
            return
        return user

    # https://github.com/GoogleCloudPlatform/flask-talisman
    app.talisman: Talisman = Talisman()
    old_force_https = app.talisman._force_https

    def _force_https():
        if request.remote_addr in ("127.0.0.1", "::1"):
            return
        private_ip_ranges = [
            ("10.0.0.0", "10.255.255.255"),
            ("172.16.0.0", "172.31.255.255"),
            ("192.168.0.0", "192.168.255.255"),
        ]
        if any(start <= request.remote_addr <= end for start, end in private_ip_ranges):
            return
        return old_force_https()

    app.talisman._force_https = _force_https
    allow_unsecure_http_requests = app.data["core"]["allow_unsecure_http_requests"]
    app.talisman.init_app(app, force_https=not allow_unsecure_http_requests, session_cookie_secure=not allow_unsecure_http_requests, content_security_policy=None)

    app.config["WTF_CSRF_ENABLED"]: bool = True
    app.config["WTF_CSRF_SECRET_KEY"]: str = base64.urlsafe_b64decode(
        Fernet.generate_key().decode()
    )
    app.csrf_protect: CSRFProtect = CSRFProtect()
    app.csrf_protect.init_app(app)
    initial_protect = app.csrf_protect.protect

    def protect():
        initial_protect()
        g.csrf_valid = False

    app.csrf_protect.protect = protect
    initial_init_field = Field.__init__

    def init_field(field, *args, **kwargs):
        initial_init_field(field, *args, **kwargs)
        if isinstance(field, FormField):
            return
        if hasattr(field, "_value"):
            field._real_value = field._value
        field._value = lambda: (field._real_value() if hasattr(field, "_real_value") else "") or (
            (field.default if isinstance(field.default, typing.List) else str(field.default))
            if field.default is not None
            else ""
        )
        if isinstance(field, SelectFieldBase):
            old_choices_generator = field._choices_generator

            def _choices_generator(choices):
                for value, label, selected, render_kw in old_choices_generator(choices):
                    yield (
                        bleach.clean(value, tags=[], strip=False) if value is not None else None,
                        bleach.clean(label, tags=[], strip=False),
                        selected
                        or (
                            field.coerce(value) == field._value()
                            if not isinstance(field._value(), typing.List)
                            else field.coerce(value) in field._value()
                        ),
                        render_kw,
                    )

            field._choices_generator = _choices_generator
        elif isinstance(field, (FileField, MultipleFileField)):
            if (
                file_allowed := next(
                    (
                        validator
                        for validator in field.validators
                        if isinstance(validator, FileAllowed)
                    ),
                    None,
                )
            ) is not None:
                field.flags.accept = ", ".join(
                    [f".{extension}" for extension in file_allowed.upload_set]
                )

    Field.__init__ = init_field

    app.bootstrap: Bootstrap = Bootstrap()
    app.bootstrap.init_app(app)

    app.moment: Moment = Moment()
    app.moment.init_app(app)

    app.markdown: Markdown = Markdown()

    @app.template_filter("markdown")
    def markdown_filter(text: str) -> Markup:
        text = bleach.clean(text, tags=[], strip=False)
        return Markup(app.markdown.convert(text).replace("\n", ""))  # <br />

    @app.template_filter("highlight")
    def highlight_filter(code, language="python") -> Markup:
        code = bleach.clean(code, tags=[], strip=False).replace("&lt;", "<").replace("&gt;", ">")
        if language == "traceback":
            lexer = Python3TracebackLexer()
        else:
            lexer = get_lexer_by_name(language, stripall=True)
        formatter = HtmlFormatter()
        return Markup(highlight(code, lexer, formatter))

    app.site_mapper: Sitemapper = Sitemapper(https=not app.testing)


def register_blueprints(app: Flask) -> None:
    for module_name in ("base", "login", "third_parties"):
        module = import_module(f"reddash.app.{module_name}.routes")
        app.register_blueprint(module.blueprint)

    @app.errorhandler(404)
    async def not_found_error(error):
        return render_template("errors/404.html", error_message=error.description), 404

    @app.errorhandler(403)
    async def access_forbidden(error):
        return render_template("errors/403.html", error_message=error.description), 403

    @app.errorhandler(500)
    async def internal_error(error):
        return render_template("errors/500.html", error_message=error.description), 500

    @app.route("/error-<error>")
    async def route_errors(error):
        if error not in ("404", "403", "500"):
            return redirect(url_for("base_blueprint.index"))
        return render_template(f"errors/{error}.html"), int(error)

    @app.before_request
    def block_ip():
        request.META = {"HTTP_USER_AGENT": request.headers.get("USER_AGENT", "")}
        request.user_agent = get_user_agent(request)
        # if request.path not in ("/", "/login") and not request.path.startswith("/static") and not (request.path.startswith("/set") and request.path.count("/") == 1):
        #     return render_template("errors/404.html"), 404
        remote_addr = request.environ.get("HTTP_X_FORWARDED_FOR", request.remote_addr)
        if request.path.startswith(("/static", "/api/stream", "/blacklisted")):
            return
        if remote_addr in app.data["core"]["blacklisted_ips"]:
            return redirect(url_for("login_blueprint.blacklisted"))
        if (
            app.locked
            and not current_user.is_owner
            and not request.path.startswith("/static")
            and request.blueprint != "login_blueprint"
            and request.endpoint
            not in (
                "base_blueprint.index",
                "base_blueprint.sitemap",
                "base_blueprint.robots",
                "base_blueprint.credits",
            )
            and not (request.path.startswith("/set") and request.path.count("/") == 1)
        ):
            flash(_("The Dashboard is currently locked."), category="danger")
            return redirect(url_for("base_blueprint.index", next=request.url))


def apply_themes(app: Flask) -> None:
    @app.context_processor
    def override_url_for() -> typing.Dict[str, str]:
        return dict(url_for=_generate_url_for_theme)

    def _generate_url_for_theme(endpoint, **values) -> str:
        if endpoint.endswith("static"):
            themename = values.get("theme", None) or app.config.get("DEFAULT_THEME", None)
            if themename:
                theme_file = "{}/{}".format(themename, values.get("filename", ""))
                if os.path.isfile(os.path.join(app.static_folder, theme_file)):
                    values["filename"] = theme_file
            values["q"] = time.time()  # So Flask doesn't cache.
        if request.args.get("debug_toolbar") in ("True", "true", "1", "t", "on"):
            values["debug_toolbar"] = "True"
        return url_for(endpoint, **values)


def add_constants(app: Flask) -> None:
    default_color = app.data["ui"]["meta"]["default_color"]
    AVAILABLE_COLORS.remove(default_color)
    AVAILABLE_COLORS.insert(0, default_color)
    def process_meta_tags() -> typing.Dict[str, typing.Any]:
        meta = deepcopy(app.data["ui"]["meta"])
        meta["color"] = request.cookies.get("color", meta["default_color"])
        meta["available_colors"]: typing.List[str] = AVAILABLE_COLORS
        meta["background_theme"] = request.cookies.get(
            "background_theme", meta["default_background_theme"]
        )
        meta["sidenav_theme"] = request.cookies.get("sidenav_theme", meta["default_sidenav_theme"])
        return {"meta": meta}

    def process_sidenav() -> typing.List[typing.Dict]:
        sidenav = sorted(app.data["ui"]["sidenav"], key=lambda x: x["pos"])
        final = []
        for item in sidenav:
            item = dict(item.items())
            if item["session"] is True and not current_user.is_authenticated:
                continue
            if item["session"] is False and current_user.is_authenticated:
                continue
            if item["owner"] and not (current_user.is_authenticated and current_user.is_owner):
                continue
            # I have to localize here opposed to storing it because... well... then it's not localized.
            if item["name"] == "builtin-home":
                item["name"] = _("Home")
            elif item["name"] == "builtin-commands":
                item["name"] = _("Commands")
            elif item["name"] == "builtin-dashboard":
                item["name"] = _("Dashboard")
            elif item["name"] == "builtin-third_parties":
                item["name"] = _("Third Parties")
            elif item["name"] == "builtin-credits":
                item["name"] = _("Credits")
            elif item["name"] == "builtin-login":
                item["name"] = _("Login")
            elif item["name"] == "builtin-logout":
                item["name"] = _("Logout")
            elif item["name"] == "builtin-admin":
                item["name"] = _("Admin")
            elif item["name"] == "builtin-cog-management":
                item["name"] = _("Cog Management")
            # if not item["is_http"]:
            try:
                item["url"] = url_for(item["route"])
            except Exception:
                continue
            if (
                item["route"].split(".")[0] == "login_blueprint"
                and request.endpoint != "base_blueprint.index"
                and request.blueprint != "login_blueprint"
            ):
                item["url"] = make_login_url(item["route"], next_url=request.url)
            item["active"] = request.endpoint == item["route"]
            final.append(item)

        if app.data["custom_pages"]:
            index = next(
                (index for index, item in enumerate(final) if item["route"] == "base_blueprint.credits"),
                None,
            )
            for custom_page in app.data["custom_pages"]:
                custom_page = {
                    "name": custom_page["title"],
                    "icon": "fa fa-file-text",
                    "route": "base_blueprint.custom_page",
                    "session": False,
                    "owner": False,
                    "locked": False,
                    "hidden": False,
                    "url": url_for("base_blueprint.custom_page", page_url=custom_page["url"]),
                    "active": request.endpoint == "base_blueprint.custom_page" and request.view_args.get("page_url") == custom_page["url"],
                }
                final.insert(index, custom_page)
                index += 1
        
        return final

    def url_for_query(_anchor: typing.Optional[str] = None, **kwargs) -> Markup:
        full_url = request.url
        url_components = urlparse(full_url)
        query_params = parse_qs(url_components.query)
        query_params.update(kwargs)
        for kwarg, value in query_params.copy().items():
            if value is None or value == "None":
                del query_params[kwarg]
        new_query_params = {k: v if isinstance(v, str) else v for k, v in query_params.items()}
        new_query_string = urlencode(new_query_params, doseq=True, quote_via=quote_plus).replace(
            "amp%3B", ""
        )
        updated_url_components = url_components._replace(query=new_query_string)
        if _anchor is not None:
            updated_url_components = updated_url_components._replace(fragment=_anchor)
        relative_url = urlunparse(updated_url_components._replace(scheme="", netloc="", params="", fragment=""))
        return Markup(relative_url)

    def number_to_text_with_suffix(number: float) -> str:
        suffixes = [
            "k",
            "m",
            "b",
            "t",
            "q",
            "Q",
            "s",
            "S",
            "o",
            "n",
            "d",
            "U",
            "D",
            "T",
            "Qa",
            "Qi",
            "Sx",
            "Sp",
            "Oc",
            "No",
            "Vi",
        ]
        index = None
        while abs(number) >= 1000 and (index if index is not None else -1) < len(suffixes) - 1:
            number /= 1000.0
            if index is None:
                index = -1
            index += 1
        # return f"{number:.1f}{suffixes[index] if index is not None else ''}"
        if number == int(number):
            formatted_number = int(number)
        elif f'{number:.1f}' != "0.0":
            formatted_number = int(float(f"{number:.1f}")) if float(f"{number:.1f}") == int(float(f"{number:.1f}")) else f"{number:.1f}"
        else:
            formatted_number = int(float(f"{number:.2f}")) if float(f"{number:.2f}") == int(float(f"{number:.2f}")) else f"{number:.2f}"
        suffix = suffixes[index] if index is not None else ""
        return f"{formatted_number}{suffix}"

    @app.context_processor
    def inject_variables() -> typing.Dict[str, typing.Any]:
        variables = deepcopy(app.variables)
        variables["locales"] = app.config["LOCALE_DICT"]
        variables["safelocales"] = json.dumps(app.config["LOCALE_DICT"])
        variables["selectedlocale"] = session.get("lang_code")
        variables["sidenav"] = process_sidenav()
        uptime = datetime.datetime.fromtimestamp(
            app.variables["stats"]["uptime"]
        )
        utc_now = datetime.datetime.utcnow().replace(second=0, microsecond=0)
        real_timedelta = utc_now - uptime
        timedelta: datetime.timedelta = utc_now - uptime.replace(
            hour=utc_now.hour
            if real_timedelta > datetime.timedelta(days=30)
            else uptime.hour,
            minute=utc_now.minute
            if real_timedelta > datetime.timedelta(days=1)
            else uptime.minute,
            second=0,
            microsecond=0,
        )
        if timedelta.total_seconds() > 60 * 60 * 24 * 365:
            timedelta = datetime.timedelta(days=timedelta.days // 30 * 30)
        variables["stats"]["uptime_timedelta"] = humanize_timedelta(timedelta=timedelta)
        variables.update(**process_meta_tags())
        return dict(
            version="1.0",
            variables=variables,
            full_login_url=make_login_url(app.login_manager.login_view, next_url=request.url)
            if request.endpoint != "base_blueprint.index"
            and request.blueprint != "login_blueprint"
            else url_for(app.login_manager.login_view),
            url_for_query=url_for_query,
            number_to_text_with_suffix=number_to_text_with_suffix,
        )


def initialize_babel(app: Flask) -> None:
    app.config["BABEL_TRANSLATION_DIRECTORIES"]: str = "translations"
    app.config["LANGUAGES"]: typing.List[str] = [
        "en-US",
        "af-ZA",
        "ar-SA",
        "bg-BG",
        "ca-ES",
        "cs-CZ",
        "da-DK",
        "de-DE",
        "el-GR",
        "es-ES",
        "fi-FI",
        "fr-FR",
        "he-IL",
        "hu-HU",
        "id-ID",
        "it-IT",
        "ja-JP",
        "ko-KR",
        "nl-NL",
        "nb-NO",
        "pl-PL",
        "pt-BR",
        "pt-PT",
        "ro-RO",
        "ru-RU",
        "sk-SK",
        "sv-SE",
        "tr-TR",
        "uk-UA",
        "vi-VN",
        "zh-CN",
        "zh-HK",
        "zh-TW",
    ]
    locale_dict: typing.Dict[str, str] = {}
    for locale in app.config["LANGUAGES"]:
        loc = Locale.parse(locale, sep="-")
        lang = loc.get_language_name()
        if territory := loc.get_territory_name():
            lang = f"{lang} - {territory}"
        locale_dict[locale] = lang
    app.config["LOCALE_DICT"]: typing.Dict[str, str] = locale_dict

    @app.before_request
    def pull_locale() -> None:
        # Locale is determined in the following priority:
        # - `lang_code` kwarg
        # - `lang_code` cookie
        # - `lang_code` session value
        # - default from browser
        locale = None
        lang = request.args.get("lang_code") or request.cookies.get(
            "lang_code"
        )  # Url is visible by user, so it's the priority.
        lang = lang or session.get("lang_code")  # User either didn't have `lang_code` argument or wasnt able to match a locale. Let's check if theres something in the session.
        if lang:
            # User had `lang_code` argument in request, lets check if its valid.
            processed = process.extractOne(lang, app.config["LANGUAGES"])
            if processed[1] < 80:
                # Too low of a match, abort lang_code argument and go to session value.
                lang = None
            else:
                # User had `lang_code` argument, and it closely matched a registered locale.
                locale = processed[0]
        # Let's save that so it will be used on next request as well.
        session["lang_code"] = locale

    # @app.babel.localeselector
    def get_locale() -> str:
        return (
            session.get("lang_code") or request.accept_languages.best_match(app.config["LANGUAGES"], default="en-US")
        ).replace("-", "_")

    app.extensions["babel"].locale_selector = get_locale


def initialize_websocket(app: Flask) -> bool:
    with app.lock:
        app.ws: websocket.WebSocket = websocket.WebSocket()
        try:
            app.ws.connect(f"ws://{app.config['WEBSOCKET_HOST']}:{app.config['WEBSOCKET_PORT']}")
        except WS_EXCEPTIONS:
            app.ws.close()
            app.ws = None
            return False
    return True


def check_for_disconnect(app: Flask, result: typing.Dict[str, typing.Any]) -> bool:
    if (
        "error" in result
        and isinstance(result["error"], typing.Dict)
        and result["error"]["message"] == "Method not found"
        or result.get("disconnected", False)
    ):
        app.config["RPC_CONNECTED"]: bool = False
        if app.ws is not None:
            app.ws.close()
            app.ws = None
        return False
    return True


async def get_result(app: Flask, request: typing.Dict[str, typing.Any], *, retry: bool = True) -> typing.Dict[str, typing.Any]:
    if app.cog is not None:
        from aiohttp_json_rpc.protocol import JsonRpcMsg, JsonRpcMsgTyp
        try:
            method = app.cog.bot.rpc._rpc.methods[request["method"]]
        except KeyError:
            return {"status": 1, "error": _("Not connected to bot.")}
        return await method(
            http_request="GET",
            rpc=app.cog.bot.rpc._rpc,
            msg=JsonRpcMsg(type=JsonRpcMsgTyp.REQUEST, data=request),
        )
    try:
        with app.lock:
            app.ws.send(json.dumps(request))
            result = json.loads(app.ws.recv())
    except WS_EXCEPTIONS:
        if not retry:
            return {"status": 1, "error": _("Not connected to bot.")}
        app.logger.warning("Connection reset.")
        if app.ws:
            app.ws.close()
        initialize_websocket(app)
        return await get_result(app, request, retry=False)
    if "error" in result:
        if result["error"]["message"] == "Method not found":
            return {"status": 1, "error": _("Not connected to bot.")}
        app.logger.error(result["error"])
        return {"status": 1, "error": _("Something went wrong.")}
    if not result["result"] or isinstance(result["result"], typing.Dict) and result["result"].get("disconnected", False):
        return {"status": 1, "error": _("Not connected to bot.")}
    return result["result"]


def notify_owner_of_blacklist(app: Flask, ip: str) -> None:
    while True:
        if app.cog is not None or app.ws and app.ws.connected:
            request = {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "DASHBOARDRPC__NOTIFY_OWNERS_OF_BLACKLIST",
                "params": [ip],
            }
            result = (app, request)
            if not result or "error" in result:
                time.sleep(1)
                continue
            break
        time.sleep(1)


# This is taken from Red-DiscordBot's `chat_formatting.py` (https://github.com/Cog-Creators/Red-DiscordBot/blob/V3/develop/redbot/core/utils/chat_formatting.py#L521-L574).
def humanize_timedelta(
    *, timedelta: typing.Optional[datetime.timedelta] = None, seconds: typing.Optional[int] = None
) -> str:
    """
    Get a locale aware human timedelta representation.
    This works with either a timedelta object or a number of seconds.
    Fractional values will be omitted, and values less than 1 second
    an empty string.
    Parameters
    ----------
    timedelta: Optional[datetime.timedelta]
        A timedelta object
    seconds: Optional[int]
        A number of seconds
    Returns
    -------
    str
        A locale aware representation of the timedelta or seconds.
    Raises
    ------
    ValueError
        The function was called with neither a number of seconds nor a timedelta object
    """
    try:
        obj = seconds if seconds is not None else timedelta.total_seconds()
    except AttributeError:
        raise ValueError("You must provide either a timedelta or a number of seconds.")

    seconds = int(obj)
    periods = [
        (_("year"), _("years"), 60 * 60 * 24 * 365),
        (_("month"), _("months"), 60 * 60 * 24 * 30),
        (_("day"), _("days"), 60 * 60 * 24),
        (_("hour"), _("hours"), 60 * 60),
        (_("minute"), _("minutes"), 60),
        (_("second"), _("seconds"), 1),
    ]

    strings = []
    for period_name, plural_period_name, period_seconds in periods:
        if seconds >= period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            if period_value == 0:
                continue
            unit = plural_period_name if period_value > 1 else period_name
            strings.append(f"{period_value} {unit}")

    return ", ".join(strings)
