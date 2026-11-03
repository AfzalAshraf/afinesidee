"""Sidee Enhanced: launch-at-login and keep-alive supervision.

Auto-start (Phase 6) is deliberately best-effort and local only:
  * Windows  -> a .vbs shortcut in the user's Startup folder
  * macOS    -> a LaunchAgent plist in ~/Library/LaunchAgents
  * other    -> reported as unsupported (the setting is still stored)

Keep-alive is a small supervisor: it runs the dashboard as a child process
and restarts it after a crash (non-zero exit), exiting cleanly on a normal
shutdown or a termination signal.
"""
from __future__ import annotations

import os
import plistlib
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import storage

AGENT_LABEL = "io.github.afzalashraf.sidee-enhanced"
STARTUP_NAME = "Sidee Enhanced.vbs"


def platform() -> str:
    if os.name == "nt" or sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "other"


def supported() -> bool:
    return platform() in ("windows", "macos")


def _startup_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        appdata = str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _launchagent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / (AGENT_LABEL + ".plist")


def _default_command() -> list[str]:
    """What a fresh login should launch."""
    if platform() == "macos":
        return ["/Applications/Sidee.app/Contents/MacOS/Sidee"]
    root = str(Path(__file__).resolve().parent.parent)
    return [sys.executable.replace("python.exe", "pythonw.exe") if os.name == "nt"
            else sys.executable,
            str(Path(root) / "sidee.py")]


def _vbs_content(launcher: str) -> str:
    # Hide the console window; quote by doubling embedded quotes.
    p = Path(launcher)
    folder = str(p.parent).replace('"', '""')
    safe = launcher.replace('"', '""')
    return ('Set sh = CreateObject("WScript.Shell")\r\n'
            f'sh.CurrentDirectory = "{folder}"\r\n'
            f'sh.Run """{safe}""", 0, False\r\n')


def _plist_content(command: list[str]) -> bytes:
    plist = {
        "Label": AGENT_LABEL,
        "ProgramArguments": command,
        "RunAtLoad": True,
        "KeepAlive": False,
        "ProcessType": "Background",
    }
    return plistlib.dumps(plist)


def is_enabled() -> bool:
    try:
        if platform() == "windows":
            return (_startup_dir() / STARTUP_NAME).is_file()
        if platform() == "macos":
            return _launchagent_path().is_file()
    except OSError:
        return False
    return False


def set_autostart(enabled: bool, command: list[str] | None = None) -> dict:
    """Enable/disable launch at login. Returns the resulting status."""
    cmd = command or _default_command()
    try:
        if platform() == "windows":
            target = _startup_dir() / STARTUP_NAME
            if enabled:
                target.parent.mkdir(parents=True, exist_ok=True)
                launcher = str(Path(__file__).resolve().parent.parent / "start-windows.bat")
                target.write_text(_vbs_content(launcher), encoding="utf-8")
            elif target.is_file():
                target.unlink()
        elif platform() == "macos":
            target = _launchagent_path()
            if enabled:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(_plist_content(cmd))
            elif target.is_file():
                target.unlink()
    except OSError as error:
        return {"ok": False, "error": str(error), "supported": supported(),
                "autostart": is_enabled(), "platform": platform()}
    storage.save_config({"autostart": bool(enabled)})
    return status()


def status() -> dict:
    cfg = storage.load_config()
    return {"ok": True, "supported": supported(), "platform": platform(),
            "autostart": bool(cfg.get("autostart")) and is_enabled(),
            "configured": bool(cfg.get("autostart")),
            "keep_alive": bool(cfg.get("keep_alive"))}


def set_keep_alive(enabled: bool) -> dict:
    storage.save_config({"keep_alive": bool(enabled)})
    return status()


def supervise(command: list[str]) -> int:
    """Run ``command`` and restart it after a crash until asked to stop."""
    stopping = {"flag": False}

    def _stop(*_):
        stopping["flag"] = True

    previous = {}
    try:
        for number in (signal.SIGINT, signal.SIGTERM):
            try:
                previous[number] = signal.signal(number, _stop)
            except (ValueError, OSError):
                pass
        restarts = 0
        while not stopping["flag"]:
            process = subprocess.Popen(command)
            code = process.wait()
            if stopping["flag"] or code == 0:
                return 0
            restarts += 1
            print(f"Sidee keep-alive: server stopped (code {code}); "
                  f"restarting ({restarts})…", flush=True)
            for _ in range(20):
                if stopping["flag"]:
                    return 0
                time.sleep(0.1)
        return 0
    finally:
        for number, handler in previous.items():
            try:
                signal.signal(number, handler)
            except (ValueError, OSError):
                pass
