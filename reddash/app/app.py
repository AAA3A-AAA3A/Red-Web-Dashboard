"""
License: Commercial
Copyright (c) 2019 - present AppSeed.us
Copyright (c) 2020 - present Neuro Assassin (https://github.com/Cog-Creators/Red-Dashboard)
"""

import typing  # isort:skip

import base64
import datetime
import logging
import sys
import threading

from flask import Flask
from flask_babel import Babel, _
from flask_bootstrap import Bootstrap
from flask_login import LoginManager
from flask_moment import Moment
from flask_sitemapper import Sitemapper
from flask_talisman import Talisman
from flask_wtf.csrf import CSRFProtect
from markdown import Markdown
from waitress import serve
from werkzeug.serving import BaseWSGIServer, make_server

from .task_manager import TaskManager
from .utils import (
    add_constants,
    apply_themes,
    initialize_babel,
    register_blueprints,
    register_extensions,
)  # NOQA


class Lock:
    def __init__(self) -> None:
        self.lock: threading.Lock = threading.Lock()

    def __enter__(self) -> None:
        self.lock.acquire()

    def __exit__(self, *args) -> None:
        self.lock.release()


class ServerThread(threading.Thread):
    def __init__(self, app: Flask, host: str, port: int) -> None:
        super().__init__()
        self.server: BaseWSGIServer = make_server(host=host, port=port, app=app, threaded=True)
        self.ctx: typing.Any = app.app_context()
        self.ctx.push()

    def run(self) -> None:
        self.server.serve_forever()

    def shutdown(self) -> None:
        self.server.shutdown()


class FlaskApp(Flask):
    def __init__(
        self,
        cog: typing.Optional[typing.Any] = None,  # To don't use RPC.
        host: str = "0.0.0.0",
        port: int = 42356,
        rpc_port: int = 6133,
        interval: int = 5,
        dev: bool = False,
    ) -> None:  # debug: bool = False,
        super().__init__(import_name=__name__, static_folder="static", template_folder="templates")

        self.cog: typing.Optional[typing.Any] = cog
        self.host: str = host
        self.port: int = port
        self.rpc_port: int = rpc_port
        self.interval: int = interval
        self.dev: bool = dev
        self.testing = self.debug = self.dev

        self.lock: Lock = Lock()
        self.babel: Babel = Babel(self)

        self.task_manager: TaskManager = TaskManager(self)
        self.data: typing.Dict[str, typing.Any] = {}
        self.variables: typing.Dict[str, typing.Any] = {}
        self.server_thread: ServerThread = None

        self.login_manager: LoginManager = None
        self.talisman: Talisman = None
        self.csrf_protect: CSRFProtect = None
        self.bootstrap: Bootstrap = None
        self.moment: Moment = None
        self.markdown: Markdown = None
        self.site_mapper: Sitemapper = None

        self.logger: logging.Logger = logging.getLogger("reddash")
        self.logger.setLevel(logging.DEBUG)

        self.already_used_tokens: typing.Set[str] = set()

        self.locked: bool = False

        global app
        app = self

    async def create_app(self) -> None:
        # Initialize websocket variables.
        self.ws = None
        self.lock: Lock = Lock()

        # Initialize core variables.
        self.running: bool = True
        self.config.from_object(__name__)
        self.config["ASSETS_ROOT"]: str = "/static/assets"
        self.config["TEMPLATES_AUTO_RELOAD"]: bool = True
        self.config["MAX_CONTENT_LENGTH"]: int = 16 * 1024 * 1024  # 16MB

        self.config["WEBSOCKET_HOST"]: str = "localhost"
        self.config["WEBSOCKET_PORT"]: int = self.rpc_port
        self.config["WEBSOCKET_INTERVAL"]: int = self.interval
        self.config["RPC_CONNECTED"]: bool = False
        self.config["LAUNCH"]: datetime.datetime = datetime.datetime.now(tz=datetime.timezone.utc)
        self.config["LAST_RPC_EVENT"]: datetime.datetime = self.config["LAUNCH"]
        await self.task_manager.update_data_variables("DASHBOARDRPC__GET_DATA")
        await self.task_manager.update_data_variables(
            "DASHBOARDRPC__GET_VARIABLES", only_bot_variables=True
        )
        self.task_manager.start_tasks()

        # Initialize security.
        # Session encoding.
        fernet_key: str = self.data["core"]["secret_key"]
        secret_key: bytes = base64.urlsafe_b64decode(fernet_key)
        # JWT encoding.
        jwt_fernet_key: str = self.data["core"]["jwt_secret_key"]
        jwt_secret_key: bytes = base64.urlsafe_b64decode(jwt_fernet_key)
        self.secret_key: bytes = secret_key
        self.config["SECRET_KEY"]: bytes = secret_key
        self.jwt_secret_key: bytes = jwt_secret_key

        # Initialize core app functions.
        register_extensions(self)
        register_blueprints(self)
        apply_themes(self)
        add_constants(self)
        initialize_babel(self)

    async def run_app(self) -> None:
        self.logger.info("Webserver started.")
        # if self.dev:
        #     # self.run(host=self.host, port=self.port, debug=self.debug)
        #     partial_run = functools.partial(self.run, host=self.host, port=self.port, debug=self.debug)
        # else:
        #     # serve(self, host=self.host, port=self.port, _quiet=True)
        #     partial_run = functools.partial(serve, self, host=self.host, port=self.port, _quiet=True)
        # t = threading.Thread(target=partial_run)
        if self.cog is not None:
            self.server_thread: ServerThread = ServerThread(
                app=self, host=self.host, port=self.port
            )
            self.server_thread.start()
        else:
            try:
                if self.dev:
                    self.run(host=self.host, port=self.port, debug=True, threaded=True)
                else:
                    serve(
                        self,
                        host=self.host,
                        port=self.port,
                        _quiet=True,
                        threads=10,
                        clear_untrusted_proxy_headers=True,
                    )
            except KeyboardInterrupt:
                pass
            finally:
                self.running: bool = False
                self.logger.fatal("Shutting down...")
                self.logger.fatal("Webserver terminated.")
                sys.exit(0)
