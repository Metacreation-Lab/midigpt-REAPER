# -*- coding: utf-8 -*-
"""
REAPER_midigpt_imgui_smoketest.py -- diagnostic only, not a real feature.

Minimal ReaImGui window to verify the Python + ReaImGui + defer-loop
mechanism actually works in this REAPER install before building the real
MIDI-GPT control dashboard on top of it. Run this action; a small window
titled "MIDI-GPT ImGui Smoke Test" should appear and stay open/interactive
(a live-updating frame counter) until you close it or click Stop.

Structure mirrors cfillion/reaimgui's own official Python example
(examples/track_manager.py) exactly: RPR_defer(str) is called directly,
with no wrapper -- REAPER injects it into the script's namespace itself,
separate from the reaper_python.py/_ft machinery.
"""

import os
import sys

from reaper_python import *

# imgui.py (the Python ReaImGui binding) lives under the ReaTeam Extensions
# API scripts folder, not next to this script -- add it to sys.path.
sys.path.append(RPR_GetResourcePath() + "/Scripts/ReaTeam Extensions/API")
import imgui


class _ReaperConsole:
    def write(self, s):
        RPR_ShowConsoleMsg(s)
    def flush(self):
        pass

sys.stdout = sys.stderr = _ReaperConsole()

RPR_ClearConsole()
print("ImGui smoke test starting...\n")
print(f"imgui module loaded from: {imgui.__file__}\n")

frame_count = [0]


def init():
    global ctx
    ctx = imgui.CreateContext('MIDI-GPT Smoke Test')
    loop()


def loop():
    frame_count[0] += 1
    imgui.SetNextWindowSize(ctx, 400, 120, imgui.Cond_FirstUseEver())
    visible, is_open = imgui.Begin(ctx, "MIDI-GPT ImGui Smoke Test", True)
    if visible:
        imgui.Text(ctx, "If you can see this, ReaImGui + Python works.")
        imgui.Text(ctx, f"Frame: {frame_count[0]}")
        if imgui.Button(ctx, "Print to console"):
            print(f"Button clicked at frame {frame_count[0]}\n")
        imgui.End(ctx)

    if is_open:
        RPR_defer("loop()")
    else:
        print(f"Window closed after {frame_count[0]} frames. Smoke test done.\n")


RPR_defer("init()")
