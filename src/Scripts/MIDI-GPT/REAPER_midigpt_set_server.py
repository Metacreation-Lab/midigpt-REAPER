# -*- coding: utf-8 -*-
"""
REAPER_midigpt_set_server.py  --  configure the MIDI-GPT server address

Prompts for the MIDI-GPT HTTP server URL (host/IP/domain, optionally with
port) and persists it via REAPER's ExtState so REAPER_midigpt_infill.py
picks it up on every run. Use this when the server is not running on the
same machine as REAPER (e.g. a remote workstation or a machine on the LAN).
"""

from reaper_python import *

EXT_STATE_SECTION = "MIDI-GPT"
EXT_STATE_KEY = "server_url"
DEFAULT_SERVER_URL = "http://127.0.0.1:3456"


def run_set_server():
    current = RPR_GetExtState(EXT_STATE_SECTION, EXT_STATE_KEY)
    current = (current or "").strip() or DEFAULT_SERVER_URL

    ret, _, _, _, csv_out, _ = RPR_GetUserInputs(
        "MIDI-GPT: Set Server Address",
        1,
        "Server URL (e.g. http://192.168.1.20:3456),extrawidth=150",
        current,
        512,
    )
    if not ret:
        return

    url = csv_out.strip()
    if not url:
        return

    if "://" not in url:
        url = f"http://{url}"

    url = url.rstrip("/")

    RPR_SetExtState(EXT_STATE_SECTION, EXT_STATE_KEY, url, True)
    RPR_ShowConsoleMsg(f"MIDI-GPT server address set to: {url}\n")


if __name__ == "__main__":
    run_set_server()
