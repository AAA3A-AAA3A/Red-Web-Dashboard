"""
The base of the RPC management has been done by Neuro Assassin (https://github.com/Cog-Creators/Red-Dashboard)!
"""

import typing  # isort:skip

import asyncio
import datetime
import threading

from flask import Flask

from .utils import check_for_disconnect, initialize_websocket, get_result


class TaskManager:
    def __init__(self, app: Flask) -> None:
        self.app: Flask = app

        self.threads: typing.List[typing.Union[threading.Thread, asyncio.Task]] = []
        self.ignore_disconnect = False

    async def update_data_variables(
        self, method: str, once: bool = True, only_bot_variables: bool = False
    ) -> None:
        try:
            while True:
                if not once:
                    await asyncio.sleep(self.app.config["WEBSOCKET_INTERVAL"])
                if not self.app.running:
                    return

                request = {
                    "jsonrpc": "2.0",
                    "id": 0,
                    "method": method,
                    "params": [only_bot_variables, [self.app.host, self.app.port]] if method == "DASHBOARDRPC__GET_VARIABLES" else [],
                }
                if self.app.cog is None:
                    with self.app.lock:
                        # This needs to be inside the lock, or both threads will create a websocket.
                        if not self.app.ws:
                            initialized = initialize_websocket(self.app)
                            if not initialized:
                                continue
                        result = await get_result(self.app, request, retry=False)
                        if not result:
                            continue
                        connected = check_for_disconnect(self.app, method, result)
                        if not connected:
                            continue
                else:
                    result = await get_result(self.app, request, retry=False)
                    if not result:
                        continue
                    connected = check_for_disconnect(self.app, method, result)
                    if not connected:
                        continue

                # if "result" not in result:
                #     self.app.logger.error(f"RPC websocket returned an unexpected response: {result}")
                #     continue
                if method == "DASHBOARDRPC__GET_DATA":
                    self.app.data.update(**result)
                elif method == "DASHBOARDRPC__GET_VARIABLES":
                    if not self.app.variables:
                        self.app.logger.info(
                            "Initial connection made with Red bot. Syncing data..."
                        )
                    self.app.variables.update(**result)

                if once:
                    break
        except Exception:
            self.app.logger.exception(f"Background task `{method}` died unexpectedly.")

    async def update_version(self) -> None:
        version: int = 0
        try:
            while True:
                await asyncio.sleep(self.app.config["WEBSOCKET_INTERVAL"])
                if not self.app.running:
                    return
                if self.app.ws and self.app.ws.connected:
                    request = {
                        "jsonrpc": "2.0",
                        "id": 0,
                        "method": "DASHBOARDRPC__CHECK_VERSION",
                        "params": [],
                    }
                    with self.app.lock:
                        if not self.app.ws:
                            initialized = initialize_websocket(self.app)
                            if not initialized:
                                continue

                        result = await get_result(self.app, request, retry=False)
                        if not result or "error" in result:
                            continue
                        if result.get("disconnected", False) or "version" not in result:
                            continue
                        if result["version"] != version != 0:
                            self.ignore_disconnect: bool = True
                            self.app.logger.info("RPC websocket behind. Closing and restarting...")
                            self.app.ws.close()
                            initialize_websocket(self.app)
                            self.ignore_disconnect: bool = False
                        version = result["version"]
        except Exception as e:
            self.app.logger.exception(
                "Background task `DASHBOARDRPC__CHECK_VERSION` died unexpectedly.", exc_info=e
            )

    async def check_if_connected(self) -> None:
        last_state_disconnected: bool = False
        while True:
            if not self.app.running:
                try:
                    self.app.ws.close()
                    del self.app.ws
                except AttributeError:
                    pass
                self.app.logger.info("RPC Websocket closed.")
                return
            await asyncio.sleep(0.1)
            if self.ignore_disconnect:
                continue
            if self.app.ws and self.app.ws.connected:
                self.app.config["RPC_CONNECTED"]: bool = True
                if last_state_disconnected:
                    self.app.logger.info("Reconnected to RPC Websocket.")
                    self.app.config["LAST_RPC_EVENT"]: datetime.datetime = datetime.datetime.now(
                        tz=datetime.timezone.utc
                    )
                    last_state_disconnected = False
            elif not last_state_disconnected:
                self.app.logger.warning("Disconnected from RPC Websocket.")
                self.app.config["RPC_CONNECTED"]: bool = False
                last_state_disconnected = True
                self.app.config["LAST_RPC_EVENT"]: datetime.datetime = datetime.datetime.now(
                    tz=datetime.timezone.utc
                )
                if self.app.ws:
                    self.app.ws.close()
                initialize_websocket(self.app)

    def start_tasks(self) -> None:
        if self.app.cog is None:
            self.threads.append(
                threading.Thread(
                    target=asyncio.run,
                    args=[self.update_data_variables("DASHBOARDRPC__GET_DATA", once=False)],
                    daemon=True,
                )
            )
            self.threads.append(
                threading.Thread(
                    target=asyncio.run,
                    args=[self.update_data_variables("DASHBOARDRPC__GET_VARIABLES", once=False)],
                    daemon=True,
                )
            )
            self.threads.append(
                threading.Thread(
                    target=asyncio.run,
                    args=[self.update_version()],
                    daemon=True,
                )
            )
            self.threads.append(
                threading.Thread(
                    target=asyncio.run,
                    args=[self.check_if_connected()],
                    daemon=True,
                )
            )
            for t in self.threads:
                t.start()
        else:
            self.threads.append(
                self.app.cog.bot.loop.create_task(
                    self.update_data_variables("DASHBOARDRPC__GET_DATA", once=False)
                )
            )
            self.threads.append(
                self.app.cog.bot.loop.create_task(
                    self.update_data_variables("DASHBOARDRPC__GET_VARIABLES", once=False)
                )
            )

    def stop_tasks(self) -> None:
        for t in self.threads:
            if isinstance(t, threading.Thread):
                t.join()
            else:
                t.stop()
