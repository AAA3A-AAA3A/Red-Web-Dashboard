# -*- encoding: utf-8 -*-
"""
License: Commercial
Copyright (c) 2019 - present AppSeed.us
Copyright (c) 2020 - present Neuro Assassin (https://github.com/Cog-Creators/Red-Dashboard)
"""

import argparse
import asyncio
import logging

import rich
from rich import columns
from rich import logging as rich_logging
from rich import panel, progress, rule
from rich import table as rtable
from rich.console import Console
from rich.style import Style
from rich.theme import Theme

from .app import FlaskApp

rich_console: Console = rich.get_console()
logging.basicConfig(
    format="[{asctime}] {name}: {message}",
    datefmt="%Y-%m-%d %H:%M:%S",
    style="{",
    handlers=[rich_logging.RichHandler(console=rich_console, rich_tracebacks=True)],
)
rich_console.push_theme(
    Theme(
        {
            "log.time": Style(dim=True),
            "logging.level.warning": Style(color="yellow"),
            "logging.level.critical": Style(color="white", bgcolor="red"),
            "logging.level.verbose": Style(color="magenta", italic=True, dim=True),
            "logging.level.trace": Style(color="white", italic=True, dim=True),
            "repr.number": Style(color="cyan"),
            "repr.url": Style(underline=True, italic=True, bold=False, color="cyan"),
        }
    )
)

parser: argparse.ArgumentParser = argparse.ArgumentParser()
parser.add_argument("--host", dest="host", type=str, default="0.0.0.0")
parser.add_argument("--port", dest="port", type=int, default=42356)
parser.add_argument("--rpc-port", dest="rpc_port", type=int, default=6133)
parser.add_argument("--interval", dest="interval", type=int, default=15, help=argparse.SUPPRESS)
parser.add_argument("--development", dest="dev", action="store_true", help=argparse.SUPPRESS)
# parser.add_argument("--debug", dest="debug", action="store_true")


async def _main():
    args = vars(parser.parse_args())
    app: FlaskApp = FlaskApp(cog=None, **args)

    table = rtable.Table(title="Settings")
    table.add_column("Setting:", style="red", no_wrap=True)
    table.add_column("Value:", style="blue", no_wrap=True)
    table.add_row("Webserver Host", app.host)
    table.add_row("Webserver Port", str(app.port))
    table.add_row("RPC Port", str(app.rpc_port))
    table.add_row("Update interval", str(app.interval))
    table.add_row("Environment", "Development" if app.dev else "Production")
    # table.add_row("Logging level", "Debug" if kwargs["debug"] else "Warning")
    progress_bar = progress.Progress(
        "{task.description}", progress.TextColumn("{task.fields[status]}\n")
    )
    progress_bar.print(rule.Rule("Red-Web-Dashboard - Webserver"))
    disclaimer = "This is an instance of Red-DiscordBot's Dashboard, created initially by Neuro Assassin (https://github.com/NeuroAssassin) then forked by AAA3A (https://github.com/AAA3A-AAA3A). This package isn't endorsed by the Org at all.\n\nThis package is protected under the AGPL License. Any action that will break this license (including but not limited to, removal of credits) may result in a DMCA takedown request, or other legal consequences.\nYou can view the license at https://github.com/AAA3A-AAA3A/Red-Web-Dashboard/blob/main/LICENSE."
    # vartask = progress_bar.add_task("Update variable task:", status="[bold blue]Starting[/bold blue]")
    # cmdtask = progress_bar.add_task("Update command task:", status="[bold blue]Starting[/bold blue]")
    # vertask = progress_bar.add_task("Update version task:", status="[bold blue]Starting[/bold blue]")
    # contask = progress_bar.add_task("RPC Connected", status="[bold blue]Starting[/bold blue]")
    progress_bar.print(columns.Columns([panel.Panel(table), panel.Panel(disclaimer)], equal=True))

    await app.create_app()
    await app.run_app()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
