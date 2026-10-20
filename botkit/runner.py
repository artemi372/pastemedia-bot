"""Start the bot, restart it on /reload, read console commands.

``run(main)`` is the whole entry point of a bot. The first process is
a small supervisor: it starts the bot in a child process and starts it
again whenever the child exits with RELOAD_EXIT_CODE, so /reload picks
up new code and a new .env on Windows, Linux, in PyCharm or under
systemd alike. Any other exit code ends the supervisor too, so with
systemd use Restart=on-failure (Restart=always would undo /stop).
"""

import asyncio
import logging
import os
import signal
import subprocess
import sys
import threading
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from botkit.core import BotKit

log = logging.getLogger("botkit")

# Set in the bot process started by the supervisor.
CHILD_ENV = "BOTKIT_CHILD"
RELOAD_EXIT_CODE = 3


def setup_logging() -> None:
    """Log to the console in the same format in every bot."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def keep_awake(on: bool) -> None:
    """Keep Windows from sleeping while the bot runs.

    The screen may still turn off; this is the same call that video
    players use. Windows also clears it when the process exits, even
    after a crash. Does nothing on other systems.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        es_continuous = 0x80000000
        es_system_required = 0x00000001
        flags = es_continuous | (es_system_required if on else 0)
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception as e:
        log.warning("couldn't control sleep mode: %s", e)


def start_console(kit: "BotKit") -> None:
    """Read console commands in a background thread.

    input() blocks, so it runs in its own thread and hands every line
    to the event loop. A daemon thread never keeps the process alive.
    Without a terminal (a service) the thread just ends.
    """
    loop = asyncio.get_running_loop()

    def reader() -> None:
        while True:
            try:
                line = input()
            except (EOFError, KeyboardInterrupt, OSError, RuntimeError):
                return
            asyncio.run_coroutine_threadsafe(kit.console(line), loop)

    threading.Thread(target=reader, daemon=True, name="console").start()


def supervise() -> int:
    """Run the bot in a child process; start it again on /reload.

    The child shares this terminal, so console commands keep working.
    Ctrl+C reaches both processes: the child shuts down gracefully and
    the supervisor just waits for it. A service stop (SIGTERM) is
    passed on to the child.
    """
    env = {**os.environ, CHILD_ENV: "1"}
    while True:
        child = subprocess.Popen([sys.executable, *sys.argv], env=env)

        def forward(signum, _frame, child=child):
            try:
                child.send_signal(signum)
            except OSError:
                pass

        if os.name != "nt":
            signal.signal(signal.SIGTERM, forward)
        while True:
            try:
                code = child.wait()
                break
            except KeyboardInterrupt:
                continue  # the child handles Ctrl+C itself
        if code != RELOAD_EXIT_CODE:
            return code
        print("Restarting the bot…")


def run(main: Callable[[], Awaitable[int]]) -> None:
    """Run the bot: ``main`` in the child, the supervisor otherwise."""
    if os.environ.get(CHILD_ENV):
        try:
            sys.exit(asyncio.run(main()))
        except KeyboardInterrupt:
            sys.exit(0)
    sys.exit(supervise())
