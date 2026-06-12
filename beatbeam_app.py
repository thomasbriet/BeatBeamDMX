#!/usr/bin/env python3
import argparse
import atexit
import colorsys
import json
import math
import mimetypes
import os
import secrets
import shutil
import socket
import struct
import subprocess
import threading
import time
from collections import deque
from contextlib import suppress
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from enttec_open_dmx import (
    DMX_CHANNELS,
    EnttecOpenDmx,
    clamp_dmx,
    find_fixture,
    find_mode,
    load_fixture_profiles,
    values_for_fixture,
)


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
CONFIG_PATH = Path(os.environ.get("BEATBEAM_CONFIG_PATH") or (ROOT / "beatbeam_config.json"))
REMOTE_ACCESS_PATH = Path(os.environ.get("BEATBEAM_REMOTE_ACCESS_PATH") or (ROOT / "beatbeam_remote.json"))
TRIGGER_LOG_PATH = Path("/tmp/beatbeam-trigger.log")
TRACK_PREVIEW_CACHE_DIR = Path(
    os.environ.get("BEATBEAM_TRACK_PREVIEW_CACHE_DIR")
    or (Path.home() / "Library/Application Support" / "BeatBeamDMX" / "track_preview_cache")
)
DEFAULT_HTTP_PORT = 8780
DEFAULT_OSC_PORT = 4461
DEFAULT_DMX_FPS = 30.0
API_SCHEMA_VERSION = 3
FIXTURE_LIBRARY = load_fixture_profiles()
SERVER_HOST = "127.0.0.1"
SERVER_PORT = DEFAULT_HTTP_PORT
REMOTE_ACCESS_CONFIG = None


class TriggerLogger:
    def __init__(self, path=TRIGGER_LOG_PATH):
        self.path = Path(path)
        self.lock = threading.Lock()

    def log(self, event, **fields):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        millis = int((time.time() % 1.0) * 1000.0)
        parts = [f"{key}={self._format_value(value)}" for key, value in fields.items()]
        line = f"{timestamp}.{millis:03d} {event}"
        if parts:
            line += " " + " ".join(parts)
        line += "\n"
        with self.lock:
            try:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
            except Exception:
                pass

    @staticmethod
    def _format_value(value):
        if value is None:
            return "-"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, float):
            return f"{value:.4f}"
        text = str(value).strip().replace("\n", " ")
        return text if text else "-"


TRIGGER_LOG = TriggerLogger()

COLOR_PRESETS = {
    "manual": None,
    "intro": (70, 145, 255, 0),
    "verse": (50, 190, 120, 0),
    "build": (255, 190, 40, 0),
    "chorus": (255, 70, 135, 0),
    "drop": (255, 55, 170, 0),
    "break": (60, 80, 255, 0),
    "outro": (255, 110, 45, 0),
    "low": (45, 90, 255, 0),
    "mid": (60, 210, 150, 0),
    "high": (255, 70, 80, 0),
}

COLOR_BANKS = {
    1: (70, 145, 255, 0),
    2: (130, 210, 255, 0),
    3: (255, 235, 180, 80),
    4: (255, 90, 55, 0),
    5: (190, 120, 255, 0),
    6: (255, 70, 160, 0),
    7: (40, 255, 225, 0),
    8: (255, 255, 255, 255),
}

VIVID_COLOR_ANCHORS = [
    (255, 0, 0, 0),
    (255, 120, 0, 0),
    (255, 220, 0, 0),
    (0, 255, 0, 0),
    (0, 255, 255, 0),
    (0, 80, 255, 0),
    (170, 0, 255, 0),
    (255, 0, 180, 0),
]

PURE_SHOW_COLORS = [
    (255, 0, 0, 0),
    (0, 255, 0, 0),
    (0, 0, 255, 0),
    (255, 0, 180, 0),
    (0, 255, 255, 0),
    (255, 140, 0, 0),
]

FIXTURE_PRESETS = {
    "shehds_flat_par_12x3w_rgbw": {
        "label_base": "PAR",
        "mode": "8ch",
        "color_source": "phrase",
    },
    "shehds_led_wash_7x12w_rgbw_moving_head": {
        "label_base": "Moving Head",
        "mode": "15ch",
        "color": {"red": 255, "green": 255, "blue": 255, "white": 255},
        "beat_pulse_enabled": False,
        "color_source": "phrase",
    },
    "uking_zq06016": {
        "label_base": "Wall Wash",
        "mode": "P001",
        "color_source": "phrase",
    },
}

WW_BLACK = (0, 0, 0)
WW_WHITE = (255, 255, 255)
WW_SOFT_WHITE = (120, 120, 120)
WW_DEEP_BLUE = (0, 0, 255)
WW_BLUE = (0, 80, 255)
WW_SOFT_BLUE = (0, 60, 255)
WW_PURPLE = (180, 0, 255)
WW_CYAN = (0, 255, 255)
WW_AMBER = (255, 120, 0)
WW_RED = (255, 0, 0)
WW_WARM_GLOW_LOW = (80, 20, 0)
WW_WARM_GLOW_MID = (140, 50, 0)
WW_WARM_GLOW_HIGH = (220, 90, 0)
WW_WARM_GLOW_PEAK = (255, 140, 0)

WALL_WASH_CUES = {
    "full_white_wash": {
        "label": "Full White Wash",
        "frames": [[WW_WHITE] * 8],
    },
    "soft_white_wash": {
        "label": "Soft White Wash",
        "frames": [[WW_SOFT_WHITE] * 8],
    },
    "deep_blue_wash": {
        "label": "Deep Blue Wash",
        "frames": [[WW_DEEP_BLUE] * 8],
    },
    "soft_blue_wash": {
        "label": "Soft Blue Wash",
        "frames": [[(0, 60, 255)] * 8],
    },
    "purple_wash": {
        "label": "Purple Wash",
        "frames": [[WW_PURPLE] * 8],
    },
    "cyan_wash": {
        "label": "Cyan Wash",
        "frames": [[WW_CYAN] * 8],
    },
    "amber_wash": {
        "label": "Amber Wash",
        "frames": [[WW_AMBER] * 8],
    },
    "red_wash": {
        "label": "Red Wash",
        "frames": [[WW_RED] * 8],
    },
    "red_blue_split": {
        "label": "Red Blue Split",
        "frames": [[WW_RED, WW_RED, WW_RED, WW_RED, WW_DEEP_BLUE, WW_DEEP_BLUE, WW_DEEP_BLUE, WW_DEEP_BLUE]],
    },
    "blue_white_split": {
        "label": "Blue White Split",
        "frames": [[WW_SOFT_BLUE, WW_SOFT_BLUE, WW_SOFT_BLUE, WW_SOFT_BLUE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE]],
    },
    "purple_cyan_split": {
        "label": "Purple Cyan Split",
        "frames": [[WW_PURPLE, WW_PURPLE, WW_PURPLE, WW_PURPLE, WW_CYAN, WW_CYAN, WW_CYAN, WW_CYAN]],
    },
    "alternating_blue_purple": {
        "label": "Alternating Blue Purple",
        "frames": [[WW_SOFT_BLUE, WW_PURPLE, WW_SOFT_BLUE, WW_PURPLE, WW_SOFT_BLUE, WW_PURPLE, WW_SOFT_BLUE, WW_PURPLE]],
    },
    "center_glow_blue": {
        "label": "Center Glow Blue",
        "frames": [[(0, 0, 40), (0, 0, 80), (0, 40, 160), (0, 100, 255), (0, 100, 255), (0, 40, 160), (0, 0, 80), (0, 0, 40)]],
    },
    "edge_glow_white": {
        "label": "Edge Glow White",
        "frames": [[WW_WHITE, (120, 180, 255), (0, 80, 255), (0, 0, 80), (0, 0, 80), (0, 80, 255), (120, 180, 255), WW_WHITE]],
    },
    "warm_center_glow": {
        "label": "Warm Center Glow",
        "frames": [[WW_WARM_GLOW_LOW, WW_WARM_GLOW_MID, WW_WARM_GLOW_HIGH, WW_WARM_GLOW_PEAK, WW_WARM_GLOW_PEAK, WW_WARM_GLOW_HIGH, WW_WARM_GLOW_MID, WW_WARM_GLOW_LOW]],
    },
    "rainbow_static": {
        "label": "Rainbow Static",
        "frames": [[WW_RED, (255, 80, 0), (255, 255, 0), (0, 255, 0), WW_CYAN, WW_DEEP_BLUE, WW_PURPLE, (255, 0, 120)]],
    },
    "blue_chase_left_to_right": {
        "label": "Blue Chase Left To Right",
        "frames": [
            [WW_BLUE, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLUE, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLUE, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLUE, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLUE, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLUE, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLUE, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLUE],
        ],
        "beats_per_frame": 0.5,
        "mirror_on_odd": True,
    },
    "blue_chase_right_to_left": {
        "label": "Blue Chase Right To Left",
        "frames": [
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLUE],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLUE, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLUE, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLUE, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLUE, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLUE, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLUE, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLUE, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
        ],
        "beats_per_frame": 0.5,
        "mirror_on_odd": True,
    },
    "knight_rider_red": {
        "label": "Knight Rider Red",
        "frames": [
            [WW_RED, (80, 0, 0), WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [(80, 0, 0), WW_RED, (80, 0, 0), WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, (80, 0, 0), WW_RED, (80, 0, 0), WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, (80, 0, 0), WW_RED, (80, 0, 0), WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLACK, (80, 0, 0), WW_RED, (80, 0, 0), WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, (80, 0, 0), WW_RED, (80, 0, 0), WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, (80, 0, 0), WW_RED, (80, 0, 0)],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, (80, 0, 0), WW_RED],
        ],
        "beats_per_frame": 0.5,
        "mirror_on_odd": True,
    },
    "white_pixel_hits": {
        "label": "White Pixel Hits",
        "frames": [
            [WW_WHITE, WW_BLACK, WW_BLACK, WW_BLACK, WW_WHITE, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_WHITE, WW_BLACK, WW_BLACK, WW_BLACK, WW_WHITE, WW_BLACK],
            [WW_BLACK, WW_WHITE, WW_BLACK, WW_WHITE, WW_BLACK, WW_BLACK, WW_BLACK, WW_WHITE],
            [WW_WHITE, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_WHITE, WW_WHITE, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_WHITE, WW_WHITE, WW_BLACK, WW_BLACK, WW_BLACK],
        ],
        "beats_per_frame": 0.5,
    },
    "purple_blue_bounce": {
        "label": "Purple Blue Bounce",
        "frames": [
            [WW_PURPLE, WW_SOFT_BLUE, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_SOFT_BLUE, WW_PURPLE],
            [WW_BLACK, WW_PURPLE, WW_SOFT_BLUE, WW_BLACK, WW_BLACK, WW_SOFT_BLUE, WW_PURPLE, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_PURPLE, WW_SOFT_BLUE, WW_SOFT_BLUE, WW_PURPLE, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_SOFT_BLUE, WW_PURPLE, WW_PURPLE, WW_SOFT_BLUE, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_PURPLE, WW_SOFT_BLUE, WW_BLACK, WW_BLACK, WW_SOFT_BLUE, WW_PURPLE, WW_BLACK],
            [WW_PURPLE, WW_SOFT_BLUE, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_SOFT_BLUE, WW_PURPLE],
        ],
        "beats_per_frame": 0.5,
    },
    "center_out_build": {
        "label": "Center Out Build",
        "frames": [
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLUE, WW_BLUE, WW_BLACK, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLACK, WW_BLUE, (0, 120, 255), (0, 120, 255), WW_BLUE, WW_BLACK, WW_BLACK],
            [WW_BLACK, WW_BLUE, (0, 120, 255), (80, 180, 255), (80, 180, 255), (0, 120, 255), WW_BLUE, WW_BLACK],
            [WW_BLUE, (0, 120, 255), (80, 180, 255), (180, 220, 255), (180, 220, 255), (80, 180, 255), (0, 120, 255), WW_BLUE],
            [WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE],
        ],
        "beats_per_frame": 0.5,
    },
    "left_to_right_build": {
        "label": "Left To Right Build",
        "frames": [
            [WW_BLUE, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [(0, 100, 255), (0, 100, 255), WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [(0, 130, 255), (0, 130, 255), (0, 130, 255), WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [(60, 160, 255), (60, 160, 255), (60, 160, 255), (60, 160, 255), WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK],
            [(100, 190, 255), (100, 190, 255), (100, 190, 255), (100, 190, 255), (100, 190, 255), WW_BLACK, WW_BLACK, WW_BLACK],
            [(160, 220, 255), (160, 220, 255), (160, 220, 255), (160, 220, 255), (160, 220, 255), (160, 220, 255), WW_BLACK, WW_BLACK],
            [(220, 240, 255), (220, 240, 255), (220, 240, 255), (220, 240, 255), (220, 240, 255), (220, 240, 255), (220, 240, 255), WW_BLACK],
            [WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE],
        ],
        "beats_per_frame": 0.5,
        "mirror_on_odd": True,
    },
    "right_to_left_build": {
        "label": "Right To Left Build",
        "frames": [
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLUE],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, (0, 100, 255), (0, 100, 255)],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, (0, 130, 255), (0, 130, 255), (0, 130, 255)],
            [WW_BLACK, WW_BLACK, WW_BLACK, WW_BLACK, (60, 160, 255), (60, 160, 255), (60, 160, 255), (60, 160, 255)],
            [WW_BLACK, WW_BLACK, WW_BLACK, (100, 190, 255), (100, 190, 255), (100, 190, 255), (100, 190, 255), (100, 190, 255)],
            [WW_BLACK, WW_BLACK, (160, 220, 255), (160, 220, 255), (160, 220, 255), (160, 220, 255), (160, 220, 255), (160, 220, 255)],
            [WW_BLACK, (220, 240, 255), (220, 240, 255), (220, 240, 255), (220, 240, 255), (220, 240, 255), (220, 240, 255), (220, 240, 255)],
            [WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE, WW_WHITE],
        ],
        "beats_per_frame": 0.5,
        "mirror_on_odd": True,
    },
    "full_white_flash": {
        "label": "Full White Flash",
        "frames": [[WW_WHITE] * 8],
        "beats_per_frame": 1.0,
        "flash": True,
        "flash_hold": 0.16,
    },
    "full_blue_flash": {
        "label": "Full Blue Flash",
        "frames": [[WW_BLUE] * 8],
        "beats_per_frame": 1.0,
        "flash": True,
        "flash_hold": 0.16,
    },
    "full_red_flash": {
        "label": "Full Red Flash",
        "frames": [[WW_RED] * 8],
        "beats_per_frame": 1.0,
        "flash": True,
        "flash_hold": 0.16,
    },
    "alternating_white_blue": {
        "label": "Alternating White Blue",
        "frames": [
            [WW_WHITE, WW_BLUE, WW_WHITE, WW_BLUE, WW_WHITE, WW_BLUE, WW_WHITE, WW_BLUE],
            [WW_BLUE, WW_WHITE, WW_BLUE, WW_WHITE, WW_BLUE, WW_WHITE, WW_BLUE, WW_WHITE],
        ],
        "beats_per_frame": 0.5,
    },
    "alternating_red_blue": {
        "label": "Alternating Red Blue",
        "frames": [
            [WW_RED, WW_DEEP_BLUE, WW_RED, WW_DEEP_BLUE, WW_RED, WW_DEEP_BLUE, WW_RED, WW_DEEP_BLUE],
            [WW_DEEP_BLUE, WW_RED, WW_DEEP_BLUE, WW_RED, WW_DEEP_BLUE, WW_RED, WW_DEEP_BLUE, WW_RED],
        ],
        "beats_per_frame": 0.5,
    },
    "center_white_punch": {
        "label": "Center White Punch",
        "frames": [[WW_BLACK, (0, 0, 80), WW_BLUE, WW_WHITE, WW_WHITE, WW_BLUE, (0, 0, 80), WW_BLACK]],
        "beats_per_frame": 1.0,
        "flash": True,
        "flash_hold": 0.18,
    },
    "edge_white_punch": {
        "label": "Edge White Punch",
        "frames": [[WW_WHITE, WW_BLUE, (0, 0, 80), WW_BLACK, WW_BLACK, (0, 0, 80), WW_BLUE, WW_WHITE]],
        "beats_per_frame": 1.0,
        "flash": True,
        "flash_hold": 0.18,
    },
    "blackout": {
        "label": "Blackout",
        "frames": [[WW_BLACK] * 8],
    },
}

LIVE_OVERRIDE_COLORS = {
    "none": None,
    "red": (255, 0, 0, 0),
    "yellow": (255, 220, 0, 0),
    "green": (0, 255, 0, 0),
    "lime": (140, 255, 0, 0),
    "purple": (180, 0, 255, 0),
    "pink": (255, 0, 180, 0),
    "cyan": (0, 255, 255, 0),
    "orange": (255, 120, 0, 0),
    "blue": (0, 80, 255, 0),
    "white": (255, 255, 255, 255),
    "rainbow": None,
}

AUTO_SHOW_STYLES = {
    "adaptive": {
        "label": "Adaptive",
        "energy_bias": 0.00,
        "brightness_bias": 0.00,
        "motion_bias": 0.00,
        "pulse_bias": 0.00,
        "strobe_bias": 0.00,
        "preferred_color_source": "hybrid",
    },
    "club": {
        "label": "Club",
        "energy_bias": 0.12,
        "brightness_bias": 0.10,
        "motion_bias": 0.16,
        "pulse_bias": 0.16,
        "strobe_bias": 0.20,
        "preferred_color_source": "color_bank",
    },
    "cinematic": {
        "label": "Cinematic",
        "energy_bias": -0.10,
        "brightness_bias": -0.16,
        "motion_bias": -0.12,
        "pulse_bias": -0.14,
        "strobe_bias": -1.00,
        "preferred_color_source": "mood",
    },
    "warm": {
        "label": "Warm",
        "energy_bias": -0.02,
        "brightness_bias": -0.05,
        "motion_bias": -0.06,
        "pulse_bias": -0.08,
        "strobe_bias": -0.70,
        "preferred_color_source": "manual",
    },
    "festival": {
        "label": "Festival",
        "energy_bias": 0.20,
        "brightness_bias": 0.16,
        "motion_bias": 0.24,
        "pulse_bias": 0.28,
        "strobe_bias": 0.34,
        "preferred_color_source": "color_bank",
    },
    "minimal": {
        "label": "Minimal",
        "energy_bias": -0.18,
        "brightness_bias": -0.20,
        "motion_bias": -0.18,
        "pulse_bias": -0.20,
        "strobe_bias": -1.00,
        "preferred_color_source": "mood",
    },
}

AUTO_SHOW_STYLE_VARIANT_RULES = {
    "club": {
        "looks": {
            "*": {"prefer": ["bank_echo", "neon_split", "ultraviolet"], "avoid": ["warm_glow"]},
            "build": {"prefer": ["neon_split", "ultraviolet", "bank_echo"]},
            "chorus": {"prefer": ["neon_split", "ultraviolet", "bank_echo"]},
            "drop": {"prefer": ["neon_split", "ultraviolet", "bank_echo"]},
        },
        "color_profiles": {
            "*": {"prefer": ["magenta_cyan", "pink_blue", "ice_fire", "teal_orange"], "avoid": ["amber_violet"]},
            "intro": {"prefer": ["blue_amber", "teal_orange"]},
            "drop": {"prefer": ["ice_fire", "pink_blue", "red_white"]},
        },
        "textures": {
            "*": {"prefer": ["split", "shuffle", "ripple", "ladder"], "avoid": ["steady"]},
        },
        "motions": {
            "intro": {"prefer": ["slow_audience_sweep_blue", "slow_audience_circle"]},
            "verse": {"prefer": ["slow_audience_sweep_blue", "slow_audience_oval", "slow_random_searchlight"]},
            "build": {"prefer": ["build_audience_wave", "build_fastening_circle", "build_color_chase", "build_rising_sweep"]},
            "chorus": {"prefer": ["fast_audience_sweep", "fast_audience_circle", "fast_audience_figure_8", "snap_position_hits", "random_search_hits"]},
            "drop": {"prefer": ["drop_crossing_beams", "drop_snap_fan", "drop_fast_circle_white", "drop_strobe_sweep", "drop_full_audience_hit"]},
            "break": {"prefer": ["slow_audience_sweep_blue", "slow_audience_oval"]},
            "outro": {"prefer": ["slow_audience_sweep_blue", "slow_audience_oval"]},
        },
        "pulses": {
            "verse": {"prefer": ["alternate_whole", "offbeat_flash", "soft_pulse"]},
            "build": {"prefer": ["gallop", "double_hit", "chase", "snake", "pivot", "ramp_up"], "avoid": ["breathing"]},
            "chorus": {"prefer": ["gallop", "double_hit", "chase", "snake", "beat_flash", "pivot"], "avoid": ["breathing"]},
            "drop": {"prefer": ["drop_blinder", "snake", "gallop", "double_hit", "chase", "beat_flash", "blackout_hit"]},
            "break": {"prefer": ["alternate_whole", "offbeat_flash", "soft_pulse"]},
            "outro": {"prefer": ["alternate_whole", "soft_pulse"]},
        },
        "washes": {
            "verse": {"prefer": ["purple_cyan_split", "alternating_blue_purple", "blue_white_split"]},
            "build": {"prefer": ["center_out_build", "left_to_right_build", "right_to_left_build", "blue_chase_left_to_right"]},
            "chorus": {"prefer": ["alternating_red_blue", "purple_blue_bounce", "white_pixel_hits", "knight_rider_red", "blue_white_split"]},
            "drop": {"prefer": ["full_white_flash", "alternating_red_blue", "center_white_punch", "edge_white_punch"]},
        },
        "accents": {
            "*": {"prefer": ["mover_focus", "alternating", "edges"]},
        },
    },
    "cinematic": {
        "looks": {
            "*": {"prefer": ["cool_air", "mood_wash", "warm_glow"], "avoid": ["neon_split", "ultraviolet"]},
            "drop": {"prefer": ["cool_air", "mood_wash", "bank_echo"]},
        },
        "color_profiles": {
            "*": {"prefer": ["deep_blue_white", "amber_violet", "purple_gold", "cobalt_amber", "rose_mint"], "avoid": ["pink_blue", "ice_fire", "red_white"]},
        },
        "textures": {
            "*": {"prefer": ["drift", "bloom", "ripple"], "avoid": ["shuffle"]},
        },
        "motions": {
            "intro": {"prefer": ["slow_high_audience_sweep", "slow_audience_circle", "slow_audience_oval"]},
            "verse": {"prefer": ["slow_high_audience_sweep", "slow_audience_circle", "slow_audience_oval", "slow_audience_figure_8"]},
            "build": {"prefer": ["build_rising_sweep", "build_narrow_to_wide_fan", "build_fastening_circle"], "avoid": ["build_strobe_ramp", "build_white_flash_prep", "build_color_chase"]},
            "chorus": {"prefer": ["slow_high_audience_sweep", "slow_audience_oval", "slow_audience_circle"], "avoid": ["snap_position_hits", "random_search_hits"]},
            "drop": {"prefer": ["drop_crossing_beams", "drop_snap_fan", "drop_full_audience_hit"], "avoid": ["drop_strobe_sweep", "drop_white_blinder"]},
            "down": {"prefer": ["slow_high_audience_sweep", "slow_audience_circle", "slow_audience_oval"]},
            "break": {"prefer": ["break_slow_pulse_circle", "break_purple_oval", "break_high_cool_sweep"]},
            "outro": {"prefer": ["slow_high_audience_sweep", "slow_audience_circle", "break_high_cool_sweep"]},
        },
        "pulses": {
            "intro": {"prefer": ["slow_fade_in", "soft_pulse", "breathing"]},
            "verse": {"prefer": ["breathing", "soft_pulse", "alternate_whole"], "avoid": ["chase", "snake"]},
            "build": {"prefer": ["soft_pulse", "alternate_whole", "pivot", "ramp_up"], "avoid": ["chase", "snake", "gallop", "drop_blinder", "blackout_hit", "tremolo_dimmer"]},
            "chorus": {"prefer": ["soft_pulse", "alternate_whole", "pivot", "double_hit"], "avoid": ["chase", "snake", "gallop", "drop_blinder", "blackout_hit"]},
            "drop": {"prefer": ["full_on", "alternate_whole", "double_hit", "pivot"], "avoid": ["snake", "gallop", "blackout_hit", "tremolo_dimmer"]},
            "down": {"prefer": ["breathing", "soft_pulse", "slow_fade_out"]},
            "break": {"prefer": ["breathing", "soft_pulse", "slow_fade_out"]},
            "outro": {"prefer": ["slow_fade_out", "breathing", "soft_pulse"]},
        },
        "washes": {
            "verse": {"prefer": ["deep_blue_wash", "soft_blue_wash", "center_glow_blue", "edge_glow_white"]},
            "build": {"prefer": ["center_glow_blue", "edge_glow_white", "warm_center_glow"], "avoid": ["blue_chase_left_to_right", "blue_chase_right_to_left"]},
            "chorus": {"prefer": ["blue_white_split", "purple_cyan_split", "edge_glow_white"], "avoid": ["white_pixel_hits", "knight_rider_red"]},
            "drop": {"prefer": ["center_white_punch", "edge_glow_white", "blue_white_split"], "avoid": ["full_red_flash", "alternating_red_blue"]},
            "break": {"prefer": ["deep_blue_wash", "soft_blue_wash", "warm_center_glow"]},
            "outro": {"prefer": ["edge_glow_white", "deep_blue_wash", "warm_center_glow"]},
        },
        "accents": {
            "*": {"prefer": ["center", "wash_lift", "edges"]},
        },
    },
    "warm": {
        "looks": {
            "*": {"prefer": ["warm_glow", "sunset_push", "bank_echo"], "avoid": ["white_bloom"]},
            "build": {"prefer": ["sunset_push", "warm_glow", "bank_echo"]},
            "drop": {"prefer": ["sunset_push", "bank_echo", "warm_glow"]},
        },
        "color_profiles": {
            "*": {"prefer": ["amber_violet", "purple_gold", "teal_orange", "blue_amber", "cobalt_amber"], "avoid": ["ice_fire"]},
        },
        "textures": {
            "*": {"prefer": ["drift", "bloom", "ripple"], "avoid": ["shuffle"]},
        },
        "motions": {
            "intro": {"prefer": ["slow_high_audience_sweep", "slow_audience_circle", "slow_audience_oval"]},
            "verse": {"prefer": ["slow_audience_sweep_white", "slow_high_audience_sweep", "slow_audience_oval", "slow_audience_figure_8"]},
            "build": {"prefer": ["build_rising_sweep", "build_narrow_to_wide_fan", "build_audience_wave"], "avoid": ["build_strobe_ramp", "build_white_flash_prep"]},
            "chorus": {"prefer": ["fast_audience_sweep", "fast_audience_figure_8", "slow_audience_oval"], "avoid": ["snap_position_hits", "random_search_hits"]},
            "drop": {"prefer": ["drop_snap_fan", "drop_full_audience_hit", "drop_crossing_beams", "fast_audience_figure_8"], "avoid": ["drop_strobe_sweep"]},
            "down": {"prefer": ["slow_high_audience_sweep", "slow_audience_circle", "slow_audience_oval"]},
            "break": {"prefer": ["break_slow_pulse_circle", "break_purple_oval", "slow_audience_oval"]},
            "outro": {"prefer": ["slow_audience_sweep_blue", "slow_high_audience_sweep", "slow_audience_oval"]},
        },
        "pulses": {
            "intro": {"prefer": ["slow_fade_in", "soft_pulse"]},
            "verse": {"prefer": ["soft_pulse", "offbeat_flash", "alternate_whole"], "avoid": ["snake"]},
            "build": {"prefer": ["ramp_up", "soft_pulse", "alternate_whole", "double_hit", "pivot"], "avoid": ["snake", "gallop", "blackout_hit", "tremolo_dimmer"]},
            "chorus": {"prefer": ["alternate_whole", "double_hit", "soft_pulse", "offbeat_flash", "beat_flash"], "avoid": ["snake", "gallop", "blackout_hit"]},
            "drop": {"prefer": ["full_on", "double_hit", "alternate_whole", "beat_flash", "drop_blinder"], "avoid": ["snake", "blackout_hit", "tremolo_dimmer"]},
            "down": {"prefer": ["soft_pulse", "breathing", "slow_fade_out"]},
            "break": {"prefer": ["breathing", "soft_pulse", "slow_fade_out"]},
            "outro": {"prefer": ["slow_fade_out", "soft_pulse", "breathing"]},
        },
        "washes": {
            "intro": {"prefer": ["warm_center_glow", "amber_wash", "soft_white_wash"]},
            "verse": {"prefer": ["warm_center_glow", "amber_wash", "purple_wash", "blue_white_split"]},
            "build": {"prefer": ["warm_center_glow", "amber_wash", "center_out_build"]},
            "chorus": {"prefer": ["warm_center_glow", "purple_wash", "alternating_white_blue"]},
            "drop": {"prefer": ["warm_center_glow", "full_white_flash", "center_white_punch", "alternating_white_blue"]},
            "down": {"prefer": ["warm_center_glow", "amber_wash", "purple_wash"]},
            "break": {"prefer": ["warm_center_glow", "amber_wash", "purple_wash", "soft_white_wash"]},
            "outro": {"prefer": ["warm_center_glow", "amber_wash", "soft_white_wash"]},
        },
        "accents": {
            "*": {"prefer": ["center", "wash_lift", "mover_focus"]},
        },
    },
    "festival": {
        "looks": {
            "*": {"prefer": ["neon_split", "ultraviolet", "bank_echo", "cool_air"], "avoid": ["warm_glow", "white_bloom"]},
            "intro": {"prefer": ["cool_air", "bank_echo"]},
            "break": {"prefer": ["bank_echo", "cool_air"]},
        },
        "color_profiles": {
            "*": {"prefer": ["ice_fire", "red_white", "pink_blue", "magenta_cyan", "teal_orange"], "avoid": ["amber_violet"]},
        },
        "textures": {
            "*": {"prefer": ["shuffle", "split", "ladder", "ripple"], "avoid": ["steady", "bloom"]},
        },
        "motions": {
            "intro": {"prefer": ["slow_audience_sweep_blue", "slow_random_searchlight"]},
            "verse": {"prefer": ["slow_audience_sweep_blue", "slow_random_searchlight", "slow_deep_audience_sweep"]},
            "build": {"prefer": ["build_strobe_ramp", "build_white_flash_prep", "build_color_chase", "build_fastening_circle", "build_audience_wave"]},
            "chorus": {"prefer": ["fast_audience_sweep", "snap_position_hits", "fast_diagonal_sweep", "random_search_hits", "fast_audience_circle"]},
            "drop": {"prefer": ["drop_white_blinder", "drop_strobe_sweep", "drop_snap_fan", "drop_crossing_beams", "drop_full_audience_hit"]},
            "down": {"prefer": ["slow_audience_sweep_blue", "slow_random_searchlight"]},
            "break": {"prefer": ["slow_audience_sweep_blue", "slow_random_searchlight"]},
            "outro": {"prefer": ["slow_audience_sweep_blue", "slow_random_searchlight"]},
        },
        "pulses": {
            "intro": {"prefer": ["soft_pulse", "offbeat_flash"]},
            "verse": {"prefer": ["alternate_whole", "offbeat_flash", "beat_flash"]},
            "build": {"prefer": ["chase", "snake", "gallop", "double_hit", "tremolo_dimmer", "ramp_up", "beat_flash"]},
            "chorus": {"prefer": ["chase", "snake", "gallop", "double_hit", "beat_flash", "pivot"]},
            "drop": {"prefer": ["drop_blinder", "blackout_hit", "snake", "gallop", "double_hit", "chase", "tremolo_dimmer"]},
            "down": {"prefer": ["alternate_whole", "soft_pulse", "offbeat_flash"]},
            "break": {"prefer": ["alternate_whole", "offbeat_flash", "soft_pulse"]},
            "outro": {"prefer": ["alternate_whole", "soft_pulse"]},
        },
        "washes": {
            "verse": {"prefer": ["red_blue_split", "alternating_blue_purple", "purple_cyan_split"]},
            "build": {"prefer": ["center_out_build", "left_to_right_build", "right_to_left_build", "blue_chase_left_to_right", "blue_chase_right_to_left"]},
            "chorus": {"prefer": ["alternating_red_blue", "white_pixel_hits", "knight_rider_red", "purple_blue_bounce", "blue_white_split"]},
            "drop": {"prefer": ["full_white_flash", "full_red_flash", "alternating_red_blue", "center_white_punch", "edge_white_punch"]},
        },
        "accents": {
            "*": {"prefer": ["mover_focus", "edges", "alternating"]},
        },
    },
    "minimal": {
        "looks": {
            "*": {"prefer": ["cool_air", "mood_wash", "warm_glow"], "avoid": ["white_bloom", "neon_split", "ultraviolet"]},
        },
        "color_profiles": {
            "*": {"prefer": ["deep_blue_white", "rose_mint", "cobalt_amber", "blue_amber"], "avoid": ["red_white", "ice_fire", "pink_blue"]},
        },
        "textures": {
            "*": {"prefer": ["steady", "drift", "bloom"], "avoid": ["shuffle", "split"]},
        },
        "motions": {
            "intro": {"prefer": ["slow_high_audience_sweep", "slow_audience_circle", "slow_audience_oval"]},
            "verse": {"prefer": ["slow_high_audience_sweep", "slow_audience_circle", "slow_audience_oval", "slow_audience_figure_8"]},
            "build": {"prefer": ["build_rising_sweep", "build_narrow_to_wide_fan", "build_audience_wave"], "avoid": ["build_strobe_ramp", "build_white_flash_prep", "build_color_chase"]},
            "chorus": {"prefer": ["slow_high_audience_sweep", "slow_audience_circle", "slow_audience_oval"], "avoid": ["snap_position_hits", "random_search_hits", "fast_diagonal_sweep"]},
            "drop": {"prefer": ["drop_snap_fan", "drop_crossing_beams", "drop_full_audience_hit"], "avoid": ["drop_strobe_sweep", "drop_white_blinder"]},
            "down": {"prefer": ["slow_high_audience_sweep", "slow_audience_circle", "slow_audience_oval"]},
            "break": {"prefer": ["break_high_cool_sweep", "break_slow_pulse_circle", "break_purple_oval"]},
            "outro": {"prefer": ["slow_high_audience_sweep", "break_high_cool_sweep", "slow_audience_circle"]},
        },
        "pulses": {
            "intro": {"prefer": ["slow_fade_in", "soft_pulse", "breathing"]},
            "verse": {"prefer": ["breathing", "soft_pulse", "alternate_whole"]},
            "build": {"prefer": ["soft_pulse", "alternate_whole", "pivot"], "avoid": ["chase", "snake", "gallop", "blackout_hit", "drop_blinder", "tremolo_dimmer"]},
            "chorus": {"prefer": ["soft_pulse", "alternate_whole", "pivot", "offbeat_flash"], "avoid": ["chase", "snake", "gallop", "blackout_hit"]},
            "drop": {"prefer": ["full_on", "alternate_whole", "pivot", "double_hit"], "avoid": ["snake", "gallop", "blackout_hit", "tremolo_dimmer"]},
            "down": {"prefer": ["breathing", "soft_pulse", "slow_fade_out"]},
            "break": {"prefer": ["breathing", "soft_pulse", "slow_fade_out"]},
            "outro": {"prefer": ["slow_fade_out", "breathing", "soft_pulse"]},
        },
        "washes": {
            "intro": {"prefer": ["deep_blue_wash", "soft_blue_wash", "center_glow_blue"]},
            "verse": {"prefer": ["deep_blue_wash", "soft_blue_wash", "blue_white_split", "center_glow_blue"]},
            "build": {"prefer": ["center_glow_blue", "edge_glow_white", "warm_center_glow"]},
            "chorus": {"prefer": ["blue_white_split", "purple_cyan_split", "edge_glow_white"]},
            "drop": {"prefer": ["center_white_punch", "edge_glow_white", "blue_white_split"]},
            "down": {"prefer": ["deep_blue_wash", "soft_blue_wash", "center_glow_blue"]},
            "break": {"prefer": ["deep_blue_wash", "soft_blue_wash", "warm_center_glow"]},
            "outro": {"prefer": ["deep_blue_wash", "edge_glow_white", "warm_center_glow"]},
        },
        "accents": {
            "*": {"prefer": ["center", "wash_lift"]},
        },
    },
}

AUTO_SHOW_SECTIONS = {
    "intro": {"energy": 0.34, "motion": 0.22, "pulse": 0.06, "strobe": False},
    "verse": {"energy": 0.56, "motion": 0.42, "pulse": 0.20, "strobe": False},
    "build": {"energy": 0.76, "motion": 0.70, "pulse": 0.48, "strobe": False},
    "chorus": {"energy": 0.88, "motion": 0.84, "pulse": 0.62, "strobe": False},
    "drop": {"energy": 1.00, "motion": 0.98, "pulse": 0.80, "strobe": True},
    "down": {"energy": 0.58, "motion": 0.50, "pulse": 0.18, "strobe": False},
    "break": {"energy": 0.48, "motion": 0.40, "pulse": 0.16, "strobe": False},
    "outro": {"energy": 0.40, "motion": 0.30, "pulse": 0.10, "strobe": False},
    "unknown": {"energy": 0.60, "motion": 0.48, "pulse": 0.28, "strobe": False},
}

AUTO_SHOW_LOOK_POOLS = {
    "intro": ["warm_glow", "cool_air", "mood_wash", "sunset_push"],
    "verse": ["bank_echo", "cool_air", "sunset_push", "mood_wash", "neon_split"],
    "build": ["sunset_push", "neon_split", "ultraviolet", "bank_echo"],
    "chorus": ["neon_split", "ultraviolet", "bank_echo", "sunset_push", "mood_wash"],
    "drop": ["neon_split", "ultraviolet", "bank_echo", "sunset_push"],
    "down": ["cool_air", "mood_wash", "bank_echo", "sunset_push"],
    "break": ["cool_air", "mood_wash", "warm_glow", "bank_echo"],
    "outro": ["warm_glow", "sunset_push", "mood_wash", "cool_air"],
    "unknown": ["bank_echo", "mood_wash", "neon_split", "cool_air"],
}

AUTO_SHOW_COLOR_PROFILE_POOLS = {
    "intro": ["blue_amber", "teal_orange", "purple_gold", "amber_violet"],
    "verse": ["blue_amber", "magenta_cyan", "teal_orange", "cobalt_amber", "rose_mint", "amber_teal", "violet_lime"],
    "build": ["purple_gold", "blue_amber", "magenta_cyan", "teal_orange", "amber_violet", "rose_mint", "ruby_lime"],
    "chorus": ["magenta_cyan", "teal_orange", "blue_amber", "purple_gold", "pink_blue", "amber_violet", "ice_fire", "violet_lime"],
    "drop": ["magenta_cyan", "blue_amber", "pink_blue", "ice_fire", "teal_orange", "ruby_lime"],
    "down": ["blue_amber", "magenta_cyan", "teal_orange", "rose_mint", "amber_teal", "violet_lime"],
    "break": ["blue_amber", "magenta_cyan", "teal_orange", "purple_gold", "rose_mint", "amber_teal"],
    "outro": ["blue_amber", "purple_gold", "teal_orange", "amber_violet"],
    "unknown": ["blue_amber", "magenta_cyan", "teal_orange", "purple_gold", "rose_mint", "amber_teal"],
}

AUTO_SHOW_TEXTURE_POOLS = {
    "intro": ["steady", "drift", "bloom"],
    "verse": ["drift", "ripple", "split", "ladder"],
    "build": ["ladder", "split", "shuffle", "ripple"],
    "chorus": ["ripple", "shuffle", "split", "bloom"],
    "drop": ["shuffle", "split", "ladder", "ripple"],
    "down": ["drift", "bloom", "ripple"],
    "break": ["steady", "drift", "bloom"],
    "outro": ["steady", "drift", "bloom"],
    "unknown": ["drift", "ripple", "split", "ladder"],
}

AUTO_SHOW_WASH_CUE_POOLS = {
    "intro": [
        "soft_white_wash",
        "soft_blue_wash",
        "center_glow_blue",
        "warm_center_glow",
        "deep_blue_wash",
    ],
    "verse": [
        "deep_blue_wash",
        "soft_blue_wash",
        "purple_wash",
        "cyan_wash",
        "blue_white_split",
        "purple_cyan_split",
        "alternating_blue_purple",
        "center_glow_blue",
        "warm_center_glow",
        "rainbow_static",
    ],
    "build": [
        "center_out_build",
        "left_to_right_build",
        "right_to_left_build",
        "blue_chase_left_to_right",
        "blue_chase_right_to_left",
    ],
    "chorus": [
        "alternating_white_blue",
        "alternating_red_blue",
        "purple_blue_bounce",
        "white_pixel_hits",
        "knight_rider_red",
        "red_blue_split",
        "blue_white_split",
    ],
    "drop": [
        "full_white_flash",
        "full_blue_flash",
        "full_red_flash",
        "alternating_white_blue",
        "alternating_red_blue",
        "center_white_punch",
        "edge_white_punch",
    ],
    "down": [
        "deep_blue_wash",
        "soft_blue_wash",
        "purple_wash",
        "blue_white_split",
        "alternating_blue_purple",
        "center_glow_blue",
        "warm_center_glow",
    ],
    "break": [
        "deep_blue_wash",
        "soft_blue_wash",
        "purple_wash",
        "blue_white_split",
        "alternating_blue_purple",
        "center_glow_blue",
        "warm_center_glow",
        "soft_white_wash",
    ],
    "outro": [
        "soft_white_wash",
        "deep_blue_wash",
        "edge_glow_white",
        "alternating_blue_purple",
        "center_glow_blue",
        "warm_center_glow",
    ],
    "unknown": [
        "soft_blue_wash",
        "center_glow_blue",
        "purple_wash",
        "blue_white_split",
        "alternating_blue_purple",
    ],
}

AUTO_SHOW_MOTION_POOLS = {
    "intro": [
        "slow_high_audience_sweep",
        "slow_audience_sweep_blue",
        "slow_audience_circle",
        "slow_audience_oval",
        "break_high_cool_sweep",
        "break_cyan_figure_8",
    ],
    "verse": [
        "slow_audience_sweep_blue",
        "slow_deep_audience_sweep",
        "slow_high_audience_sweep",
        "slow_audience_circle",
        "slow_audience_oval",
        "slow_audience_figure_8",
        "slow_random_searchlight",
    ],
    "build": [
        "build_rising_sweep",
        "build_dimmer_pulse",
        "build_fastening_circle",
        "build_narrow_to_wide_fan",
        "build_strobe_ramp",
        "build_color_chase",
        "build_audience_wave",
        "build_white_flash_prep",
    ],
    "chorus": [
        "fast_audience_sweep",
        "fast_audience_circle",
        "fast_audience_figure_8",
        "snap_position_hits",
        "fast_diagonal_sweep",
        "random_search_hits",
    ],
    "drop": [
        "drop_white_blinder",
        "drop_strobe_sweep",
        "drop_snap_fan",
        "drop_crossing_beams",
        "drop_full_audience_hit",
        "fast_audience_figure_8",
        "fast_audience_circle",
    ],
    "down": [
        "slow_high_audience_sweep",
        "slow_audience_sweep_blue",
        "slow_audience_circle",
        "slow_audience_oval",
        "slow_random_searchlight",
        "break_high_cool_sweep",
        "break_cyan_figure_8",
    ],
    "break": [
        "break_slow_pulse_circle",
        "break_purple_oval",
        "break_high_cool_sweep",
        "slow_high_audience_sweep",
        "slow_audience_oval",
        "slow_random_searchlight",
        "break_cyan_figure_8",
        "slow_audience_circle",
        "slow_audience_figure_8",
    ],
    "outro": [
        "slow_audience_sweep_blue",
        "slow_high_audience_sweep",
        "break_high_cool_sweep",
        "break_cyan_figure_8",
        "slow_audience_circle",
        "slow_audience_oval",
        "slow_random_searchlight",
    ],
    "unknown": [
        "slow_audience_sweep_white",
        "slow_audience_circle",
        "fast_audience_sweep",
        "slow_audience_oval",
        "slow_random_searchlight",
    ],
}

AUTO_SHOW_MEMBER_MIRROR_MOTIONS = {
    "slow_left_right_sweep",
    "fast_left_right_sweep",
    "audience_sweep",
    "ceiling_sweep",
    "up_down_sweep",
    "slow_circle",
    "fast_circle",
    "oval_circle",
    "figure_8",
    "small_figure_8",
    "mirror_bounce",
}

AUTO_SHOW_PULSE_POOLS = {
    "intro": ["slow_fade_in", "soft_pulse", "offbeat_flash"],
    "verse": ["soft_pulse", "offbeat_flash", "breathing", "alternate_whole"],
    "build": ["ramp_up", "soft_pulse", "beat_flash", "alternate_whole", "double_hit", "gallop", "pivot", "chase", "snake", "tremolo_dimmer"],
    "chorus": ["soft_pulse", "offbeat_flash", "beat_flash", "alternate_whole", "double_hit", "gallop", "pivot", "chase", "snake"],
    "drop": ["full_on", "beat_flash", "drop_blinder", "blackout_hit", "alternate_whole", "double_hit", "gallop", "pivot", "chase", "snake", "tremolo_dimmer"],
    "down": ["soft_pulse", "offbeat_flash", "breathing", "slow_fade_out", "alternate_whole"],
    "break": ["breathing", "soft_pulse", "offbeat_flash", "slow_fade_out"],
    "outro": ["soft_pulse", "offbeat_flash", "breathing", "slow_fade_out"],
    "unknown": ["soft_pulse", "offbeat_flash", "breathing", "alternate_whole"],
}

AUTO_SHOW_ACCENT_POOLS = {
    "intro": ["wash_lift", "center", "alternating"],
    "verse": ["alternating", "center", "edges", "wash_lift"],
    "build": ["edges", "mover_focus", "alternating"],
    "chorus": ["mover_focus", "alternating", "center", "edges"],
    "drop": ["mover_focus", "edges", "alternating"],
    "down": ["wash_lift", "center", "alternating"],
    "break": ["wash_lift", "center"],
    "outro": ["center", "wash_lift", "alternating"],
    "unknown": ["alternating", "center", "edges"],
}

AUTO_SHOW_PULSE_PROFILES = {
    "full_on": {"depth": 0, "decay": 0, "movement": 0.00, "mode": "full_on"},
    "low_glow": {"depth": 0, "decay": 0, "movement": -0.02, "mode": "low_glow"},
    "medium": {"depth": 0, "decay": 0, "movement": 0.00, "mode": "medium"},
    "slow_fade_in": {"depth": 0, "decay": 0, "movement": -0.01, "mode": "fade_in"},
    "slow_fade_out": {"depth": 0, "decay": 0, "movement": -0.02, "mode": "fade_out"},
    "soft_pulse": {"depth": 18, "decay": 140, "movement": 0.00, "mode": "soft_pulse"},
    "strong_pulse": {"depth": 46, "decay": 80, "movement": 0.00, "mode": "strong_pulse"},
    "beat_flash": {"depth": 60, "decay": 42, "movement": 0.00, "mode": "beat_flash"},
    "offbeat_flash": {"depth": 44, "decay": 56, "movement": 0.00, "mode": "offbeat_flash"},
    "drop_blinder": {"depth": 72, "decay": 80, "movement": 0.00, "mode": "drop_blinder"},
    "blackout_hit": {"depth": 0, "decay": 36, "movement": 0.00, "mode": "blackout_hit"},
    "ramp_up": {"depth": 0, "decay": 0, "movement": 0.00, "mode": "ramp_up"},
    "ramp_down": {"depth": 0, "decay": 0, "movement": 0.00, "mode": "ramp_down"},
    "breathing": {"depth": 20, "decay": 180, "movement": -0.01, "mode": "breathing"},
    "tremolo_dimmer": {"depth": 38, "decay": 34, "movement": 0.00, "mode": "tremolo"},
    "alternate_whole": {"depth": 26, "decay": 76, "movement": 0.00, "mode": "alternate_whole"},
    "double_hit": {"depth": 54, "decay": 44, "movement": 0.00, "mode": "double_hit"},
    "gallop": {"depth": 44, "decay": 54, "movement": 0.00, "mode": "gallop"},
    "pivot": {"depth": 30, "decay": 72, "movement": 0.00, "mode": "pivot"},
    "chase": {"depth": 26, "decay": 60, "movement": 0.00, "mode": "chase"},
    "snake": {"depth": 30, "decay": 60, "movement": 0.00, "mode": "snake"},
}

TRACK_SHOW_THEMES = {
    "solar_dusk": {
        "label": "Solar Dusk",
        "color_profiles": ["blue_amber", "purple_gold", "amber_violet", "teal_orange"],
        "looks": ["sunset_push", "warm_glow", "bank_echo"],
        "accents": ["center", "alternating", "wash_lift"],
        "textures": ["drift", "bloom", "ladder"],
        "energy_bias": 0.03,
        "motion_bias": -0.02,
        "pulse_bias": -0.05,
        "contrast": 0.18,
        "white_bias": -0.03,
    },
    "ocean_drive": {
        "label": "Ocean Drive",
        "color_profiles": ["teal_orange", "blue_amber", "cobalt_amber", "amber_teal"],
        "looks": ["cool_air", "bank_echo", "mood_wash"],
        "accents": ["edges", "center", "alternating"],
        "textures": ["ripple", "drift", "split"],
        "energy_bias": -0.02,
        "motion_bias": 0.02,
        "pulse_bias": -0.08,
        "contrast": 0.24,
        "white_bias": -0.01,
    },
    "neon_wire": {
        "label": "Neon Wire",
        "color_profiles": ["magenta_cyan", "pink_blue", "ice_fire", "violet_lime"],
        "looks": ["neon_split", "ultraviolet", "bank_echo"],
        "accents": ["alternating", "mover_focus", "edges"],
        "textures": ["split", "shuffle", "ripple"],
        "energy_bias": 0.06,
        "motion_bias": 0.05,
        "pulse_bias": -0.04,
        "contrast": 0.32,
        "white_bias": 0.00,
    },
    "velvet_heat": {
        "label": "Velvet Heat",
        "color_profiles": ["amber_violet", "purple_gold", "magenta_cyan", "amber_teal"],
        "looks": ["warm_glow", "sunset_push", "ultraviolet"],
        "accents": ["center", "wash_lift", "mover_focus"],
        "textures": ["drift", "bloom", "ripple"],
        "energy_bias": 0.00,
        "motion_bias": -0.01,
        "pulse_bias": -0.07,
        "contrast": 0.22,
        "white_bias": -0.01,
    },
    "citrus_pop": {
        "label": "Citrus Pop",
        "color_profiles": ["blue_amber", "yellow_blue", "teal_orange", "amber_teal"],
        "looks": ["bank_echo", "mood_wash", "sunset_push"],
        "accents": ["alternating", "edges", "center"],
        "textures": ["ladder", "split", "shuffle"],
        "energy_bias": 0.05,
        "motion_bias": 0.01,
        "pulse_bias": -0.06,
        "contrast": 0.28,
        "white_bias": -0.01,
    },
    "polar_haze": {
        "label": "Polar Haze",
        "color_profiles": ["ice_fire", "blue_amber", "magenta_cyan", "rose_mint"],
        "looks": ["cool_air", "bank_echo", "mood_wash"],
        "accents": ["center", "edges", "wash_lift"],
        "textures": ["steady", "drift", "bloom"],
        "energy_bias": -0.04,
        "motion_bias": -0.03,
        "pulse_bias": -0.12,
        "contrast": 0.18,
        "white_bias": 0.00,
    },
    "acid_arc": {
        "label": "Acid Arc",
        "color_profiles": ["magenta_cyan", "pink_blue", "blue_amber", "teal_orange"],
        "looks": ["neon_split", "bank_echo", "ultraviolet"],
        "accents": ["alternating", "edges", "mover_focus"],
        "textures": ["split", "ladder", "shuffle"],
        "energy_bias": 0.08,
        "motion_bias": 0.06,
        "pulse_bias": -0.03,
        "contrast": 0.34,
        "white_bias": -0.02,
    },
    "ember_storm": {
        "label": "Ember Storm",
        "color_profiles": ["ruby_lime", "blue_amber", "ice_fire", "amber_violet"],
        "looks": ["sunset_push", "ultraviolet", "bank_echo"],
        "accents": ["mover_focus", "edges", "center"],
        "textures": ["ripple", "split", "ladder"],
        "energy_bias": 0.04,
        "motion_bias": 0.03,
        "pulse_bias": -0.05,
        "contrast": 0.30,
        "white_bias": -0.01,
    },
    "candy_night": {
        "label": "Candy Night",
        "color_profiles": ["magenta_cyan", "pink_blue", "purple_gold", "rose_mint"],
        "looks": ["neon_split", "warm_glow", "mood_wash"],
        "accents": ["alternating", "wash_lift", "center"],
        "textures": ["shuffle", "drift", "bloom"],
        "energy_bias": 0.01,
        "motion_bias": 0.00,
        "pulse_bias": -0.08,
        "contrast": 0.26,
        "white_bias": -0.01,
    },
    "steel_lotus": {
        "label": "Steel Lotus",
        "color_profiles": ["blue_amber", "teal_orange", "purple_gold", "rose_mint"],
        "looks": ["cool_air", "ultraviolet", "bank_echo"],
        "accents": ["edges", "mover_focus", "center"],
        "textures": ["ripple", "steady", "split"],
        "energy_bias": -0.01,
        "motion_bias": 0.04,
        "pulse_bias": -0.09,
        "contrast": 0.27,
        "white_bias": -0.01,
    },
}

TRACK_SHOW_THEME_SEQUENCE = list(TRACK_SHOW_THEMES.keys())

TRACK_SHOW_THEME_CHARACTER = {
    "solar_dusk": {
        "motions": {
            "verse": ["slow_audience_oval", "slow_audience_circle", "slow_high_audience_sweep"],
            "build": ["build_rising_sweep", "build_narrow_to_wide_fan", "build_audience_wave"],
            "chorus": ["fast_audience_sweep", "fast_audience_circle", "drop_crossing_beams"],
            "drop": ["drop_crossing_beams", "drop_snap_fan", "drop_full_audience_hit"],
        },
        "pulses": {
            "build": ["ramp_up", "alternate_whole", "pivot"],
            "chorus": ["alternate_whole", "double_hit", "pivot"],
            "drop": ["double_hit", "gallop", "beat_flash"],
        },
        "mirror_bias": 0.14,
        "white_bias": -0.06,
    },
    "ocean_drive": {
        "motions": {
            "verse": ["slow_high_audience_sweep", "slow_audience_circle", "slow_random_searchlight"],
            "build": ["build_rising_sweep", "build_audience_wave", "build_fastening_circle"],
            "chorus": ["fast_audience_circle", "fast_audience_sweep", "random_search_hits"],
            "drop": ["drop_fast_circle_white", "drop_crossing_beams", "fast_audience_figure_8"],
        },
        "pulses": {
            "build": ["soft_pulse", "ramp_up", "alternate_whole"],
            "chorus": ["alternate_whole", "pivot", "double_hit"],
            "drop": ["gallop", "double_hit", "snake"],
        },
        "mirror_bias": 0.18,
        "white_bias": -0.03,
    },
    "neon_wire": {
        "motions": {
            "verse": ["slow_audience_figure_8", "slow_random_searchlight", "slow_audience_oval"],
            "build": ["build_fastening_circle", "build_color_chase", "build_audience_wave"],
            "chorus": ["fast_diagonal_sweep", "fast_audience_figure_8", "random_search_hits"],
            "drop": ["drop_crossing_beams", "drop_strobe_sweep", "drop_snap_fan"],
        },
        "pulses": {
            "build": ["alternate_whole", "double_hit", "gallop"],
            "chorus": ["gallop", "pivot", "snake"],
            "drop": ["double_hit", "gallop", "snake", "beat_flash"],
        },
        "mirror_bias": 0.26,
        "white_bias": -0.02,
    },
    "velvet_heat": {
        "motions": {
            "verse": ["slow_audience_oval", "slow_audience_circle", "slow_deep_audience_sweep"],
            "build": ["build_rising_sweep", "build_narrow_to_wide_fan", "build_fastening_circle"],
            "chorus": ["fast_audience_sweep", "fast_audience_circle", "drop_crossing_beams"],
            "drop": ["drop_snap_fan", "drop_crossing_beams", "drop_full_audience_hit"],
        },
        "pulses": {
            "build": ["ramp_up", "soft_pulse", "alternate_whole"],
            "chorus": ["pivot", "double_hit", "chase_whole"],
            "drop": ["double_hit", "gallop", "drop_blinder"],
        },
        "mirror_bias": 0.12,
        "white_bias": -0.05,
    },
    "citrus_pop": {
        "motions": {
            "verse": ["slow_audience_sweep_blue", "slow_high_audience_sweep", "slow_audience_figure_8"],
            "build": ["build_rising_sweep", "build_audience_wave", "build_narrow_to_wide_fan"],
            "chorus": ["fast_audience_sweep", "fast_diagonal_sweep", "snap_position_hits"],
            "drop": ["drop_snap_fan", "drop_crossing_beams", "drop_full_audience_hit"],
        },
        "pulses": {
            "build": ["alternate_whole", "ramp_up", "double_hit"],
            "chorus": ["alternate_whole", "double_hit", "gallop"],
            "drop": ["gallop", "double_hit", "snake"],
        },
        "mirror_bias": 0.20,
        "white_bias": -0.04,
    },
    "polar_haze": {
        "motions": {
            "verse": ["slow_high_audience_sweep", "slow_audience_circle", "break_high_cool_sweep"],
            "build": ["build_rising_sweep", "build_fastening_circle", "build_audience_wave"],
            "chorus": ["fast_audience_circle", "fast_audience_sweep", "fast_audience_figure_8"],
            "drop": ["drop_fast_circle_white", "drop_crossing_beams", "drop_full_audience_hit"],
        },
        "pulses": {
            "build": ["soft_pulse", "alternate_whole", "ramp_up"],
            "chorus": ["alternate_whole", "pivot", "beat_flash"],
            "drop": ["double_hit", "drop_blinder", "chase_whole"],
        },
        "mirror_bias": 0.10,
        "white_bias": -0.02,
    },
    "acid_arc": {
        "motions": {
            "verse": ["slow_random_searchlight", "slow_audience_figure_8", "slow_audience_oval"],
            "build": ["build_color_chase", "build_fastening_circle", "build_audience_wave"],
            "chorus": ["fast_diagonal_sweep", "random_search_hits", "fast_audience_figure_8"],
            "drop": ["drop_crossing_beams", "drop_strobe_sweep", "drop_fast_circle_white"],
        },
        "pulses": {
            "build": ["alternate_whole", "gallop", "double_hit"],
            "chorus": ["gallop", "snake", "pivot"],
            "drop": ["snake", "gallop", "double_hit", "tremolo_dimmer"],
        },
        "mirror_bias": 0.28,
        "white_bias": -0.03,
    },
    "ember_storm": {
        "motions": {
            "verse": ["slow_deep_audience_sweep", "slow_audience_circle", "slow_random_searchlight"],
            "build": ["build_rising_sweep", "build_audience_wave", "build_narrow_to_wide_fan"],
            "chorus": ["fast_audience_sweep", "fast_diagonal_sweep", "snap_position_hits"],
            "drop": ["drop_full_audience_hit", "drop_crossing_beams", "drop_strobe_sweep"],
        },
        "pulses": {
            "build": ["ramp_up", "double_hit", "alternate_whole"],
            "chorus": ["double_hit", "gallop", "pivot"],
            "drop": ["drop_blinder", "gallop", "snake", "beat_flash"],
        },
        "mirror_bias": 0.18,
        "white_bias": -0.04,
    },
    "candy_night": {
        "motions": {
            "verse": ["slow_audience_oval", "slow_audience_figure_8", "slow_high_audience_sweep"],
            "build": ["build_fastening_circle", "build_narrow_to_wide_fan", "build_audience_wave"],
            "chorus": ["fast_audience_circle", "fast_audience_figure_8", "fast_audience_sweep"],
            "drop": ["drop_crossing_beams", "drop_fast_circle_white", "drop_snap_fan"],
        },
        "pulses": {
            "build": ["soft_pulse", "alternate_whole", "pivot"],
            "chorus": ["pivot", "double_hit", "gallop"],
            "drop": ["double_hit", "snake", "beat_flash"],
        },
        "mirror_bias": 0.16,
        "white_bias": -0.05,
    },
    "steel_lotus": {
        "motions": {
            "verse": ["slow_high_audience_sweep", "slow_audience_circle", "slow_random_searchlight"],
            "build": ["build_rising_sweep", "build_fastening_circle", "build_narrow_to_wide_fan"],
            "chorus": ["fast_audience_sweep", "fast_audience_circle", "random_search_hits"],
            "drop": ["drop_crossing_beams", "drop_fast_circle_white", "drop_full_audience_hit"],
        },
        "pulses": {
            "build": ["alternate_whole", "ramp_up", "soft_pulse"],
            "chorus": ["alternate_whole", "pivot", "double_hit"],
            "drop": ["gallop", "double_hit", "chase_whole"],
        },
        "mirror_bias": 0.22,
        "white_bias": -0.03,
    },
}

for _theme_name, _character in TRACK_SHOW_THEME_CHARACTER.items():
    if _theme_name in TRACK_SHOW_THEMES:
        TRACK_SHOW_THEMES[_theme_name].update(_character)


def _motion_profile(pattern, **overrides):
    profile = {
        "pattern": pattern,
        "phase_scale": 1.0,
        "spread": 0.0,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "lock_color": False,
    }
    profile.update(overrides)
    return profile


def _profile_tilt_phase_scale(profile, default=1.0):
    try:
        return max(0.1, float(profile.get("tilt_phase_scale", default)))
    except (TypeError, ValueError):
        return float(default)


def _profile_tilt_phase_offset(profile, default=0.0):
    try:
        return float(profile.get("tilt_phase_offset", default))
    except (TypeError, ValueError):
        return float(default)

AUTO_SHOW_MOTION_PROFILES = {
    "center": {
        "pattern": "center_hold",
        "phase_scale": 0.0,
        "spread": 0.0,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 0,
        "speed_max": 30,
        "pan_center": 128,
        "tilt_center": 176,
        "tilt_floor": 164,
    },
    "slow_left_right_sweep": {
        "pattern": "horizontal_sweep",
        "phase_scale": 0.42,
        "spread": 0.22,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": True,
        "use_taught_poses": False,
        "speed_min": 140,
        "speed_max": 180,
        "pan_center": 128,
        "pan_wave": 88,
        "tilt_center": 176,
        "tilt_wave": 0,
        "tilt_floor": 164,
    },
    "fast_left_right_sweep": {
        "pattern": "horizontal_sweep",
        "phase_scale": 0.92,
        "spread": 0.24,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": True,
        "use_taught_poses": False,
        "speed_min": 0,
        "speed_max": 40,
        "pan_center": 128,
        "pan_wave": 98,
        "tilt_center": 178,
        "tilt_wave": 0,
        "tilt_floor": 166,
    },
    "up_down_sweep": {
        "pattern": "vertical_sweep",
        "use_full_tilt_range": True,
        "phase_scale": 0.62,
        "spread": 0.10,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 100,
        "speed_max": 140,
        "pan_center": 128,
        "pan_wave": 0,
        "tilt_min": 0,
        "tilt_max": 255,
    },
    "audience_sweep": {
        "pattern": "horizontal_sweep",
        "phase_scale": 0.62,
        "spread": 0.34,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": True,
        "use_taught_poses": False,
        "speed_min": 60,
        "speed_max": 100,
        "pan_center": 128,
        "pan_wave": 88,
        "tilt_center": 198,
        "tilt_wave": 0,
        "tilt_floor": 182,
        "rgbw": [255, 120, 0, 0],
    },
    "ceiling_sweep": {
        "pattern": "horizontal_sweep",
        "phase_scale": 0.58,
        "spread": 0.34,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": True,
        "use_taught_poses": False,
        "speed_min": 80,
        "speed_max": 120,
        "pan_center": 128,
        "pan_wave": 88,
        "tilt_center": 0,
        "tilt_wave": 0,
        "rgbw": [0, 80, 255, 100],
    },
    "diagonal_sweep": {
        "pattern": "diagonal_sweep",
        "phase_scale": 0.66,
        "spread": 0.18,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 60,
        "speed_max": 100,
        "pan_center": 128,
        "pan_wave": 88,
        "tilt_center": 184,
        "tilt_wave": 34,
        "tilt_floor": 164,
    },
    "reverse_diagonal_sweep": {
        "pattern": "reverse_diagonal_sweep",
        "phase_scale": 0.66,
        "spread": 0.18,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 60,
        "speed_max": 100,
        "pan_center": 128,
        "pan_wave": 88,
        "tilt_center": 184,
        "tilt_wave": 34,
        "tilt_floor": 164,
    },
    "slow_circle": {
        "pattern": "circle",
        "phase_scale": 0.34,
        "spread": 0.10,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 120,
        "speed_max": 160,
        "pan_center": 128,
        "pan_wave": 60,
        "tilt_center": 184,
        "tilt_wave": 28,
        "tilt_floor": 166,
        "rgbw": [0, 0, 255, 0],
    },
    "fast_circle": {
        "pattern": "circle",
        "phase_scale": 0.82,
        "spread": 0.10,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 0,
        "speed_max": 40,
        "pan_center": 128,
        "pan_wave": 78,
        "tilt_center": 186,
        "tilt_wave": 34,
        "tilt_floor": 168,
        "rgbw": [255, 255, 255, 255],
    },
    "oval_circle": {
        "pattern": "circle",
        "phase_scale": 0.52,
        "spread": 0.12,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 60,
        "speed_max": 100,
        "pan_center": 128,
        "pan_wave": 88,
        "tilt_center": 186,
        "tilt_wave": 18,
        "tilt_floor": 170,
        "rgbw": [180, 0, 255, 0],
    },
    "figure_8": {
        "pattern": "figure_8",
        "phase_scale": 0.56,
        "spread": 0.12,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 40,
        "speed_max": 80,
        "pan_center": 128,
        "pan_wave": 70,
        "tilt_center": 186,
        "tilt_wave": 34,
        "tilt_floor": 168,
        "rgbw": [255, 255, 255, 255],
    },
    "small_figure_8": {
        "pattern": "figure_8",
        "phase_scale": 0.42,
        "spread": 0.10,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 100,
        "speed_max": 140,
        "pan_center": 128,
        "pan_wave": 38,
        "tilt_center": 184,
        "tilt_wave": 24,
        "tilt_floor": 170,
        "rgbw": [0, 80, 255, 0],
    },
    "random_searchlight": {
        "pattern": "random_searchlight",
        "phase_scale": 1.0,
        "spread": 0.0,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 20,
        "speed_max": 60,
        "window_beats": 8.0,
        "pan_min": 30,
        "pan_max": 225,
        "tilt_min": 50,
        "tilt_max": 210,
    },
    "slow_searchlight": {
        "pattern": "random_searchlight",
        "phase_scale": 1.0,
        "spread": 0.0,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 150,
        "speed_max": 210,
        "window_beats": 24.0,
        "pan_min": 60,
        "pan_max": 196,
        "tilt_min": 70,
        "tilt_max": 190,
    },
    "snap_position_hits": {
        "pattern": "snap_hits",
        "phase_scale": 1.0,
        "spread": 0.0,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 0,
        "speed_max": 0,
    },
    "strobe_sweep": {
        "pattern": "horizontal_sweep",
        "phase_scale": 0.90,
        "spread": 0.24,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": True,
        "use_taught_poses": False,
        "speed_min": 20,
        "speed_max": 60,
        "pan_center": 128,
        "pan_wave": 88,
        "tilt_center": 182,
        "tilt_wave": 0,
        "tilt_floor": 170,
        "strobe_min": 180,
        "strobe_max": 255,
    },
    "blinder_flash": {
        "pattern": "blinder_flash",
        "phase_scale": 1.0,
        "spread": 0.0,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 0,
        "speed_max": 0,
        "tilt_center": 255,
    },
    "fan_open": {
        "pattern": "fan_open",
        "phase_scale": 0.0,
        "spread": 0.0,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 20,
        "speed_max": 60,
        "fan_width": 88,
        "tilt_center": 182,
        "tilt_floor": 172,
        "fan_positions_4": [60, 105, 150, 195],
        "fan_positions_2": [105, 150],
    },
    "fan_close": {
        "pattern": "center_hold",
        "phase_scale": 0.0,
        "spread": 0.0,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 20,
        "speed_max": 60,
        "pan_center": 128,
        "tilt_center": 176,
        "tilt_floor": 166,
    },
    "fan_wave": {
        "pattern": "fan_wave",
        "phase_scale": 0.60,
        "spread": 0.08,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 60,
        "speed_max": 100,
        "fan_width": 92,
        "fan_wave_pan_positions_4": [70, 110, 150, 190],
        "fan_wave_pan_positions_2": [110, 150],
        "fan_wave_tilt_min": 0,
        "fan_wave_tilt_max": 255,
        "rgbw": [0, 120, 255, 120],
    },
    "crossing_beams": {
        "pattern": "crossing_beams",
        "phase_scale": 0.70,
        "spread": 0.0,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 40,
        "speed_max": 80,
        "crossing_frames_4": [(60, 182), (100, 182), (156, 182), (196, 182)],
        "crossing_frames_2": [(100, 182), (156, 182)],
        "tilt_floor": 174,
        "rgbw": [255, 255, 255, 255],
    },
    "mirror_bounce": {
        "pattern": "mirror_bounce",
        "use_full_tilt_range": True,
        "phase_scale": 0.72,
        "spread": 0.20,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "member_mirror": True,
        "use_taught_poses": False,
        "speed_min": 10,
        "speed_max": 50,
        "pan_center": 128,
        "pan_wave": 68,
        "tilt_center": 184,
        "tilt_wave": 20,
        "tilt_floor": 170,
        "rgbw": [255, 0, 255, 0],
    },
    "color_chase_movement": {
        "pattern": "horizontal_sweep",
        "phase_scale": 0.62,
        "spread": 0.22,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": True,
        "use_taught_poses": False,
        "speed_min": 60,
        "speed_max": 100,
        "pan_center": 128,
        "pan_wave": 88,
        "tilt_center": 182,
        "tilt_wave": 18,
        "tilt_floor": 170,
        "color_program_min": 232,
        "color_program_max": 255,
        "color_speed_min": 80,
        "color_speed_max": 180,
        "rgbw": [0, 0, 0, 0],
    },
    "pulse_circle": {
        "pattern": "pulse_circle",
        "phase_scale": 0.52,
        "spread": 0.10,
        "orbit_pan": 0,
        "orbit_tilt": 0,
        "tilt_lift": 0,
        "edge_drop": 0,
        "snap": 0,
        "mirror": False,
        "use_taught_poses": False,
        "speed_min": 70,
        "speed_max": 110,
        "pan_center": 128,
        "pan_wave": 55,
        "tilt_center": 184,
        "tilt_wave": 24,
        "tilt_floor": 170,
        "rgbw": [0, 80, 255, 80],
    },
    "sweep_narrow": {"pattern": "smooth_sweep", "phase_scale": 0.46, "spread": 0.52, "orbit_pan": 0, "orbit_tilt": 0, "tilt_lift": 12, "edge_drop": 4, "snap": 0, "mirror": True, "pan_base": 34, "pan_extra": 22, "tilt_base": 174, "tilt_wave": 20, "tilt_extra": 10},
    "sweep_mid": {"pattern": "smooth_sweep", "phase_scale": 0.58, "spread": 0.78, "orbit_pan": 0, "orbit_tilt": 0, "tilt_lift": 10, "edge_drop": 6, "snap": 0, "mirror": True, "pan_base": 50, "pan_extra": 30, "tilt_base": 162, "tilt_wave": 28, "tilt_extra": 14},
    "sweep_wide": {"pattern": "smooth_sweep", "phase_scale": 0.72, "spread": 1.08, "orbit_pan": 0, "orbit_tilt": 0, "tilt_lift": 8, "edge_drop": 8, "snap": 0, "mirror": True, "pan_base": 68, "pan_extra": 42, "tilt_base": 152, "tilt_wave": 34, "tilt_extra": 16},
    "sweep_arc": {"pattern": "arc_sweep", "phase_scale": 0.64, "spread": 0.96, "orbit_pan": 0, "orbit_tilt": 0, "tilt_lift": 14, "edge_drop": 6, "snap": 0, "mirror": True, "pan_base": 58, "pan_extra": 34, "tilt_base": 160, "tilt_wave": 38, "tilt_extra": 18},
    "sweep_high": {"pattern": "tilt_sweep", "use_full_tilt_range": True, "phase_scale": 0.50, "spread": 0.66, "orbit_pan": 0, "orbit_tilt": 0, "tilt_lift": 18, "edge_drop": 4, "snap": 0, "mirror": True, "pan_base": 40, "pan_extra": 24, "tilt_base": 176, "tilt_wave": 20, "tilt_extra": 10},
    "sweep_narrow_mirror": {"pattern": "smooth_sweep", "phase_scale": 0.46, "spread": 0.52, "orbit_pan": 0, "orbit_tilt": 0, "tilt_lift": 12, "edge_drop": 4, "snap": 0, "mirror": True, "member_mirror": True, "pan_base": 34, "pan_extra": 22, "tilt_base": 174, "tilt_wave": 20, "tilt_extra": 10},
    "sweep_mid_mirror": {"pattern": "smooth_sweep", "phase_scale": 0.58, "spread": 0.78, "orbit_pan": 0, "orbit_tilt": 0, "tilt_lift": 10, "edge_drop": 6, "snap": 0, "mirror": True, "member_mirror": True, "pan_base": 50, "pan_extra": 30, "tilt_base": 162, "tilt_wave": 28, "tilt_extra": 14},
    "sweep_wide_mirror": {"pattern": "smooth_sweep", "phase_scale": 0.72, "spread": 1.08, "orbit_pan": 0, "orbit_tilt": 0, "tilt_lift": 8, "edge_drop": 8, "snap": 0, "mirror": True, "member_mirror": True, "pan_base": 68, "pan_extra": 42, "tilt_base": 152, "tilt_wave": 34, "tilt_extra": 16},
    "sweep_arc_mirror": {"pattern": "arc_sweep", "phase_scale": 0.64, "spread": 0.96, "orbit_pan": 0, "orbit_tilt": 0, "tilt_lift": 14, "edge_drop": 6, "snap": 0, "mirror": True, "member_mirror": True, "pan_base": 58, "pan_extra": 34, "tilt_base": 160, "tilt_wave": 38, "tilt_extra": 18},
    "sweep_high_mirror": {"pattern": "tilt_sweep", "use_full_tilt_range": True, "phase_scale": 0.50, "spread": 0.66, "orbit_pan": 0, "orbit_tilt": 0, "tilt_lift": 18, "edge_drop": 4, "snap": 0, "mirror": True, "member_mirror": True, "pan_base": 40, "pan_extra": 24, "tilt_base": 176, "tilt_wave": 20, "tilt_extra": 10},
}

AUTO_SHOW_MOTION_PROFILES.update({
    "center_audience_white": _motion_profile("center_hold", pan_center=128, tilt_center=175, pan_tilt_speed_static=20, dimmer_static=255, rgbw=[255, 255, 255, 255]),
    "center_audience_blue": _motion_profile("center_hold", pan_center=128, tilt_center=175, pan_tilt_speed_static=20, dimmer_static=180, rgbw=[0, 40, 255, 80]),
    "wide_fan_white": _motion_profile("static_positions", positions_4=[60, 105, 150, 195], positions_2=[105, 150], tilt_static=180, pan_tilt_speed_static=40, dimmer_static=255, rgbw=[255, 255, 255, 255]),
    "wide_fan_blue": _motion_profile("static_positions", positions_4=[60, 105, 150, 195], positions_2=[105, 150], tilt_static=180, pan_tilt_speed_static=40, dimmer_static=200, rgbw=[0, 80, 255, 120]),
    "narrow_fan_white": _motion_profile("static_positions", positions_4=[100, 120, 136, 156], positions_2=[120, 136], tilt_static=180, pan_tilt_speed_static=40, dimmer_static=255, rgbw=[255, 255, 255, 255]),
    "crossing_static_beams": _motion_profile("static_positions", positions_4=[196, 156, 100, 60], positions_2=[156, 100], tilt_static=185, pan_tilt_speed_static=50, dimmer_static=255, rgbw=[255, 255, 255, 255]),
    "low_audience_amber": _motion_profile("center_hold", pan_center=128, tilt_center=194, pan_tilt_speed_static=20, dimmer_static=180, rgbw=[255, 120, 0, 0]),
    "high_audience_cool_white": _motion_profile("center_hold", pan_center=128, tilt_center=145, pan_tilt_speed_static=20, dimmer_static=220, rgbw=[120, 180, 255, 255]),
    "slow_audience_sweep_white": _motion_profile("horizontal_sweep", phase_scale=0.42, tilt_phase_scale=3.4, full_tilt_curve=0.64, spread=0.0, pan_center=128, pan_wave=88, tilt_center=180, tilt_wave=0, pan_tilt_speed_static=160, dimmer_static=255, rgbw=[255, 255, 255, 255]),
    "slow_audience_sweep_blue": _motion_profile("horizontal_sweep", phase_scale=0.40, tilt_phase_scale=3.6, full_tilt_curve=0.62, spread=0.0, pan_center=128, pan_wave=88, tilt_center=180, tilt_wave=0, pan_tilt_speed_static=170, dimmer_static=200, rgbw=[0, 80, 255, 100]),
    "slow_deep_audience_sweep": _motion_profile("horizontal_sweep", phase_scale=0.44, tilt_phase_scale=3.2, full_tilt_curve=0.62, spread=0.0, pan_center=128, pan_wave=88, tilt_center=192, tilt_wave=0, pan_tilt_speed_static=150, dimmer_static=220, rgbw=[255, 120, 0, 0]),
    "slow_high_audience_sweep": _motion_profile("horizontal_sweep", phase_scale=0.40, tilt_phase_scale=3.4, full_tilt_curve=0.62, spread=0.0, pan_center=128, pan_wave=88, tilt_center=145, tilt_wave=0, pan_tilt_speed_static=160, dimmer_static=220, rgbw=[100, 160, 255, 255]),
    "slow_audience_circle": _motion_profile("circle", phase_scale=0.34, tilt_phase_scale=2.4, full_tilt_curve=0.64, spread=0.0, pan_center=128, pan_wave=60, tilt_center=180, tilt_wave=35, pan_tilt_speed_static=140, dimmer_static=220, rgbw=[0, 0, 255, 80]),
    "slow_audience_oval": _motion_profile("circle", phase_scale=0.44, tilt_phase_scale=2.1, full_tilt_curve=0.66, spread=0.0, pan_center=128, pan_wave=88, tilt_center=180, tilt_wave=25, pan_tilt_speed_static=120, dimmer_static=220, rgbw=[160, 0, 255, 40]),
    "slow_audience_figure_8": _motion_profile("figure_8", phase_scale=0.34, tilt_phase_scale=2.0, full_tilt_curve=0.64, spread=0.0, pan_center=128, pan_wave=70, tilt_center=178, tilt_wave=36, pan_tilt_speed_static=130, dimmer_static=220, rgbw=[150, 210, 255, 80]),
    "slow_random_searchlight": _motion_profile("random_searchlight", window_beats=24.0, pan_min=60, pan_max=196, tilt_min=148, tilt_max=198, pan_tilt_speed_static=180, dimmer_static=200, rgbw=[80, 120, 255, 80]),
    "fast_audience_sweep": _motion_profile("horizontal_sweep", phase_scale=0.92, tilt_phase_scale=2.2, full_tilt_curve=0.60, spread=0.0, pan_center=128, pan_wave=98, tilt_center=180, tilt_wave=0, pan_tilt_speed_static=20, dimmer_static=255, rgbw=[255, 120, 35, 0]),
    "fast_audience_circle": _motion_profile("circle", phase_scale=0.82, tilt_phase_scale=1.8, full_tilt_curve=0.60, spread=0.0, pan_center=128, pan_wave=78, tilt_center=180, tilt_wave=34, pan_tilt_speed_static=20, dimmer_static=255, rgbw=[0, 120, 255, 60]),
    "fast_audience_figure_8": _motion_profile("figure_8", phase_scale=0.86, tilt_phase_scale=1.7, full_tilt_curve=0.60, spread=0.0, pan_center=128, pan_wave=80, tilt_center=182, tilt_wave=36, pan_tilt_speed_static=25, dimmer_static=255, rgbw=[255, 60, 200, 0]),
    "snap_position_hits": _motion_profile("snap_hits", use_full_tilt_range=True, pan_tilt_speed_static=0, dimmer_static=255, rgbw=[255, 255, 255, 255], snap_positions=[(40, 155), (216, 155), (216, 215), (40, 215), (128, 180)]),
    "fast_diagonal_sweep": _motion_profile("diagonal_sweep", phase_scale=0.84, tilt_phase_scale=1.8, full_tilt_curve=0.58, spread=0.0, pan_center=128, pan_wave=88, tilt_center=185, tilt_wave=40, pan_tilt_speed_static=30, dimmer_static=255, rgbw=[255, 255, 255, 255]),
    "reverse_fast_diagonal": _motion_profile("reverse_diagonal_sweep", phase_scale=0.84, tilt_phase_scale=1.8, full_tilt_curve=0.58, spread=0.0, pan_center=128, pan_wave=88, tilt_center=185, tilt_wave=40, pan_tilt_speed_static=30, dimmer_static=255, rgbw=[255, 255, 255, 255]),
    "mirror_bounce_show": _motion_profile("mirror_bounce", use_full_tilt_range=True, phase_scale=0.82, tilt_phase_scale=1.6, full_tilt_curve=0.60, spread=0.0, pan_center=128, pan_wave=78, tilt_center=188, tilt_wave=35, pan_tilt_speed_static=30, dimmer_static=255, rgbw=[255, 0, 255, 0], member_mirror=True),
    "random_search_hits": _motion_profile("random_searchlight", window_beats=4.0, pan_min=30, pan_max=225, tilt_min=148, tilt_max=198, pan_tilt_speed_static=20, dimmer_static=255, rgbw=[255, 110, 40, 0]),
    "build_rising_sweep": _motion_profile("rising_sweep", use_full_tilt_range=True, phase_scale=0.62, tilt_phase_scale=1.8, full_tilt_curve=0.60, pan_center=128, pan_wave=88, tilt_min=150, tilt_max=196, pan_tilt_speed_static=70, dimmer_min=120, dimmer_max=255, rgbw=[255, 170, 45, 0]),
    "build_dimmer_pulse": _motion_profile("hold_pulse", pan_center=128, tilt_center=178, pulse_phase_scale=0.50, pan_tilt_speed_static=60, dimmer_min=80, dimmer_max=255, rgbw=[255, 120, 40, 0]),
    "build_fastening_circle": _motion_profile("pulse_circle", phase_scale=0.70, tilt_phase_scale=1.7, full_tilt_curve=0.60, spread=0.0, pan_center=128, pan_wave=65, tilt_center=178, tilt_wave=28, pan_tilt_speed_static=80, dimmer_min=150, dimmer_max=255, rgbw=[150, 80, 255, 0]),
    "build_narrow_to_wide_fan": _motion_profile("fan_morph", positions_start_4=[115, 125, 135, 145], positions_mid_4=[90, 115, 140, 165], positions_end_4=[60, 105, 150, 195], positions_start_2=[122, 134], positions_mid_2=[112, 144], positions_end_2=[105, 150], tilt_static=178, phase_scale=0.45, pan_tilt_speed_static=70, dimmer_min=150, dimmer_max=255, rgbw=[0, 160, 255, 40]),
    "build_strobe_ramp": _motion_profile("horizontal_sweep", phase_scale=0.76, tilt_phase_scale=2.2, full_tilt_curve=0.60, spread=0.0, pan_center=128, pan_wave=88, tilt_center=178, tilt_wave=0, pan_tilt_speed_static=30, dimmer_static=255, strobe_min=40, strobe_max=220, rgbw=[255, 160, 55, 0]),
    "build_color_chase": _motion_profile("horizontal_sweep", phase_scale=0.62, tilt_phase_scale=2.0, full_tilt_curve=0.60, spread=0.0, pan_center=128, pan_wave=88, tilt_center=185, tilt_wave=25, pan_tilt_speed_static=80, dimmer_static=255, color_program_min=232, color_program_max=255, color_speed_min=80, color_speed_max=180, rgbw=[0, 0, 0, 0], lock_color=True),
    "build_audience_wave": _motion_profile("fan_wave", phase_scale=0.60, tilt_phase_scale=2.3, full_tilt_curve=0.58, spread=0.0, fan_wave_pan_positions_4=[70, 110, 150, 190], fan_wave_pan_positions_2=[110, 150], fan_wave_tilt_min=154, fan_wave_tilt_max=202, pan_tilt_speed_static=80, dimmer_min=180, dimmer_max=255, rgbw=[0, 120, 255, 120]),
    "build_white_flash_prep": _motion_profile("hold_pulse", pan_center=128, tilt_center=184, pulse_phase_scale=1.00, pan_tilt_speed_static=0, dimmer_min=0, dimmer_max=220, rgbw=[255, 255, 255, 255], lock_color=True),
    "drop_white_blinder": _motion_profile("center_hold", pan_center=128, tilt_center=198, pan_tilt_speed_static=0, dimmer_static=255, rgbw=[255, 255, 255, 255], lock_color=True),
    "drop_strobe_sweep": _motion_profile("horizontal_sweep", phase_scale=0.96, tilt_phase_scale=2.4, full_tilt_curve=0.58, spread=0.0, pan_center=128, pan_wave=98, tilt_center=185, tilt_wave=0, pan_tilt_speed_static=20, dimmer_static=255, strobe_min=200, strobe_max=255, rgbw=[255, 255, 255, 255], lock_color=True),
    "drop_snap_fan": _motion_profile("static_positions", positions_4=[50, 100, 155, 205], positions_2=[100, 155], tilt_static=188, pan_tilt_speed_static=0, dimmer_static=255, rgbw=[255, 255, 255, 255]),
    "drop_fast_circle_white": _motion_profile("circle", phase_scale=1.00, tilt_phase_scale=1.9, full_tilt_curve=0.58, spread=0.0, pan_center=128, pan_wave=85, tilt_center=182, tilt_wave=36, pan_tilt_speed_static=10, dimmer_static=255, rgbw=[255, 255, 255, 255]),
    "drop_crossing_beams": _motion_profile("crossing_beams", phase_scale=0.92, spread=0.0, crossing_frames_4=[(196, 185), (156, 185), (100, 185), (60, 185)], crossing_frames_2=[(156, 185), (100, 185)], pan_tilt_speed_static=20, dimmer_static=255, rgbw=[255, 255, 255, 255]),
    "drop_red_blue_bounce": _motion_profile("mirror_bounce", use_full_tilt_range=True, phase_scale=0.92, tilt_phase_scale=1.8, full_tilt_curve=0.58, spread=0.0, pan_center=128, pan_wave=78, tilt_center=184, tilt_wave=28, pan_tilt_speed_static=20, dimmer_static=255, rgbw=[255, 0, 255, 0], member_mirror=True),
    "drop_full_audience_hit": _motion_profile("center_hold", pan_center=128, tilt_center=202, pan_tilt_speed_static=0, dimmer_static=255, rgbw=[255, 255, 255, 255], lock_color=True),
    "drop_blackout_hit": _motion_profile("blackout_hit", pan_center=128, tilt_center=202, pan_tilt_speed_static=0, dimmer_min=0, dimmer_max=255, rgbw=[255, 255, 255, 255], lock_color=True),
    "break_soft_blue_center": _motion_profile("center_hold", pan_center=128, tilt_center=165, pan_tilt_speed_static=160, dimmer_static=100, rgbw=[0, 40, 255, 40]),
    "break_slow_pulse_circle": _motion_profile("pulse_circle", phase_scale=0.34, tilt_phase_scale=2.0, full_tilt_curve=0.64, spread=0.0, pan_center=128, pan_wave=55, tilt_center=180, tilt_wave=35, pan_tilt_speed_static=160, dimmer_min=60, dimmer_max=180, rgbw=[0, 80, 255, 80]),
    "break_purple_oval": _motion_profile("circle", phase_scale=0.34, tilt_phase_scale=2.1, full_tilt_curve=0.66, spread=0.0, pan_center=128, pan_wave=70, tilt_center=170, tilt_wave=20, pan_tilt_speed_static=170, dimmer_static=140, rgbw=[180, 0, 255, 0]),
    "break_high_cool_sweep": _motion_profile("horizontal_sweep", phase_scale=0.38, tilt_phase_scale=3.4, full_tilt_curve=0.62, spread=0.0, pan_center=128, pan_wave=78, tilt_center=145, tilt_wave=0, pan_tilt_speed_static=180, dimmer_static=130, rgbw=[100, 180, 255, 180]),
    "break_dimmed_fan": _motion_profile("static_positions", positions_4=[70, 110, 150, 190], positions_2=[110, 150], tilt_static=165, pan_tilt_speed_static=120, dimmer_static=90, rgbw=[0, 80, 255, 80]),
    "break_cyan_figure_8": _motion_profile("figure_8", phase_scale=0.32, tilt_phase_scale=2.0, full_tilt_curve=0.64, spread=0.0, pan_center=128, pan_wave=45, tilt_center=175, tilt_wave=25, pan_tilt_speed_static=170, dimmer_static=120, rgbw=[0, 255, 255, 60]),
    "break_warm_low_glow": _motion_profile("center_hold", pan_center=128, tilt_center=195, pan_tilt_speed_static=180, dimmer_static=100, rgbw=[255, 130, 20, 80]),
    "break_no_movement_fade": _motion_profile("hold_pulse", pan_center=128, tilt_center=170, pulse_phase_scale=0.22, pan_tilt_speed_static=200, dimmer_min=0, dimmer_max=160, rgbw=[0, 60, 255, 80]),
    "live_audience_tilt_sweep": _motion_profile("tilt_sweep", use_full_tilt_range=True, tilt_phase_scale=2.0, full_tilt_curve=0.58, pan_base=12, pan_extra=10, tilt_base=188, tilt_wave=34, tilt_extra=12, pan_tilt_speed_static=26, dimmer_static=255, rgbw=[255, 255, 255, 255]),
})

AUTO_SHOW_COLOR_PROFILES = {
    "yellow_blue": {
        "label": "Yellow Blue",
        "primary": (255, 210, 0, 0),
        "secondary": (0, 95, 255, 0),
        "accent": (255, 245, 120, 0),
        "white": (255, 255, 255, 60),
        "base_mix": 0.38,
        "accent_mix": 0.08,
        "white_mix": 0.005,
        "split_mix": 0.32,
    },
    "magenta_cyan": {
        "label": "Magenta Cyan",
        "primary": (255, 30, 190, 0),
        "secondary": (0, 220, 255, 0),
        "accent": (255, 140, 230, 0),
        "white": (255, 255, 255, 60),
        "base_mix": 0.40,
        "accent_mix": 0.08,
        "white_mix": 0.005,
        "split_mix": 0.34,
    },
    "amber_teal": {
        "label": "Amber Teal",
        "primary": (255, 150, 20, 0),
        "secondary": (0, 210, 185, 0),
        "accent": (255, 215, 120, 0),
        "white": (255, 250, 235, 50),
        "base_mix": 0.36,
        "accent_mix": 0.08,
        "white_mix": 0.004,
        "split_mix": 0.28,
    },
    "amber_violet": {
        "label": "Amber Violet",
        "primary": (255, 165, 30, 0),
        "secondary": (145, 70, 255, 0),
        "accent": (255, 210, 140, 0),
        "white": (255, 248, 240, 55),
        "base_mix": 0.36,
        "accent_mix": 0.08,
        "white_mix": 0.004,
        "split_mix": 0.30,
    },
    "teal_orange": {
        "label": "Teal Orange",
        "primary": (0, 210, 200, 0),
        "secondary": (255, 110, 15, 0),
        "accent": (255, 190, 95, 0),
        "white": (250, 255, 255, 55),
        "base_mix": 0.38,
        "accent_mix": 0.08,
        "white_mix": 0.005,
        "split_mix": 0.31,
    },
    "violet_lime": {
        "label": "Violet Lime",
        "primary": (165, 65, 255, 0),
        "secondary": (180, 255, 30, 0),
        "accent": (235, 200, 255, 0),
        "white": (255, 255, 240, 45),
        "base_mix": 0.33,
        "accent_mix": 0.07,
        "white_mix": 0.003,
        "split_mix": 0.30,
    },
    "ice_fire": {
        "label": "Ice Fire",
        "primary": (90, 215, 255, 0),
        "secondary": (255, 75, 0, 0),
        "accent": (255, 240, 215, 0),
        "white": (255, 255, 255, 120),
        "base_mix": 0.40,
        "accent_mix": 0.07,
        "white_mix": 0.010,
        "split_mix": 0.34,
    },
    "rose_mint": {
        "label": "Rose Mint",
        "primary": (255, 90, 150, 0),
        "secondary": (45, 245, 190, 0),
        "accent": (255, 205, 225, 0),
        "white": (250, 255, 248, 45),
        "base_mix": 0.35,
        "accent_mix": 0.07,
        "white_mix": 0.004,
        "split_mix": 0.28,
    },
    "cobalt_amber": {
        "label": "Cobalt Amber",
        "primary": (0, 85, 255, 0),
        "secondary": (255, 170, 25, 0),
        "accent": (175, 210, 255, 0),
        "white": (255, 248, 235, 60),
        "base_mix": 0.40,
        "accent_mix": 0.07,
        "white_mix": 0.005,
        "split_mix": 0.32,
    },
    "ruby_lime": {
        "label": "Ruby Lime",
        "primary": (255, 40, 60, 0),
        "secondary": (175, 255, 35, 0),
        "accent": (255, 190, 90, 0),
        "white": (255, 255, 235, 45),
        "base_mix": 0.35,
        "accent_mix": 0.07,
        "white_mix": 0.003,
        "split_mix": 0.30,
    },
    "lilac_gold": {
        "label": "Lilac Gold",
        "primary": (170, 110, 255, 0),
        "secondary": (255, 205, 55, 0),
        "accent": (240, 210, 255, 0),
        "white": (255, 252, 235, 55),
        "base_mix": 0.35,
        "accent_mix": 0.07,
        "white_mix": 0.004,
        "split_mix": 0.28,
    },
    "blue_amber": {
        "label": "Blue Amber",
        "primary": (0, 85, 255, 0),
        "secondary": (255, 150, 20, 0),
        "accent": (255, 215, 110, 0),
        "white": (255, 250, 235, 55),
        "base_mix": 0.40,
        "accent_mix": 0.07,
        "white_mix": 0.005,
        "split_mix": 0.34,
    },
    "purple_gold": {
        "label": "Purple Gold",
        "primary": (155, 65, 255, 0),
        "secondary": (255, 205, 35, 0),
        "accent": (230, 205, 255, 0),
        "white": (255, 250, 235, 55),
        "base_mix": 0.37,
        "accent_mix": 0.07,
        "white_mix": 0.004,
        "split_mix": 0.31,
    },
    "deep_blue_white": {
        "label": "Deep Blue White",
        "primary": (0, 70, 255, 0),
        "secondary": (235, 245, 255, 90),
        "accent": (140, 180, 255, 0),
        "white": (255, 255, 255, 90),
        "base_mix": 0.36,
        "accent_mix": 0.06,
        "white_mix": 0.010,
        "split_mix": 0.28,
    },
    "red_white": {
        "label": "Red White",
        "primary": (255, 35, 35, 0),
        "secondary": (255, 255, 255, 120),
        "accent": (255, 155, 155, 0),
        "white": (255, 255, 255, 90),
        "base_mix": 0.34,
        "accent_mix": 0.06,
        "white_mix": 0.012,
        "split_mix": 0.26,
    },
    "pink_blue": {
        "label": "Pink Blue",
        "primary": (255, 40, 180, 0),
        "secondary": (0, 105, 255, 0),
        "accent": (255, 145, 215, 0),
        "white": (245, 250, 255, 55),
        "base_mix": 0.39,
        "accent_mix": 0.07,
        "white_mix": 0.005,
        "split_mix": 0.33,
    },
}


def fixture_preset(fixture_id):
    fixture = find_fixture(FIXTURE_LIBRARY, fixture_id)
    preset = dict(FIXTURE_PRESETS.get(fixture_id, {}))
    preset.setdefault("label_base", fixture["model"])
    preset.setdefault("mode", fixture["modes"][0]["name"])
    return preset


def slot_sequence_index(slot_id, base_id):
    slot_id = str(slot_id or "")
    base_id = str(base_id or "")
    if slot_id == "head":
        return 0
    if slot_id == base_id:
        return 1
    prefix = f"{base_id}_"
    if slot_id.startswith(prefix):
        suffix = slot_id[len(prefix) :]
        with suppress(Exception):
            return int(suffix)
    return None


def default_group_name_for_slot(slot_id, fixture_id, label=""):
    fixture_id = str(fixture_id or "")
    label_text = str(label or "").lower()
    if fixture_id == "shehds_led_wash_7x12w_rgbw_moving_head" or "moving head" in label_text:
        moving_index = slot_sequence_index(slot_id, "moving_head")
        pair_index = 0 if moving_index is None else max(0, moving_index // 2)
        pair_index = min(pair_index, 25)
        return f"movers_{chr(ord('a') + pair_index)}"
    if fixture_id == "shehds_flat_par_12x3w_rgbw" or "par" in label_text:
        return "pars"
    if fixture_id == "uking_zq06016" or "wash" in label_text:
        return "washes"
    return "fixtures"


def mode_capabilities(mode):
    channel_types = {channel["type"] for channel in mode["channels"]}
    color_components = {
        channel.get("component")
        for channel in mode["channels"]
        if channel["type"] == "color"
    }
    return {
        "dimmer": "intensity" in channel_types,
        "strobe": "strobe" in channel_types,
        "program": any(
            channel_type in channel_types
            for channel_type in ("program", "color_program", "auto_mode")
        ),
        "speed": any(channel_type in channel_types for channel_type in ("speed", "color_speed")),
        "pan": "pan" in channel_types,
        "pan_fine": "pan_fine" in channel_types,
        "tilt": "tilt" in channel_types,
        "tilt_fine": "tilt_fine" in channel_types,
        "pan_tilt_speed": "pan_tilt_speed" in channel_types,
        "white": "white" in color_components or "coolwhite" in color_components,
    }


def wave_sine(position):
    return math.sin(position * math.tau)


def wave_cosine(position):
    return math.cos(position * math.tau)


def wave_triangle(position):
    fraction = position % 1.0
    return 1.0 - 4.0 * abs(fraction - 0.5)


def wave_square(position):
    return 1.0 if (position % 1.0) < 0.5 else -1.0


def clamp_motion(center, amplitude, wave):
    return clamp_dmx(round(center + amplitude * wave))


def phrase_motion(phrase, beat_value):
    key = normalize_phrase(phrase)
    beat_value = float(beat_value or 0.0)

    if key.startswith("intro"):
        cycle = beat_value / 8.0
        return {
            "pan": clamp_motion(116, 28, wave_sine(cycle)),
            "tilt": clamp_motion(176, 10, wave_triangle(cycle)),
            "pan_tilt_speed": 0,
        }
    if key.startswith("verse"):
        cycle = beat_value / 4.0
        return {
            "pan": clamp_motion(127, 52, wave_sine(cycle)),
            "tilt": clamp_motion(150, 18, wave_triangle(cycle + 0.25)),
            "pan_tilt_speed": 0,
        }
    if key.startswith("up") or key.startswith("build"):
        cycle = beat_value / 2.0
        return {
            "pan": clamp_motion(127, 34, wave_triangle(cycle)),
            "tilt": clamp_motion(118, 34, wave_sine(cycle + 0.25)),
            "pan_tilt_speed": 0,
        }
    if key.startswith("chorus"):
        cycle = beat_value / 2.0
        return {
            "pan": clamp_motion(127, 72, wave_sine(cycle)),
            "tilt": clamp_motion(134, 26, wave_sine(cycle * 2.0)),
            "pan_tilt_speed": 0,
        }
    if key.startswith("drop"):
        cycle = beat_value
        return {
            "pan": clamp_motion(127, 82, wave_square(cycle)),
            "tilt": clamp_motion(108, 22, wave_triangle(cycle / 2.0)),
            "pan_tilt_speed": 0,
        }
    if key.startswith("bridge"):
        cycle = beat_value / 4.0
        return {
            "pan": clamp_motion(127, 24, wave_sine(cycle)),
            "tilt": clamp_motion(160, 28, wave_sine(cycle + 0.25)),
            "pan_tilt_speed": 0,
        }
    if key.startswith("down") or key.startswith("break"):
        cycle = beat_value / 8.0
        return {
            "pan": clamp_motion(127, 18, wave_sine(cycle)),
            "tilt": clamp_motion(188, 10, wave_triangle(cycle)),
            "pan_tilt_speed": 0,
        }
    if key.startswith("outro"):
        cycle = beat_value / 8.0
        return {
            "pan": clamp_motion(110, 46, wave_triangle(cycle)),
            "tilt": clamp_motion(178, 12, wave_sine(cycle)),
            "pan_tilt_speed": 0,
        }
    return None


def parse_osc_string(data, index):
    end = data.find(b"\0", index)
    if end < 0:
        return None, index
    text = data[index:end].decode("utf-8", "replace")
    index = (end + 4) & ~3
    return text, index


def parse_osc_message(data):
    index = 0
    address, index = parse_osc_string(data, index)
    if not address or not address.startswith("/"):
        return None

    tags, index = parse_osc_string(data, index)
    if not tags or not tags.startswith(","):
        return {"address": address, "numeric": None, "text": None}

    numeric = None
    text = None
    for tag in tags[1:]:
        if tag == "f" and index + 4 <= len(data):
            value = struct.unpack(">f", data[index : index + 4])[0]
            index += 4
            if numeric is None:
                numeric = float(value)
                text = f"{value:.4f}"
        elif tag == "i" and index + 4 <= len(data):
            value = struct.unpack(">i", data[index : index + 4])[0]
            index += 4
            if numeric is None:
                numeric = float(value)
                text = str(value)
        elif tag == "s":
            value, index = parse_osc_string(data, index)
            if text is None:
                text = value
        else:
            break

    return {"address": address, "numeric": numeric, "text": text}


def normalize_phrase(text):
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def color_for_phrase(phrase):
    key = normalize_phrase(phrase)
    if key.startswith("intro"):
        return COLOR_PRESETS["intro"]
    if key.startswith("verse"):
        return COLOR_PRESETS["verse"]
    if key.startswith("up") or key.startswith("build"):
        return COLOR_PRESETS["build"]
    if key.startswith("chorus"):
        return COLOR_PRESETS["chorus"]
    if key.startswith("drop"):
        return COLOR_PRESETS["drop"]
    if key.startswith("down") or key.startswith("break"):
        return COLOR_PRESETS["break"]
    if key.startswith("outro"):
        return COLOR_PRESETS["outro"]
    return None


def color_for_mood(mood):
    if mood is None:
        return None
    value = int(round(mood))
    if value <= 1:
        return COLOR_PRESETS["high"]
    if value == 2:
        return COLOR_PRESETS["mid"]
    return COLOR_PRESETS["low"]


AUTO_SHOW_PHRASE_OVERRIDES = {
    "none": "Auto",
    "intro": "Intro",
    "verse": "Verse",
    "build": "Build",
    "chorus": "Chorus",
    "drop": "Drop",
    "down": "Down",
    "break": "Break",
    "outro": "Outro",
}


def auto_show_phrase_override_name(value):
    normalized = str(value or "none").strip().lower()
    if normalized in {"", "auto"}:
        normalized = "none"
    return normalized if normalized in AUTO_SHOW_PHRASE_OVERRIDES else "none"


def auto_show_phrase_override_label(value):
    return AUTO_SHOW_PHRASE_OVERRIDES.get(
        auto_show_phrase_override_name(value),
        AUTO_SHOW_PHRASE_OVERRIDES["none"],
    )


def track_color_signature(track_title=None, track_artist=None, track_album=None):
    parts = [
        str(track_title or "").strip(),
        str(track_artist or "").strip(),
        str(track_album or "").strip(),
    ]
    meaningful = [part for part in parts if part and part != "-"]
    if not meaningful:
        return None
    return "|".join(parts)


def color_phrase_group(phrase):
    key = normalize_phrase(phrase)
    if key.startswith("intro"):
        return "intro"
    if key.startswith("verse") or key.startswith("up"):
        return "verse"
    if key.startswith("chorus"):
        return "chorus"
    if key in {"bridge", "down", "break", "build", "drop"}:
        return "bridge"
    if key.startswith("outro"):
        return "outro"
    return None


def themed_bank_options(theme, group):
    if theme == 0:
        return {
            "intro": [1, 4],
            "verse": [2, 1],
            "chorus": [3, 6],
            "bridge": [4, 1],
            "outro": [5, 1],
        }.get(group, [2])
    if theme == 1:
        return {
            "intro": [5, 1],
            "verse": [5, 2],
            "chorus": [3, 5, 8],
            "bridge": [4, 5],
            "outro": [5],
        }.get(group, [5])
    if theme == 2:
        return {
            "intro": [6, 1],
            "verse": [2, 6],
            "chorus": [6, 3, 8],
            "bridge": [4, 6],
            "outro": [5, 6],
        }.get(group, [6])
    if theme == 3:
        return {
            "intro": [7, 1],
            "verse": [2, 7],
            "chorus": [7, 8, 3],
            "bridge": [4, 7],
            "outro": [5, 7],
        }.get(group, [7])
    if theme == 4:
        return {
            "intro": [1, 4],
            "verse": [4, 2],
            "chorus": [3, 4, 5],
            "bridge": [4, 1],
            "outro": [5, 4],
        }.get(group, [4])
    return {
        "intro": [1, 6],
        "verse": [2, 5],
        "chorus": [8, 3, 6],
        "bridge": [4, 8],
        "outro": [5, 1],
    }.get(group, [8])


def themed_color_bank_for_phrase(phrase, track_title=None, track_artist=None, track_album=None):
    group = color_phrase_group(phrase)
    if not group:
        return None
    signature = track_color_signature(track_title, track_artist, track_album)
    if not signature:
        return None
    theme = int(stable_hash(signature) % 6)
    options = themed_bank_options(theme, group)
    if not options:
        return None
    variant = int(stable_hash(f"{signature}|{group}|{normalize_phrase(phrase)}") % len(options))
    return options[variant]


def track_fallback_color_bank(track_title=None, track_artist=None, track_album=None):
    signature = track_color_signature(track_title, track_artist, track_album)
    if not signature:
        return None
    return int(stable_hash(signature) % 8) + 1


def derive_color_bank_value(color_bank, phrase=None, track_title=None, track_artist=None, track_album=None):
    if color_bank is not None:
        try:
            value = int(round(float(color_bank)))
        except (TypeError, ValueError):
            value = None
        if value is not None:
            if value != 0:
                return value
    themed = themed_color_bank_for_phrase(
        phrase,
        track_title=track_title,
        track_artist=track_artist,
        track_album=track_album,
    )
    if themed is not None:
        return themed
    fallback = track_fallback_color_bank(
        track_title=track_title,
        track_artist=track_artist,
        track_album=track_album,
    )
    if fallback is not None:
        return fallback
    return 1


def mood_value_for_phrase(phrase):
    key = normalize_phrase(phrase)
    if key in {
        "intro1",
        "intro2",
        "up1",
        "up2",
        "up3",
        "down",
        "chorus1",
        "chorus2",
        "outro1",
        "outro2",
    }:
        return 1.0
    if key in {"verse3", "verse4", "verse5", "verse6"}:
        return 2.0
    if key in {
        "intro",
        "verse",
        "verse1",
        "verse2",
        "bridge",
        "chorus",
        "outro",
    }:
        return 2.0
    return None


def derive_mood_value(mood, phrase=None, color_bank=None):
    if mood is not None:
        try:
            value = float(mood)
        except (TypeError, ValueError):
            value = None
        if value is not None and math.isfinite(value):
            clamped = min(3.0, max(1.0, value))
            return clamped

    derived_from_phrase = mood_value_for_phrase(phrase)
    if derived_from_phrase is not None:
        return derived_from_phrase

    if color_bank is not None:
        return 2.0

    return None


def mood_factor_from_value(mood):
    if mood is None:
        return 0.5
    value = min(3.0, max(1.0, float(mood)))
    # BPM Trigger / Rekordbox semantics:
    # 1 = high, 2 = mid, 3 = low
    return clamp_unit((3.0 - value) / 2.0)


def clamp_unit(value):
    return max(0.0, min(1.0, float(value)))


def clamp_rgbw(rgbw):
    return tuple(clamp_dmx(component) for component in rgbw)


def mix_rgbw(base, target, amount):
    amount = clamp_unit(amount)
    return clamp_rgbw(
        round(base[index] + (target[index] - base[index]) * amount)
        for index in range(4)
    )


def saturate_rgbw(rgbw, minimum_saturation=0.0, white_cap=None):
    r, g, b, w = (clamp_dmx(component) for component in rgbw)
    if white_cap is not None:
        w = min(w, clamp_dmx(white_cap))
    maximum = max(r, g, b)
    minimum = min(r, g, b)
    chroma = maximum - minimum
    if maximum <= 0 or chroma < 12:
        return (r, g, b, w)

    hue, saturation, value = colorsys.rgb_to_hsv(
        float(r) / 255.0,
        float(g) / 255.0,
        float(b) / 255.0,
    )
    if saturation >= minimum_saturation:
        return (r, g, b, w)

    boosted = colorsys.hsv_to_rgb(hue, minimum_saturation, value)
    return (
        clamp_dmx(round(boosted[0] * 255.0)),
        clamp_dmx(round(boosted[1] * 255.0)),
        clamp_dmx(round(boosted[2] * 255.0)),
        w,
    )


def normalize_rgbw_peak(rgbw, peak_target=255, white_cap=None, minimum_peak=96):
    r, g, b, w = (clamp_dmx(component) for component in rgbw)
    if white_cap is not None:
        w = min(w, clamp_dmx(white_cap))
    current_peak = max(r, g, b)
    if current_peak < max(1, int(minimum_peak)):
        return (r, g, b, w)
    if current_peak >= peak_target:
        return (r, g, b, w)
    scale = float(peak_target) / float(current_peak)
    return (
        clamp_dmx(round(r * scale)),
        clamp_dmx(round(g * scale)),
        clamp_dmx(round(b * scale)),
        w,
    )


def _rgb_hue(rgbw):
    r, g, b = (float(clamp_dmx(component)) / 255.0 for component in rgbw[:3])
    hue, _saturation, _value = colorsys.rgb_to_hsv(r, g, b)
    return hue


def clarify_rgbw(rgbw, anchor_strength=0.72, white_cap=None):
    r, g, b, w = (clamp_dmx(component) for component in rgbw)
    if white_cap is not None:
        w = min(w, clamp_dmx(white_cap))
    peak = max(r, g, b)
    chroma = peak - min(r, g, b)
    if peak < 96 or chroma < 36:
        return (r, g, b, w)

    hue = _rgb_hue((r, g, b, 0))
    anchor = min(
        VIVID_COLOR_ANCHORS,
        key=lambda candidate: min(
            abs(_rgb_hue(candidate) - hue),
            1.0 - abs(_rgb_hue(candidate) - hue),
        ),
    )
    clarified = mix_rgbw((r, g, b, 0), anchor, anchor_strength)
    clarified = saturate_rgbw(clarified, minimum_saturation=0.84, white_cap=0)
    clarified = normalize_rgbw_peak(clarified, peak_target=255, white_cap=0, minimum_peak=96)
    return clarified


def stable_hash(text):
    value = 0
    for char in str(text or ""):
        value = ((value * 131) + ord(char)) & 0xFFFFFFFF
    return value


def track_preview_identity(track_title=None, track_artist=None, track_album=None):
    return "|".join(
        [
            str(track_title or "").strip(),
            str(track_artist or "").strip(),
            str(track_album or "").strip(),
        ]
    )


def track_preview_cache_key(track_title=None, track_artist=None, track_album=None):
    return f"{stable_hash(track_preview_identity(track_title, track_artist, track_album)):08x}"


def track_preview_summary_path(track_title=None, track_artist=None, track_album=None):
    return TRACK_PREVIEW_CACHE_DIR / f"{track_preview_cache_key(track_title, track_artist, track_album)}.json"


def track_preview_summary_path_for_cache_key(cache_key):
    return TRACK_PREVIEW_CACHE_DIR / f"{str(cache_key or '').strip()}.json"


def pick_variant(options, seed, fallback):
    if not options:
        return fallback
    return options[int(seed) % len(options)]


def merge_variant_pools(*pools):
    merged = []
    for pool in pools:
        for item in pool or []:
            if item not in merged:
                merged.append(item)
    return merged


def titleize_variant(name):
    return str(name or "").replace("_", " ").title()


def phrase_bucket(phrase):
    key = normalize_phrase(phrase)
    if key.startswith("intro"):
        return "intro"
    if key.startswith("verse"):
        return "verse"
    if key.startswith("bridge"):
        return "down"
    if key.startswith("up") or key.startswith("build"):
        return "build"
    if key.startswith("chorus"):
        return "chorus"
    if key.startswith("drop"):
        return "drop"
    if key.startswith("down"):
        return "down"
    if key.startswith("break"):
        return "break"
    if key.startswith("outro"):
        return "outro"
    return "unknown"


def build_phrase_stage(phrase):
    key = normalize_phrase(phrase)
    if not (key.startswith("up") or key.startswith("build")):
        return None
    digits = "".join(ch for ch in key if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except (TypeError, ValueError):
        return None


def is_early_build_phrase(phrase):
    stage = build_phrase_stage(phrase)
    return stage is not None and stage <= 2


def waveform_analysis_from_samples(samples, now):
    if not samples:
        return None

    recent = [(ts, clamp_unit(value)) for ts, value in samples if now - ts <= 8.0]
    if not recent:
        return None

    def window_values(seconds):
        values = [value for ts, value in recent if now - ts <= seconds]
        return values or [recent[-1][1]]

    def average(values):
        return sum(values) / len(values) if values else 0.0

    short_values = window_values(0.85)
    mid_values = window_values(2.8)
    long_values = window_values(6.5)
    instant = recent[-1][1]
    short_avg = average(short_values)
    mid_avg = average(mid_values)
    long_avg = average(long_values)

    volatility_values = []
    transient = 0.0
    for index in range(1, len(short_values)):
        delta = short_values[index] - short_values[index - 1]
        volatility_values.append(abs(delta))
        transient = max(transient, delta)

    lift = short_avg - long_avg
    crest = short_avg - mid_avg
    volatility = clamp_unit(average(volatility_values) * 4.0) if volatility_values else 0.0
    sustained_high = short_avg >= 0.72 and mid_avg >= 0.60
    attack = transient >= 0.09 and instant >= 0.64 and lift >= 0.08
    calm = short_avg <= 0.26 and mid_avg <= 0.30 and volatility <= 0.08
    breakdown = short_avg <= 0.22 and mid_avg <= 0.28 and lift <= -0.07

    if sustained_high or attack or (short_avg >= 0.80 and lift >= 0.06):
        mood_hint = 1.0
    elif breakdown or calm:
        mood_hint = 3.0
    elif short_avg >= 0.52 or mid_avg >= 0.48 or lift >= 0.08:
        mood_hint = 2.0
    else:
        mood_hint = None

    return {
        "instant": instant,
        "short_avg": short_avg,
        "mid_avg": mid_avg,
        "long_avg": long_avg,
        "lift": lift,
        "crest": crest,
        "transient": transient,
        "volatility": volatility,
        "sustained_high": sustained_high,
        "attack": attack,
        "calm": calm,
        "breakdown": breakdown,
        "mood_hint": mood_hint,
    }


def refine_mood_with_waveform(mood, phrase=None, analysis=None):
    if not analysis:
        return mood

    section = phrase_bucket(phrase)
    base = None
    if mood is not None:
        try:
            base = min(3.0, max(1.0, float(mood)))
        except (TypeError, ValueError):
            base = None

    hint = analysis.get("mood_hint")
    if hint is None:
        return base

    short_avg = float(analysis.get("short_avg") or 0.0)
    mid_avg = float(analysis.get("mid_avg") or 0.0)
    lift = float(analysis.get("lift") or 0.0)
    transient = float(analysis.get("transient") or 0.0)
    calm = bool(analysis.get("calm"))
    breakdown = bool(analysis.get("breakdown"))
    sustained_high = bool(analysis.get("sustained_high"))
    attack = bool(analysis.get("attack"))

    target = None
    if section in ("intro", "down", "break", "outro") and (calm or breakdown):
        target = 3.0
    elif section == "verse":
        if sustained_high and (lift >= 0.10 or transient >= 0.08):
            target = 1.0
        elif breakdown and short_avg <= 0.20:
            target = 3.0
    elif section in ("build", "chorus", "drop"):
        if attack or sustained_high or short_avg >= 0.74 or mid_avg >= 0.62:
            target = 1.0
        elif breakdown and not attack:
            target = 2.0

    if target is None:
        return base

    if base is None:
        return target

    if target < base:
        return max(target, base - 1.0)
    if target > base:
        return min(target, base + 1.0)
    return base


def osc_waveform_band_profile(osc):
    audio_bands = osc.get("audio_bands") or {}
    preview_bands = osc.get("waveform_bands") or {}
    bands = (
        audio_bands
        if any(audio_bands.get(key) is not None for key in ("low", "mid", "high"))
        else preview_bands
    )

    def band_value(key):
        value = bands.get(key)
        if value is None:
            return None
        try:
            return clamp_unit(float(value))
        except (TypeError, ValueError):
            return None

    low = band_value("low")
    mid = band_value("mid")
    high = band_value("high")
    return {
        "low": low,
        "mid": mid,
        "high": high,
        "has_data": any(value is not None for value in (low, mid, high)),
        "low_focus": clamp_unit((low or 0.0) * 1.00 + (mid or 0.0) * 0.20),
        "mid_focus": clamp_unit((mid or 0.0) * 1.00 + (high or 0.0) * 0.18),
        "high_focus": clamp_unit((high or 0.0) * 1.00 + (mid or 0.0) * 0.12),
    }


def weighted_band_activity(profile):
    if not profile or not profile.get("has_data"):
        return None
    return clamp_unit(
        (profile.get("low") or 0.0) * 0.52
        + (profile.get("mid") or 0.0) * 0.30
        + (profile.get("high") or 0.0) * 0.18
    )


def osc_waveform_lookahead_profile(osc, beats_ahead):
    lookahead = osc.get("waveform_lookahead") or {}
    bands = lookahead.get(str(int(beats_ahead))) or {}

    def band_value(key):
        value = bands.get(key)
        if value is None:
            return None
        try:
            return clamp_unit(float(value))
        except (TypeError, ValueError):
            return None

    low = band_value("low")
    mid = band_value("mid")
    high = band_value("high")
    profile = {
        "low": low,
        "mid": mid,
        "high": high,
        "has_data": any(value is not None for value in (low, mid, high)),
        "beats_ahead": int(beats_ahead),
    }
    profile["activity"] = weighted_band_activity(profile)
    return profile


def osc_drum_profile(osc):
    audio_signals = osc.get("audio_drums") or {}
    preview_signals = osc.get("drum_signals") or {}
    signals = (
        audio_signals
        if any(
            audio_signals.get(key) is not None
            for key in ("kick", "snare", "hihat", "low_onset", "mid_onset", "high_onset")
        )
        else preview_signals
    )

    def signal_value(key):
        value = signals.get(key)
        if value is None:
            return 0.0
        try:
            return clamp_unit(float(value))
        except (TypeError, ValueError):
            return 0.0

    # Treat drum extraction as guidance, not a hard driver for the autoshow.
    kick = clamp_unit(max(signal_value("kick"), signal_value("low_onset")) * 0.72)
    snare = clamp_unit(max(signal_value("snare"), signal_value("mid_onset")) * 0.66)
    hihat = clamp_unit(max(signal_value("hihat"), signal_value("high_onset")) * 0.58)
    impact = clamp_unit(kick * 0.82 + snare * 0.48)
    motion = clamp_unit(kick * 0.28 + snare * 0.32 + hihat * 0.20)
    sparkle = clamp_unit(hihat * 0.42 + snare * 0.16)
    return {
        "kick": kick,
        "snare": snare,
        "hihat": hihat,
        "impact": impact,
        "motion": motion,
        "sparkle": sparkle,
        "percussive": max(kick, snare, hihat),
        "busy": clamp_unit(impact * 0.60 + sparkle * 0.40),
    }


def osc_dimmer_activity_profile(osc, drums=None):
    waveform = osc.get("waveform_analysis") or {}
    drums = drums or osc_drum_profile(osc)
    waveform_energy = osc.get("waveform_energy")
    try:
        waveform_energy = (
            None if waveform_energy is None else clamp_unit(float(waveform_energy))
        )
    except (TypeError, ValueError):
        waveform_energy = None

    short_avg = clamp_unit(float(waveform.get("short_avg") or 0.0))
    mid_avg = clamp_unit(float(waveform.get("mid_avg") or 0.0))
    transient = clamp_unit(float(waveform.get("transient") or 0.0) * 4.5)
    volatility = clamp_unit(float(waveform.get("volatility") or 0.0) * 4.0)
    impact = clamp_unit(float(drums.get("impact") or 0.0))
    motion = clamp_unit(float(drums.get("motion") or 0.0))
    sparkle = clamp_unit(float(drums.get("sparkle") or 0.0))

    activity = clamp_unit(
        (0.28 * short_avg)
        + (0.18 * mid_avg)
        + (0.16 * (waveform_energy if waveform_energy is not None else short_avg))
        + (0.14 * transient)
        + (0.08 * volatility)
        + (0.10 * impact)
        + (0.04 * motion)
        + (0.02 * sparkle)
    )
    calm = bool(waveform.get("calm")) or activity <= 0.28
    breakdown = bool(waveform.get("breakdown")) or activity <= 0.22
    active = activity >= 0.48
    peak = activity >= 0.66
    return {
        "activity": activity,
        "calm": calm,
        "breakdown": breakdown,
        "active": active,
        "peak": peak,
    }


def auto_show_style(style_name):
    return AUTO_SHOW_STYLES.get(style_name, AUTO_SHOW_STYLES["adaptive"])


def weighted_variant_pool(base_options, prefer=None, avoid=None, prefer_weight=3):
    avoid_set = {str(item) for item in (avoid or [])}
    filtered = [item for item in (base_options or []) if str(item) not in avoid_set]
    if not prefer:
        return filtered
    weighted = []
    for item in prefer:
        if str(item) in avoid_set:
            continue
        weighted.extend([item] * prefer_weight)
    weighted.extend(filtered)
    return weighted or list(base_options or [])


def auto_show_style_variant_pool(style_name, category, section, base_options):
    rules = AUTO_SHOW_STYLE_VARIANT_RULES.get(style_name, {})
    category_rules = rules.get(category, {})
    wildcard = category_rules.get("*", {})
    specific = category_rules.get(section, {})
    prefer = list(wildcard.get("prefer", [])) + list(specific.get("prefer", []))
    avoid = list(wildcard.get("avoid", [])) + list(specific.get("avoid", []))
    weight = int(specific.get("prefer_weight") or wildcard.get("prefer_weight") or 3)
    return weighted_variant_pool(base_options, prefer=prefer, avoid=avoid, prefer_weight=weight)


def auto_show_profile(section):
    return AUTO_SHOW_SECTIONS.get(section, AUTO_SHOW_SECTIONS["unknown"])


def auto_show_effective_section(
    section,
    osc,
    waveform_factor=None,
    waveform_bands=None,
    waveform_lookahead_2=None,
    waveform_lookahead_4=None,
    drum_profile=None,
    waveform_analysis=None,
):
    if section != "outro":
        return section

    activity = auto_show_outro_activity_score(
        osc,
        waveform_factor=waveform_factor,
        waveform_bands=waveform_bands,
        waveform_lookahead_2=waveform_lookahead_2,
        waveform_lookahead_4=waveform_lookahead_4,
        drum_profile=drum_profile,
        waveform_analysis=waveform_analysis,
    )
    return auto_show_outro_bucket_for_activity(activity)


def auto_show_outro_activity_score(
    osc,
    waveform_factor=None,
    waveform_bands=None,
    waveform_lookahead_2=None,
    waveform_lookahead_4=None,
    drum_profile=None,
    waveform_analysis=None,
):
    waveform_bands = waveform_bands or osc_waveform_band_profile(osc)
    waveform_lookahead_2 = waveform_lookahead_2 or osc_waveform_lookahead_profile(osc, 2)
    waveform_lookahead_4 = waveform_lookahead_4 or osc_waveform_lookahead_profile(osc, 4)
    drum_profile = drum_profile or osc_drum_profile(osc)
    analysis = waveform_analysis or osc.get("waveform_analysis") or {}

    def optional_unit(value):
        if value is None:
            return None
        try:
            return clamp_unit(float(value))
        except (TypeError, ValueError):
            return None

    activity_sum = 0.0
    weight_sum = 0.0

    def add_component(value, weight):
        nonlocal activity_sum, weight_sum
        unit = optional_unit(value)
        if unit is None:
            return
        activity_sum += unit * weight
        weight_sum += weight

    add_component(waveform_factor, 0.34)
    add_component(analysis.get("short_avg"), 0.24)
    add_component(analysis.get("mid_avg"), 0.18)
    add_component((waveform_bands or {}).get("low"), 0.08)
    add_component((waveform_bands or {}).get("mid"), 0.07)
    add_component((waveform_bands or {}).get("high"), 0.05)
    add_component((waveform_lookahead_2 or {}).get("activity"), 0.07)
    add_component((waveform_lookahead_4 or {}).get("activity"), 0.04)
    add_component((drum_profile or {}).get("impact"), 0.10)
    add_component((drum_profile or {}).get("motion"), 0.06)

    activity = activity_sum / weight_sum if weight_sum > 0.0 else 0.0
    activity = clamp_unit(
        activity
        + (0.05 if analysis.get("sustained_high") else 0.0)
        + (0.03 if analysis.get("attack") else 0.0)
        - (0.05 if analysis.get("calm") else 0.0)
        - (0.07 if analysis.get("breakdown") else 0.0)
    )

    return activity


def auto_show_outro_bucket_for_activity(activity):
    activity = clamp_unit(activity)
    if activity >= 0.76:
        return "chorus"
    if activity >= 0.62:
        return "build"
    if activity >= 0.52:
        return "verse"
    return "outro"


def auto_show_color_source(style_name, section, osc):
    preferred = auto_show_style(style_name)["preferred_color_source"]
    has_phrase = bool(osc.get("phrase_current"))
    has_mood = osc.get("mood") is not None
    has_bank = osc.get("color_bank") in COLOR_BANKS

    if preferred == "color_bank" and has_bank:
        return "color_bank"
    if preferred == "mood" and has_mood:
        return "mood"
    if preferred == "manual":
        return "manual"

    if section in ("chorus", "drop") and has_bank:
        return "color_bank"
    if section in ("build", "chorus", "drop") and has_phrase:
        return "phrase"
    if section in ("verse", "down", "break") and has_mood:
        return "mood"
    if has_phrase:
        return "phrase"
    if has_mood:
        return "mood"
    if has_bank:
        return "color_bank"
    return "manual"


def auto_show_manual_color(style_name, section, osc):
    scene = auto_show_scene_variants(style_name, section, osc)
    color_profile = auto_show_color_profile(scene["color_profile_name"])
    pair_a = color_profile["primary"]
    pair_b = color_profile["secondary"]
    pair_mix = mix_rgbw(pair_a, pair_b, 0.5)

    if style_name == "warm":
        palette = {
            "intro": mix_rgbw(pair_a, (255, 130, 40, 0), 0.40),
            "verse": mix_rgbw(pair_a, (255, 165, 65, 0), 0.42),
            "build": mix_rgbw(pair_a, (255, 200, 55, 0), 0.45),
            "chorus": mix_rgbw(pair_mix, (255, 120, 70, 30), 0.50),
            "drop": mix_rgbw(pair_mix, (255, 220, 170, 255), 0.55),
            "break": mix_rgbw(pair_b, (255, 115, 55, 0), 0.32),
            "outro": mix_rgbw(pair_a, (255, 110, 45, 0), 0.40),
            "unknown": mix_rgbw(pair_mix, (255, 150, 55, 0), 0.40),
        }
        return palette.get(section, palette["unknown"])

    if style_name == "festival":
        palette = {
            "intro": mix_rgbw(pair_mix, (80, 130, 255, 0), 0.46),
            "verse": mix_rgbw(pair_mix, (255, 70, 170, 0), 0.42),
            "build": mix_rgbw(pair_a, (255, 80, 60, 0), 0.44),
            "chorus": mix_rgbw(pair_b, (255, 60, 210, 18), 0.50),
            "drop": mix_rgbw(pair_mix, (255, 235, 255, 255), 0.62),
            "break": mix_rgbw(pair_b, (80, 140, 255, 0), 0.42),
            "outro": mix_rgbw(pair_mix, (255, 95, 150, 0), 0.42),
            "unknown": mix_rgbw(pair_mix, (180, 90, 255, 0), 0.46),
        }
        return palette.get(section, palette["unknown"])

    if style_name == "minimal":
        palette = {
            "intro": mix_rgbw(pair_b, (60, 95, 170, 0), 0.44),
            "verse": mix_rgbw(pair_mix, (70, 110, 150, 0), 0.40),
            "build": mix_rgbw(pair_a, (160, 150, 120, 0), 0.28),
            "chorus": mix_rgbw(pair_b, (150, 145, 210, 8), 0.36),
            "drop": mix_rgbw(pair_mix, (210, 220, 245, 120), 0.44),
            "break": mix_rgbw(pair_b, (55, 85, 165, 0), 0.46),
            "outro": mix_rgbw(pair_mix, (95, 105, 135, 0), 0.38),
            "unknown": mix_rgbw(pair_mix, (90, 120, 155, 0), 0.40),
        }
        return palette.get(section, palette["unknown"])

    if style_name == "cinematic":
        palette = {
            "intro": mix_rgbw(pair_b, (55, 90, 180, 0), 0.52),
            "verse": mix_rgbw(pair_mix, (60, 150, 125, 0), 0.46),
            "build": mix_rgbw(pair_a, (255, 180, 65, 0), 0.35),
            "chorus": mix_rgbw(pair_b, (210, 110, 255, 20), 0.46),
            "drop": mix_rgbw(pair_mix, (220, 235, 255, 255), 0.58),
            "break": mix_rgbw(pair_b, (50, 80, 190, 0), 0.54),
            "outro": mix_rgbw(pair_mix, (90, 95, 150, 0), 0.44),
            "unknown": mix_rgbw(pair_mix, (85, 125, 190, 0), 0.48),
        }
        return palette.get(section, palette["unknown"])

    if style_name == "club":
        return (
            COLOR_BANKS.get(osc.get("color_bank"))
            or mix_rgbw(pair_a, pair_b, 0.35)
            or color_for_phrase(osc.get("phrase_current"))
            or pair_a
        )

    return (
        mix_rgbw(
            color_for_phrase(osc.get("phrase_current"))
            or color_for_mood(osc.get("mood"))
            or COLOR_BANKS.get(osc.get("color_bank"))
            or COLOR_PRESETS["mid"],
            pair_mix,
            0.24,
        )
    )


def auto_show_section_accent(section):
    palette = {
        "intro": (255, 175, 110, 0),
        "verse": (45, 210, 165, 0),
        "build": (255, 185, 35, 0),
        "chorus": (255, 80, 200, 0),
        "drop": (255, 90, 200, 0),
        "break": (95, 100, 255, 0),
        "outro": (255, 140, 75, 24),
        "unknown": (95, 215, 185, 20),
    }
    return palette.get(section, palette["unknown"])


def auto_show_color_profile(name):
    return AUTO_SHOW_COLOR_PROFILES.get(name, AUTO_SHOW_COLOR_PROFILES["yellow_blue"])


def osc_track_identity(osc):
    title = str(osc.get("track_title") or "").strip()
    artist = str(osc.get("track_artist") or "").strip()
    album = str(osc.get("track_album") or "").strip()
    meaningful = [value for value in (title, artist, album) if value and value != "-"]
    if meaningful:
        return track_preview_identity(title, artist, album)
    return "|".join(
        [
            "fallback",
            str(round(float(osc.get("bpm") or 0.0))),
            str(int(round(float(osc.get("mood") or 0.0))) if osc.get("mood") is not None else ""),
            str(int(round(float(osc.get("color_bank") or 0.0))) if osc.get("color_bank") is not None else ""),
        ]
    )


def auto_show_track_theme(theme_name):
    return TRACK_SHOW_THEMES.get(theme_name, TRACK_SHOW_THEMES[TRACK_SHOW_THEME_SEQUENCE[0]])


def track_show_theme_for_identity(identity):
    theme_name = TRACK_SHOW_THEME_SEQUENCE[
        stable_hash(identity) % max(1, len(TRACK_SHOW_THEME_SEQUENCE))
    ]
    return theme_name, auto_show_track_theme(theme_name)


def track_show_theme_for_osc(osc):
    identity = osc_track_identity(osc)
    return track_show_theme_for_identity(identity)


def osc_track_signature(osc):
    return "|".join(
        [
            osc_track_identity(osc),
            str(round(float(osc.get("bpm") or 0.0))),
            str(phrase_bucket(osc.get("phrase_current"))),
        ]
    )


def auto_show_scene_selection(
    style_name,
    section,
    track_signature,
    theme_name,
    bpm_bucket=0,
    mood_bucket=0,
    scene_window=0,
    motion_window=0,
    mirror_window=0,
    color_window=0,
    texture_window=0,
    wash_window=0,
):
    theme = auto_show_track_theme(theme_name)
    base_seed = stable_hash(
        f"{track_signature}|{style_name}|{section}|{theme_name}|{bpm_bucket}|{mood_bucket}"
    )

    theme_motion_options = (
        ((theme.get("motions") or {}).get(section, []))
        if isinstance(theme.get("motions"), dict)
        else []
    )
    theme_pulse_options = (
        ((theme.get("pulses") or {}).get(section, []))
        if isinstance(theme.get("pulses"), dict)
        else []
    )
    look_options = merge_variant_pools(
        theme.get("looks"),
        AUTO_SHOW_LOOK_POOLS.get(section, AUTO_SHOW_LOOK_POOLS["unknown"]),
    )
    color_options = merge_variant_pools(
        theme.get("color_profiles"),
        AUTO_SHOW_COLOR_PROFILE_POOLS.get(section, AUTO_SHOW_COLOR_PROFILE_POOLS["unknown"]),
    )
    accent_options = merge_variant_pools(
        theme.get("accents"),
        AUTO_SHOW_ACCENT_POOLS.get(section, AUTO_SHOW_ACCENT_POOLS["unknown"]),
    )
    texture_options = merge_variant_pools(
        theme.get("textures"),
        AUTO_SHOW_TEXTURE_POOLS.get(section, AUTO_SHOW_TEXTURE_POOLS["unknown"]),
    )
    motion_options = merge_variant_pools(
        theme_motion_options,
        AUTO_SHOW_MOTION_POOLS.get(section, AUTO_SHOW_MOTION_POOLS["unknown"]),
    )
    pulse_options = merge_variant_pools(
        theme_pulse_options,
        AUTO_SHOW_PULSE_POOLS.get(section, AUTO_SHOW_PULSE_POOLS["unknown"]),
    )
    wash_options = AUTO_SHOW_WASH_CUE_POOLS.get(section, AUTO_SHOW_WASH_CUE_POOLS["unknown"])

    look_options = auto_show_style_variant_pool(style_name, "looks", section, look_options)
    color_options = auto_show_style_variant_pool(style_name, "color_profiles", section, color_options)
    accent_options = auto_show_style_variant_pool(style_name, "accents", section, accent_options)
    texture_options = auto_show_style_variant_pool(style_name, "textures", section, texture_options)
    motion_options = auto_show_style_variant_pool(style_name, "motions", section, motion_options)
    pulse_options = auto_show_style_variant_pool(style_name, "pulses", section, pulse_options)
    wash_options = auto_show_style_variant_pool(style_name, "washes", section, wash_options)

    look_name = pick_variant(
        look_options,
        base_seed + scene_window,
        "bank_echo",
    )
    pulse_name = pick_variant(
        pulse_options,
        (base_seed >> 5) + scene_window,
        "medium",
    )
    accent_name = pick_variant(
        accent_options,
        (base_seed >> 11) + scene_window,
        "center",
    )
    color_profile_name = pick_variant(
        color_options,
        (base_seed >> 13) + color_window,
        "yellow_blue",
    )
    motion_name = pick_variant(
        motion_options,
        (base_seed >> 17) + motion_window,
        "center",
    )
    wash_cue_name = pick_variant(
        wash_options,
        (base_seed >> 29) + wash_window,
        "soft_blue_wash",
    )
    texture_name = pick_variant(
        texture_options,
        (base_seed >> 19) + texture_window,
        "steady",
    )
    mirror_seed_unit = (((base_seed >> 23) + mirror_window) % 1000) / 999.0
    mirror_threshold = clamp_unit(
        float(theme.get("mirror_bias", 0.20))
        * {
            "intro": 0.55,
            "verse": 0.80,
            "build": 1.00,
            "chorus": 1.00,
            "drop": 0.82,
            "down": 0.72,
            "break": 0.60,
            "outro": 0.55,
            "unknown": 0.76,
        }.get(section, 0.76)
    )
    mirror_within_group = (
        motion_name in AUTO_SHOW_MEMBER_MIRROR_MOTIONS
        and mirror_seed_unit <= mirror_threshold
    )

    return {
        "theme_name": theme_name,
        "theme_label": theme["label"],
        "look_name": look_name,
        "look_label": titleize_variant(look_name),
        "color_profile_name": color_profile_name,
        "color_profile_label": auto_show_color_profile(color_profile_name)["label"],
        "motion_name": motion_name,
        "motion_label": titleize_variant(motion_name),
        "wash_cue_name": wash_cue_name,
        "wash_cue_label": auto_show_wall_wash_cue(wash_cue_name)["label"],
        "texture_name": texture_name,
        "texture_label": titleize_variant(texture_name),
        "mirror_within_group": mirror_within_group,
        "pulse_name": pulse_name,
        "accent_name": accent_name,
        "scene_window": scene_window,
        "motion_window": motion_window,
        "mirror_window": mirror_window,
        "color_window": color_window,
        "texture_window": texture_window,
        "wash_window": wash_window,
        "track_signature": track_signature,
    }


def auto_show_scene_variants(style_name, section, osc):
    beat_value = float(osc.get("beat_value") or 0.0)
    track_signature = osc_track_signature(osc)
    theme_name, _theme = track_show_theme_for_osc(osc)
    scene_window = int(beat_value // 64.0)
    motion_window_size = {
        "intro": 128.0,
        "verse": 128.0,
        "build": 96.0,
        "chorus": 96.0,
        "drop": 64.0,
        "down": 128.0,
        "break": 128.0,
        "outro": 128.0,
        "unknown": 128.0,
    }.get(section, 128.0)
    motion_window = int(beat_value // motion_window_size)
    mirror_window = int(beat_value // 128.0)
    color_window = int(beat_value // 32.0)
    texture_window = int(beat_value // 32.0)
    wash_window_size = {
        "intro": 64.0,
        "verse": 64.0,
        "build": 32.0,
        "chorus": 32.0,
        "drop": 16.0,
        "down": 64.0,
        "break": 64.0,
        "outro": 64.0,
        "unknown": 64.0,
    }.get(section, 64.0)
    wash_window = int(beat_value // wash_window_size)
    bpm_bucket = int(round(float(osc.get("bpm") or 0.0) / 4.0))
    mood_bucket = (
        int(round(float(osc.get("mood") or 0.0))) if osc.get("mood") is not None else 0
    )
    return auto_show_scene_selection(
        style_name,
        section,
        track_signature,
        theme_name,
        bpm_bucket=bpm_bucket,
        mood_bucket=mood_bucket,
        scene_window=scene_window,
        motion_window=motion_window,
        mirror_window=mirror_window,
        color_window=color_window,
        texture_window=texture_window,
        wash_window=wash_window,
    )


def auto_show_motion_profile(name):
    return AUTO_SHOW_MOTION_PROFILES.get(name, AUTO_SHOW_MOTION_PROFILES["center"])


def auto_show_wall_wash_cue(name):
    return WALL_WASH_CUES.get(name, WALL_WASH_CUES["soft_blue_wash"])


def live_override_color_name(value):
    key = str(value or "none").strip().lower()
    return key if key in LIVE_OVERRIDE_COLORS else "none"


def live_override_color_label(value):
    labels = {
        "none": "Auto",
        "red": "Red",
        "yellow": "Yellow",
        "green": "Green",
        "lime": "Lime",
        "purple": "Purple",
        "pink": "Pink",
        "cyan": "Cyan",
        "orange": "Orange",
        "blue": "Blue",
        "white": "White",
        "rainbow": "Rainbow",
    }
    return labels.get(live_override_color_name(value), "Auto")


def live_override_energy_name(value):
    key = str(value or "none").strip().lower()
    return key if key in {"none", "low", "mid", "high"} else "none"


def live_override_energy_label(value):
    labels = {
        "none": "Auto",
        "low": "Low",
        "mid": "Mid",
        "high": "High",
    }
    return labels.get(live_override_energy_name(value), "Auto")


ONE_SHOT_CUES = {
    "audience_riser": {
        "label": "Audience Rise",
        "duration_beats": 16.0,
    },
    "white_hit": {
        "label": "White Hit",
        "duration_beats": 4.0,
    },
    "color_burst": {
        "label": "Color Burst",
        "duration_beats": 4.0,
    },
    "snap_fan": {
        "label": "Snap Fan",
        "duration_beats": 4.0,
    },
    "mirror_bounce": {
        "label": "Mirror Bounce",
        "duration_beats": 8.0,
    },
    "par_chase_burst": {
        "label": "PAR Chase",
        "duration_beats": 8.0,
    },
}


def one_shot_cue_name(value):
    key = str(value or "").strip().lower()
    return key if key in ONE_SHOT_CUES else "none"


def one_shot_cue_label(value):
    cue_name = one_shot_cue_name(value)
    if cue_name == "none":
        return "None"
    return ONE_SHOT_CUES[cue_name]["label"]


def one_shot_cue_definition(value):
    cue_name = one_shot_cue_name(value)
    if cue_name == "none":
        return None
    return ONE_SHOT_CUES[cue_name]


def apply_live_energy_override(level, value, *, low_target, mid_target, high_target, mix=0.68):
    name = live_override_energy_name(level)
    targets = {
        "low": low_target,
        "mid": mid_target,
        "high": high_target,
    }
    target = targets.get(name)
    if target is None:
        return clamp_unit(value)
    return clamp_unit(value * (1.0 - mix) + target * mix)


def auto_show_refined_mood_factor(level, mood_factor):
    return apply_live_energy_override(
        level,
        mood_factor,
        low_target=0.22,
        mid_target=0.50,
        high_target=0.82,
        mix=0.74,
    )


def auto_show_refined_pulse_name(section, pulse_name, style_name, osc, mood_factor, energy, override_energy="none"):
    beat_value = float(osc.get("beat_value") or 0.0)
    scene_window = int(beat_value // 64.0)
    even_window = scene_window % 2 == 0
    rare_window = scene_window % 4 == 3
    early_build = is_early_build_phrase(osc.get("phrase_current"))
    waveform = osc.get("waveform_analysis") or {}
    drums = osc_drum_profile(osc)
    attack = bool(waveform.get("attack"))
    sustained_high = bool(waveform.get("sustained_high"))
    calm = bool(waveform.get("calm"))
    breakdown = bool(waveform.get("breakdown"))
    transient = float(waveform.get("transient") or 0.0)
    kick = float(drums.get("kick") or 0.0)
    snare = float(drums.get("snare") or 0.0)
    hihat = float(drums.get("hihat") or 0.0)
    impact = float(drums.get("impact") or 0.0)
    percussive = float(drums.get("percussive") or 0.0)
    activity = osc_dimmer_activity_profile(osc, drums)
    high_mood = mood_factor >= 0.78
    peak_mood = mood_factor >= 0.90
    high_energy = energy >= 0.80
    peak_energy = energy >= 0.995
    override_energy = live_override_energy_name(override_energy)
    low_override = override_energy == "low"
    high_override = override_energy == "high"

    quiet_modes = {"low_glow", "medium", "slow_fade_in", "slow_fade_out", "breathing", "soft_pulse"}
    active_modes = {"strong_pulse", "beat_flash", "offbeat_flash", "drop_blinder", "blackout_hit", "ramp_up", "ramp_down", "tremolo_dimmer", "alternate_whole", "double_hit", "gallop", "pivot", "chase", "snake", "full_on"}

    if style_name == "festival":
        if pulse_name in {"breathing", "slow_fade_in", "slow_fade_out"}:
            pulse_name = "alternate_whole" if section in {"build", "chorus", "drop"} else "offbeat_flash"
        elif pulse_name == "soft_pulse" and section in {"build", "chorus", "drop"}:
            pulse_name = "beat_flash"
    elif style_name == "minimal":
        if pulse_name in {"snake", "chase", "drop_blinder", "blackout_hit", "gallop", "tremolo_dimmer"}:
            pulse_name = "alternate_whole" if section in {"build", "chorus", "drop"} else "soft_pulse"
        elif pulse_name == "double_hit" and section != "drop":
            pulse_name = "pivot"
    elif style_name == "cinematic":
        if pulse_name in {"snake", "chase", "drop_blinder", "blackout_hit", "gallop", "tremolo_dimmer"}:
            pulse_name = "pivot" if section in {"build", "chorus", "drop"} else "soft_pulse"
        elif pulse_name == "double_hit" and section != "drop":
            pulse_name = "alternate_whole"
    elif style_name == "warm":
        if pulse_name in {"snake", "chase", "tremolo_dimmer", "blackout_hit"}:
            pulse_name = "double_hit" if section in {"chorus", "drop"} else "alternate_whole"
        elif pulse_name == "gallop":
            pulse_name = "double_hit"
    elif style_name == "club":
        if section in {"build", "chorus", "drop"} and pulse_name in {"breathing", "slow_fade_in", "slow_fade_out"}:
            pulse_name = "alternate_whole"

    if low_override:
        if section == "intro":
            return "soft_pulse"
        if section == "outro":
            return "slow_fade_out" if even_window else "breathing"
        if section in {"down", "break"}:
            return "breathing" if even_window else "soft_pulse"
        if section == "verse":
            return "soft_pulse"
        if section == "build":
            return "breathing" if early_build or calm or breakdown else "soft_pulse"
        if section == "chorus":
            return "alternate_whole" if activity["active"] or snare >= 0.42 else "soft_pulse"
        if section == "drop":
            return "alternate_whole" if activity["active"] or impact >= 0.42 else "soft_pulse"

    if high_override and pulse_name in quiet_modes:
        if section == "build":
            pulse_name = "ramp_up" if early_build else ("double_hit" if snare >= 0.42 else "chase")
        elif section == "chorus":
            pulse_name = "double_hit" if snare >= 0.46 else ("gallop" if hihat >= 0.44 else "chase")
        elif section == "drop":
            pulse_name = "drop_blinder" if impact >= 0.52 else ("snake" if kick >= 0.46 else "chase")

    if section == "intro":
        if pulse_name in {"slow_fade_in", "soft_pulse", "offbeat_flash"}:
            return pulse_name
        return "soft_pulse"

    if section == "outro":
        if breakdown or calm:
            return "slow_fade_out" if even_window else "breathing"
        if (high_mood and transient >= 0.09 and rare_window) or (snare >= 0.58 and rare_window):
            return "offbeat_flash"
        if pulse_name in {"slow_fade_out", "breathing", "soft_pulse", "offbeat_flash"}:
            return pulse_name
        return "soft_pulse"

    if section == "down":
        if breakdown or calm:
            return "breathing" if even_window else "soft_pulse"
        if (high_mood and transient >= 0.09 and rare_window) or (hihat >= 0.54 and rare_window):
            return "offbeat_flash"
        if pulse_name in {"breathing", "soft_pulse", "offbeat_flash", "slow_fade_out"}:
            return pulse_name
        return "soft_pulse"

    if section == "break":
        if breakdown or calm:
            return "slow_fade_out" if even_window else "breathing"
        if (high_mood and transient >= 0.09 and rare_window) or (hihat >= 0.56 and rare_window):
            return "offbeat_flash"
        if pulse_name in {"breathing", "slow_fade_out", "soft_pulse", "offbeat_flash"}:
            return pulse_name
        return "breathing"

    if section == "verse":
        if breakdown or calm:
            return "soft_pulse"
        if snare >= 0.60 and rare_window:
            return "offbeat_flash"
        if pulse_name in {"breathing", "soft_pulse", "offbeat_flash"}:
            return pulse_name
        return "soft_pulse"

    if section == "build":
        if activity["breakdown"]:
            return "soft_pulse"
        if activity["calm"] and not attack:
            if high_override:
                return "ramp_up" if early_build else ("double_hit" if snare >= 0.24 else "chase")
            return "breathing" if early_build and even_window else "soft_pulse"
        if early_build and not activity["peak"]:
            if pulse_name in {"chase", "snake", "strong_pulse", "beat_flash", "tremolo_dimmer", "drop_blinder", "double_hit", "gallop"}:
                if activity["active"] or attack or kick >= 0.46 or snare >= 0.46:
                    return "ramp_up"
                return "breathing"
        if peak_mood and peak_energy and (attack or sustained_high or kick >= 0.58):
            return "drop_blinder"
        if not activity["active"] and pulse_name in {"chase", "snake", "strong_pulse", "beat_flash", "ramp_up", "double_hit", "gallop", "pivot"}:
            if high_override:
                return "ramp_up" if early_build else ("double_hit" if snare >= 0.24 else "chase")
            return "breathing" if early_build else "soft_pulse"
        if kick >= 0.60 and snare >= 0.48:
            return "chase" if even_window else "ramp_up"
        if snare >= 0.58:
            return "double_hit" if hihat >= 0.36 else "strong_pulse"
        if hihat >= 0.56 and (not early_build or activity["peak"] or attack):
            return "gallop" if kick >= 0.34 else "offbeat_flash"
        if high_mood and high_energy and attack:
            return pulse_name if pulse_name in active_modes else "ramp_up"
        if early_build and not activity["peak"] and pulse_name == "ramp_up":
            return "soft_pulse"
        if pulse_name in {"ramp_up", "strong_pulse", "soft_pulse", "breathing"}:
            return pulse_name
        return "ramp_up"

    if section == "chorus":
        if breakdown and not peak_mood:
            return "soft_pulse"
        if activity["breakdown"]:
            return "breathing"
        if activity["calm"] and not sustained_high:
            if high_override:
                return "alternate_whole" if kick < 0.24 and snare < 0.24 else ("double_hit" if snare >= hihat else "chase")
            return "soft_pulse"
        if not activity["active"] and pulse_name in {"chase", "snake", "beat_flash", "strong_pulse", "double_hit", "gallop", "pivot"}:
            if high_override:
                return "alternate_whole" if kick < 0.24 and snare < 0.24 else ("double_hit" if snare >= hihat else "chase")
            return "soft_pulse"
        if kick >= 0.56 and snare >= 0.48:
            return "gallop" if hihat >= 0.44 else ("chase" if even_window else "snake")
        if snare >= 0.60:
            return "double_hit"
        if hihat >= 0.54:
            return "pivot" if kick >= 0.36 else "offbeat_flash"
        if high_mood and high_energy and (attack or sustained_high):
            return pulse_name if pulse_name in {"chase", "snake", "beat_flash", "offbeat_flash", "strong_pulse", "alternate_whole", "double_hit", "gallop", "pivot"} else "beat_flash"
        if pulse_name in {"soft_pulse", "offbeat_flash", "beat_flash", "alternate_whole", "double_hit", "gallop", "pivot"}:
            return pulse_name
        return "soft_pulse"

    if section == "drop":
        if activity["breakdown"]:
            return "soft_pulse"
        if activity["calm"] and not peak_energy:
            if high_override:
                return "alternate_whole" if impact < 0.28 else ("snake" if kick >= 0.28 else "beat_flash")
            return "breathing"
        if not activity["active"] and pulse_name in {"snake", "chase", "beat_flash", "tremolo_dimmer", "drop_blinder", "double_hit", "gallop", "pivot"}:
            if high_override:
                return "alternate_whole" if impact < 0.28 else ("snake" if kick >= 0.28 else "chase")
            return "soft_pulse"
        if peak_mood and peak_energy and (attack or sustained_high or impact >= 0.56):
            return pulse_name if pulse_name in {"drop_blinder", "blackout_hit", "beat_flash", "snake", "chase", "tremolo_dimmer", "double_hit", "gallop", "pivot"} else "drop_blinder"
        if kick >= 0.62 and snare >= 0.46:
            return "gallop" if hihat >= 0.40 else "snake"
        if kick >= 0.58:
            return "drop_blinder"
        if snare >= 0.58:
            return "double_hit"
        if hihat >= 0.56:
            return "pivot"
        if high_mood and high_energy:
            return pulse_name if pulse_name in active_modes else "beat_flash"
        return "full_on"

    if percussive >= 0.62 and pulse_name not in quiet_modes:
        return "chase"
    if pulse_name in quiet_modes or pulse_name in active_modes:
        return pulse_name
    return "soft_pulse"


def auto_show_refined_motion_name(section, motion_name, style_name, osc, energy, movement, override_energy="none"):
    if section != "build":
        return motion_name

    beat_value = float(osc.get("beat_value") or 0.0)
    motion_window = int(beat_value // 32.0)
    early_build = is_early_build_phrase(osc.get("phrase_current"))
    waveform = osc.get("waveform_analysis") or {}
    drums = osc_drum_profile(osc)
    activity = osc_dimmer_activity_profile(osc, drums)
    kick = float(drums.get("kick") or 0.0)
    snare = float(drums.get("snare") or 0.0)
    hihat = float(drums.get("hihat") or 0.0)
    transient = float(waveform.get("transient") or 0.0)
    attack = bool(waveform.get("attack"))
    override_energy = live_override_energy_name(override_energy)
    low_override = override_energy == "low"
    high_override = override_energy == "high"

    calm_variants = [
        "build_rising_sweep",
        "build_narrow_to_wide_fan",
        "build_audience_wave",
    ]
    mid_variants = [
        "build_rising_sweep",
        "build_narrow_to_wide_fan",
        "build_audience_wave",
        "build_fastening_circle",
        "build_color_chase",
    ]
    aggressive_variants = {"build_strobe_ramp", "build_white_flash_prep"}
    flashy_variants = aggressive_variants | {"build_dimmer_pulse", "build_fastening_circle", "build_color_chase"}

    if style_name == "festival":
        calm_variants = [
            "build_audience_wave",
            "build_rising_sweep",
            "build_fastening_circle",
        ]
        mid_variants = [
            "build_fastening_circle",
            "build_color_chase",
            "build_audience_wave",
            "build_rising_sweep",
            "build_dimmer_pulse",
        ]
    elif style_name == "minimal":
        calm_variants = [
            "build_rising_sweep",
            "build_narrow_to_wide_fan",
            "build_audience_wave",
        ]
        mid_variants = [
            "build_rising_sweep",
            "build_narrow_to_wide_fan",
            "build_audience_wave",
            "build_fastening_circle",
        ]
        aggressive_variants = {"build_strobe_ramp", "build_white_flash_prep", "build_color_chase"}
        flashy_variants = aggressive_variants | {"build_dimmer_pulse", "build_fastening_circle"}
    elif style_name == "cinematic":
        calm_variants = [
            "build_rising_sweep",
            "build_narrow_to_wide_fan",
            "build_fastening_circle",
        ]
        mid_variants = [
            "build_rising_sweep",
            "build_narrow_to_wide_fan",
            "build_fastening_circle",
            "build_audience_wave",
        ]
        aggressive_variants = {"build_strobe_ramp", "build_white_flash_prep", "build_color_chase"}
        flashy_variants = aggressive_variants | {"build_dimmer_pulse"}
    elif style_name == "warm":
        calm_variants = [
            "build_rising_sweep",
            "build_narrow_to_wide_fan",
            "build_audience_wave",
        ]
        mid_variants = [
            "build_rising_sweep",
            "build_narrow_to_wide_fan",
            "build_audience_wave",
            "build_fastening_circle",
        ]
        aggressive_variants = {"build_strobe_ramp", "build_white_flash_prep"}
        flashy_variants = aggressive_variants | {"build_dimmer_pulse", "build_color_chase"}
    elif style_name == "club":
        calm_variants = [
            "build_audience_wave",
            "build_rising_sweep",
            "build_fastening_circle",
        ]
        mid_variants = [
            "build_audience_wave",
            "build_fastening_circle",
            "build_color_chase",
            "build_rising_sweep",
            "build_dimmer_pulse",
        ]

    calm_choice = calm_variants[motion_window % len(calm_variants)]
    mid_choice = mid_variants[motion_window % len(mid_variants)]

    if low_override:
        return calm_choice if early_build or activity["calm"] or not activity["active"] else mid_choice
    if high_override and motion_name in flashy_variants and not (attack or kick >= 0.42 or snare >= 0.42 or movement >= 0.58 or energy >= 0.68):
        return mid_choice

    if activity["breakdown"]:
        return calm_choice
    if activity["calm"] and not attack:
        return calm_choice
    if early_build and not activity["peak"] and motion_name in flashy_variants:
        return calm_choice if not activity["active"] else mid_choice
    if not activity["active"] and motion_name in flashy_variants:
        return mid_choice if (kick >= 0.42 or snare >= 0.42 or transient >= 0.09) else calm_choice
    if motion_name in aggressive_variants and not (attack or kick >= 0.56 or snare >= 0.56 or hihat >= 0.62 or movement >= 0.72 or energy >= 0.82):
        return mid_choice
    return motion_name


def auto_show_par_rhythm_mode(section, base_mode, style_name, osc, slot_context, override_energy="none"):
    activity = osc_dimmer_activity_profile(osc)
    override_energy = live_override_energy_name(override_energy)
    low_override = override_energy == "low"
    high_override = override_energy == "high"
    if low_override:
        if section == "drop":
            return "pair_hold" if activity["active"] else "breathing"
        if section in {"build", "chorus"}:
            return "pair_hold" if activity["active"] else "soft_pulse"
        if section in {"break", "down", "outro"}:
            return "breathing"
        if section == "verse":
            return "soft_pulse"
    elif high_override:
        if section == "build" and base_mode in {"soft_pulse", "breathing", "slow_fade_out", "slow_fade_in", "medium"}:
            base_mode = "pair_swap"
        elif section == "chorus" and base_mode in {"soft_pulse", "breathing", "medium", "full_on"}:
            base_mode = "pair_swap"
        elif section == "drop" and base_mode in {"soft_pulse", "breathing", "medium", "full_on"}:
            base_mode = "pair_bounce"
    if style_name == "festival":
        if section in {"build", "chorus", "drop"} and base_mode in {"soft_pulse", "breathing", "slow_fade_out"}:
            base_mode = "pair_swap"
        if base_mode in {"pair_hold", "alternate_whole"} and section == "drop":
            base_mode = "pair_bounce"
    elif style_name == "minimal":
        if base_mode in {"snake", "chase", "tremolo_dimmer", "gallop", "drop_blinder", "blackout_hit"}:
            base_mode = "pair_hold" if section in {"build", "chorus", "drop"} else "soft_pulse"
        elif base_mode == "double_hit" and section != "drop":
            base_mode = "pair_hold"
    elif style_name == "cinematic":
        if base_mode in {"snake", "chase", "tremolo_dimmer", "gallop", "drop_blinder", "blackout_hit"}:
            base_mode = "pair_hold" if section in {"build", "chorus", "drop"} else "soft_pulse"
        elif base_mode == "double_hit" and section != "drop":
            base_mode = "pair_hold"
    elif style_name == "warm":
        if base_mode in {"snake", "chase", "tremolo_dimmer", "gallop", "blackout_hit"}:
            base_mode = "pair_swap" if section in {"chorus", "drop"} else "pair_hold"
    elif style_name == "club":
        if section in {"build", "chorus", "drop"} and base_mode in {"soft_pulse", "breathing", "slow_fade_out"}:
            base_mode = "pair_swap"
    if section == "intro":
        return base_mode if base_mode in {"slow_fade_in", "soft_pulse", "offbeat_flash"} else "soft_pulse"
    if section == "outro":
        return base_mode if base_mode in {"slow_fade_out", "breathing", "soft_pulse", "offbeat_flash"} else "soft_pulse"
    if section == "down":
        return base_mode if base_mode in {"breathing", "soft_pulse", "offbeat_flash", "slow_fade_out"} else "soft_pulse"
    if section == "break":
        return base_mode if base_mode in {"breathing", "soft_pulse", "offbeat_flash", "slow_fade_out"} else "breathing"
    if section == "verse":
        return base_mode if base_mode in {"breathing", "soft_pulse", "offbeat_flash"} else "soft_pulse"
    if section == "build":
        if activity["breakdown"]:
            return "soft_pulse"
        if activity["calm"] and not high_override and base_mode in {"pair_swap", "pair_bounce", "chase", "beat_flash", "strong_pulse", "snake", "alternate_whole", "double_hit", "gallop", "pivot"}:
            return "soft_pulse"
        if base_mode == "snake":
            return "pair_bounce"
        if base_mode == "gallop":
            return "pair_bounce"
        if base_mode == "pivot":
            return "pair_hold"
        if base_mode == "alternate_whole":
            return "pair_hold"
        if base_mode == "double_hit":
            return "pair_swap"
        if base_mode in {"chase", "beat_flash", "strong_pulse"}:
            return "pair_swap"
        if base_mode in {"ramp_up", "medium"}:
            return "pair_hold"
        return "pair_swap"
    if section == "chorus":
        if activity["breakdown"]:
            return "breathing"
        if activity["calm"] and not high_override and base_mode in {"pair_swap", "pair_bounce", "chase", "beat_flash", "snake", "alternate_whole", "double_hit", "gallop", "pivot"}:
            return "soft_pulse"
        if base_mode == "snake":
            return "pair_bounce"
        if base_mode == "gallop":
            return "pair_bounce"
        if base_mode == "pivot":
            return "pair_hold"
        if base_mode == "alternate_whole":
            return "pair_hold"
        if base_mode == "double_hit":
            return "pair_swap"
        if base_mode in {"chase", "offbeat_flash", "beat_flash"}:
            return "pair_swap"
        if base_mode in {"medium", "soft_pulse", "full_on"}:
            return "pair_hold"
        return "pair_swap"
    if section == "drop":
        if activity["breakdown"]:
            return "soft_pulse"
        if activity["calm"] and not high_override and base_mode in {"pair_swap", "pair_bounce", "chase", "beat_flash", "snake", "tremolo_dimmer", "alternate_whole", "double_hit", "gallop", "pivot"}:
            return "breathing"
        if base_mode == "full_on":
            return "full_on"
        if base_mode in {"drop_blinder", "blackout_hit"}:
            return base_mode
        if base_mode == "snake":
            return "pair_bounce"
        if base_mode == "gallop":
            return "pair_bounce"
        if base_mode == "pivot":
            return "pair_hold"
        if base_mode == "alternate_whole":
            return "pair_hold"
        if base_mode == "double_hit":
            return "pair_swap"
        if base_mode in {"chase", "beat_flash", "tremolo_dimmer"}:
            return "pair_swap"
        return "pair_hold"
    return "soft_pulse"


def auto_show_moving_rhythm_mode(section, base_mode, style_name, osc, slot_context, energy, movement, override_energy="none"):
    activity = osc_dimmer_activity_profile(osc)
    override_energy = live_override_energy_name(override_energy)
    low_override = override_energy == "low"
    high_override = override_energy == "high"
    if section == "intro":
        return base_mode if base_mode in {"slow_fade_in", "soft_pulse", "offbeat_flash"} else "soft_pulse"
    if section == "outro":
        return base_mode if base_mode in {"slow_fade_out", "breathing", "soft_pulse", "offbeat_flash"} else "soft_pulse"
    if section == "down":
        return base_mode if base_mode in {"breathing", "soft_pulse", "offbeat_flash", "slow_fade_out"} else "soft_pulse"
    if section == "break":
        return base_mode if base_mode in {"breathing", "slow_fade_out", "soft_pulse", "offbeat_flash"} else "breathing"
    if section == "verse":
        return base_mode if base_mode in {"breathing", "soft_pulse", "offbeat_flash"} else "soft_pulse"
    drums = osc_drum_profile(osc)
    kick = float(drums.get("kick") or 0.0)
    snare = float(drums.get("snare") or 0.0)
    hihat = float(drums.get("hihat") or 0.0)
    early_build = is_early_build_phrase(osc.get("phrase_current"))
    active_window = activity["active"] or movement >= 0.62 or energy >= 0.74 or kick >= 0.40 or snare >= 0.42
    peak_window = activity["peak"] or movement >= 0.78 or energy >= 0.88 or kick >= 0.52 or snare >= 0.52
    moderate_window = active_window and not peak_window
    surge_window = peak_window or kick >= 0.60 or snare >= 0.62 or hihat >= 0.66
    if low_override:
        surge_window = False
        peak_window = False
        active_window = active_window and energy >= 0.58 and kick >= 0.34
    elif high_override:
        active_window = active_window or (section in {"build", "chorus", "drop"} and (energy >= 0.62 or kick >= 0.34 or snare >= 0.34))
        peak_window = peak_window or (section in {"build", "chorus", "drop"} and (energy >= 0.78 or kick >= 0.44 or snare >= 0.44))
        surge_window = surge_window or (section in {"build", "chorus", "drop"} and (energy >= 0.84 or kick >= 0.52 or snare >= 0.52 or hihat >= 0.56))
        if section == "build" and base_mode in {"soft_pulse", "breathing", "slow_fade_out", "medium", "offbeat_flash"}:
            base_mode = "chase_whole"
        elif section == "chorus" and base_mode in {"soft_pulse", "breathing", "medium", "offbeat_flash"}:
            base_mode = "chase_whole"
        elif section == "drop" and base_mode in {"soft_pulse", "breathing", "medium", "offbeat_flash", "full_on"}:
            base_mode = "snake_whole" if kick >= 0.28 else "chase_whole"
    if style_name == "festival":
        active_window = active_window or (section in {"build", "chorus", "drop"} and (energy >= 0.64 or kick >= 0.34 or snare >= 0.34))
        peak_window = peak_window or (section in {"build", "chorus", "drop"} and (kick >= 0.44 or snare >= 0.46 or hihat >= 0.48))
        surge_window = surge_window or (section in {"build", "chorus", "drop"} and (kick >= 0.48 or snare >= 0.50 or hihat >= 0.54))
        if base_mode in {"soft_pulse", "breathing", "slow_fade_out"} and section in {"build", "chorus", "drop"}:
            base_mode = "chase_whole"
    elif style_name == "minimal":
        if base_mode in {"snake", "snake_whole", "chase", "chase_whole", "gallop", "drop_blinder", "blackout_hit", "tremolo_dimmer"}:
            base_mode = "alternate_whole" if section in {"build", "chorus", "drop"} else "soft_pulse"
        elif base_mode == "double_hit" and section != "drop":
            base_mode = "pivot"
        surge_window = False
        peak_window = peak_window and energy >= 0.94 and kick >= 0.60
    elif style_name == "cinematic":
        if base_mode in {"snake", "snake_whole", "chase", "chase_whole", "gallop", "drop_blinder", "blackout_hit", "tremolo_dimmer"}:
            base_mode = "alternate_whole" if section in {"build", "chorus", "drop"} else "soft_pulse"
        elif base_mode == "double_hit" and section != "drop":
            base_mode = "pivot"
        surge_window = False
        peak_window = peak_window and energy >= 0.92 and kick >= 0.56
    elif style_name == "warm":
        if base_mode in {"snake", "snake_whole", "chase", "chase_whole", "gallop", "tremolo_dimmer", "blackout_hit"}:
            base_mode = "double_hit" if section in {"chorus", "drop"} else "alternate_whole"
    elif style_name == "club":
        active_window = active_window or (section in {"build", "chorus", "drop"} and (energy >= 0.66 or kick >= 0.36 or snare >= 0.36))
        peak_window = peak_window or (section in {"chorus", "drop"} and (kick >= 0.48 or snare >= 0.50 or hihat >= 0.54))
        surge_window = surge_window or (section in {"build", "chorus", "drop"} and (kick >= 0.54 or snare >= 0.56))
    if low_override:
        if section == "drop":
            if base_mode in {"snake", "snake_whole", "chase", "chase_whole", "beat_flash", "drop_blinder", "tremolo_dimmer", "double_hit", "gallop"}:
                return "alternate_whole" if activity["active"] else "breathing"
        elif section in {"build", "chorus"}:
            if base_mode in {"snake", "snake_whole", "chase", "chase_whole", "beat_flash", "strong_pulse", "ramp_up", "double_hit", "gallop", "pivot", "drop_blinder", "blackout_hit"}:
                return "soft_pulse" if section == "chorus" else "breathing"
    if section == "build":
        if activity["breakdown"]:
            return "soft_pulse"
        if activity["calm"] and not high_override and base_mode in {"snake", "snake_whole", "chase", "chase_whole", "beat_flash", "strong_pulse", "ramp_up", "alternate_whole", "double_hit", "gallop", "pivot"}:
            return "breathing" if early_build else "soft_pulse"
        if early_build and not peak_window and base_mode in {"snake", "snake_whole", "chase", "chase_whole", "beat_flash", "strong_pulse", "double_hit", "gallop"}:
            return "chase_whole" if active_window and (kick >= 0.44 or snare >= 0.44) else "soft_pulse"
        if base_mode in {"drop_blinder", "blackout_hit"}:
            return "beat_flash"
        if base_mode in {"alternate_whole", "pivot"}:
            return base_mode if active_window else "soft_pulse"
        if base_mode == "double_hit":
            return "double_hit" if surge_window or snare >= 0.48 else "alternate_whole"
        if base_mode == "gallop":
            return "gallop" if surge_window or hihat >= 0.44 else "alternate_whole"
        if base_mode == "snake":
            return "snake" if surge_window else "snake_whole"
        if base_mode == "snake_whole":
            return "snake" if surge_window else "snake_whole"
        if base_mode == "chase":
            return "chase" if surge_window else "chase_whole"
        if base_mode == "chase_whole":
            return "chase" if surge_window else "chase_whole"
        if active_window and base_mode in {"medium", "soft_pulse", "offbeat_flash", "strong_pulse", "ramp_up"}:
            if kick >= snare or hihat < 0.38:
                return "chase" if surge_window else "chase_whole"
            return "beat_flash"
        return "beat_flash" if peak_window else base_mode
    if section == "chorus":
        if activity["breakdown"]:
            return "breathing"
        if activity["calm"] and not high_override and base_mode in {"snake", "snake_whole", "chase", "chase_whole", "beat_flash", "strong_pulse", "alternate_whole", "double_hit", "gallop", "pivot"}:
            return "soft_pulse"
        if base_mode in {"alternate_whole", "pivot"}:
            return base_mode if active_window else "soft_pulse"
        if base_mode == "double_hit":
            return "double_hit" if peak_window or snare >= 0.46 else "alternate_whole"
        if base_mode == "gallop":
            return "gallop" if surge_window or hihat >= 0.48 else "pivot"
        if base_mode == "snake":
            return "snake" if surge_window else "snake_whole"
        if base_mode == "snake_whole":
            return "snake" if surge_window else "snake_whole"
        if base_mode == "chase":
            return "chase" if surge_window else "chase_whole"
        if base_mode == "chase_whole":
            return "chase" if surge_window else "chase_whole"
        if base_mode in {"medium", "soft_pulse", "offbeat_flash", "beat_flash", "strong_pulse"}:
            if peak_window:
                return "snake"
            if active_window:
                return "chase" if surge_window else "chase_whole"
            return "beat_flash"
        return base_mode
    if section == "drop":
        if activity["breakdown"]:
            return "soft_pulse"
        if activity["calm"] and not high_override and base_mode in {"snake", "snake_whole", "chase", "chase_whole", "beat_flash", "tremolo_dimmer", "drop_blinder", "alternate_whole", "double_hit", "gallop", "pivot"}:
            return "breathing"
        if base_mode in {"drop_blinder", "blackout_hit"}:
            return base_mode
        if base_mode == "alternate_whole":
            return "alternate_whole"
        if base_mode == "pivot":
            return "pivot" if active_window else "alternate_whole"
        if base_mode == "double_hit":
            return "double_hit" if active_window else "alternate_whole"
        if base_mode == "gallop":
            return "gallop" if active_window else "alternate_whole"
        if peak_window:
            return "snake"
        if active_window:
            if kick >= 0.44:
                return "snake" if surge_window else "snake_whole"
            return "chase" if surge_window else "chase_whole"
        if base_mode in {"full_on", "tremolo_dimmer", "medium", "soft_pulse"}:
            return "beat_flash"
        return base_mode
    return "soft_pulse"


def _slot_pose(config, key):
    if not isinstance(config, dict):
        return None
    pose = config.get(key)
    if not isinstance(pose, dict):
        return None
    pan = pose.get("pan")
    tilt = pose.get("tilt")
    if pan is None or tilt is None:
        return None
    return {
        "pan": clamp_dmx(pan),
        "tilt": clamp_dmx(tilt),
    }


def _interpolate_pose(pose_a, pose_b, amount):
    if not pose_a or not pose_b:
        return None
    amount = clamp_unit(amount)
    return {
        "pan": clamp_dmx(round(pose_a["pan"] + (pose_b["pan"] - pose_a["pan"]) * amount)),
        "tilt": clamp_dmx(round(pose_a["tilt"] + (pose_b["tilt"] - pose_a["tilt"]) * amount)),
    }


def _interpolate_pose_path(left_pose, center_pose, right_pose, amount):
    amount = clamp_unit(amount)
    if left_pose and center_pose and right_pose:
        if amount <= 0.5:
            return _interpolate_pose(left_pose, center_pose, amount * 2.0)
        return _interpolate_pose(center_pose, right_pose, (amount - 0.5) * 2.0)
    if left_pose and right_pose:
        return _interpolate_pose(left_pose, right_pose, amount)
    if center_pose and left_pose:
        return _interpolate_pose(left_pose, center_pose, amount)
    if center_pose and right_pose:
        return _interpolate_pose(center_pose, right_pose, amount)
    return center_pose or left_pose or right_pose


def _interpolate_scalar_path(left_value, center_value, right_value, amount):
    amount = clamp_unit(amount)
    if left_value is not None and center_value is not None and right_value is not None:
        if amount <= 0.5:
            local = amount * 2.0
            return round(left_value + (center_value - left_value) * local)
        local = (amount - 0.5) * 2.0
        return round(center_value + (right_value - center_value) * local)
    if left_value is not None and right_value is not None:
        return round(left_value + (right_value - left_value) * amount)
    if center_value is not None and left_value is not None:
        return round(left_value + (center_value - left_value) * amount)
    if center_value is not None and right_value is not None:
        return round(center_value + (right_value - center_value) * amount)
    return center_value if center_value is not None else left_value if left_value is not None else right_value


def _fallback_pose_from_config(config):
    for key in ("pose_center", "pose_audience_center", "pose_ceiling_center", "pose_audience_left", "pose_audience_right"):
        pose = _slot_pose(config, key)
        if pose:
            return pose
    return {"pan": 128, "tilt": 128}


def _reference_mid(low_value, high_value, fallback):
    if low_value is not None and high_value is not None:
        return round((float(low_value) + float(high_value)) * 0.5)
    return fallback


def _safe_pose_tilt(pose, fallback, lower=0, upper=255):
    if pose and lower <= int(pose.get("tilt", -1)) <= upper:
        return int(pose["tilt"])
    return fallback


def _vertical_pose_ready(audience_pose, ceiling_pose, minimum_delta=12):
    if not audience_pose or not ceiling_pose:
        return False
    return abs(int(ceiling_pose["tilt"]) - int(audience_pose["tilt"])) >= minimum_delta


FULL_TILT_MOTION_PATTERNS = {
    "horizontal_sweep",
    "vertical_sweep",
    "diagonal_sweep",
    "reverse_diagonal_sweep",
    "circle",
    "figure_8",
    "random_searchlight",
    "snap_hits",
    "rising_sweep",
    "fan_wave",
    "crossing_beams",
    "mirror_bounce",
    "pulse_circle",
    "smooth_sweep",
    "arc_sweep",
    "tilt_sweep",
}


def _motion_profile_tilt_wave(pattern, profile, movement_scale, default_wave=0.0):
    try:
        base_wave = float(profile.get("tilt_wave", default_wave))
    except (TypeError, ValueError):
        base_wave = float(default_wave)
    if pattern == "horizontal_sweep" and abs(base_wave) < 1.0:
        base_wave = 18.0 + movement_scale * 14.0
    if pattern in {"smooth_sweep", "arc_sweep", "tilt_sweep"}:
        try:
            base_wave += movement_scale * float(profile.get("tilt_extra", 0.0))
        except (TypeError, ValueError):
            pass
    return abs(base_wave)


def _motion_profile_tilt_source_range(pattern, profile, movement_scale, default_tilt_center):
    if pattern not in FULL_TILT_MOTION_PATTERNS:
        return None
    if not bool(profile.get("use_full_tilt_range", False)):
        return None

    if pattern == "vertical_sweep":
        tilt_min = profile.get("tilt_min")
        tilt_max = profile.get("tilt_max")
        if tilt_min is not None and tilt_max is not None:
            return float(tilt_min), float(tilt_max)
        center = float(profile.get("tilt_center", default_tilt_center))
        wave = _motion_profile_tilt_wave(pattern, profile, movement_scale, 80.0)
        return center - wave, center + wave

    if pattern == "random_searchlight":
        return float(profile.get("tilt_min", 50)), float(profile.get("tilt_max", 210))

    if pattern == "rising_sweep":
        return float(profile.get("tilt_min", 145)), float(profile.get("tilt_max", 220))

    if pattern == "fan_wave":
        tilt_min = profile.get("fan_wave_tilt_min")
        tilt_max = profile.get("fan_wave_tilt_max")
        if tilt_min is not None and tilt_max is not None:
            return float(tilt_min), float(tilt_max)
        center = float(profile.get("tilt_center", default_tilt_center))
        wave = float(profile.get("fan_wave_tilt_wave", 40))
        return center - wave, center + wave

    if pattern == "crossing_beams":
        frames = list(profile.get("crossing_frames_4", [])) + list(profile.get("crossing_frames_2", []))
        tilts = [float(frame[1]) for frame in frames if isinstance(frame, (list, tuple)) and len(frame) >= 2]
        if tilts:
            return min(tilts), max(tilts)
        center = float(profile.get("tilt_center", default_tilt_center))
        return center, center

    if pattern == "snap_hits":
        positions = profile.get("snap_positions", [])
        tilts = [float(position[1]) for position in positions if isinstance(position, (list, tuple)) and len(position) >= 2]
        if tilts:
            return min(tilts), max(tilts)
        center = float(profile.get("tilt_center", default_tilt_center))
        return center, center

    if pattern in {"smooth_sweep", "arc_sweep", "tilt_sweep"}:
        default_centers = {
            "smooth_sweep": 152.0,
            "arc_sweep": 148.0,
            "tilt_sweep": 178.0,
        }
        default_waves = {
            "smooth_sweep": 10.0,
            "arc_sweep": 16.0,
            "tilt_sweep": 8.0,
        }
        center = float(profile.get("tilt_base", default_centers[pattern]))
        wave = _motion_profile_tilt_wave(pattern, profile, movement_scale, default_waves[pattern])
        return center - wave, center + wave

    default_waves = {
        "horizontal_sweep": 0.0,
        "diagonal_sweep": 88.0,
        "reverse_diagonal_sweep": 88.0,
        "circle": 38.0,
        "figure_8": 58.0,
        "mirror_bounce": 55.0,
        "pulse_circle": 35.0,
    }
    center = float(profile.get("tilt_center", default_tilt_center))
    wave = _motion_profile_tilt_wave(pattern, profile, movement_scale, default_waves.get(pattern, 0.0))
    return center - wave, center + wave


def _bias_normalized_tilt_toward_extremes(normalized, curve=0.72):
    centered = clamp_unit(float(normalized)) * 2.0 - 1.0
    biased = math.copysign(abs(centered) ** max(0.35, float(curve)), centered)
    return clamp_unit(0.5 + 0.5 * biased)


def _expand_motion_tilt_range(tilt_value, pattern, profile, movement_scale, default_tilt_center):
    source_range = _motion_profile_tilt_source_range(
        pattern,
        profile,
        movement_scale,
        default_tilt_center,
    )
    if not source_range:
        return clamp_dmx(int(round(float(tilt_value))))
    source_min, source_max = source_range
    span = float(source_max) - float(source_min)
    if span < 1.0:
        return clamp_dmx(int(round(float(tilt_value))))
    normalized = clamp_unit((float(tilt_value) - float(source_min)) / span)
    normalized = _bias_normalized_tilt_toward_extremes(
        normalized,
        curve=profile.get("full_tilt_curve", 0.72),
    )
    return clamp_dmx(round(normalized * 255.0))


def _motion_profile_uses_full_tilt_range(profile):
    pattern = str((profile or {}).get("pattern", "") or "")
    if pattern not in FULL_TILT_MOTION_PATTERNS:
        return False
    return bool((profile or {}).get("use_full_tilt_range", False))


def _full_tilt_motion_speed_cap(profile, section):
    if not _motion_profile_uses_full_tilt_range(profile):
        return None
    default_caps = {
        "intro": 56,
        "verse": 44,
        "build": 32,
        "chorus": 32,
        "drop": 24,
        "down": 40,
        "break": 48,
        "outro": 56,
        "unknown": 38,
    }
    try:
        override = profile.get("pan_tilt_speed_cap")
        if override is not None:
            return clamp_dmx(int(override))
    except (TypeError, ValueError):
        pass
    return int(default_caps.get(section, 38))


AUDIENCE_PAN_FOCUS_SOURCE_MIN = 30
AUDIENCE_PAN_FOCUS_SOURCE_MAX = 225
AUDIENCE_TILT_BRANCH_BLEND = 20


def _default_turn_audience_pan_limits(target_min, target_max):
    center = (float(target_min) + float(target_max)) / 2.0
    half_turn_span = 85.0
    direction = -1.0 if center >= 127.5 else 1.0
    turn_min = clamp_dmx(round(float(target_min) + direction * half_turn_span))
    turn_max = clamp_dmx(round(float(target_max) + direction * half_turn_span))
    if turn_max < turn_min:
        turn_min, turn_max = turn_max, turn_min
    return turn_min, turn_max


def _audience_pan_focus_limits(config):
    enabled = bool(config.get("_auto_show_audience_pan_focus_enabled", True))
    try:
        target_min = clamp_dmx(int(config.get("_auto_show_audience_pan_min", 135)))
    except (TypeError, ValueError):
        target_min = 135
    try:
        target_max = clamp_dmx(int(config.get("_auto_show_audience_pan_max", 205)))
    except (TypeError, ValueError):
        target_max = 205
    if target_max < target_min:
        target_min, target_max = target_max, target_min
    default_turn_min, default_turn_max = _default_turn_audience_pan_limits(
        target_min,
        target_max,
    )
    try:
        turn_min = clamp_dmx(
            int(config.get("_auto_show_audience_turn_pan_min", default_turn_min))
        )
    except (TypeError, ValueError):
        turn_min = default_turn_min
    try:
        turn_max = clamp_dmx(
            int(config.get("_auto_show_audience_turn_pan_max", default_turn_max))
        )
    except (TypeError, ValueError):
        turn_max = default_turn_max
    if turn_max < turn_min:
        turn_min, turn_max = turn_max, turn_min
    try:
        tilt_split = clamp_dmx(int(config.get("_auto_show_audience_tilt_split", 127)))
    except (TypeError, ValueError):
        tilt_split = 127
    return enabled, target_min, target_max, turn_min, turn_max, tilt_split


def _focused_audience_pan_value(pan_value, tilt_value=None, config=None):
    try:
        pan_value = float(pan_value)
    except (TypeError, ValueError):
        return clamp_dmx(170)
    try:
        tilt_value = float(tilt_value)
    except (TypeError, ValueError):
        tilt_value = 170.0
    (
        enabled,
        target_min,
        target_max,
        turn_min,
        turn_max,
        tilt_split,
    ) = _audience_pan_focus_limits(config or {})
    if not enabled:
        return clamp_dmx(round(pan_value))
    source_min = float(AUDIENCE_PAN_FOCUS_SOURCE_MIN)
    source_max = float(AUDIENCE_PAN_FOCUS_SOURCE_MAX)
    if source_max <= source_min:
        return clamp_dmx(round(target_min))
    normalized = (max(source_min, min(source_max, pan_value)) - source_min) / (source_max - source_min)
    front_pan = float(target_min) + normalized * (float(target_max) - float(target_min))
    turn_pan = float(turn_min) + normalized * (float(turn_max) - float(turn_min))
    blend_lower = float(tilt_split) - AUDIENCE_TILT_BRANCH_BLEND
    blend_upper = float(tilt_split) + AUDIENCE_TILT_BRANCH_BLEND
    if blend_upper <= blend_lower:
        front_mix = 1.0 if tilt_value >= float(tilt_split) else 0.0
    else:
        front_mix = clamp_unit((tilt_value - blend_lower) / (blend_upper - blend_lower))
    focused = turn_pan + (front_pan - turn_pan) * front_mix
    return clamp_dmx(round(focused))


def _apply_audience_pan_focus_to_motion(motion, slot_context, config=None):
    if not motion or not slot_context:
        return motion
    if str(slot_context.get("role", "")) != "moving":
        return motion
    focused = dict(motion)
    focused["pan"] = _focused_audience_pan_value(
        focused.get("pan", 170),
        tilt_value=focused.get("tilt", 170),
        config=config,
    )
    return focused


def styled_phrase_motion(phrase, beat_value, family, slot_context, movement_scale, config=None):
    profile = auto_show_motion_profile(family)
    slot_context = slot_context or {}
    role = str(slot_context.get("role", ""))
    group_index = int(slot_context.get("group_index", 0))
    group_centered = float(slot_context.get("group_centered", slot_context.get("centered", 0.0)))
    group_edge_bias = float(slot_context.get("group_edge_bias", slot_context.get("edge_bias", 0.0)))
    group_center_bias = float(slot_context.get("group_center_bias", slot_context.get("center_bias", 1.0)))
    group_alternate = float(slot_context.get("group_alternate", slot_context.get("alternate", 1.0)))
    member_index = int(slot_context.get("member_index", 0))
    role_index = int(slot_context.get("role_index", member_index))
    member_centered = float(slot_context.get("member_centered", 0.0))
    member_alternate = float(slot_context.get("member_alternate", slot_context.get("alternate", 1.0)))
    member_count = max(1, int(slot_context.get("member_count", 1)))
    role_count = max(1, int(slot_context.get("role_count", member_count)))
    beat_value = float(beat_value or 0.0)
    movement_scale = float(movement_scale or 0.0)
    pattern = profile.get("pattern", "base")
    use_taught_poses = bool(profile.get("use_taught_poses", False))
    span_index = role_index if role == "moving" and role_count >= 4 else member_index
    span_count = role_count if role == "moving" and role_count >= 4 else member_count

    adjusted_beat = beat_value * profile["phase_scale"]
    pose_center = _slot_pose(config, "pose_center") or _slot_pose(config, "pose_audience_center")
    pose_audience_left = _slot_pose(config, "pose_audience_left")
    pose_audience_center = _slot_pose(config, "pose_audience_center") or pose_center
    pose_audience_right = _slot_pose(config, "pose_audience_right")
    pose_ceiling_center = _slot_pose(config, "pose_ceiling_center")
    fallback_pose = _fallback_pose_from_config(config)
    raw_pan_left = config.get("pan_left_value") if isinstance(config, dict) else None
    raw_pan_right = config.get("pan_right_value") if isinstance(config, dict) else None
    raw_tilt_back = config.get("tilt_back_value") if isinstance(config, dict) else None
    raw_tilt_front = config.get("tilt_front_value") if isinstance(config, dict) else None
    raw_pan_center = None
    if pose_center:
        raw_pan_center = pose_center["pan"]
    elif pose_audience_center:
        raw_pan_center = pose_audience_center["pan"]
    raw_tilt_center = None
    if pose_center:
        raw_tilt_center = pose_center["tilt"]
    elif pose_audience_center:
        raw_tilt_center = pose_audience_center["tilt"]
    raw_vertical_path_available = (
        raw_tilt_back is not None
        and raw_tilt_front is not None
        and raw_tilt_center is not None
    )
    if use_taught_poses:
        default_pan_center = raw_pan_center if raw_pan_center is not None else _reference_mid(raw_pan_left, raw_pan_right, 128)
        default_tilt_center = _safe_pose_tilt(
            pose_audience_center or pose_center,
            int(profile.get("tilt_center", 128)),
        )
    else:
        default_pan_center = int(profile.get("pan_center", 128))
        default_tilt_center = int(profile.get("tilt_center", 128))
    vertical_pose_available = _vertical_pose_ready(pose_audience_center or pose_center, pose_ceiling_center)
    motion = None
    if pattern == "base":
        motion = phrase_motion(phrase, adjusted_beat)
    elif pattern == "center_hold":
        if use_taught_poses and (pose_center or fallback_pose):
            learned = pose_center or fallback_pose
            motion = {
                "pan": learned["pan"],
                "tilt": _safe_pose_tilt(learned, default_tilt_center),
                "pan_tilt_speed": 0,
            }
        else:
            motion = {
                "pan": int(profile.get("pan_center", 128)),
                "tilt": int(profile.get("tilt_center", 128)),
                "pan_tilt_speed": 0,
            }
    elif pattern == "static_positions":
        if span_count >= 4:
            positions = profile.get("positions_4", [60, 105, 150, 195])
        elif span_count == 2:
            positions = profile.get("positions_2", [105, 150])
        else:
            positions = [int(profile.get("pan_center", 128))]
        pan_value = positions[min(len(positions) - 1, span_index if len(positions) > 1 else 0)]
        motion = {
            "pan": clamp_dmx(pan_value),
            "tilt": clamp_dmx(int(profile.get("tilt_static", profile.get("tilt_center", 180)))),
            "pan_tilt_speed": 0,
        }
    elif pattern == "horizontal_sweep":
        sweep_phase = adjusted_beat / 24.0
        tilt_phase = sweep_phase * _profile_tilt_phase_scale(profile, 1.0) + _profile_tilt_phase_offset(profile, 0.0)
        profile_tilt_center = int(profile.get("tilt_center", default_tilt_center))
        profile_tilt_wave = _motion_profile_tilt_wave(
            pattern,
            profile,
            movement_scale,
            0.0,
        )
        base_tilt_center = _safe_pose_tilt(pose_audience_center or pose_center, profile_tilt_center)
        if use_taught_poses and pose_audience_left and (pose_audience_center or pose_center or pose_audience_right):
            amount = 0.5 + 0.5 * wave_sine(sweep_phase)
            sweep_pose = _interpolate_pose_path(
                pose_audience_left,
                pose_audience_center or pose_center,
                pose_audience_right,
                amount,
            )
            tilt_value = clamp_motion(base_tilt_center, profile_tilt_wave, wave_sine(tilt_phase))
            if family == "ceiling_sweep" and vertical_pose_available:
                tilt_wave = wave_sine(tilt_phase)
                ceiling_wave = profile.get("tilt_wave", 0)
                tilt_value = clamp_dmx(round(pose_ceiling_center["tilt"] + tilt_wave * ceiling_wave))
            motion = {
                "pan": sweep_pose["pan"],
                "tilt": tilt_value,
                "pan_tilt_speed": 0,
            }
        else:
            motion = {
                "pan": clamp_motion(
                    profile.get("pan_center", 128),
                    profile.get("pan_wave", 88),
                    wave_sine(sweep_phase),
                ),
                "tilt": clamp_motion(
                    profile_tilt_center,
                    profile_tilt_wave,
                    wave_sine(tilt_phase),
                ),
                "pan_tilt_speed": 0,
            }
        if use_taught_poses and raw_pan_left is not None and raw_pan_right is not None:
            amount = 0.5 + 0.5 * wave_sine(sweep_phase)
            pan_value = _interpolate_scalar_path(raw_pan_left, raw_pan_center, raw_pan_right, amount)
            if pan_value is not None:
                motion["pan"] = clamp_dmx(pan_value)
    elif pattern == "vertical_sweep":
        sweep_phase = adjusted_beat / 24.0
        tilt_phase = sweep_phase * _profile_tilt_phase_scale(profile, 1.0) + _profile_tilt_phase_offset(profile, 0.0)
        if use_taught_poses and vertical_pose_available:
            amount = 0.5 + 0.5 * wave_sine(tilt_phase)
            vertical_pose = _interpolate_pose(pose_audience_center or pose_center, pose_ceiling_center, amount)
            motion = {
                "pan": (pose_audience_center or pose_center)["pan"],
                "tilt": vertical_pose["tilt"],
                "pan_tilt_speed": 0,
            }
        else:
            tilt_min = profile.get("tilt_min")
            tilt_max = profile.get("tilt_max")
            if tilt_min is not None and tilt_max is not None:
                tilt_amount = 0.5 + 0.5 * wave_sine(tilt_phase)
                tilt_value = round(float(tilt_min) + (float(tilt_max) - float(tilt_min)) * tilt_amount)
            else:
                tilt_value = clamp_motion(
                    int(profile.get("tilt_center", default_tilt_center)),
                    profile.get("tilt_wave", 80),
                    wave_sine(tilt_phase),
                )
            motion = {
                "pan": clamp_motion(
                    default_pan_center,
                    profile.get("pan_wave", 0),
                    wave_sine(sweep_phase / 3.0),
                ),
                "tilt": clamp_dmx(tilt_value),
                "pan_tilt_speed": 0,
            }
        if use_taught_poses and raw_vertical_path_available:
            amount = 0.5 + 0.5 * wave_sine(tilt_phase)
            tilt_value = _interpolate_scalar_path(raw_tilt_back, raw_tilt_center, raw_tilt_front, amount)
            if tilt_value is not None:
                motion["tilt"] = clamp_dmx(tilt_value)
            if raw_pan_center is not None:
                motion["pan"] = clamp_dmx(raw_pan_center)
    elif pattern == "diagonal_sweep":
        sweep_phase = adjusted_beat / 24.0
        tilt_phase = sweep_phase * _profile_tilt_phase_scale(profile, 1.0) + _profile_tilt_phase_offset(profile, 0.0)
        diagonal_wave = wave_sine(sweep_phase)
        motion = {
            "pan": clamp_motion(
                profile.get("pan_center", 128),
                profile.get("pan_wave", 88),
                diagonal_wave,
            ),
            "tilt": clamp_motion(
                profile.get("tilt_center", 128),
                profile.get("tilt_wave", 88),
                wave_sine(tilt_phase),
            ),
            "pan_tilt_speed": 0,
        }
    elif pattern == "reverse_diagonal_sweep":
        sweep_phase = adjusted_beat / 24.0
        tilt_phase = sweep_phase * _profile_tilt_phase_scale(profile, 1.0) + _profile_tilt_phase_offset(profile, 0.0)
        diagonal_wave = wave_sine(sweep_phase)
        motion = {
            "pan": clamp_motion(
                profile.get("pan_center", 128),
                profile.get("pan_wave", 88),
                -diagonal_wave,
            ),
            "tilt": clamp_motion(
                profile.get("tilt_center", 128),
                profile.get("tilt_wave", 88),
                wave_sine(tilt_phase),
            ),
            "pan_tilt_speed": 0,
        }
    elif pattern == "circle":
        circle_phase = adjusted_beat / 28.0
        tilt_phase = circle_phase * _profile_tilt_phase_scale(profile, 1.0) + _profile_tilt_phase_offset(profile, 0.0)
        pan_center = profile.get("pan_center", 128)
        pan_wave = profile.get("pan_wave", 58)
        tilt_center = profile.get("tilt_center", 128)
        tilt_wave = profile.get("tilt_wave", 38)
        motion = {
            "pan": clamp_motion(pan_center, pan_wave, wave_sine(circle_phase)),
            "tilt": clamp_motion(tilt_center, tilt_wave, wave_cosine(tilt_phase)),
            "pan_tilt_speed": 0,
        }
    elif pattern == "figure_8":
        fig_phase = adjusted_beat / 28.0
        tilt_phase = fig_phase * _profile_tilt_phase_scale(profile, 1.0) + _profile_tilt_phase_offset(profile, 0.0)
        motion = {
            "pan": clamp_motion(
                profile.get("pan_center", 128),
                profile.get("pan_wave", 68),
                wave_sine(fig_phase),
            ),
            "tilt": clamp_motion(
                profile.get("tilt_center", 128),
                profile.get("tilt_wave", 58),
                wave_sine(tilt_phase * 2.0),
            ),
            "pan_tilt_speed": 0,
        }
    elif pattern == "random_searchlight":
        window_beats = max(1.0, float(profile.get("window_beats", 8.0)))
        window_index = int(math.floor(beat_value / window_beats))
        seed_base = f"{family}|{window_index}|{group_index}|{member_count}|{group_centered:.3f}"
        pan_seed = stable_hash(seed_base + "|pan")
        tilt_seed = stable_hash(seed_base + "|tilt")
        pan_min = int(profile.get("pan_min", 30))
        pan_max = int(profile.get("pan_max", 225))
        tilt_min = int(profile.get("tilt_min", 50))
        tilt_max = int(profile.get("tilt_max", 210))
        pan_value = pan_min + ((pan_seed % 1000) / 999.0) * max(1, pan_max - pan_min)
        tilt_value = tilt_min + ((tilt_seed % 1000) / 999.0) * max(1, tilt_max - tilt_min)
        motion = {
            "pan": clamp_dmx(round(pan_value)),
            "tilt": clamp_dmx(round(tilt_value)),
            "pan_tilt_speed": 0,
        }
    elif pattern == "snap_hits":
        positions = profile.get(
            "snap_positions",
            [
                (40, 80),
                (216, 80),
                (216, 190),
                (40, 190),
                (128, 128),
            ],
        )
        step = int(math.floor(beat_value)) % len(positions)
        pan_value, tilt_value = positions[step]
        motion = {
            "pan": pan_value,
            "tilt": tilt_value,
            "pan_tilt_speed": 0,
            "rgbw": (255, 255, 255, 255),
        }
    elif pattern == "blinder_flash":
        flash_phase = beat_value % 1.0
        flash_open = flash_phase < 0.18
        motion = {
            "pan": 128,
            "tilt": int(profile.get("tilt_center", 170)),
            "pan_tilt_speed": 0,
            "dimmer": 255 if flash_open else 0,
            "rgbw": (255, 255, 255, 255),
        }
    elif pattern == "hold_pulse":
        pulse_phase = (0.5 + 0.5 * wave_sine(beat_value * float(profile.get("pulse_phase_scale", 0.5)))) if beat_value is not None else 0.5
        dimmer_min = int(profile.get("dimmer_min", 80))
        dimmer_max = int(profile.get("dimmer_max", 255))
        motion = {
            "pan": int(profile.get("pan_center", 128)),
            "tilt": int(profile.get("tilt_center", default_tilt_center)),
            "pan_tilt_speed": 0,
            "dimmer": clamp_dmx(round(dimmer_min + (dimmer_max - dimmer_min) * pulse_phase)),
        }
    elif pattern == "blackout_hit":
        hit_phase = beat_value % 1.0
        blackout_open = hit_phase < float(profile.get("blackout_window", 0.14))
        dimmer_min = int(profile.get("dimmer_min", 0))
        dimmer_max = int(profile.get("dimmer_max", 255))
        motion = {
            "pan": int(profile.get("pan_center", 128)),
            "tilt": int(profile.get("tilt_center", default_tilt_center)),
            "pan_tilt_speed": 0,
            "dimmer": dimmer_min if blackout_open else dimmer_max,
        }
    elif pattern == "rising_sweep":
        sweep_phase = adjusted_beat / 24.0
        tilt_amount = 0.5 + 0.5 * wave_triangle(sweep_phase / 1.8)
        tilt_min = int(profile.get("tilt_min", 145))
        tilt_max = int(profile.get("tilt_max", 220))
        dimmer_min = int(profile.get("dimmer_min", 120))
        dimmer_max = int(profile.get("dimmer_max", 255))
        motion = {
            "pan": clamp_motion(
                profile.get("pan_center", 128),
                profile.get("pan_wave", 88),
                wave_sine(sweep_phase),
            ),
            "tilt": clamp_dmx(round(tilt_min + (tilt_max - tilt_min) * tilt_amount)),
            "pan_tilt_speed": 0,
            "dimmer": clamp_dmx(round(dimmer_min + (dimmer_max - dimmer_min) * tilt_amount)),
        }
    elif pattern == "fan_morph":
        morph_phase = 0.5 + 0.5 * wave_sine(adjusted_beat / 20.0)
        if morph_phase <= 0.5:
            amount = morph_phase * 2.0
            positions_a = profile.get("positions_start_4", [115, 125, 135, 145]) if span_count >= 4 else profile.get("positions_start_2", [122, 134])
            positions_b = profile.get("positions_mid_4", [90, 115, 140, 165]) if span_count >= 4 else profile.get("positions_mid_2", [112, 144])
        else:
            amount = (morph_phase - 0.5) * 2.0
            positions_a = profile.get("positions_mid_4", [90, 115, 140, 165]) if span_count >= 4 else profile.get("positions_mid_2", [112, 144])
            positions_b = profile.get("positions_end_4", [60, 105, 150, 195]) if span_count >= 4 else profile.get("positions_end_2", [105, 150])
        pan_a = positions_a[min(len(positions_a) - 1, span_index if len(positions_a) > 1 else 0)]
        pan_b = positions_b[min(len(positions_b) - 1, span_index if len(positions_b) > 1 else 0)]
        dimmer_min = int(profile.get("dimmer_min", 150))
        dimmer_max = int(profile.get("dimmer_max", 255))
        motion = {
            "pan": clamp_dmx(round(pan_a + (pan_b - pan_a) * amount)),
            "tilt": clamp_dmx(int(profile.get("tilt_static", 180))),
            "pan_tilt_speed": 0,
            "dimmer": clamp_dmx(round(dimmer_min + (dimmer_max - dimmer_min) * morph_phase)),
        }
    elif pattern == "fan_open":
        fan_anchor = member_centered if span_count > 1 else group_centered
        fan_width = profile.get("fan_width", 88)
        if use_taught_poses and pose_audience_left and (pose_audience_center or pose_center or pose_audience_right):
            center_tilt = _safe_pose_tilt(pose_audience_center or pose_center, default_tilt_center)
            if span_count == 2:
                fraction = [0.35, 0.65][min(1, span_index)]
            else:
                fraction = 0.5 if span_count <= 1 else span_index / max(1, span_count - 1)
            fan_pose = _interpolate_pose_path(
                pose_audience_left,
                pose_audience_center or pose_center,
                pose_audience_right,
                fraction,
            )
            motion = {
                "pan": fan_pose["pan"],
                "tilt": center_tilt,
                "pan_tilt_speed": 0,
            }
        elif span_count >= 4:
            fan_positions = profile.get("fan_positions_4", [60, 105, 150, 195])
            fan_position = fan_positions[min(len(fan_positions) - 1, span_index)]
            motion = {
                "pan": fan_position,
                "tilt": int(profile.get("tilt_center", default_tilt_center)),
                "pan_tilt_speed": 0,
            }
        elif span_count == 2:
            fan_positions = profile.get("fan_positions_2", [105, 150])
            motion = {
                "pan": fan_positions[min(len(fan_positions) - 1, span_index)],
                "tilt": int(profile.get("tilt_center", default_tilt_center)),
                "pan_tilt_speed": 0,
            }
        else:
            motion = {
                "pan": clamp_motion(128, fan_width * 0.5, fan_anchor * 2.0),
                "tilt": default_tilt_center,
                "pan_tilt_speed": 0,
            }
        if use_taught_poses and raw_pan_left is not None and raw_pan_right is not None:
            if span_count == 2:
                fraction = [0.35, 0.65][min(1, span_index)]
            else:
                fraction = 0.5 if span_count <= 1 else span_index / max(1, span_count - 1)
            pan_value = _interpolate_scalar_path(raw_pan_left, raw_pan_center, raw_pan_right, fraction)
            if pan_value is not None:
                motion["pan"] = clamp_dmx(pan_value)
            motion["tilt"] = clamp_dmx(default_tilt_center)
    elif pattern == "fan_wave":
        fan_phase = adjusted_beat / 24.0
        tilt_phase_scale = _profile_tilt_phase_scale(profile, 1.0)
        fan_anchor = member_centered if span_count > 1 else group_centered
        fan_width = profile.get("fan_width", 92)
        fan_tilt_min = profile.get("fan_wave_tilt_min")
        fan_tilt_max = profile.get("fan_wave_tilt_max")
        fan_tilt_wave = wave_sine(
            (fan_phase * tilt_phase_scale) / 1.8
            + fan_anchor * 0.12
            + _profile_tilt_phase_offset(profile, 0.0)
        )
        if use_taught_poses and pose_audience_left and (pose_audience_center or pose_center or pose_audience_right):
            if span_count == 2:
                fraction = [0.35, 0.65][min(1, span_index)]
            else:
                fraction = 0.5 if span_count <= 1 else span_index / max(1, span_count - 1)
            base_pose = _interpolate_pose_path(
                pose_audience_left,
                pose_audience_center or pose_center,
                pose_audience_right,
                fraction,
            )
            if vertical_pose_available:
                low_tilt = int((pose_audience_center or pose_center)["tilt"])
                high_tilt = int(pose_ceiling_center["tilt"])
                tilt_center = round((low_tilt + high_tilt) * 0.5)
                tilt_wave = max(8, abs(high_tilt - low_tilt) // 2)
            else:
                tilt_center = default_tilt_center
                tilt_wave = 24
            if fan_tilt_min is not None and fan_tilt_max is not None:
                tilt_value = round(float(fan_tilt_min) + (float(fan_tilt_max) - float(fan_tilt_min)) * (0.5 + 0.5 * fan_tilt_wave))
            else:
                tilt_value = clamp_motion(
                    tilt_center,
                    tilt_wave,
                    fan_tilt_wave,
                )
            motion = {
                "pan": clamp_motion(
                    base_pose["pan"],
                    10 + movement_scale * 8,
                    wave_sine(fan_phase),
                ),
                "tilt": clamp_dmx(tilt_value),
                "pan_tilt_speed": 0,
            }
        elif span_count >= 4:
            pan_positions = profile.get("fan_wave_pan_positions_4", [70, 110, 150, 190])
            pan_center = pan_positions[min(len(pan_positions) - 1, span_index)]
            if fan_tilt_min is not None and fan_tilt_max is not None:
                tilt_value = round(float(fan_tilt_min) + (float(fan_tilt_max) - float(fan_tilt_min)) * (0.5 + 0.5 * fan_tilt_wave))
            else:
                tilt_centers = profile.get("fan_wave_tilt_centers_4", [130, 150, 130, 150])
                tilt_center = tilt_centers[min(len(tilt_centers) - 1, span_index)]
                tilt_value = clamp_motion(
                    tilt_center,
                    int(profile.get("fan_wave_tilt_wave", 40)),
                    fan_tilt_wave,
                )
            motion = {
                "pan": clamp_motion(
                    pan_center,
                    10 + movement_scale * 8,
                    wave_sine(fan_phase),
                ),
                "tilt": clamp_dmx(tilt_value),
                "pan_tilt_speed": 0,
            }
        elif span_count == 2:
            pan_positions = profile.get("fan_wave_pan_positions_2", [110, 150])
            pan_center = pan_positions[min(len(pan_positions) - 1, span_index)]
            if fan_tilt_min is not None and fan_tilt_max is not None:
                tilt_value = round(float(fan_tilt_min) + (float(fan_tilt_max) - float(fan_tilt_min)) * (0.5 + 0.5 * fan_tilt_wave))
            else:
                tilt_centers = profile.get("fan_wave_tilt_centers_2", [130, 150])
                tilt_center = tilt_centers[min(len(tilt_centers) - 1, span_index)]
                tilt_value = clamp_motion(
                    tilt_center,
                    int(profile.get("fan_wave_tilt_wave", 40)),
                    fan_tilt_wave,
                )
            motion = {
                "pan": clamp_motion(
                    pan_center,
                    8 + movement_scale * 6,
                    wave_sine(fan_phase),
                ),
                "tilt": clamp_dmx(tilt_value),
                "pan_tilt_speed": 0,
            }
        else:
            if fan_tilt_min is not None and fan_tilt_max is not None:
                tilt_value = round(float(fan_tilt_min) + (float(fan_tilt_max) - float(fan_tilt_min)) * (0.5 + 0.5 * fan_tilt_wave))
            else:
                tilt_value = clamp_motion(
                    216,
                    30,
                    fan_tilt_wave,
                )
            motion = {
                "pan": clamp_motion(
                    128 + fan_anchor * fan_width * 0.45,
                    18 + movement_scale * 14,
                    wave_sine(fan_phase),
                ),
                "tilt": clamp_dmx(tilt_value),
                "pan_tilt_speed": 0,
            }
        if use_taught_poses and raw_pan_left is not None and raw_pan_right is not None:
            if span_count == 2:
                fraction = [0.35, 0.65][min(1, span_index)]
            else:
                fraction = 0.5 if span_count <= 1 else span_index / max(1, span_count - 1)
            base_pan = _interpolate_scalar_path(raw_pan_left, raw_pan_center, raw_pan_right, fraction)
            if base_pan is not None:
                motion["pan"] = clamp_dmx(round(base_pan + wave_sine(fan_phase) * (10 + movement_scale * 8)))
            if raw_vertical_path_available:
                low_tilt = default_tilt_center
                high_tilt = pose_ceiling_center["tilt"] if pose_ceiling_center else raw_tilt_back
                if fan_tilt_min is not None and fan_tilt_max is not None:
                    motion["tilt"] = clamp_dmx(
                        round(float(fan_tilt_min) + (float(fan_tilt_max) - float(fan_tilt_min)) * (0.5 + 0.5 * fan_tilt_wave))
                    )
                else:
                    tilt_center = round((low_tilt + high_tilt) * 0.5)
                    tilt_wave = max(8, abs(high_tilt - low_tilt) // 2)
                    motion["tilt"] = clamp_motion(
                        tilt_center,
                        tilt_wave,
                        fan_tilt_wave,
                    )
    elif pattern == "crossing_beams":
        if use_taught_poses and pose_audience_left and (pose_audience_center or pose_center or pose_audience_right):
            fractions_a = [0.0, 0.28, 0.72, 1.0]
            fractions_b = list(reversed(fractions_a))
            fractions = fractions_a if (int(math.floor(beat_value / 4.0)) % 2 == 0) else fractions_b
            if span_count == 2:
                pair_fractions = [0.28, 0.72] if (int(math.floor(beat_value / 4.0)) % 2 == 0) else [0.72, 0.28]
                fraction = pair_fractions[min(1, span_index)]
            else:
                fraction = fractions[min(len(fractions) - 1, span_index)]
            cross_pose = _interpolate_pose_path(
                pose_audience_left,
                pose_audience_center or pose_center,
                pose_audience_right,
                fraction,
            )
            pan_value = cross_pose["pan"]
            tilt_value = _safe_pose_tilt(pose_audience_center or pose_center, 214)
        else:
            state_a = profile.get("crossing_frames_4", [(60, 150), (100, 150), (156, 150), (196, 150)])
            state_b = list(reversed(state_a))
            frame = state_a if (int(math.floor(beat_value / 4.0)) % 2 == 0) else state_b
            if span_count == 2:
                compact_frame = profile.get("crossing_frames_2", [(100, 150), (156, 150)])
                compact_frame = compact_frame if (int(math.floor(beat_value / 4.0)) % 2 == 0) else list(reversed(compact_frame))
                pan_value, tilt_value = compact_frame[min(len(compact_frame) - 1, span_index)]
            else:
                pan_value, tilt_value = frame[min(len(frame) - 1, span_index)]
        motion = {
            "pan": pan_value,
            "tilt": tilt_value,
            "pan_tilt_speed": 0,
            "rgbw": (255, 255, 255, 255),
        }
        if use_taught_poses and raw_pan_left is not None and raw_pan_right is not None:
            fractions_a = [0.0, 0.28, 0.72, 1.0]
            fractions_b = list(reversed(fractions_a))
            fractions = fractions_a if (int(math.floor(beat_value / 4.0)) % 2 == 0) else fractions_b
            if span_count == 2:
                pair_fractions = [0.28, 0.72] if (int(math.floor(beat_value / 4.0)) % 2 == 0) else [0.72, 0.28]
                fraction = pair_fractions[min(1, span_index)]
            else:
                fraction = fractions[min(len(fractions) - 1, span_index)]
            raw_pan = _interpolate_scalar_path(raw_pan_left, raw_pan_center, raw_pan_right, fraction)
            if raw_pan is not None:
                motion["pan"] = clamp_dmx(raw_pan)
            motion["tilt"] = clamp_dmx(default_tilt_center)
    elif pattern == "mirror_bounce":
        bounce_phase = adjusted_beat / 16.0
        motion = {
            "pan": clamp_motion(
                profile.get("pan_center", 128),
                profile.get("pan_wave", 68),
                wave_triangle(bounce_phase),
            ),
            "tilt": clamp_motion(
                profile.get("tilt_center", 125),
                profile.get("tilt_wave", 55),
                wave_triangle(
                    (
                        bounce_phase * _profile_tilt_phase_scale(profile, 1.0)
                        + _profile_tilt_phase_offset(profile, 0.0)
                    )
                    / 1.9
                ),
            ),
            "pan_tilt_speed": 0,
        }
    elif pattern == "pulse_circle":
        circle_phase = adjusted_beat / 28.0
        tilt_phase = circle_phase * _profile_tilt_phase_scale(profile, 1.0) + _profile_tilt_phase_offset(profile, 0.0)
        dimmer_phase = 0.5 + 0.5 * wave_sine(circle_phase)
        dimmer_min = int(profile.get("dimmer_min", 80))
        dimmer_max = int(profile.get("dimmer_max", 255))
        motion = {
            "pan": clamp_motion(
                profile.get("pan_center", 128),
                profile.get("pan_wave", 55),
                wave_sine(circle_phase),
            ),
            "tilt": clamp_motion(
                profile.get("tilt_center", 128),
                profile.get("tilt_wave", 35),
                wave_cosine(tilt_phase),
            ),
            "pan_tilt_speed": 0,
            "dimmer": clamp_dmx(round(dimmer_min + dimmer_phase * (dimmer_max - dimmer_min))),
            "rgbw": tuple(profile.get("rgbw", (0, 80, 255, 80))),
        }
    elif pattern == "smooth_sweep":
        sweep_phase = adjusted_beat / 28.0
        tilt_phase = sweep_phase * _profile_tilt_phase_scale(profile, 1.0) + _profile_tilt_phase_offset(profile, 0.0)
        pan_amount = profile.get("pan_base", 32) + movement_scale * profile.get("pan_extra", 18)
        tilt_base = profile.get("tilt_base", 152)
        tilt_wave = profile.get("tilt_wave", 10) + movement_scale * profile.get("tilt_extra", 0)
        motion = {
            "pan": clamp_motion(127, pan_amount, wave_sine(sweep_phase)),
            "tilt": clamp_motion(
                tilt_base,
                tilt_wave,
                wave_sine(tilt_phase / 2.0),
            ),
            "pan_tilt_speed": 0,
        }
    elif pattern == "arc_sweep":
        sweep_phase = adjusted_beat / 28.0
        tilt_phase = sweep_phase * _profile_tilt_phase_scale(profile, 1.0) + _profile_tilt_phase_offset(profile, 0.0)
        pan_amount = profile.get("pan_base", 36) + movement_scale * profile.get("pan_extra", 20)
        tilt_base = profile.get("tilt_base", 148)
        tilt_wave = profile.get("tilt_wave", 16) + movement_scale * profile.get("tilt_extra", 0)
        motion = {
            "pan": clamp_motion(127, pan_amount, wave_sine(sweep_phase)),
            "tilt": clamp_motion(
                tilt_base,
                tilt_wave,
                wave_triangle(tilt_phase / 1.8),
            ),
            "pan_tilt_speed": 0,
        }
    elif pattern == "tilt_sweep":
        sweep_phase = adjusted_beat / 32.0
        tilt_phase = sweep_phase * _profile_tilt_phase_scale(profile, 1.0) + _profile_tilt_phase_offset(profile, 0.0)
        pan_amount = profile.get("pan_base", 26) + movement_scale * profile.get("pan_extra", 14)
        tilt_base = profile.get("tilt_base", 178)
        tilt_wave = profile.get("tilt_wave", 8) + movement_scale * profile.get("tilt_extra", 0)
        motion = {
            "pan": clamp_motion(127, pan_amount, wave_sine(sweep_phase)),
            "tilt": clamp_motion(
                tilt_base,
                tilt_wave,
                wave_sine(tilt_phase / 2.4),
            ),
            "pan_tilt_speed": 0,
        }
    elif pattern == "pendulum":
        motion = {
            "pan": clamp_motion(127, 42 + movement_scale * 54, wave_triangle(adjusted_beat / 2.0)),
            "tilt": clamp_motion(150, 12 + movement_scale * 18, wave_sine(adjusted_beat / 5.0 + group_centered * 0.6)),
            "pan_tilt_speed": 0,
        }
    elif pattern == "ripple":
        motion = {
            "pan": clamp_motion(127, 46 + movement_scale * 44, wave_sine(adjusted_beat / 2.4 + group_index * 0.35)),
            "tilt": clamp_motion(142, 16 + movement_scale * 18, wave_triangle(adjusted_beat / 3.8 + group_index * 0.22)),
            "pan_tilt_speed": 0,
        }
    elif pattern == "helix":
        motion = {
            "pan": clamp_motion(127, 52 + movement_scale * 42, wave_sine(adjusted_beat / 1.8 + group_centered * 0.4)),
            "tilt": clamp_motion(132, 24 + movement_scale * 24, wave_sine(adjusted_beat / 1.8 + 0.25 + group_index * 0.18)),
            "pan_tilt_speed": 0,
        }
    elif pattern == "criss_cross":
        motion = {
            "pan": clamp_motion(127, 62 + movement_scale * 34, wave_triangle(adjusted_beat / 1.4 + group_index * 0.12)),
            "tilt": clamp_motion(136, 16 + movement_scale * 16, wave_square(adjusted_beat / 2.0 + group_alternate * 0.1)),
            "pan_tilt_speed": 0,
        }
    elif pattern == "ladder":
        step_phase = int((adjusted_beat * 0.75 + group_index * 0.25) % 4)
        pan_steps = [72, 112, 148, 188]
        tilt_steps = [156, 142, 128, 116]
        motion = {
            "pan": clamp_dmx(pan_steps[step_phase]),
            "tilt": clamp_dmx(tilt_steps[(step_phase + group_index) % 4]),
            "pan_tilt_speed": 0,
        }
    if not motion:
        return None

    pan = float(motion["pan"])
    tilt = float(motion["tilt"])
    if profile["mirror"] and group_alternate < 0:
        pan = 254.0 - pan

    spread = (18.0 + movement_scale * 28.0) * profile["spread"]
    pan += group_centered * spread

    phase = beat_value * math.tau * profile["phase_scale"] * 0.18
    pan += math.sin(phase) * profile["orbit_pan"] * (0.45 + movement_scale)
    tilt += math.cos(phase * 0.72 + group_centered * 0.20) * profile["orbit_tilt"] * (0.35 + movement_scale)
    tilt += group_center_bias * profile["tilt_lift"]
    tilt -= group_edge_bias * profile["edge_drop"] * (0.60 + movement_scale)

    if profile["snap"]:
        pan += wave_square(beat_value * 0.5 + group_index * 0.17) * profile["snap"] * (
            0.35 + movement_scale
        )

    result = {
        "pan": clamp_dmx(round(pan)),
        "tilt": clamp_dmx(round(tilt)),
        "pan_tilt_speed": motion["pan_tilt_speed"],
    }
    result["tilt"] = _expand_motion_tilt_range(
        result["tilt"],
        pattern,
        profile,
        movement_scale,
        default_tilt_center,
    )
    for key in ("dimmer", "strobe", "program", "speed", "rgbw"):
        if key in motion:
            result[key] = motion[key]

    if "rgbw" not in result and profile.get("rgbw") is not None:
        result["rgbw"] = tuple(profile.get("rgbw"))

    if "dimmer" not in result and profile.get("dimmer_static") is not None:
        result["dimmer"] = clamp_dmx(profile.get("dimmer_static"))

    if "program" not in result and profile.get("program_static") is not None:
        result["program"] = clamp_dmx(profile.get("program_static"))

    if "speed" not in result and profile.get("program_speed_static") is not None:
        result["speed"] = clamp_dmx(profile.get("program_speed_static"))

    if "strobe" not in result and profile.get("strobe_static") is not None:
        result["strobe"] = clamp_dmx(profile.get("strobe_static"))

    if "strobe" not in result and "strobe_min" in profile:
        strobe_min = int(profile.get("strobe_min", 0))
        strobe_max = int(profile.get("strobe_max", strobe_min))
        result["strobe"] = clamp_dmx(
            round(strobe_min + movement_scale * max(0, strobe_max - strobe_min))
        )

    if "program" not in result and "color_program_min" in profile:
        program_min = int(profile.get("color_program_min", 232))
        program_max = int(profile.get("color_program_max", program_min))
        jump_phase = 0.5 + 0.5 * wave_sine(adjusted_beat / 5.0 + group_index * 0.11)
        result["program"] = clamp_dmx(
            round(program_min + jump_phase * max(0, program_max - program_min))
        )

    if "speed" not in result and "color_speed_min" in profile:
        color_speed_min = int(profile.get("color_speed_min", 80))
        color_speed_max = int(profile.get("color_speed_max", color_speed_min))
        result["speed"] = clamp_dmx(
            round(color_speed_max - movement_scale * max(0, color_speed_max - color_speed_min))
        )

    return result


def maybe_apply_member_mirror(motion, slot_context, enabled, config=None):
    if not motion or not enabled or not slot_context:
        return motion
    member_count = max(1, int(slot_context.get("member_count", 1)))
    if member_count != 2:
        return motion
    member_alternate = float(slot_context.get("member_alternate", slot_context.get("alternate", 1.0)))
    if member_alternate >= 0:
        return motion
    mirror_center_pan = None
    if isinstance(config, dict):
        pose_center = _slot_pose(config, "pose_center") or _slot_pose(config, "pose_audience_center")
        if pose_center:
            mirror_center_pan = pose_center["pan"]
        elif config.get("pan_left_value") is not None and config.get("pan_right_value") is not None:
            mirror_center_pan = round((int(config.get("pan_left_value")) + int(config.get("pan_right_value"))) / 2.0)
    if mirror_center_pan is None:
        mirror_center_pan = 127
    mirrored = dict(motion)
    mirrored["pan"] = clamp_dmx(round(float(mirror_center_pan) * 2.0 - int(motion["pan"])))
    mirrored["tilt"] = clamp_dmx(int(motion["tilt"]))
    return mirrored


class OscListener:
    def __init__(self, port=DEFAULT_OSC_PORT):
        self.port = port
        self.debug_log = TRIGGER_LOG
        self.lock = threading.Lock()
        self.socket = None
        self.thread = None
        self.running = False
        self.error = None
        self.message_count = 0
        self.last_received_at = None
        self.last_message = None
        self.bpm = None
        self.beat = None
        self.beat_total = None
        self.beat_cycle_offset = 0.0
        self.beat_updated_at = None
        self.last_tick_index = None
        self.last_tick_at = None
        self.time_seconds = None
        self.time_updated_at = None
        self.phrase_current = None
        self.phrase_next = None
        self.phrase_count_in = None
        self.phrase_count_in_updated_at = None
        self.mood = None
        self.color_bank = None
        self.waveform_energy = None
        self.waveform_energy_updated_at = None
        self.audio_bands = self._empty_band_state()
        self.audio_bands_updated_at = None
        self.audio_drums = self._empty_trigger_state()
        self.waveform_bands = self._empty_band_state()
        self.waveform_bands_updated_at = None
        self.waveform_lookahead = self._empty_lookahead_state()
        self.waveform_samples = deque(maxlen=480)
        self.waveform_state_name = "neutral"
        self.waveform_state_changed_at = 0.0
        self.waveform_state_candidate = None
        self.waveform_state_candidate_since = None
        self.drum_signals = self._empty_trigger_state()
        self.strobe_active = False
        self.strobe_count_in = None
        self.track_title = None
        self.track_artist = None
        self.track_album = None
        self.decks = {}
        self.last_beat_index = None
        self.last_beat_at = None

    def start(self):
        self.stop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", self.port))
        sock.settimeout(0.25)

        with self.lock:
            self.socket = sock
            self.running = True
            self.error = None

        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        with self.lock:
            sock = self.socket
            thread = self.thread
            self.running = False
            self.socket = None
            self.thread = None

        if sock:
            with suppress(Exception):
                sock.close()
        if thread and thread.is_alive():
            thread.join(timeout=1.0)

    def state(self):
        with self.lock:
            now = time.time()
            stale = (
                self.last_received_at is None
                or now - self.last_received_at > 3.0
            )
            beat_display = self._continuous_beat_display(now)
            beat_phase_age_seconds = self._continuous_beat_phase_age_seconds(now)
            phrase_countdown_beats = self._continuous_phrase_countdown(now)
            phrase_countdown_seconds = None
            if phrase_countdown_beats is not None and self.bpm and self.bpm > 0:
                phrase_countdown_seconds = phrase_countdown_beats * 60.0 / self.bpm
            time_display_seconds = self._resolved_time_display_seconds(now)
            track_title = self.track_title or self._deck_fallback_value("track_title")
            track_artist = self.track_artist or self._deck_fallback_value("track_artist")
            track_album = self.track_album or self._deck_fallback_value("track_album")
            phrase_current = self._resolved_phrase_current()
            phrase_next = self._resolved_phrase_next()
            raw_color_bank = (
                self.color_bank
                if self.color_bank is not None
                else self._deck_fallback_value("color_bank")
            )
            color_bank = derive_color_bank_value(
                raw_color_bank,
                phrase=phrase_current or phrase_next,
                track_title=track_title,
                track_artist=track_artist,
                track_album=track_album,
            )
            base_mood = derive_mood_value(
                self.mood if self.mood is not None else self._deck_fallback_value("mood"),
                phrase=phrase_current,
                color_bank=color_bank,
            )
            waveform_energy = self._resolved_waveform_energy(now)
            audio_bands = self._resolved_audio_bands(now)
            waveform_bands = self._resolved_waveform_bands(now)
            waveform_lookahead = self._resolved_waveform_lookahead(now)
            waveform_analysis = self._resolved_waveform_analysis(now)
            audio_drums = self._resolved_audio_drums(now)
            drum_signals = self._resolved_drum_signals(now)
            mood = refine_mood_with_waveform(
                base_mood,
                phrase=phrase_current or phrase_next,
                analysis=waveform_analysis,
            )
            return {
                "port": self.port,
                "running": self.running,
                "stale": stale,
                "error": self.error,
                "message_count": self.message_count,
                "last_received_at": self.last_received_at,
                "last_message": self.last_message,
                "bpm": self.bpm,
                "beat": self.beat,
                "beat_display": beat_display,
                "beat_phase_age_seconds": beat_phase_age_seconds,
                "time_seconds": self._resolved_time_seconds(),
                "time_display_seconds": time_display_seconds,
                "phrase_current": phrase_current,
                "phrase_next": phrase_next,
                "phrase_count_in": self.phrase_count_in,
                "phrase_countdown_beats": phrase_countdown_beats,
                "phrase_countdown_seconds": phrase_countdown_seconds,
                "mood": mood,
                "color_bank": color_bank,
                "waveform_energy": waveform_energy,
                "audio_bands": audio_bands,
                "waveform_bands": waveform_bands,
                "waveform_lookahead": waveform_lookahead,
                "waveform_analysis": waveform_analysis,
                "audio_drums": audio_drums,
                "drum_signals": drum_signals,
                "strobe_active": self.strobe_active,
                "strobe_count_in": self.strobe_count_in,
                "track_title": track_title,
                "track_artist": track_artist,
                "track_album": track_album,
                "decks": {
                    deck_id: self._public_deck_state(deck_state, now)
                    for deck_id, deck_state in sorted(
                        self.decks.items(),
                        key=lambda item: (
                            0,
                            int(item[0]),
                        )
                        if item[0].isdigit()
                        else (1, str(item[0])),
                    )
                },
                "last_beat_at": self.last_beat_at,
            }

    def snapshot_for_render(self):
        with self.lock:
            now = time.time()
            track_title = self.track_title or self._deck_fallback_value("track_title")
            track_artist = self.track_artist or self._deck_fallback_value("track_artist")
            track_album = self.track_album or self._deck_fallback_value("track_album")
            phrase_current = self._resolved_phrase_current()
            phrase_next = self._resolved_phrase_next()
            raw_color_bank = (
                self.color_bank
                if self.color_bank is not None
                else self._deck_fallback_value("color_bank")
            )
            color_bank = derive_color_bank_value(
                raw_color_bank,
                phrase=phrase_current or phrase_next,
                track_title=track_title,
                track_artist=track_artist,
                track_album=track_album,
            )
            base_mood = derive_mood_value(
                self.mood if self.mood is not None else self._deck_fallback_value("mood"),
                phrase=phrase_current,
                color_bank=color_bank,
            )
            waveform_energy = self._resolved_waveform_energy(now)
            audio_bands = self._resolved_audio_bands(now)
            waveform_bands = self._resolved_waveform_bands(now)
            waveform_lookahead = self._resolved_waveform_lookahead(now)
            waveform_analysis = self._resolved_waveform_analysis(now)
            audio_drums = self._resolved_audio_drums(now)
            drum_signals = self._resolved_drum_signals(now)
            mood = refine_mood_with_waveform(
                base_mood,
                phrase=phrase_current or phrase_next,
                analysis=waveform_analysis,
            )
            return {
                "bpm": self.bpm,
                "beat": self.beat,
                "beat_value": self._continuous_beat_value(now),
                "beat_display": self._continuous_beat_display(now),
                "beat_phase_age_seconds": self._continuous_beat_phase_age_seconds(now),
                "time_seconds": self._resolved_time_seconds(),
                "time_display_seconds": self._resolved_time_display_seconds(now),
                "phrase_current": phrase_current,
                "phrase_next": phrase_next,
                "mood": mood,
                "color_bank": color_bank,
                "waveform_energy": waveform_energy,
                "audio_bands": audio_bands,
                "waveform_bands": waveform_bands,
                "waveform_lookahead": waveform_lookahead,
                "waveform_analysis": waveform_analysis,
                "audio_drums": audio_drums,
                "drum_signals": drum_signals,
                "strobe_active": self.strobe_active,
                "strobe_count_in": self.strobe_count_in,
                "track_title": track_title,
                "track_artist": track_artist,
                "track_album": track_album,
                "last_beat_at": self.last_beat_at,
                "stale": self.last_received_at is None or now - self.last_received_at > 3.0,
            }

    def _loop(self):
        while True:
            with self.lock:
                if not self.running or not self.socket:
                    return
                sock = self.socket
            try:
                data, source = sock.recvfrom(8192)
            except socket.timeout:
                continue
            except OSError:
                return
            except Exception as exc:
                with self.lock:
                    self.error = str(exc)
                continue

            message = parse_osc_message(data)
            if message:
                self._handle_message(message, source)

    def _handle_message(self, message, source):
        address = message["address"]
        numeric = message["numeric"]
        text = message["text"]
        now = time.time()

        with self.lock:
            self.message_count += 1
            self.last_received_at = now
            self.last_message = {
                "address": address,
                "numeric": numeric,
                "text": text,
                "source": f"{source[0]}:{source[1]}",
            }

            parts = [part for part in address.split("/") if part]
            if address in ("/bpm/master/current", "/master/bpm/current") and numeric:
                self.bpm = numeric
            elif address in ("/beat/master", "/master/beat") and numeric is not None:
                previous_beat = self.beat
                self.beat = numeric
                if previous_beat is not None:
                    # Rekordbox/BPM Trigger stuurt beat doorgaans als een 4-beat fase
                    # (0..4). Voor bewegingen hebben we een doorlopende teller nodig,
                    # anders resetten sweeps elke maat terug naar hun beginpunt.
                    if numeric < 1.0 and previous_beat > 3.0:
                        self.beat_cycle_offset += 4.0
                    elif numeric + 2.0 < previous_beat:
                        # Veilige fallback bij onregelmatige wrap/jitter.
                        self.beat_cycle_offset += 4.0
                self.beat_total = self.beat_cycle_offset + float(numeric)
                self.beat_updated_at = now
                tick_index = int(math.floor(max(0.0, self.beat_total) * 24.0))
                if self.last_tick_index is None or tick_index != self.last_tick_index:
                    self.last_tick_index = tick_index
                    self.last_tick_at = now
                beat_index = tick_index // 24
                if self.last_beat_index is None or beat_index != self.last_beat_index:
                    self.last_beat_index = beat_index
                    self.last_beat_at = now
            elif address == "/master/time" and numeric is not None:
                self.time_seconds = numeric
                self.time_updated_at = now
            elif address == "/master/track/title":
                if text != self.track_title:
                    self.debug_log.log("OSC_TRACK", scope="master", title=text)
                self.track_title = text
            elif address == "/master/track/artist":
                self.track_artist = text
            elif address == "/master/track/album":
                self.track_album = text
            elif address in ("/master/phrase/current", "/phrase/master/current"):
                phrase_value = text if text not in (None, "") else numeric
                if phrase_value != self.phrase_current:
                    self.debug_log.log("OSC_PHRASE", scope="master", current=phrase_value)
                self.phrase_current = phrase_value
            elif address in ("/master/phrase/next", "/phrase/master/next"):
                phrase_value = text if text not in (None, "") else numeric
                if phrase_value != self.phrase_next:
                    self.debug_log.log("OSC_PHRASE_NEXT", scope="master", next=phrase_value)
                self.phrase_next = phrase_value
            elif address == "/master/phrase/countin" and numeric is not None:
                count_in = max(0, int(round(numeric)))
                if count_in != self.phrase_count_in:
                    self.debug_log.log("OSC_COUNTIN", scope="master", beats=count_in)
                self.phrase_count_in = count_in
                self.phrase_count_in_updated_at = now
            elif address in ("/master/mood", "/mood/master") and numeric is not None:
                if numeric != self.mood:
                    self.debug_log.log("OSC_MOOD", scope="master", value=numeric)
                self.mood = numeric
            elif address in ("/master/color_bank", "/color_bank/master") and numeric is not None:
                bank_value = int(round(numeric))
                if bank_value != self.color_bank:
                    self.debug_log.log("OSC_BANK", scope="master", value=bank_value)
                self.color_bank = bank_value
            elif address in ("/master/waveform/energy", "/waveform/master/energy") and numeric is not None:
                self.waveform_energy = clamp_unit(numeric)
                self.waveform_energy_updated_at = now
                self._append_waveform_sample(self.waveform_samples, now, self.waveform_energy)
            elif address in ("/master/audio/low_energy", "/audio/master/low_energy") and numeric is not None:
                self._update_waveform_band(self.audio_bands, self.audio_drums, "low", numeric, now)
                self.audio_bands_updated_at = now
            elif address in ("/master/audio/mid_energy", "/audio/master/mid_energy") and numeric is not None:
                self._update_waveform_band(self.audio_bands, self.audio_drums, "mid", numeric, now)
                self.audio_bands_updated_at = now
            elif address in ("/master/audio/high_energy", "/audio/master/high_energy") and numeric is not None:
                self._update_waveform_band(self.audio_bands, self.audio_drums, "high", numeric, now)
                self.audio_bands_updated_at = now
            elif address in ("/master/audio/kick", "/audio/master/kick") and numeric is not None:
                self._set_trigger_signal(self.audio_drums, "kick", numeric, now)
            elif address in ("/master/audio/snare", "/audio/master/snare") and numeric is not None:
                self._set_trigger_signal(self.audio_drums, "snare", numeric, now)
            elif address in ("/master/audio/hihat", "/audio/master/hihat") and numeric is not None:
                self._set_trigger_signal(self.audio_drums, "hihat", numeric, now)
            elif address in ("/master/waveform/low_energy", "/waveform/master/low_energy") and numeric is not None:
                self._update_waveform_band(self.waveform_bands, self.drum_signals, "low", numeric, now)
                self.waveform_bands_updated_at = now
            elif address in ("/master/waveform/mid_energy", "/waveform/master/mid_energy") and numeric is not None:
                self._update_waveform_band(self.waveform_bands, self.drum_signals, "mid", numeric, now)
                self.waveform_bands_updated_at = now
            elif address in ("/master/waveform/high_energy", "/waveform/master/high_energy") and numeric is not None:
                self._update_waveform_band(self.waveform_bands, self.drum_signals, "high", numeric, now)
                self.waveform_bands_updated_at = now
            elif (
                len(parts) >= 5
                and (
                    parts[:3] == ["master", "waveform", "lookahead"]
                    or parts[:3] == ["waveform", "master", "lookahead"]
                )
                and numeric is not None
            ):
                beats_ahead = str(parts[3])
                band_key = parts[4]
                if beats_ahead in self.waveform_lookahead and band_key in ("low_energy", "mid_energy", "high_energy"):
                    channel = band_key.split("_", 1)[0]
                    lookahead_state = self.waveform_lookahead[beats_ahead]
                    self._update_waveform_band(lookahead_state, None, channel, numeric, now)
            elif address in ("/master/waveform/low_onset", "/waveform/master/low_onset") and numeric is not None:
                self._set_trigger_signal(self.drum_signals, "low_onset", numeric, now)
            elif address in ("/master/waveform/mid_onset", "/waveform/master/mid_onset") and numeric is not None:
                self._set_trigger_signal(self.drum_signals, "mid_onset", numeric, now)
            elif address in ("/master/waveform/high_onset", "/waveform/master/high_onset") and numeric is not None:
                self._set_trigger_signal(self.drum_signals, "high_onset", numeric, now)
            elif address in ("/master/drums/kick", "/drums/master/kick") and numeric is not None:
                self._set_trigger_signal(self.drum_signals, "kick", numeric, now)
            elif address in ("/master/drums/snare", "/drums/master/snare") and numeric is not None:
                self._set_trigger_signal(self.drum_signals, "snare", numeric, now)
            elif address in ("/master/drums/hihat", "/drums/master/hihat") and numeric is not None:
                self._set_trigger_signal(self.drum_signals, "hihat", numeric, now)
            elif address in ("/master/strobe/active", "/strobe/master/active") and numeric is not None:
                active = int(round(numeric)) != 0
                if active != self.strobe_active:
                    self.debug_log.log("OSC_STROBE", scope="master", active=active)
                self.strobe_active = active
            elif address in ("/master/strobe/countin", "/strobe/master/countin") and numeric is not None:
                count_in = max(0, int(round(numeric)))
                if count_in != self.strobe_count_in:
                    self.debug_log.log("OSC_STROBE_COUNTIN", scope="master", beats=count_in)
                self.strobe_count_in = count_in
            elif len(parts) >= 2 and parts[0].isdigit():
                deck_id = parts[0]
                deck = self._deck_state(deck_id)
                key = "/".join(parts[1:])
                if key == "phrase/current":
                    phrase_value = text if text not in (None, "") else numeric
                    if phrase_value != deck.get("phrase_current"):
                        self.debug_log.log("OSC_PHRASE", scope=f"deck{deck_id}", current=phrase_value)
                    deck["phrase_current"] = phrase_value
                elif key == "phrase/next":
                    phrase_value = text if text not in (None, "") else numeric
                    if phrase_value != deck.get("phrase_next"):
                        self.debug_log.log("OSC_PHRASE_NEXT", scope=f"deck{deck_id}", next=phrase_value)
                    deck["phrase_next"] = phrase_value
                elif key == "track/title":
                    if text != deck.get("track_title"):
                        self.debug_log.log("OSC_TRACK", scope=f"deck{deck_id}", title=text)
                    deck["track_title"] = text
                elif key == "track/artist":
                    deck["track_artist"] = text
                elif key == "track/album":
                    deck["track_album"] = text
                elif key == "time" and numeric is not None:
                    deck["time_seconds"] = numeric
                    deck["time_updated_at"] = now
                elif key == "mood" and numeric is not None:
                    if numeric != deck.get("mood"):
                        self.debug_log.log("OSC_MOOD", scope=f"deck{deck_id}", value=numeric)
                    deck["mood"] = numeric
                elif key == "color_bank" and numeric is not None:
                    bank_value = int(round(numeric))
                    if bank_value != deck.get("color_bank"):
                        self.debug_log.log("OSC_BANK", scope=f"deck{deck_id}", value=bank_value)
                    deck["color_bank"] = bank_value
                elif key == "waveform/energy" and numeric is not None:
                    deck["waveform_energy"] = clamp_unit(numeric)
                    deck["waveform_energy_updated_at"] = now
                    self._append_waveform_sample(
                        deck.setdefault("waveform_samples", deque(maxlen=480)),
                        now,
                        deck["waveform_energy"],
                    )
                elif key == "waveform/low_energy" and numeric is not None:
                    self._update_waveform_band(deck["waveform_bands"], deck["drum_signals"], "low", numeric, now)
                    deck["waveform_bands_updated_at"] = now
                elif key == "waveform/mid_energy" and numeric is not None:
                    self._update_waveform_band(deck["waveform_bands"], deck["drum_signals"], "mid", numeric, now)
                    deck["waveform_bands_updated_at"] = now
                elif key == "waveform/high_energy" and numeric is not None:
                    self._update_waveform_band(deck["waveform_bands"], deck["drum_signals"], "high", numeric, now)
                    deck["waveform_bands_updated_at"] = now
                elif len(parts) >= 5 and parts[1] == "waveform" and parts[2] == "lookahead" and numeric is not None:
                    beats_ahead = str(parts[3])
                    band_key = parts[4]
                    if beats_ahead in deck["waveform_lookahead"] and band_key in ("low_energy", "mid_energy", "high_energy"):
                        channel = band_key.split("_", 1)[0]
                        self._update_waveform_band(deck["waveform_lookahead"][beats_ahead], None, channel, numeric, now)
                elif key == "waveform/low_onset" and numeric is not None:
                    self._set_trigger_signal(deck["drum_signals"], "low_onset", numeric, now)
                elif key == "waveform/mid_onset" and numeric is not None:
                    self._set_trigger_signal(deck["drum_signals"], "mid_onset", numeric, now)
                elif key == "waveform/high_onset" and numeric is not None:
                    self._set_trigger_signal(deck["drum_signals"], "high_onset", numeric, now)
                elif key == "drums/kick" and numeric is not None:
                    self._set_trigger_signal(deck["drum_signals"], "kick", numeric, now)
                elif key == "drums/snare" and numeric is not None:
                    self._set_trigger_signal(deck["drum_signals"], "snare", numeric, now)
                elif key == "drums/hihat" and numeric is not None:
                    self._set_trigger_signal(deck["drum_signals"], "hihat", numeric, now)

    def _empty_deck_state(self):
        return {
            "track_title": None,
            "track_artist": None,
            "track_album": None,
            "time_seconds": None,
            "time_updated_at": None,
            "phrase_current": None,
            "phrase_next": None,
            "mood": None,
            "color_bank": None,
            "waveform_energy": None,
            "waveform_energy_updated_at": None,
            "waveform_bands": self._empty_band_state(),
            "waveform_bands_updated_at": None,
            "waveform_lookahead": self._empty_lookahead_state(),
            "waveform_samples": deque(maxlen=480),
            "drum_signals": self._empty_trigger_state(),
        }

    def _empty_band_state(self):
        return {"low": None, "mid": None, "high": None}

    def _empty_lookahead_state(self):
        return {"2": self._empty_band_state(), "4": self._empty_band_state()}

    def _empty_trigger_state(self):
        return {
            "kick": {"value": 0.0, "updated_at": None},
            "snare": {"value": 0.0, "updated_at": None},
            "hihat": {"value": 0.0, "updated_at": None},
            "low_onset": {"value": 0.0, "updated_at": None},
            "mid_onset": {"value": 0.0, "updated_at": None},
            "high_onset": {"value": 0.0, "updated_at": None},
        }

    def _estimated_band_onset(self, band_key, current, previous):
        energy_floor = {"low": 0.05, "mid": 0.03, "high": 0.02}.get(band_key, 0.03)
        delta_floor = {"low": 0.008, "mid": 0.006, "high": 0.005}.get(band_key, 0.006)
        delta = max(0.0, current - previous)
        if current < energy_floor or delta <= delta_floor:
            return 0.0
        delta_score = clamp_unit((delta - delta_floor) / 0.08)
        energy_score = clamp_unit((current - energy_floor) / 0.24)
        return clamp_unit(delta_score * 0.75 + energy_score * 0.25)

    def _update_waveform_band(self, band_target, trigger_target, key, value, now):
        if band_target is None:
            return
        try:
            numeric = clamp_unit(float(value))
        except (TypeError, ValueError):
            return
        previous = float(band_target.get(key) or 0.0)
        band_target[key] = numeric
        onset_key = {
            "low": "low_onset",
            "mid": "mid_onset",
            "high": "high_onset",
        }.get(key)
        if onset_key and trigger_target is not None:
            onset_value = self._estimated_band_onset(key, numeric, previous)
            if onset_value > 0.0:
                self._set_trigger_signal(trigger_target, onset_key, onset_value, now)

    def _set_trigger_signal(self, target, key, value, now):
        if target is None or key not in target:
            return
        try:
            numeric = clamp_unit(float(value))
        except (TypeError, ValueError):
            return
        if numeric <= 0.001:
            return
        entry = target[key]
        previous = float(entry.get("value") or 0.0)
        entry["value"] = max(numeric, previous * 0.72)
        entry["updated_at"] = now

    def _deck_state(self, deck_id):
        deck_id = str(deck_id)
        if deck_id not in self.decks:
            self.decks[deck_id] = self._empty_deck_state()
        return self.decks[deck_id]

    def _deck_fallback_value(self, key):
        for deck_id in sorted(
            self.decks.keys(),
            key=lambda value: (0, int(value)) if str(value).isdigit() else (1, str(value)),
        ):
            value = self.decks[deck_id].get(key)
            if value not in (None, ""):
                return value
        return None

    def _resolved_time_seconds(self):
        if self.time_seconds is not None:
            return self.time_seconds
        return self._deck_fallback_value("time_seconds")

    def _resolved_time_display_seconds(self, now):
        value = self._continuous_time_seconds(now)
        if value is not None:
            return value
        for deck_id in sorted(
            self.decks.keys(),
            key=lambda key: (0, int(key)) if str(key).isdigit() else (1, str(key)),
        ):
            deck_value = self._continuous_deck_time_seconds(self.decks[deck_id], now)
            if deck_value is not None:
                return deck_value
        return None

    def _resolved_waveform_energy(self, now):
        if (
            self.waveform_energy is not None
            and self.waveform_energy_updated_at is not None
            and now - self.waveform_energy_updated_at < 3.0
        ):
            return self.waveform_energy

        for deck_id in sorted(
            self.decks.keys(),
            key=lambda value: (0, int(value)) if str(value).isdigit() else (1, str(value)),
        ):
            deck = self.decks[deck_id]
            value = deck.get("waveform_energy")
            updated_at = deck.get("waveform_energy_updated_at")
            if value is not None and updated_at is not None and now - updated_at < 3.0:
                return value
        return None

    def _resolved_waveform_bands(self, now):
        if (
            self.waveform_bands_updated_at is not None
            and now - self.waveform_bands_updated_at < 3.0
            and any(self.waveform_bands.get(key) is not None for key in ("low", "mid", "high"))
        ):
            return {
                key: self.waveform_bands.get(key)
                for key in ("low", "mid", "high")
            }

        for deck_id in sorted(
            self.decks.keys(),
            key=lambda value: (0, int(value)) if str(value).isdigit() else (1, str(value)),
        ):
            deck = self.decks[deck_id]
            updated_at = deck.get("waveform_bands_updated_at")
            band_state = deck.get("waveform_bands") or {}
            if (
                updated_at is not None
                and now - updated_at < 3.0
                and any(band_state.get(key) is not None for key in ("low", "mid", "high"))
            ):
                return {
                    key: band_state.get(key)
                    for key in ("low", "mid", "high")
                }
        return None

    def _resolved_audio_bands(self, now):
        if (
            self.audio_bands_updated_at is not None
            and now - self.audio_bands_updated_at < 3.0
            and any(self.audio_bands.get(key) is not None for key in ("low", "mid", "high"))
        ):
            return {
                key: self.audio_bands.get(key)
                for key in ("low", "mid", "high")
            }
        return None

    def _resolved_waveform_lookahead(self, now):
        master_has_data = (
            self.waveform_bands_updated_at is not None
            and now - self.waveform_bands_updated_at < 3.0
            and any(
                any((self.waveform_lookahead.get(str(beats)) or {}).get(key) is not None for key in ("low", "mid", "high"))
                for beats in (2, 4)
            )
        )
        if master_has_data:
            return {
                str(beats): {
                    key: (self.waveform_lookahead.get(str(beats)) or {}).get(key)
                    for key in ("low", "mid", "high")
                }
                for beats in (2, 4)
            }

        for deck_id in sorted(
            self.decks.keys(),
            key=lambda value: (0, int(value)) if str(value).isdigit() else (1, str(value)),
        ):
            lookahead_state = (self.decks[deck_id] or {}).get("waveform_lookahead") or {}
            has_data = (
                (self.decks[deck_id] or {}).get("waveform_bands_updated_at") is not None
                and now - float((self.decks[deck_id] or {}).get("waveform_bands_updated_at") or 0.0) < 3.0
                and any(
                    any((lookahead_state.get(str(beats)) or {}).get(key) is not None for key in ("low", "mid", "high"))
                    for beats in (2, 4)
                )
            )
            if has_data:
                return {
                    str(beats): {
                        key: (lookahead_state.get(str(beats)) or {}).get(key)
                        for key in ("low", "mid", "high")
                    }
                    for beats in (2, 4)
                }
        return None

    def _resolved_trigger_state(self, target, now):
        result = {}
        decay_map = {
            "kick": 0.36,
            "snare": 0.28,
            "hihat": 0.20,
            "low_onset": 0.36,
            "mid_onset": 0.28,
            "high_onset": 0.20,
        }
        for key, entry in (target or {}).items():
            value = float(entry.get("value") or 0.0)
            updated_at = entry.get("updated_at")
            if updated_at is None or value <= 0.0:
                result[key] = 0.0
                continue
            age = max(0.0, now - updated_at)
            decay = decay_map.get(key, 0.18)
            result[key] = clamp_unit(value * max(0.0, 1.0 - (age / decay)))
        return result

    def _resolved_drum_signals(self, now):
        master_state = self._resolved_trigger_state(self.drum_signals, now)
        if max(master_state.values(), default=0.0) > 0.0:
            return master_state

        for deck_id in sorted(
            self.decks.keys(),
            key=lambda value: (0, int(value)) if str(value).isdigit() else (1, str(value)),
        ):
            deck_state = self._resolved_trigger_state(
                (self.decks[deck_id] or {}).get("drum_signals"),
                now,
            )
            if max(deck_state.values(), default=0.0) > 0.0:
                return deck_state
        return master_state

    def _resolved_audio_drums(self, now):
        if (
            self.audio_bands_updated_at is not None
            and now - self.audio_bands_updated_at < 3.0
        ):
            return self._resolved_trigger_state(self.audio_drums, now)
        return None

    def _resolved_waveform_analysis(self, now):
        if (
            self.waveform_energy is not None
            and self.waveform_energy_updated_at is not None
            and now - self.waveform_energy_updated_at < 3.0
        ):
            analysis = self._stabilize_waveform_analysis(
                waveform_analysis_from_samples(self.waveform_samples, now),
                now,
            )
            if analysis:
                return analysis

        for deck_id in sorted(
            self.decks.keys(),
            key=lambda value: (0, int(value)) if str(value).isdigit() else (1, str(value)),
        ):
            deck = self.decks[deck_id]
            updated_at = deck.get("waveform_energy_updated_at")
            if updated_at is None or now - updated_at >= 3.0:
                continue
            analysis = self._stabilize_waveform_analysis(
                waveform_analysis_from_samples(deck.get("waveform_samples"), now),
                now,
            )
            if analysis:
                return analysis
        return None

    def _resolved_phrase_current(self):
        return (
            self.phrase_current
            or self._deck_fallback_value("phrase_current")
            or self.phrase_next
            or self._deck_fallback_value("phrase_next")
        )

    def _resolved_phrase_next(self):
        return self.phrase_next or self._deck_fallback_value("phrase_next")

    def _continuous_deck_time_seconds(self, deck_state, now):
        value = deck_state.get("time_seconds")
        if value is None:
            return None
        updated_at = deck_state.get("time_updated_at")
        if updated_at and self.last_received_at and now - self.last_received_at < 1.0:
            return value + max(0.0, now - updated_at)
        return value

    def _public_deck_state(self, deck_state, now):
        phrase_current = deck_state.get("phrase_current")
        phrase_next = deck_state.get("phrase_next")
        color_bank = derive_color_bank_value(
            deck_state.get("color_bank"),
            phrase=phrase_current or phrase_next,
            track_title=deck_state.get("track_title"),
            track_artist=deck_state.get("track_artist"),
            track_album=deck_state.get("track_album"),
        )
        base_mood = derive_mood_value(
            deck_state.get("mood"),
            phrase=phrase_current,
            color_bank=color_bank,
        )
        mood = refine_mood_with_waveform(
            base_mood,
            phrase=phrase_current or phrase_next,
            analysis=waveform_analysis_from_samples(
                deck_state.get("waveform_samples"), now
            ),
        )
        return {
            "track_title": deck_state.get("track_title"),
            "track_artist": deck_state.get("track_artist"),
            "track_album": deck_state.get("track_album"),
            "time_seconds": deck_state.get("time_seconds"),
            "time_display_seconds": self._continuous_deck_time_seconds(deck_state, now),
            "phrase_current": phrase_current,
            "phrase_next": phrase_next,
            "mood": mood,
            "color_bank": color_bank,
            "waveform_energy": deck_state.get("waveform_energy"),
            "waveform_bands": dict(deck_state.get("waveform_bands") or {}),
            "waveform_lookahead": {
                "2": dict(((deck_state.get("waveform_lookahead") or {}).get("2")) or {}),
                "4": dict(((deck_state.get("waveform_lookahead") or {}).get("4")) or {}),
            },
            "drum_signals": self._resolved_trigger_state(deck_state.get("drum_signals"), now),
        }

    def _append_waveform_sample(self, target, now, value):
        if target is None or value is None:
            return
        try:
            numeric = clamp_unit(float(value))
        except (TypeError, ValueError):
            return
        target.append((now, numeric))

    def _classify_waveform_state(self, analysis):
        if not analysis:
            return "neutral"
        if analysis.get("attack"):
            return "attack"
        if analysis.get("breakdown"):
            return "breakdown"
        if analysis.get("sustained_high"):
            return "sustain"
        if analysis.get("calm"):
            return "calm"
        return "neutral"

    def _stabilize_waveform_analysis(self, analysis, now):
        if not analysis:
            return None

        raw_state = self._classify_waveform_state(analysis)
        current_state = self.waveform_state_name or "neutral"

        if raw_state == current_state:
            self.waveform_state_candidate = None
            self.waveform_state_candidate_since = None
        else:
            if self.waveform_state_candidate != raw_state:
                self.waveform_state_candidate = raw_state
                self.waveform_state_candidate_since = now
            hold_seconds = 2.0 if current_state == "neutral" else 2.6
            if raw_state == "neutral":
                hold_seconds = 3.2
            elif raw_state in ("attack", "breakdown"):
                hold_seconds = 2.1
            if (
                self.waveform_state_candidate_since is not None
                and now - self.waveform_state_candidate_since >= hold_seconds
            ):
                self.waveform_state_name = raw_state
                self.waveform_state_changed_at = now
                self.debug_log.log(
                    "WAVEFORM_STATE",
                    state=raw_state,
                    instant=analysis.get("instant"),
                    short=analysis.get("short_avg"),
                    mid=analysis.get("mid_avg"),
                    long=analysis.get("long_avg"),
                    transient=analysis.get("transient"),
                    volatility=analysis.get("volatility"),
                )
                current_state = raw_state
                self.waveform_state_candidate = None
                self.waveform_state_candidate_since = None

        stabilized = dict(analysis)
        stabilized["attack"] = current_state == "attack"
        stabilized["breakdown"] = current_state == "breakdown"
        stabilized["sustained_high"] = current_state == "sustain"
        stabilized["calm"] = current_state == "calm"
        stabilized["state"] = current_state
        if current_state in ("attack", "sustain"):
            stabilized["mood_hint"] = 1.0
        elif current_state in ("calm", "breakdown"):
            stabilized["mood_hint"] = 3.0
        elif analysis.get("mood_hint") == 2.0:
            stabilized["mood_hint"] = 2.0
        else:
            stabilized["mood_hint"] = None
        return stabilized

    def _continuous_beat_value(self, now):
        if self.beat_total is None:
            return None
        value = float(self.beat_total)
        if self.bpm and self.bpm > 0 and self.beat_updated_at and now - self.beat_updated_at < 1.0:
            beat_seconds = 60.0 / self.bpm
            if beat_seconds > 0:
                delta_beats = (now - self.beat_updated_at) / beat_seconds
                value += delta_beats
        return value

    def _continuous_beat_display(self, now):
        value = self._continuous_beat_value(now)
        if value is None:
            return None
        phase = value % 1.0
        beat_index = int(math.floor(value)) % 4 + 1
        return beat_index + phase

    def _continuous_beat_phase_age_seconds(self, now):
        value = self._continuous_beat_value(now)
        if value is None or not self.bpm or self.bpm <= 0:
            return None
        beat_seconds = 60.0 / self.bpm
        return (value % 1.0) * beat_seconds

    def _continuous_phrase_countdown(self, now):
        if self.phrase_count_in is None:
            return None
        value = float(self.phrase_count_in)
        if self.bpm and self.bpm > 0 and self.phrase_count_in_updated_at and now - self.phrase_count_in_updated_at < 1.0:
            beat_seconds = 60.0 / self.bpm
            if beat_seconds > 0:
                value = max(0.0, value - ((now - self.phrase_count_in_updated_at) / beat_seconds))
        return value

    def _continuous_time_seconds(self, now):
        if self.time_seconds is None:
            return None
        if self.time_updated_at and self.last_received_at and now - self.last_received_at < 1.0:
            return self.time_seconds + max(0.0, now - self.time_updated_at)
        return self.time_seconds


class DmxController:
    def __init__(self, osc_listener):
        self.osc = osc_listener
        self.debug_log = TRIGGER_LOG
        self.lock = threading.Lock()
        self.dmx = None
        self.thread = None
        self.running = False
        self.connected = False
        self.port = None
        self.fps = DEFAULT_DMX_FPS
        self.error = None
        self.last_sent = None
        self.current_values = {}
        self.current_slot_previews = {}
        self.conflicts = []
        self.motion_states = {}
        self.save_timer = None
        self.last_auto_show_signature = None
        self.last_slot_trigger_signatures = {}
        self.last_slot_strobe_outputs = {}
        self.outro_behavior_state = None
        self.active_one_shot_cue = None
        self.track_preview_summaries = {}
        self.track_show_plans = {}
        self.last_track_plan_prewarm_at = 0.0
        self.config = self._load_config()

    @staticmethod
    def default_config():
        return {
            "active_slot": "head",
            "blackout_active": False,
            "auto_show": DmxController.default_auto_show_config(),
            "slot_order": ["head", "par"],
            "slots": {
                "head": DmxController.default_slot_config("head"),
                "par": DmxController.default_slot_config("par"),
            },
        }

    @staticmethod
    def default_auto_show_config():
        default_turn_min, default_turn_max = _default_turn_audience_pan_limits(135, 205)
        return {
            "enabled": False,
            "style": "adaptive",
            "audience_pan_focus_enabled": True,
            "audience_pan_min": 135,
            "audience_pan_max": 205,
            "audience_turn_pan_min": default_turn_min,
            "audience_turn_pan_max": default_turn_max,
            "audience_tilt_split": 127,
            "override_phrase": "none",
            "override_color": "none",
            "override_energy": "none",
            "override_manual_strobe": False,
            "override_audience_sweep": False,
            "override_all_on": False,
            "override_par_chase": False,
            "override_par_snake": False,
        }

    @staticmethod
    def default_slot_config(slot_id, fixture_id=None, label=None, address=None, mode=None):
        common = {
            "enabled": True,
            "color": {"red": 255, "green": 0, "blue": 0, "white": 0},
            "dimmer": 255,
            "strobe": 0,
            "program": 0,
            "speed": 0,
            "pan": 127,
            "tilt": 127,
            "pan_tilt_speed": 0,
            "sync_enabled": True,
            "beat_pulse_enabled": True,
            "beat_depth": 65,
            "beat_decay_ms": 180,
            "color_source": "manual",
            "osc_strobe_enabled": True,
            "use_fine_pan_tilt": True,
            "pan_invert": False,
            "tilt_invert": False,
            "pan_offset_deg": 0,
            "tilt_offset_deg": 0,
            "pan_span_percent": 100,
            "tilt_span_percent": 100,
            "pan_left_value": None,
            "pan_right_value": None,
            "tilt_back_value": None,
            "tilt_front_value": None,
            "pose_center": None,
            "pose_audience_left": None,
            "pose_audience_center": None,
            "pose_audience_right": None,
            "pose_ceiling_center": None,
        }
        if fixture_id is None:
            fixture_id = (
                "shehds_led_wash_7x12w_rgbw_moving_head"
                if slot_id == "head"
                else "shehds_flat_par_12x3w_rgbw"
            )
        preset = fixture_preset(fixture_id)
        common.update(
            {
                "label": label or preset["label_base"],
                "fixture": fixture_id,
                "mode": mode or preset["mode"],
                "address": address if address is not None else (30 if fixture_id == "shehds_led_wash_7x12w_rgbw_moving_head" else 1),
            }
        )
        common["group"] = default_group_name_for_slot(
            slot_id,
            fixture_id,
            common["label"],
        )
        for key in (
            "color",
            "dimmer",
            "strobe",
            "program",
            "speed",
            "pan",
            "tilt",
            "pan_tilt_speed",
            "sync_enabled",
            "beat_pulse_enabled",
            "beat_depth",
            "beat_decay_ms",
            "color_source",
            "osc_strobe_enabled",
            "use_fine_pan_tilt",
        ):
            if key in preset:
                common[key] = preset[key]
        return common

    def _preview_track_candidates(self, osc):
        candidates = {}

        def add_candidate(track_title=None, track_artist=None, track_album=None):
            title = str(track_title or "").strip()
            artist = str(track_artist or "").strip()
            album = str(track_album or "").strip()
            if not any(value and value != "-" for value in (title, artist, album)):
                return
            cache_key = track_preview_cache_key(title, artist, album)
            candidates[cache_key] = (title, artist, album)

        add_candidate(
            osc.get("track_title"),
            osc.get("track_artist"),
            osc.get("track_album"),
        )

        with self.osc.lock:
            deck_states = [
                dict(deck_state or {})
                for _deck_id, deck_state in sorted(
                    self.osc.decks.items(),
                    key=lambda item: (
                        0,
                        int(item[0]),
                    )
                    if str(item[0]).isdigit()
                    else (1, str(item[0])),
                )
            ]

        for deck_state in deck_states:
            add_candidate(
                deck_state.get("track_title"),
                deck_state.get("track_artist"),
                deck_state.get("track_album"),
            )

        return list(candidates.values())

    def _load_track_preview_summary(
        self,
        track_title=None,
        track_artist=None,
        track_album=None,
    ):
        cache_key = track_preview_cache_key(track_title, track_artist, track_album)
        cache_path = track_preview_summary_path(track_title, track_artist, track_album)
        try:
            cache_mtime = cache_path.stat().st_mtime
        except FileNotFoundError:
            cache_mtime = None
        except OSError:
            cache_mtime = None

        cached_entry = self.track_preview_summaries.get(cache_key)
        if cached_entry and cached_entry.get("mtime") == cache_mtime:
            return cached_entry.get("summary")

        if cache_mtime is None:
            self.track_preview_summaries[cache_key] = {"mtime": None, "summary": None}
            stale_plan_keys = [
                plan_key
                for plan_key in self.track_show_plans.keys()
                if plan_key[0] == cache_key
            ]
            for plan_key in stale_plan_keys:
                self.track_show_plans.pop(plan_key, None)
            return None

        summary = None
        try:
            with cache_path.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict) and isinstance(loaded.get("segments"), list):
                loaded.setdefault("cache_key", cache_key)
                loaded.setdefault(
                    "identity",
                    track_preview_identity(track_title, track_artist, track_album),
                )
                summary = loaded
        except Exception as exc:
            self.debug_log.log(
                "TRACK_PREVIEW_LOAD_ERROR",
                key=cache_key,
                error=str(exc),
            )

        self.track_preview_summaries[cache_key] = {
            "mtime": cache_mtime,
            "summary": summary,
        }

        stale_plan_keys = [
            plan_key
            for plan_key, plan_entry in self.track_show_plans.items()
            if plan_key[0] == cache_key
            and plan_entry.get("summary_mtime") != cache_mtime
        ]
        for plan_key in stale_plan_keys:
            self.track_show_plans.pop(plan_key, None)

        return summary

    def _all_track_preview_summaries(self):
        summaries = []
        try:
            paths = sorted(TRACK_PREVIEW_CACHE_DIR.glob("*.json"))
        except Exception:
            return summaries
        for path in paths:
            cache_key = path.stem
            try:
                cache_mtime = path.stat().st_mtime
            except OSError:
                continue
            cached_entry = self.track_preview_summaries.get(cache_key)
            if cached_entry and cached_entry.get("mtime") == cache_mtime:
                summary = cached_entry.get("summary")
            else:
                summary = None
                try:
                    with path.open("r", encoding="utf-8") as handle:
                        loaded = json.load(handle)
                    if isinstance(loaded, dict) and isinstance(loaded.get("segments"), list):
                        loaded.setdefault("cache_key", cache_key)
                        summary = loaded
                except Exception:
                    summary = None
                self.track_preview_summaries[cache_key] = {
                    "mtime": cache_mtime,
                    "summary": summary,
                }
            if summary:
                summaries.append(summary)
        return summaries

    def _preview_summary_segment_for_seconds(self, preview_summary, current_seconds):
        try:
            current_seconds = max(0.0, float(current_seconds))
        except (TypeError, ValueError):
            return None
        segments = preview_summary.get("segments") or []
        if not segments:
            return None
        selected = segments[-1]
        for segment in segments:
            start_seconds = float(segment.get("start_seconds") or 0.0)
            end_seconds = float(segment.get("end_seconds") or start_seconds)
            if current_seconds < start_seconds:
                selected = segment
                break
            if start_seconds <= current_seconds < end_seconds:
                selected = segment
                break
        return selected

    def _preview_summary_match_score(self, preview_summary, osc_like):
        current_seconds = osc_like.get("time_display_seconds")
        if current_seconds is None:
            current_seconds = osc_like.get("time_seconds")
        try:
            current_seconds = (
                None if current_seconds is None else max(0.0, float(current_seconds))
            )
        except (TypeError, ValueError):
            current_seconds = None
        if current_seconds is None:
            return None

        duration_seconds = float(preview_summary.get("duration_seconds") or 0.0)
        if duration_seconds <= 0.0:
            return None

        time_penalty = 0.0
        if current_seconds > duration_seconds:
            time_penalty = min(1.0, (current_seconds - duration_seconds) / 18.0)

        segment = self._preview_summary_segment_for_seconds(
            preview_summary,
            min(current_seconds, duration_seconds),
        )
        if not segment:
            return None

        score = 0.55 - time_penalty * 0.70
        band_state = osc_like.get("waveform_bands") or {}
        segment_pairs = [
            (band_state.get("low"), segment.get("low")),
            (band_state.get("mid"), segment.get("mid")),
            (band_state.get("high"), segment.get("high")),
        ]
        diffs = []
        for current_value, segment_value in segment_pairs:
            if current_value is None or segment_value is None:
                continue
            try:
                diffs.append(abs(float(current_value) - float(segment_value)))
            except (TypeError, ValueError):
                continue
        if diffs:
            score += max(0.0, 1.0 - (sum(diffs) / len(diffs))) * 0.95

        current_energy = osc_like.get("waveform_energy")
        if current_energy is not None and segment.get("energy") is not None:
            try:
                score += max(
                    0.0,
                    1.0 - abs(float(current_energy) - float(segment.get("energy"))),
                ) * 0.35
            except (TypeError, ValueError):
                pass

        phrase_now = phrase_bucket(osc_like.get("phrase_current"))
        phrase_segment = phrase_bucket(segment.get("phrase"))
        if phrase_now != "unknown":
            if phrase_now == phrase_segment:
                score += 0.35
            elif phrase_now in {"break", "down"} and phrase_segment in {"break", "down"}:
                score += 0.20
            elif phrase_now == "outro" and phrase_segment in {"outro", "down", "break"}:
                score += 0.20
            else:
                score -= 0.12

        lookahead_state = osc_like.get("waveform_lookahead") or {}
        lookahead_2 = lookahead_state.get("2") or {}
        if any(lookahead_2.get(key) is not None for key in ("low", "mid", "high")):
            next_index = min(
                len(preview_summary.get("segments") or []) - 1,
                int(segment.get("index") or 0) + 1,
            )
            next_segment = (preview_summary.get("segments") or [segment])[next_index]
            diffs = []
            for key in ("low", "mid", "high"):
                current_value = lookahead_2.get(key)
                next_value = next_segment.get(key)
                if current_value is None or next_value is None:
                    continue
                try:
                    diffs.append(abs(float(current_value) - float(next_value)))
                except (TypeError, ValueError):
                    continue
            if diffs:
                score += max(0.0, 1.0 - (sum(diffs) / len(diffs))) * 0.45

        return score

    def _matched_track_preview_summary(self, osc_like):
        best_score = None
        best_summary = None
        for preview_summary in self._all_track_preview_summaries():
            score = self._preview_summary_match_score(preview_summary, osc_like)
            if score is None:
                continue
            if best_score is None or score > best_score:
                best_score = score
                best_summary = preview_summary
        if best_score is None or best_score < 1.05:
            return None
        return best_summary

    def _planned_section_for_preview_segment(self, segment):
        section = phrase_bucket(segment.get("phrase"))
        activity = clamp_unit(segment.get("activity") or 0.0)
        energy = clamp_unit(segment.get("energy") or activity)
        rise = clamp_unit(segment.get("rise") if segment.get("rise") is not None else 0.5)
        rising = rise >= 0.58
        falling = rise <= 0.42

        if section == "unknown":
            if activity <= 0.24:
                return "intro"
            if activity <= 0.46:
                return "verse"
            if activity <= 0.66:
                return "build"
            if activity <= 0.86:
                return "chorus"
            return "drop"

        if section == "intro":
            if activity >= 0.58 and rising:
                return "build"
            if activity >= 0.40:
                return "verse"
            return "intro"

        if section == "verse":
            if activity >= 0.80 and energy >= 0.76:
                return "chorus"
            if activity >= 0.60 and rising:
                return "build"
            return "verse"

        if section == "build":
            if activity >= 0.90 and energy >= 0.84:
                return "drop"
            if activity >= 0.76 and not falling:
                return "chorus"
            return "build"

        if section == "chorus":
            if activity >= 0.94 and energy >= 0.88 and rising:
                return "drop"
            if activity <= 0.50 and falling:
                return "build"
            return "chorus"

        if section == "drop":
            if activity <= 0.58 and falling:
                return "chorus"
            return "drop"

        if section == "down":
            if activity >= 0.74 and rising:
                return "build"
            return "down"

        if section == "break":
            if activity >= 0.70 and rising:
                return "build"
            if activity >= 0.46:
                return "down"
            return "break"

        if section == "outro":
            if activity >= 0.82:
                return "chorus"
            if activity >= 0.68:
                return "build"
            if activity >= 0.52:
                return "down" if falling else "verse"
            return "outro"

        return section

    def _build_track_show_plan(self, preview_summary, style_name):
        segments = preview_summary.get("segments") or []
        if not segments:
            return None

        title = str(preview_summary.get("title") or "").strip()
        artist = str(preview_summary.get("artist") or "").strip()
        album = str(preview_summary.get("album") or "").strip()
        cache_key = str(
            preview_summary.get("cache_key")
            or track_preview_cache_key(title, artist, album)
        )
        identity = str(
            preview_summary.get("identity")
            or track_preview_identity(title, artist, album)
        )
        theme_name, theme = track_show_theme_for_identity(identity)
        plan_segments = []

        for raw_segment in segments:
            segment_index = int(raw_segment.get("index") or len(plan_segments))
            segment_section = self._planned_section_for_preview_segment(raw_segment)
            segment_activity = clamp_unit(raw_segment.get("activity") or 0.0)
            segment_energy = clamp_unit(raw_segment.get("energy") or segment_activity)
            segment_rise = clamp_unit(
                raw_segment.get("rise") if raw_segment.get("rise") is not None else 0.5
            )
            scene = auto_show_scene_selection(
                style_name,
                segment_section,
                (
                    f"{cache_key}|segment:{segment_index}|"
                    f"{segment_section}|{round(segment_activity, 3)}|{round(segment_rise, 3)}"
                ),
                theme_name,
                scene_window=segment_index,
                motion_window=segment_index + int(segment_activity * 6.0) + (1 if segment_rise >= 0.60 else 0),
                mirror_window=(segment_index // 2) + (1 if segment_rise >= 0.64 else 0),
                color_window=segment_index + int(segment_energy * 5.0) + (1 if segment_activity >= 0.72 else 0),
                texture_window=segment_index + int(segment_activity * 4.0) + (1 if segment_energy >= 0.78 else 0),
                wash_window=segment_index + int(max(segment_rise, 1.0 - segment_rise) * 3.0),
            )
            scene.update(
                {
                    "section": segment_section,
                    "plan_segment_index": segment_index,
                    "plan_start_seconds": float(raw_segment.get("start_seconds") or 0.0),
                    "plan_end_seconds": float(raw_segment.get("end_seconds") or 0.0),
                    "plan_start_beat": int(raw_segment.get("start_beat") or 0),
                    "plan_end_beat": int(raw_segment.get("end_beat") or 0),
                    "plan_phrase": str(raw_segment.get("phrase") or ""),
                    "plan_activity": segment_activity,
                    "plan_energy": segment_energy,
                    "plan_rise": segment_rise,
                }
            )
            plan_segments.append(scene)

        if not plan_segments:
            return None

        return {
            "cache_key": cache_key,
            "identity": identity,
            "style_name": style_name,
            "theme_name": theme_name,
            "theme_label": theme["label"],
            "title": title,
            "artist": artist,
            "album": album,
            "duration_seconds": float(preview_summary.get("duration_seconds") or 0.0),
            "total_beats": int(preview_summary.get("total_beats") or 0),
            "segment_beats": max(1, int(preview_summary.get("segment_beats") or 8)),
            "segments": plan_segments,
        }

    def _track_show_plan_for_summary(self, preview_summary, style_name):
        if not preview_summary:
            return None
        cache_key = str(preview_summary.get("cache_key") or "").strip()
        summary_entry = self.track_preview_summaries.get(cache_key) or {}
        summary_mtime = summary_entry.get("mtime")
        plan_key = (cache_key, style_name)
        cached_plan = self.track_show_plans.get(plan_key)
        if cached_plan and cached_plan.get("summary_mtime") == summary_mtime:
            return cached_plan.get("plan")
        plan = self._build_track_show_plan(preview_summary, style_name)
        self.track_show_plans[plan_key] = {
            "summary_mtime": summary_mtime,
            "plan": plan,
        }
        if plan:
            self.debug_log.log(
                "TRACK_PLAN_BUILD",
                key=cache_key,
                style=style_name,
                segments=len(plan.get("segments") or []),
            )
        return plan

    def _track_show_plan(
        self,
        track_title=None,
        track_artist=None,
        track_album=None,
        style_name="adaptive",
    ):
        cache_key = track_preview_cache_key(track_title, track_artist, track_album)
        preview_summary = self._load_track_preview_summary(
            track_title,
            track_artist,
            track_album,
        )
        if not preview_summary:
            return None
        return self._track_show_plan_for_summary(preview_summary, style_name)

    def _track_show_plan_for_osc(self, osc, style_name):
        title = str(osc.get("track_title") or "").strip()
        artist = str(osc.get("track_artist") or "").strip()
        album = str(osc.get("track_album") or "").strip()
        if any(value and value != "-" for value in (title, artist, album)):
            return self._track_show_plan(
                title,
                artist,
                album,
                style_name=style_name,
            )

        matched_summary = self._matched_track_preview_summary(osc)
        if matched_summary:
            return self._track_show_plan_for_summary(matched_summary, style_name)
        return None

    def _current_track_plan_segment(self, plan, osc):
        segments = (plan or {}).get("segments") or []
        if not segments:
            return None

        current_seconds = osc.get("time_display_seconds")
        if current_seconds is None:
            current_seconds = osc.get("time_seconds")
        try:
            current_seconds = (
                None if current_seconds is None else max(0.0, float(current_seconds))
            )
        except (TypeError, ValueError):
            current_seconds = None

        if current_seconds is None:
            beat_value = osc.get("beat_value")
            try:
                beat_value = (
                    None if beat_value is None else max(0.0, float(beat_value))
                )
            except (TypeError, ValueError):
                beat_value = None
            if beat_value is None:
                return dict(segments[0])
            segment_beats = max(1, int(plan.get("segment_beats") or 8))
            segment_index = min(
                len(segments) - 1,
                max(0, int(beat_value // float(segment_beats))),
            )
            return dict(segments[segment_index])

        selected = segments[-1]
        for segment in segments:
            start_seconds = float(segment.get("plan_start_seconds") or 0.0)
            end_seconds = float(segment.get("plan_end_seconds") or start_seconds)
            if current_seconds < start_seconds:
                selected = segment
                break
            if start_seconds <= current_seconds < end_seconds:
                selected = segment
                break
        return dict(selected)

    def _planned_scene_variants(self, style_name, osc):
        plan = self._track_show_plan_for_osc(osc, style_name)
        if not plan:
            return None
        return self._current_track_plan_segment(plan, osc)

    def _prewarm_track_show_plans(self, style_name, osc):
        now = time.time()
        if now - self.last_track_plan_prewarm_at < 0.75:
            return
        self.last_track_plan_prewarm_at = now
        for track_title, track_artist, track_album in self._preview_track_candidates(osc):
            self._track_show_plan(
                track_title,
                track_artist,
                track_album,
                style_name=style_name,
            )
        if not self._preview_track_candidates(osc):
            matched_summary = self._matched_track_preview_summary(osc)
            if matched_summary:
                self._track_show_plan_for_summary(matched_summary, style_name)

    def connect(self, port, fps=DEFAULT_DMX_FPS):
        self.disconnect()
        dmx = EnttecOpenDmx(port)
        with self.lock:
            self.dmx = dmx
            self.port = port
            self.fps = max(1.0, min(60.0, float(fps)))
            self.running = True
            self.connected = True
            self.error = None
            self.debug_log.log("DMX_CONNECT", port=port, fps=self.fps)
        self.thread = threading.Thread(target=self._send_loop, daemon=True)
        self.thread.start()

    def disconnect(self):
        self.flush_config()
        with self.lock:
            dmx = self.dmx
            thread = self.thread
            fps = self.fps
            self.running = False
            self.active_one_shot_cue = None

        if thread and thread.is_alive():
            thread.join(timeout=1.5)

        if dmx:
            interval = 1 / fps if fps else 1 / DEFAULT_DMX_FPS
            with suppress(Exception):
                for _ in range(5):
                    dmx.send({})
                    time.sleep(interval)
            with suppress(Exception):
                dmx.close()

        with self.lock:
            self.dmx = None
            self.thread = None
            self.connected = False
            self.port = None
            self.running = False
            self.debug_log.log("DMX_DISCONNECT")

    def update_config(self, payload):
        with self.lock:
            self.config = self._merge_payload(payload)
            now = time.time()
            config = self._clean_full_config(dict(self.config))
            osc = self.osc.snapshot_for_render()
            auto_show = self._auto_show_state(osc, config["auto_show"])
            values = self._render_values(
                now,
                config=config,
                osc=osc,
                auto_show=auto_show,
            )
            self.current_values = values
            self.current_slot_previews = self._build_slot_previews(
                config,
                osc,
                now,
                auto_show=auto_show,
            )
            self._schedule_save_locked()
            self.debug_log.log(
                "CONFIG_UPDATE",
                active_slot=self.config.get("active_slot"),
                blackout=self.config.get("blackout_active"),
                auto_show_enabled=(self.config.get("auto_show") or {}).get("enabled"),
                auto_show_style=(self.config.get("auto_show") or {}).get("style"),
            )
            return values

    def trigger_one_shot_cue(self, cue_id):
        cue_name = one_shot_cue_name(cue_id)
        cue = one_shot_cue_definition(cue_name)
        if not cue:
            raise ValueError("Onbekende cue-trigger")
        with self.lock:
            now = time.time()
            osc = self.osc.snapshot_for_render()
            start_beat = osc.get("beat_value")
            try:
                start_beat = None if start_beat is None else float(start_beat)
            except (TypeError, ValueError):
                start_beat = None
            try:
                bpm = float(osc.get("bpm") or 0.0)
            except (TypeError, ValueError):
                bpm = 0.0
            self.active_one_shot_cue = {
                "id": cue_name,
                "started_at": now,
                "start_beat": start_beat,
                "bpm": bpm,
            }
            self.config["blackout_active"] = False
            config = self._clean_full_config(dict(self.config))
            auto_show = self._auto_show_state(osc, config["auto_show"])
            self.current_values = self._render_values(
                now,
                config=config,
                osc=osc,
                auto_show=auto_show,
            )
            self.current_slot_previews = self._build_slot_previews(
                config,
                osc,
                now,
                auto_show=auto_show,
            )
            self.debug_log.log("ONE_SHOT_TRIGGER", cue=cue_name)
            return dict(self.current_values)

    def blackout(self):
        with self.lock:
            self.config["blackout_active"] = True
            self.active_one_shot_cue = None
            self.current_values = {}
            self.current_slot_previews = {}
            self.debug_log.log("BLACKOUT", active=True)

    def _resolved_one_shot_cue_state(self, osc, now=None):
        raw = self.active_one_shot_cue
        if not raw:
            return None
        cue = one_shot_cue_definition(raw.get("id"))
        if not cue:
            self.active_one_shot_cue = None
            return None
        now = time.time() if now is None else float(now)
        elapsed_beats = None
        start_beat = raw.get("start_beat")
        current_beat = osc.get("beat_value")
        try:
            if start_beat is not None and current_beat is not None:
                elapsed_beats = float(current_beat) - float(start_beat)
                if elapsed_beats < -0.25:
                    elapsed_beats = None
        except (TypeError, ValueError):
            elapsed_beats = None
        if elapsed_beats is None:
            try:
                bpm = float(osc.get("bpm") or raw.get("bpm") or 120.0)
            except (TypeError, ValueError):
                bpm = 120.0
            bpm = max(60.0, bpm)
            elapsed_beats = max(
                0.0,
                (now - float(raw.get("started_at") or now)) * bpm / 60.0,
            )
        duration_beats = max(0.25, float(cue.get("duration_beats") or 1.0))
        progress = elapsed_beats / duration_beats
        if progress >= 1.0:
            self.active_one_shot_cue = None
            return None
        return {
            "id": str(raw.get("id")),
            "label": cue["label"],
            "duration_beats": duration_beats,
            "elapsed_beats": elapsed_beats,
            "progress": clamp_unit(progress),
        }

    def state(self):
        with self.lock:
            config = self._clean_full_config(dict(self.config))
            now = time.time()
            osc = self.osc.snapshot_for_render()
            auto_show = self._auto_show_state(osc, config["auto_show"])
            try:
                if self.connected and self.running:
                    live_values = dict(self.current_values)
                    slot_previews = dict(self.current_slot_previews)
                    if not slot_previews:
                        slot_previews = self._build_slot_previews(
                            config,
                            osc,
                            now,
                            auto_show=auto_show,
                        )
                else:
                    live_values = self._render_values(
                        now,
                        advance_motion=True,
                        config=config,
                        osc=osc,
                        auto_show=auto_show,
                    )
                    self.current_values = live_values
                    slot_previews = self._build_slot_previews(
                        config,
                        osc,
                        now,
                        auto_show=auto_show,
                    )
                    self.current_slot_previews = slot_previews
            except Exception:
                live_values = dict(self.current_values)
                slot_previews = dict(self.current_slot_previews)
            values = dict(sorted(live_values.items()))
            return {
                "connected": self.connected,
                "port": self.port,
                "fps": self.fps,
                "error": self.error,
                "last_sent": self.last_sent,
                "active_slot": config["active_slot"],
                "blackout_active": config["blackout_active"],
                "auto_show": auto_show,
                "slot_order": list(config["slot_order"]),
                "slots": config["slots"],
                "slot_ranges": {
                    slot_id: self._range_for_slot(slot_id, slot_config)
                    for slot_id, slot_config in config["slots"].items()
                },
                "slot_capabilities": {
                    slot_id: self._capabilities_for_slot(slot_config)
                    for slot_id, slot_config in config["slots"].items()
                },
                "slot_previews": slot_previews,
                "conflicts": list(self.conflicts),
                "values": values,
            }

    def add_slot(self, fixture_id, mode=None):
        fixture = find_fixture(FIXTURE_LIBRARY, fixture_id)
        selected_mode = mode or fixture_preset(fixture_id)["mode"]
        find_mode(fixture, selected_mode)
        with self.lock:
            config = self._clean_full_config(dict(self.config))
            slot_id = self._next_slot_id(config, fixture_id)
            label = self._next_slot_label(config, fixture_preset(fixture_id)["label_base"])
            address = self._next_available_address(config, fixture, selected_mode)
            slot_config = self.default_slot_config(
                slot_id,
                fixture_id=fixture_id,
                label=label,
                address=address,
                mode=selected_mode,
            )
            config["slots"][slot_id] = self._clean_slot_config(slot_id, slot_config)
            config["slot_order"].append(slot_id)
            config["active_slot"] = slot_id
            config["blackout_active"] = False
            self.config = self._clean_full_config(config)
            now = time.time()
            full_config = self._clean_full_config(dict(self.config))
            osc = self.osc.snapshot_for_render()
            auto_show = self._auto_show_state(osc, full_config["auto_show"])
            self.current_values = self._render_values(
                now,
                config=full_config,
                osc=osc,
                auto_show=auto_show,
            )
            self.current_slot_previews = self._build_slot_previews(
                full_config,
                osc,
                now,
                auto_show=auto_show,
            )
            self._schedule_save_locked()
            self.debug_log.log(
                "SLOT_ADD",
                slot=slot_id,
                fixture=fixture_id,
                mode=selected_mode,
                address=address,
                label=label,
            )
            return dict(self.current_values)

    def remove_slot(self, slot_id):
        slot_id = str(slot_id or "").strip()
        if not slot_id:
            raise ValueError("Geen fixture geselecteerd om te verwijderen")
        with self.lock:
            config = self._clean_full_config(dict(self.config))
            if slot_id not in config["slots"]:
                raise ValueError(f"Fixture '{slot_id}' bestaat niet")
            if len(config["slot_order"]) <= 1:
                raise ValueError("Minimaal 1 fixture moet aanwezig blijven")
            removed_slot = dict(config["slots"][slot_id])
            previous_order = list(config["slot_order"])
            removed_index = previous_order.index(slot_id)
            del config["slots"][slot_id]
            config["slot_order"] = [current for current in previous_order if current != slot_id]
            if config["active_slot"] == slot_id or config["active_slot"] not in config["slots"]:
                fallback_index = min(removed_index, len(config["slot_order"]) - 1)
                config["active_slot"] = config["slot_order"][fallback_index]
            config["blackout_active"] = False
            self.config = self._clean_full_config(config)
            now = time.time()
            full_config = self._clean_full_config(dict(self.config))
            osc = self.osc.snapshot_for_render()
            auto_show = self._auto_show_state(osc, full_config["auto_show"])
            self.current_values = self._render_values(
                now,
                config=full_config,
                osc=osc,
                auto_show=auto_show,
            )
            self.current_slot_previews = self._build_slot_previews(
                full_config,
                osc,
                now,
                auto_show=auto_show,
            )
            self._schedule_save_locked()
            self.debug_log.log(
                "SLOT_REMOVE",
                slot=slot_id,
                fixture=removed_slot.get("fixture"),
                address=removed_slot.get("address"),
                label=removed_slot.get("label"),
            )
            return dict(self.current_values)

    def flush_config(self):
        with self.lock:
            timer = self.save_timer
            self.save_timer = None
            config = self._clean_full_config(dict(self.config))
        if timer:
            timer.cancel()
        self._write_config(config)

    def _merge_payload(self, payload):
        config = self._clean_full_config(dict(self.config))
        active_slot = str(payload.get("active_slot") or config["active_slot"])
        if active_slot not in config["slots"]:
            active_slot = config["slot_order"][0]
        config["active_slot"] = active_slot

        if "blackout_active" in payload:
            config["blackout_active"] = bool(payload["blackout_active"])

        if "auto_show" in payload and isinstance(payload["auto_show"], dict):
            merged_auto_show = {**config["auto_show"], **payload["auto_show"]}
            config["auto_show"] = self._clean_auto_show_config(merged_auto_show)

        slot_id = payload.get("slot_id")
        slot_payload = payload.get("slot")
        if slot_id and slot_id in config["slots"] and isinstance(slot_payload, dict):
            merged = {**config["slots"][slot_id], **slot_payload}
            config["slots"][slot_id] = self._clean_slot_config(slot_id, merged)
            config["blackout_active"] = False

        if "slots" in payload and isinstance(payload["slots"], dict):
            for current_slot_id, current_payload in payload["slots"].items():
                if current_slot_id in config["slots"] and isinstance(current_payload, dict):
                    merged = {**config["slots"][current_slot_id], **current_payload}
                    config["slots"][current_slot_id] = self._clean_slot_config(
                        current_slot_id, merged
                    )
            config["blackout_active"] = False

        return self._clean_full_config(config)

    def _load_config(self):
        defaults = self.default_config()
        if not CONFIG_PATH.exists():
            return defaults
        try:
            payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"BeatBeam DMX: config load failed, using defaults: {exc}")
            return defaults
        try:
            return self._clean_full_config(payload)
        except Exception as exc:
            print(f"BeatBeam DMX: config invalid, using defaults: {exc}")
            return defaults

    def _schedule_save_locked(self):
        if self.save_timer:
            self.save_timer.cancel()
        timer = threading.Timer(0.35, self._save_config_worker)
        timer.daemon = True
        self.save_timer = timer
        timer.start()

    def _save_config_worker(self):
        with self.lock:
            self.save_timer = None
            config = self._clean_full_config(dict(self.config))
        self._write_config(config)

    def _write_config(self, config):
        persistable = self._persistable_config(config)
        tmp_path = CONFIG_PATH.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(persistable, indent=2), encoding="utf-8")
        tmp_path.replace(CONFIG_PATH)

    def _persistable_config(self, config):
        persistable = self._clean_full_config(dict(config))
        persistable["blackout_active"] = False
        return persistable

    def _clean_slot_config(self, slot_id, config):
        fixture_id = (config or {}).get("fixture")
        if not any(fixture["id"] == fixture_id for fixture in FIXTURE_LIBRARY):
            fixture_id = None
        defaults = self.default_slot_config(slot_id, fixture_id=fixture_id)
        cleaned = {**defaults, **config}
        color = config.get("color") or {}
        cleaned["color"] = {
            "red": clamp_dmx(color.get("red", 255)),
            "green": clamp_dmx(color.get("green", 0)),
            "blue": clamp_dmx(color.get("blue", 0)),
            "white": clamp_dmx(color.get("white", 0)),
        }
        for key in (
            "dimmer",
            "strobe",
            "program",
            "speed",
            "pan",
            "tilt",
            "pan_tilt_speed",
            "beat_depth",
        ):
            cleaned[key] = clamp_dmx(cleaned.get(key, defaults.get(key, 0)))
        cleaned["pan_offset_deg"] = max(
            -180, min(180, int(cleaned.get("pan_offset_deg", defaults["pan_offset_deg"])))
        )
        cleaned["tilt_offset_deg"] = max(
            -90, min(90, int(cleaned.get("tilt_offset_deg", defaults["tilt_offset_deg"])))
        )
        cleaned["pan_span_percent"] = max(
            5, min(160, int(cleaned.get("pan_span_percent", defaults["pan_span_percent"])))
        )
        cleaned["tilt_span_percent"] = max(
            5, min(160, int(cleaned.get("tilt_span_percent", defaults["tilt_span_percent"])))
        )
        for key in ("pan_left_value", "pan_right_value", "tilt_back_value", "tilt_front_value"):
            raw_value = cleaned.get(key, defaults.get(key))
            if raw_value is None or raw_value == "":
                cleaned[key] = None
            else:
                cleaned[key] = clamp_dmx(raw_value)
        for key in (
            "pose_center",
            "pose_audience_left",
            "pose_audience_center",
            "pose_audience_right",
            "pose_ceiling_center",
        ):
            raw_pose = cleaned.get(key, defaults.get(key))
            if not isinstance(raw_pose, dict):
                cleaned[key] = None
                continue
            pan = raw_pose.get("pan")
            tilt = raw_pose.get("tilt")
            if pan is None or tilt is None:
                cleaned[key] = None
                continue
            cleaned[key] = {
                "pan": clamp_dmx(pan),
                "tilt": clamp_dmx(tilt),
            }
        cleaned["beat_decay_ms"] = max(
            30, min(1500, int(cleaned.get("beat_decay_ms", defaults["beat_decay_ms"])))
        )
        cleaned["address"] = max(1, min(512, int(cleaned.get("address", defaults["address"]))))
        for key in (
            "sync_enabled",
            "beat_pulse_enabled",
            "osc_strobe_enabled",
            "use_fine_pan_tilt",
            "pan_invert",
            "tilt_invert",
        ):
            cleaned[key] = bool(cleaned.get(key, False))
        cleaned["enabled"] = bool(cleaned.get("enabled", True))
        cleaned["label"] = str(cleaned.get("label", defaults["label"]))
        requested_fixture = str(cleaned.get("fixture", defaults["fixture"]))
        if not any(fixture["id"] == requested_fixture for fixture in FIXTURE_LIBRARY):
            requested_fixture = defaults["fixture"]
        cleaned["fixture"] = requested_fixture
        fixture = find_fixture(FIXTURE_LIBRARY, cleaned["fixture"])
        requested_mode = str(cleaned.get("mode", defaults["mode"]))
        if cleaned["fixture"] == "uking_zq06016" and requested_mode.upper() == "H001":
            requested_mode = "P001"
        with suppress(Exception):
            requested_mode = find_mode(fixture, requested_mode)["name"]
        if not any(mode["name"].lower() == requested_mode.lower() for mode in fixture["modes"]):
            requested_mode = fixture["modes"][0]["name"]
        cleaned["mode"] = requested_mode
        cleaned["color_source"] = str(cleaned.get("color_source", "manual"))
        raw_group = str(cleaned.get("group", "") or "").strip().lower()
        raw_group = "".join(ch if (ch.isalnum() or ch in ("_", "-")) else "_" for ch in raw_group)
        raw_group = raw_group.strip("_-")
        if not raw_group:
            raw_group = default_group_name_for_slot(
                slot_id,
                cleaned["fixture"],
                cleaned.get("label", ""),
            )
        cleaned["group"] = raw_group
        return cleaned

    def _clean_auto_show_config(self, config):
        defaults = self.default_auto_show_config()
        cleaned = {**defaults, **(config or {})}
        cleaned["enabled"] = bool(cleaned.get("enabled", defaults["enabled"]))
        style = str(cleaned.get("style", defaults["style"])).lower()
        if style not in AUTO_SHOW_STYLES:
            style = defaults["style"]
        cleaned["style"] = style
        cleaned["audience_pan_focus_enabled"] = bool(
            cleaned.get("audience_pan_focus_enabled", defaults["audience_pan_focus_enabled"])
        )
        try:
            cleaned["audience_pan_min"] = clamp_dmx(
                int(cleaned.get("audience_pan_min", defaults["audience_pan_min"]))
            )
        except (TypeError, ValueError):
            cleaned["audience_pan_min"] = defaults["audience_pan_min"]
        try:
            cleaned["audience_pan_max"] = clamp_dmx(
                int(cleaned.get("audience_pan_max", defaults["audience_pan_max"]))
            )
        except (TypeError, ValueError):
            cleaned["audience_pan_max"] = defaults["audience_pan_max"]
        if cleaned["audience_pan_max"] < cleaned["audience_pan_min"]:
            cleaned["audience_pan_min"], cleaned["audience_pan_max"] = (
                cleaned["audience_pan_max"],
                cleaned["audience_pan_min"],
            )
        default_turn_min, default_turn_max = _default_turn_audience_pan_limits(
            cleaned["audience_pan_min"],
            cleaned["audience_pan_max"],
        )
        try:
            cleaned["audience_turn_pan_min"] = clamp_dmx(
                int(cleaned.get("audience_turn_pan_min", default_turn_min))
            )
        except (TypeError, ValueError):
            cleaned["audience_turn_pan_min"] = default_turn_min
        try:
            cleaned["audience_turn_pan_max"] = clamp_dmx(
                int(cleaned.get("audience_turn_pan_max", default_turn_max))
            )
        except (TypeError, ValueError):
            cleaned["audience_turn_pan_max"] = default_turn_max
        if cleaned["audience_turn_pan_max"] < cleaned["audience_turn_pan_min"]:
            cleaned["audience_turn_pan_min"], cleaned["audience_turn_pan_max"] = (
                cleaned["audience_turn_pan_max"],
                cleaned["audience_turn_pan_min"],
            )
        try:
            cleaned["audience_tilt_split"] = clamp_dmx(
                int(cleaned.get("audience_tilt_split", defaults["audience_tilt_split"]))
            )
        except (TypeError, ValueError):
            cleaned["audience_tilt_split"] = defaults["audience_tilt_split"]
        cleaned["override_phrase"] = auto_show_phrase_override_name(
            cleaned.get("override_phrase", defaults["override_phrase"])
        )
        cleaned["override_color"] = live_override_color_name(
            cleaned.get("override_color", defaults["override_color"])
        )
        cleaned["override_energy"] = live_override_energy_name(
            cleaned.get("override_energy", defaults["override_energy"])
        )
        for key in (
            "override_manual_strobe",
            "override_audience_sweep",
            "override_all_on",
            "override_par_chase",
            "override_par_snake",
        ):
            cleaned[key] = bool(cleaned.get(key, defaults[key]))
        if cleaned["override_par_snake"]:
            cleaned["override_par_chase"] = False
        return cleaned

    def _clean_full_config(self, config):
        defaults = self.default_config()
        raw_slots = config.get("slots") if isinstance(config.get("slots"), dict) else {}
        if not raw_slots:
            raw_slots = dict(defaults["slots"])
        raw_order = config.get("slot_order") if isinstance(config.get("slot_order"), list) else []
        if not raw_order:
            raw_order = [slot_id for slot_id in defaults["slot_order"] if slot_id in raw_slots]
        cleaned = {
            "active_slot": str(config.get("active_slot", defaults["active_slot"])),
            "blackout_active": bool(config.get("blackout_active", False)),
            "auto_show": self._clean_auto_show_config(config.get("auto_show")),
            "slot_order": [],
            "slots": {},
        }
        seen = set()
        for slot_id in raw_order:
            slot_id = str(slot_id)
            if slot_id in seen or slot_id not in raw_slots:
                continue
            cleaned["slots"][slot_id] = self._clean_slot_config(slot_id, raw_slots.get(slot_id, {}))
            cleaned["slot_order"].append(slot_id)
            seen.add(slot_id)
        for slot_id, slot_config in raw_slots.items():
            slot_id = str(slot_id)
            if slot_id in seen:
                continue
            cleaned["slots"][slot_id] = self._clean_slot_config(slot_id, slot_config)
            cleaned["slot_order"].append(slot_id)
        if not cleaned["slot_order"]:
            for slot_id in defaults["slot_order"]:
                cleaned["slots"][slot_id] = self._clean_slot_config(slot_id, defaults["slots"][slot_id])
                cleaned["slot_order"].append(slot_id)
        if cleaned["active_slot"] not in cleaned["slots"]:
            cleaned["active_slot"] = cleaned["slot_order"][0]
        return cleaned

    def _capabilities_for_slot(self, config):
        fixture = find_fixture(FIXTURE_LIBRARY, config["fixture"])
        mode = find_mode(fixture, config["mode"])
        return mode_capabilities(mode)

    def _role_for_slot(self, config, capabilities=None):
        capabilities = capabilities or self._capabilities_for_slot(config)
        fixture = find_fixture(FIXTURE_LIBRARY, config["fixture"])
        label_text = f"{fixture['manufacturer']} {fixture['model']} {config.get('label', '')}".lower()
        beam_layout = str(fixture.get("beam_layout", {}).get("type", "")).lower()
        if capabilities["pan"] or capabilities["tilt"]:
            return "moving"
        if "wall wash" in label_text or beam_layout == "strip":
            return "wash"
        if "par" in label_text:
            return "par"
        return "static"

    def _slot_context(self, full_config, slot_id, config):
        capabilities = self._capabilities_for_slot(config)
        role = self._role_for_slot(config, capabilities)
        slot_order = list(full_config.get("slot_order") or [])
        if slot_id not in slot_order:
            slot_order.append(slot_id)
        global_index = slot_order.index(slot_id)
        slots = full_config.get("slots") or {}

        role_slot_ids = []
        for current_slot_id in slot_order:
            current_config = slots.get(current_slot_id)
            if current_config is None:
                if current_slot_id != slot_id:
                    continue
                current_config = config
            current_capabilities = self._capabilities_for_slot(current_config)
            if self._role_for_slot(current_config, current_capabilities) == role:
                role_slot_ids.append(current_slot_id)

        if slot_id not in role_slot_ids:
            role_slot_ids.append(slot_id)

        group_name = str(config.get("group") or default_group_name_for_slot(
            slot_id,
            config.get("fixture"),
            config.get("label", ""),
        ))
        grouped_role_slot_ids = []
        role_group_names = []
        for current_slot_id in role_slot_ids:
            current_config = slots.get(current_slot_id)
            if current_config is None:
                if current_slot_id != slot_id:
                    continue
                current_config = config
            current_group = str(current_config.get("group") or default_group_name_for_slot(
                current_slot_id,
                current_config.get("fixture"),
                current_config.get("label", ""),
            ))
            if current_group == group_name:
                grouped_role_slot_ids.append(current_slot_id)
            if current_group not in role_group_names:
                role_group_names.append(current_group)

        if slot_id not in grouped_role_slot_ids:
            grouped_role_slot_ids.append(slot_id)
        if group_name not in role_group_names:
            role_group_names.append(group_name)

        role_index = grouped_role_slot_ids.index(slot_id)
        role_count = len(grouped_role_slot_ids)
        if role_count <= 1:
            normalized = 0.5
            centered = 0.0
        else:
            normalized = role_index / max(1, role_count - 1)
            centered = normalized * 2.0 - 1.0

        group_index = role_group_names.index(group_name)
        group_count = len(role_group_names)
        if group_count <= 1:
            group_normalized = 0.5
            group_centered = 0.0
        else:
            group_normalized = group_index / max(1, group_count - 1)
            group_centered = group_normalized * 2.0 - 1.0

        member_seed = stable_hash(slot_id)
        seed_unit = ((member_seed % 1000) / 999.0) * 2.0 - 1.0
        group_seed = stable_hash(f"{role}:{group_name}")
        group_seed_unit = ((group_seed % 1000) / 999.0) * 2.0 - 1.0

        return {
            "role": role,
            "group": group_name,
            "global_index": global_index,
            "global_count": len(slot_order),
            "role_index": role_index,
            "role_count": role_count,
            "normalized": normalized,
            "centered": centered,
            "center_bias": 1.0 - abs(centered),
            "edge_bias": abs(centered),
            "alternate": -1.0 if role_index % 2 == 0 else 1.0,
            "member_index": role_index,
            "member_count": role_count,
            "member_normalized": normalized,
            "member_centered": centered,
            "member_center_bias": 1.0 - abs(centered),
            "member_edge_bias": abs(centered),
            "member_alternate": -1.0 if role_index % 2 == 0 else 1.0,
            "group_index": group_index,
            "group_count": group_count,
            "group_normalized": group_normalized,
            "group_centered": group_centered,
            "group_center_bias": 1.0 - abs(group_centered),
            "group_edge_bias": abs(group_centered),
            "group_alternate": -1.0 if group_index % 2 == 0 else 1.0,
            "seed_unit": seed_unit,
            "member_seed_unit": seed_unit,
            "group_seed_unit": group_seed_unit,
        }

    def _accent_dimmer_offset(self, role, slot_context, accent_name, movement):
        center_bias = slot_context.get("group_center_bias", slot_context["center_bias"])
        edge_bias = slot_context.get("group_edge_bias", slot_context["edge_bias"])
        alternate = slot_context.get("group_alternate", slot_context["alternate"])

        if accent_name == "center":
            return round(center_bias * (18 if role == "moving" else 12) - edge_bias * 6)
        if accent_name == "edges":
            return round(edge_bias * (24 if role == "moving" else 16) - center_bias * 8)
        if accent_name == "alternating":
            return round(alternate * (10 if role == "moving" else 7))
        if accent_name == "wash_lift":
            if role == "wash":
                return 20
            if role == "moving":
                return -10
            return 4
        if accent_name == "mover_focus":
            if role == "moving":
                return round(16 + movement * 12 - edge_bias * 4)
            if role == "wash":
                return -8
            return -2
        return 0

    def _rhythm_envelope(self, mode, beat_value, slot_context, movement_scale, osc, now, decay, energy=0.0):
        if mode == "none":
            return 0.0

        if mode in ("pulse", "gate", "lift"):
            age = osc.get("beat_phase_age_seconds")
            if age is None:
                last_beat_at = osc.get("last_beat_at")
                if not last_beat_at:
                    return 0.0
                age = now - last_beat_at
            envelope = max(0.0, 1.0 - (age / decay)) if decay > 0 else 0.0
            if mode == "lift":
                return envelope ** 0.72
            if mode == "gate":
                return envelope ** 0.45
            return envelope

        if mode in ("hit", "cut"):
            if beat_value is None:
                return 0.0
            age = osc.get("beat_phase_age_seconds")
            if age is None:
                last_beat_at = osc.get("last_beat_at")
                if not last_beat_at:
                    return 0.0
                age = now - last_beat_at
            envelope = max(0.0, 1.0 - (age / decay)) if decay > 0 else 0.0
            cycle_length = 8
            beat_step = int(math.floor(float(beat_value))) % cycle_length
            group_key = str(slot_context.get("group") or slot_context.get("role") or "moving")
            window = int(math.floor(float(beat_value) / cycle_length))
            pattern_seed = stable_hash(f"{osc_track_signature(osc)}|{group_key}|{window}")
            if energy >= 0.96:
                patterns = [(0, 2, 4, 6), (0, 3, 4, 7), (1, 3, 5, 7)]
            elif energy >= 0.88:
                patterns = [(0, 4), (0, 3, 6), (1, 5), (0, 5)]
            else:
                patterns = [(0, 4), (1, 5), (0, 6)]
            active_hits = patterns[pattern_seed % len(patterns)]
            if beat_step not in active_hits:
                return 0.0
            if mode == "cut":
                return envelope ** 0.22
            return envelope ** 0.34

        if beat_value is None:
            return 0.0

        role = str(slot_context.get("role", ""))
        if role == "par":
            member_count = max(1, int(slot_context.get("member_count", 1)))
            member_index = int(slot_context.get("member_index", 0))
            role_count = max(1, (member_count + 1) // 2)
            role_index = min(member_index, member_count - 1 - member_index)
            centered = (
                ((role_index / max(1, role_count - 1)) * 2.0) - 1.0
                if role_count > 1
                else 0.0
            )
        else:
            role_count = max(
                1,
                int(slot_context.get("group_count", slot_context.get("role_count", 1))),
            )
            role_index = int(slot_context.get("group_index", slot_context.get("role_index", 0)))
            centered = float(
                slot_context.get("group_centered", slot_context.get("centered", 0.0))
            )
        movement_scale = float(movement_scale or 0.0)
        beat_value = float(beat_value)

        if mode == "breathe":
            return 0.50 + 0.50 * wave_sine(beat_value / 8.0 + centered * 0.12)

        if mode == "stagger":
            step = (int(math.floor(beat_value * 2.0)) + role_index) % 2
            return 1.0 if step == 0 else 0.28 + movement_scale * 0.12

        if mode == "alternate_whole":
            phase = int(math.floor(beat_value)) % 2
            if role == "par":
                active_side = role_index % 2
            elif role_count <= 2:
                active_side = role_index % 2
            else:
                active_side = 0 if centered <= 0 else 1
            return 1.0 if phase == active_side else 0.0

        if mode == "double_hit":
            phase = beat_value % 1.0
            if phase < 0.16:
                return 1.0
            if 0.46 <= phase < 0.60:
                return 1.0 if ((int(math.floor(beat_value)) + role_index) % 2 == 0) else 0.0
            return 0.0

        if mode == "gallop":
            phase = (beat_value + role_index * 0.18) % 1.0
            if phase < 0.18:
                return 1.0
            if 0.34 <= phase < 0.46:
                return 1.0
            if phase >= 0.72 and phase < 0.82 and energy >= 0.72:
                return 1.0 if role != "moving" or role_index % 2 == 0 else 0.0
            return 0.0

        if mode == "pivot":
            phase = int(math.floor(beat_value)) % 4
            if role_count <= 2:
                return 1.0 if phase in ((0, 3) if role_index % 2 == 0 else (1, 2)) else 0.0
            is_center = abs(centered) < 0.34
            return 1.0 if (phase in (0, 2) and is_center) or (phase in (1, 3) and not is_center) else 0.0

        if mode == "pair_swap" and role == "par":
            step = int(math.floor(beat_value)) % role_count
            return 1.0 if role_index == step else 0.0

        if mode == "pair_hold" and role == "par":
            step = int(math.floor(beat_value / 2.0)) % role_count
            return 1.0 if role_index == step else 0.0

        if mode == "pair_bounce" and role == "par":
            phase = int(math.floor(beat_value)) % 4
            if phase == 0:
                return 1.0 if role_index == 0 else 0.0
            if phase == 1:
                return 1.0
            if phase == 2:
                return 1.0 if role_index == min(1, role_count - 1) else 0.0
            return 1.0

        if mode == "par_snake" and role == "par":
            member_count = max(1, int(slot_context.get("member_count", 1)))
            member_index = int(slot_context.get("member_index", 0))
            cycle = max(2, member_count * 2 - 2)
            raw_step = int(math.floor(beat_value)) % cycle
            step = raw_step if raw_step < member_count else (cycle - raw_step)
            return 1.0 if member_index == step else 0.0

        if mode in {"chase", "chase_whole"}:
            subdivision = 1 if mode == "chase_whole" and role == "moving" else 2 if role == "moving" else 1 if role == "par" else 2
            step = int(math.floor(beat_value * subdivision)) % role_count
            return 1.0 if role_index == step else 0.0

        if mode in {"snake", "snake_whole"}:
            subdivision = 1 if mode == "snake_whole" and role == "moving" else 2 if role == "moving" else 1 if role == "par" else 2
            cycle = max(2, role_count * 2 - 2)
            raw_step = int(math.floor(beat_value * subdivision)) % cycle
            step = raw_step if raw_step < role_count else (cycle - raw_step)
            width = 0 if role == "moving" else 1 if role_count >= 4 else 0
            return 1.0 if abs(role_index - step) <= width else 0.0

        if mode == "ripple":
            return 0.50 + 0.50 * wave_sine(
                beat_value / (2.8 - movement_scale * 0.6)
                + role_index * 0.35
                + centered * 0.18
            )

        if mode == "split":
            phase = int(math.floor(beat_value * 1.5)) % 2
            return 1.0 if phase == (0 if centered <= 0 else 1) else 0.32 + movement_scale * 0.10

        if mode == "ladder":
            step_count = max(2, role_count)
            step = (int(math.floor(beat_value * 2.0)) + role_index) % step_count
            return 1.0 - (step / max(1, step_count - 1)) * 0.64

        if mode == "bloom":
            return 0.36 + (1.0 - abs(centered)) * 0.56 + 0.08 * wave_sine(beat_value / 6.0 + role_index * 0.11)

        return 0.0

    def _texture_multiplier(self, config, osc, now):
        texture_name = str(config.get("_auto_show_texture_name", "steady"))
        slot_context = config.get("_slot_context") or {}
        role = str(slot_context.get("role", "static"))
        if role == "moving":
            return 1.0
        if role == "par":
            return 1.0
        beat_value = osc.get("beat_value")
        beat_value = float(beat_value if beat_value is not None else now * 1.6)
        member_index = int(slot_context.get("member_index", slot_context.get("group_index", 0)))
        member_count = max(1, int(slot_context.get("member_count", slot_context.get("group_count", 1))))
        centered = float(slot_context.get("member_centered", slot_context.get("group_centered", 0.0)))
        center_bias = float(slot_context.get("member_center_bias", slot_context.get("group_center_bias", 0.0)))
        alternate = float(slot_context.get("member_alternate", slot_context.get("group_alternate", 0.0)))
        seed_unit = float(slot_context.get("member_seed_unit", slot_context.get("seed_unit", 0.0)))
        group_seed_unit = float(slot_context.get("group_seed_unit", seed_unit))
        role_depth = {
            "moving": 0.08,
            "par": 0.28,
            "wash": 0.18,
            "static": 0.14,
        }.get(role, 0.14)
        base = 1.0 - role_depth
        phase_seed = seed_unit * 0.37 + group_seed_unit * 0.21

        if texture_name == "steady":
            multiplier = 0.96 + center_bias * 0.04 - abs(seed_unit) * 0.02
        elif texture_name == "drift":
            multiplier = base + role_depth * (0.40 + 0.60 * (0.5 + 0.5 * wave_sine(beat_value / 12.0 + phase_seed)))
        elif texture_name == "ripple":
            multiplier = base + role_depth * (
                0.24 + 0.76 * (0.5 + 0.5 * wave_sine(beat_value / 4.0 + member_index * 0.42 + phase_seed))
            )
        elif texture_name == "split":
            active = (int(math.floor(beat_value * 1.5)) % 2) == (0 if alternate < 0 else 1)
            multiplier = 1.0 if active else base + role_depth * 0.10
        elif texture_name == "ladder":
            step = (int(math.floor(beat_value * 2.0)) + member_index) % max(2, member_count)
            gradient = 1.0 - (step / max(1, member_count - 1)) * 0.82
            multiplier = base + role_depth * max(0.18, gradient)
        elif texture_name == "shuffle":
            window = int(math.floor(beat_value * 1.25))
            random_unit = ((stable_hash(f"{window}|{member_index}|{group_seed_unit:.3f}") % 1000) / 999.0)
            multiplier = base + role_depth * (0.18 + 0.82 * random_unit)
        elif texture_name == "bloom":
            bloom = 0.28 + 0.72 * center_bias
            bloom += 0.10 * wave_sine(beat_value / 6.0 + phase_seed)
            multiplier = base + role_depth * clamp_unit(bloom)
        else:
            multiplier = 1.0

        return max(0.62 if role == "par" else 0.74, min(1.04, multiplier))

    def _resolved_sync_rgbw(self, config, osc):
        manual = config["color"]
        rgbw = (manual["red"], manual["green"], manual["blue"], manual["white"])
        if not config["sync_enabled"]:
            return rgbw

        source = config["color_source"]
        if source == "phrase":
            return color_for_phrase(osc["phrase_current"]) or rgbw
        if source == "mood":
            return color_for_mood(osc["mood"]) or rgbw
        if source == "color_bank":
            return COLOR_BANKS.get(osc["color_bank"], rgbw)
        return rgbw

    def _auto_show_rgbw_for_slot(self, base_rgbw, slot_context, auto_show):
        role = slot_context["role"]
        section = auto_show.get("behavior_bucket", auto_show["phrase_bucket"])
        beat_step = int(auto_show.get("beat_step", 1) or 1)
        energy = auto_show["energy"]
        alternate = slot_context.get("group_alternate", slot_context["alternate"])
        edge_bias = slot_context.get("group_edge_bias", slot_context["edge_bias"])
        center_bias = slot_context.get("group_center_bias", slot_context["center_bias"])
        seed_unit = slot_context.get("group_seed_unit", slot_context.get("seed_unit", 0.0))
        member_seed_unit = slot_context.get("member_seed_unit", slot_context.get("seed_unit", 0.0))
        style = auto_show["style"]
        track_theme = auto_show_track_theme(
            auto_show.get("theme_name", TRACK_SHOW_THEME_SEQUENCE[0])
        )
        look_name = auto_show.get("look_name", "bank_echo")
        color_profile = auto_show_color_profile(
            auto_show.get("color_profile_name", "yellow_blue")
        )
        pulse_name = auto_show.get("pulse_name", "medium")
        drum_signals = auto_show.get("drum_signals") or {}
        kick = clamp_unit(float(drum_signals.get("kick") or 0.0))
        snare = clamp_unit(float(drum_signals.get("snare") or 0.0))
        hihat = clamp_unit(float(drum_signals.get("hihat") or 0.0))
        section_accent = auto_show_section_accent(section)
        theme_contrast = float(track_theme.get("contrast", 0.0))
        theme_white_bias = float(track_theme.get("white_bias", 0.0)) * 0.40

        warm_fill = color_profile["primary"]
        cool_fill = color_profile["secondary"]
        accent = color_profile["accent"]
        white_peak = color_profile["white"]
        warm_mix = float(color_profile["base_mix"])
        cool_mix = float(color_profile["base_mix"])
        accent_mix = float(color_profile["accent_mix"])
        white_mix = float(color_profile["white_mix"])
        split_mix = float(color_profile["split_mix"])

        if style == "festival":
            accent = mix_rgbw(accent, (255, 80, 200, 0), 0.22)
            accent_mix += 0.07
            split_mix += 0.10
            white_mix -= 0.02
        elif style == "minimal":
            warm_fill = mix_rgbw(warm_fill, (170, 150, 120, 0), 0.22)
            cool_fill = mix_rgbw(cool_fill, (100, 125, 190, 0), 0.26)
            accent_mix -= 0.04
            split_mix -= 0.04
            white_mix -= 0.02
        elif style == "warm":
            cool_fill = mix_rgbw(cool_fill, warm_fill, 0.45)
        elif style == "cinematic":
            warm_fill = mix_rgbw(warm_fill, (220, 150, 110, 20), 0.28)
            cool_fill = mix_rgbw(cool_fill, (120, 145, 255, 16), 0.24)

        if look_name == "warm_glow":
            accent = mix_rgbw(accent, warm_fill, 0.55)
            warm_mix += 0.08
            cool_mix -= 0.08
            accent_mix -= 0.01
            white_mix -= 0.01
        elif look_name == "cool_air":
            accent = mix_rgbw(accent, cool_fill, 0.50)
            warm_mix -= 0.08
            cool_mix += 0.08
            white_mix -= 0.01
        elif look_name == "white_bloom":
            accent = mix_rgbw(accent, white_peak, 0.18)
            warm_mix -= 0.02
            cool_mix -= 0.02
            accent_mix -= 0.01
            white_mix += 0.02
        elif look_name == "sunset_push":
            accent = mix_rgbw(accent, warm_fill, 0.38)
            warm_mix += 0.08
            cool_mix -= 0.08
            accent_mix += 0.05
        elif look_name == "ultraviolet":
            accent = mix_rgbw(accent, (205, 110, 255, 10), 0.44)
            warm_mix -= 0.08
            cool_mix += 0.06
            accent_mix += 0.06
            split_mix += 0.04
        elif look_name == "mood_wash":
            accent_mix -= 0.03
            warm_mix -= 0.02
            cool_mix -= 0.02
            white_mix -= 0.02
        elif look_name == "bank_echo":
            accent_mix += 0.03
            warm_mix -= 0.02
            cool_mix -= 0.02
            white_mix -= 0.01
        elif look_name == "neon_split":
            accent = mix_rgbw(accent, (255, 95, 180, 0), 0.32)
            warm_mix -= 0.08
            cool_mix -= 0.08
            accent_mix += 0.04
            white_mix -= 0.02
            split_mix += 0.06

        warm_mix = max(0.02, warm_mix)
        cool_mix = max(0.02, cool_mix)
        accent_mix = max(0.02, accent_mix)
        white_mix = max(0.0, white_mix)
        split_mix = max(0.08, split_mix)
        split_mix += theme_contrast * 0.12
        accent_mix += theme_contrast * 0.05
        white_mix = max(0.0, white_mix + theme_white_bias)

        if section in ("intro", "verse", "down", "break", "outro", "unknown"):
            white_mix = min(white_mix, 0.003)
        elif section == "chorus":
            white_mix = min(white_mix, 0.008)
        elif section == "build":
            white_mix = min(white_mix, 0.012)
        elif section == "drop":
            white_mix = min(white_mix, 0.020)

        accent_mix += abs(seed_unit) * 0.03 + abs(member_seed_unit) * 0.012
        warm_mix += max(0.0, -seed_unit) * 0.05
        cool_mix += max(0.0, seed_unit) * 0.05
        if pulse_name in {"chase", "snake", "gallop"}:
            split_mix += 0.08
            accent_mix += 0.03
            white_mix = max(0.0, white_mix - 0.02)
        elif pulse_name in {"beat_flash", "drop_blinder", "strong_pulse", "double_hit"}:
            white_mix += 0.005
            accent_mix += 0.01
        elif pulse_name in {"low_glow", "slow_fade_out"}:
            white_mix = max(0.0, white_mix - 0.01)
            accent_mix = max(0.03, accent_mix - 0.02)

        if role == "moving":
            palette_shift = int(abs(stable_hash(auto_show.get("theme_name", ""))) % 4)
            moving_palette = [warm_fill, cool_fill, accent, section_accent]
            group_index = int(slot_context.get("group_index", 0))
            member_index = int(slot_context.get("member_index", 0))
            member_count = max(1, int(slot_context.get("member_count", 1)))
            moving_variant_seed = stable_hash(
                "|".join(
                    [
                        str(auto_show.get("theme_name", "")),
                        str(section),
                        str(auto_show.get("motion_name", "")),
                        str(auto_show.get("look_name", "")),
                        str(auto_show.get("color_profile_name", "")),
                        str(auto_show.get("pulse_name", "")),
                    ]
                )
            )
            moving_variant_unit = (moving_variant_seed % 1000) / 999.0
            primary_bias = {
                "intro": 0.06,
                "verse": 0.12,
                "build": 0.24,
                "chorus": 0.30,
                "drop": 0.34,
                "break": 0.10,
                "outro": 0.08,
                "unknown": 0.18,
            }.get(section, 0.16)
            primary_bias += {
                "festival": 0.14,
                "club": 0.10,
                "adaptive": 0.04,
                "warm": -0.04,
                "cinematic": -0.08,
                "minimal": -0.10,
            }.get(style, 0.0)
            primary_hit_active = moving_variant_unit < clamp_unit(primary_bias)
            primary_base = stable_hash(
                "|".join(
                    [
                        str(auto_show.get("theme_name", "")),
                        str(section),
                        str(auto_show.get("color_profile_name", "")),
                    ]
                )
            ) % len(PURE_SHOW_COLORS)
            group_split_threshold = {
                "intro": 0.18,
                "verse": 0.48,
                "build": 0.68,
                "chorus": 0.80,
                "drop": 0.86,
                "break": 0.34,
                "outro": 0.28,
                "unknown": 0.54,
            }.get(section, 0.46)
            member_split_threshold = {
                "intro": 0.00,
                "verse": 0.16,
                "build": 0.44,
                "chorus": 0.60,
                "drop": 0.66,
                "break": 0.10,
                "outro": 0.08,
                "unknown": 0.28,
            }.get(section, 0.20)
            group_split_active = moving_variant_unit <= group_split_threshold
            member_split_active = (
                group_split_active
                and (
                    moving_variant_unit <= member_split_threshold
                    or pulse_name in {"chase", "snake", "beat_flash", "drop_blinder"}
                )
            )
            common_tint = moving_palette[palette_shift % len(moving_palette)]
            pair_base = (group_index * 2 + palette_shift) % len(moving_palette)
            group_tint = moving_palette[pair_base] if group_split_active else common_tint
            secondary_tint = (
                moving_palette[(pair_base + 1) % len(moving_palette)]
                if member_split_active
                else group_tint
            )
            if primary_hit_active:
                group_tint = PURE_SHOW_COLORS[(primary_base + group_index) % len(PURE_SHOW_COLORS)]
                secondary_tint = PURE_SHOW_COLORS[
                    (primary_base + group_index + 2 + member_index) % len(PURE_SHOW_COLORS)
                ]
                if not group_split_active:
                    common_tint = group_tint
            member_phase = member_index / max(1, member_count - 1) if member_count > 1 else 0.5
            member_tint = group_tint if (member_index % 2 == 0 or not member_split_active) else secondary_tint
            group_tint_mix = (
                max(warm_mix, cool_mix)
                * (0.68 if group_split_active else 0.82)
                + split_mix * (0.12 + edge_bias * (0.18 if group_split_active else 0.10))
                + abs(seed_unit) * 0.03
                + theme_contrast * 0.08
            )
            member_tint_mix = (
                (0.18 if member_split_active else 0.04)
                + split_mix * ((0.12 + member_phase * 0.10) if member_split_active else 0.03)
                + abs(member_seed_unit) * 0.03
                + energy * (0.04 if member_split_active else 0.01)
            )
            rgbw = mix_rgbw(base_rgbw, accent, accent_mix + energy * 0.04 + center_bias * 0.02)
            rgbw = mix_rgbw(rgbw, group_tint, group_tint_mix)
            rgbw = mix_rgbw(rgbw, member_tint, member_tint_mix)
            rgbw = mix_rgbw(
                rgbw,
                section_accent,
                0.03 + edge_bias * 0.05 + max(0.0, member_seed_unit) * 0.03,
            )
            if section in ("build", "chorus", "drop"):
                rgbw = mix_rgbw(
                    rgbw,
                    white_peak,
                    white_mix * 0.10 + energy * 0.003 + center_bias * 0.002 + max(0.0, seed_unit) * 0.002,
                )
            if section == "chorus":
                beat_palette = (
                    [
                        PURE_SHOW_COLORS[(primary_base + member_index) % len(PURE_SHOW_COLORS)],
                        PURE_SHOW_COLORS[(primary_base + member_index + 2) % len(PURE_SHOW_COLORS)],
                        PURE_SHOW_COLORS[(primary_base + member_index + 4) % len(PURE_SHOW_COLORS)],
                    ]
                    if primary_hit_active
                    else [group_tint, secondary_tint, accent]
                )
                beat_color = beat_palette[(beat_step - 1 + member_index + group_index) % len(beat_palette)]
                beat_mix = 0.20 if beat_step in (2, 4) and group_split_active else 0.10
                rgbw = mix_rgbw(rgbw, beat_color, beat_mix)
                if beat_step == 1:
                    rgbw = mix_rgbw(rgbw, accent, 0.08)
            elif section in ("build", "drop") and group_split_active:
                beat_palette = (
                    [
                        PURE_SHOW_COLORS[(primary_base + member_index) % len(PURE_SHOW_COLORS)],
                        PURE_SHOW_COLORS[(primary_base + member_index + 3) % len(PURE_SHOW_COLORS)],
                    ]
                    if primary_hit_active
                    else [group_tint, secondary_tint]
                )
                beat_color = beat_palette[(beat_step + member_index) % len(beat_palette)]
                rgbw = mix_rgbw(rgbw, beat_color, 0.12 if beat_step in (1, 3) else 0.06)
            if section in ("build", "chorus", "drop"):
                if snare > 0.0:
                    rgbw = mix_rgbw(rgbw, accent, 0.02 + snare * 0.07)
                if hihat > 0.0:
                    rgbw = mix_rgbw(
                        rgbw,
                        secondary_tint if member_split_active else cool_fill,
                        0.01 + hihat * 0.04,
                    )
                if kick > 0.44 and section in ("build", "drop"):
                    rgbw = mix_rgbw(rgbw, white_peak, 0.002 + kick * 0.006)
            saturation_floor = {
                "intro": 0.68,
                "verse": 0.72,
                "build": 0.78,
                "chorus": 0.80,
                "drop": 0.84,
                "break": 0.70,
                "outro": 0.68,
                "unknown": 0.74,
            }.get(section, 0.74)
            rgbw = saturate_rgbw(rgbw, minimum_saturation=saturation_floor, white_cap=0)
            rgbw = normalize_rgbw_peak(rgbw, peak_target=255, white_cap=0, minimum_peak=110)
            return clarify_rgbw(rgbw, anchor_strength=0.76, white_cap=0)

        if role == "par":
            palette_shift = int(abs(stable_hash(auto_show.get("theme_name", ""))) % 4)
            par_palette = [warm_fill, cool_fill, accent, section_accent]
            member_index = int(slot_context.get("member_index", 0))
            member_count = max(1, int(slot_context.get("member_count", 1)))
            pair_index = min(member_index, member_count - 1 - member_index)
            par_variant_seed = stable_hash(
                "|".join(
                    [
                        str(auto_show.get("theme_name", "")),
                        str(section),
                        str(auto_show.get("color_profile_name", "")),
                        "par",
                    ]
                )
            )
            par_variant_unit = (par_variant_seed % 1000) / 999.0
            par_primary_bias = {
                "intro": 0.04,
                "verse": 0.10,
                "build": 0.22,
                "chorus": 0.28,
                "drop": 0.32,
                "break": 0.08,
                "outro": 0.06,
                "unknown": 0.16,
            }.get(section, 0.14)
            par_primary_bias += {
                "festival": 0.12,
                "club": 0.08,
                "adaptive": 0.04,
                "warm": -0.04,
                "cinematic": -0.08,
                "minimal": -0.10,
            }.get(style, 0.0)
            par_primary_active = par_variant_unit < clamp_unit(par_primary_bias)
            par_primary_base = par_variant_seed % len(PURE_SHOW_COLORS)
            pair_count = max(1, (member_count + 1) // 2)
            pair_phase = pair_index / max(1, pair_count - 1) if pair_count > 1 else 0.0
            tint = par_palette[(pair_index + palette_shift) % len(par_palette)]
            secondary_tint = par_palette[(pair_index + palette_shift + 1) % len(par_palette)]
            if par_primary_active:
                tint = PURE_SHOW_COLORS[(par_primary_base + pair_index) % len(PURE_SHOW_COLORS)]
                secondary_tint = PURE_SHOW_COLORS[(par_primary_base + pair_index + 2) % len(PURE_SHOW_COLORS)]
            tint_mix = (
                max(warm_mix, cool_mix) * 0.96
                + 0.08
                + abs(seed_unit) * 0.06
                + abs(member_seed_unit) * 0.012
                + edge_bias * 0.06
                + theme_contrast * 0.10
            )
            rgbw = mix_rgbw(base_rgbw, tint, tint_mix)
            rgbw = mix_rgbw(
                rgbw,
                secondary_tint,
                0.01 + split_mix * (0.04 + pair_phase * 0.06),
            )
            rgbw = mix_rgbw(
                rgbw,
                accent,
                accent_mix * (0.18 + pair_phase * 0.10) + energy * 0.03,
            )
            if section == "chorus":
                beat_palette = (
                    [
                        PURE_SHOW_COLORS[(par_primary_base + pair_index) % len(PURE_SHOW_COLORS)],
                        PURE_SHOW_COLORS[(par_primary_base + pair_index + 3) % len(PURE_SHOW_COLORS)],
                    ]
                    if par_primary_active
                    else [warm_fill, cool_fill]
                )
                beat_color = beat_palette[(beat_step - 1 + pair_index) % len(beat_palette)]
                beat_mix = 0.22 if beat_step in (2, 4) else 0.12
                rgbw = mix_rgbw(rgbw, beat_color, beat_mix)
                if beat_step == 1:
                    rgbw = mix_rgbw(rgbw, accent, 0.08)
            if section in ("build", "chorus", "drop"):
                if snare > 0.0:
                    rgbw = mix_rgbw(rgbw, accent, 0.015 + snare * 0.05)
                if hihat > 0.0:
                    rgbw = mix_rgbw(rgbw, cool_fill, 0.01 + hihat * 0.03)
            if section in ("intro", "down", "break", "outro"):
                rgbw = mix_rgbw(rgbw, warm_fill, warm_mix * 0.28)
            saturation_floor = {
                "intro": 0.56,
                "verse": 0.62,
                "build": 0.72,
                "chorus": 0.76,
                "drop": 0.80,
                "break": 0.60,
                "outro": 0.56,
                "unknown": 0.64,
            }.get(section, 0.64)
            rgbw = saturate_rgbw(rgbw, minimum_saturation=saturation_floor, white_cap=0)
            rgbw = normalize_rgbw_peak(rgbw, peak_target=255, white_cap=0, minimum_peak=110)
            return clarify_rgbw(rgbw, anchor_strength=0.70, white_cap=0)

        if role == "wash":
            wash_palette = [cool_fill, warm_fill, section_accent]
            tint = wash_palette[(int(slot_context.get("group_index", 0)) + (0 if section in ("verse", "down", "break") else 1)) % len(wash_palette)]
            tint_mix = (
                max(warm_mix, cool_mix)
                + 0.10
                + edge_bias * 0.10
                + abs(seed_unit) * 0.05
                + abs(member_seed_unit) * 0.010
                + theme_contrast * 0.06
            )
            rgbw = mix_rgbw(base_rgbw, tint, tint_mix)
            rgbw = mix_rgbw(rgbw, white_peak, white_mix * 0.35 + (1.0 - energy) * 0.015)
            if section == "chorus":
                beat_palette = [cool_fill, warm_fill]
                beat_color = beat_palette[(beat_step - 1 + int(slot_context.get("group_index", 0))) % len(beat_palette)]
                rgbw = mix_rgbw(rgbw, beat_color, 0.10 if beat_step in (1, 3) else 0.18)
            if section in ("build", "chorus", "drop") and hihat > 0.0:
                rgbw = mix_rgbw(rgbw, section_accent, 0.01 + hihat * 0.04)
            rgbw = saturate_rgbw(rgbw, minimum_saturation=0.46, white_cap=0)
            return normalize_rgbw_peak(rgbw, peak_target=255, white_cap=0, minimum_peak=96)

        rgbw = saturate_rgbw(
            mix_rgbw(base_rgbw, accent, accent_mix + energy * 0.06),
            minimum_saturation=0.60,
            white_cap=0,
        )
        return normalize_rgbw_peak(rgbw, peak_target=255, white_cap=0, minimum_peak=110)

    def _wall_wash_zone_rgb_for_slot(self, slot_context, auto_show, osc):
        cue_name = str(auto_show.get("wash_cue_name", "soft_blue_wash"))
        cue = auto_show_wall_wash_cue(cue_name)
        frames = cue.get("frames") or [[[0, 0, 0]] * 8]
        beats_per_frame = max(0.125, float(cue.get("beats_per_frame", 1.0) or 1.0))
        beat_value = float(osc.get("beat_value") or 0.0)
        frame_index = int(math.floor(beat_value / beats_per_frame)) % max(1, len(frames))
        segments = list(frames[frame_index])

        if cue.get("mirror_on_odd") and int(slot_context.get("member_index", 0)) % 2 == 1:
            segments = list(reversed(segments))

        if cue.get("flash"):
            flash_hold = max(0.04, min(1.0, float(cue.get("flash_hold", 0.18) or 0.18)))
            phase = (beat_value / beats_per_frame) % 1.0
            if phase > flash_hold:
                segments = [WW_BLACK] * 8

        zone_rgb = []
        for segment in segments[:8]:
            red = clamp_dmx(segment[0] if len(segment) > 0 else 0)
            green = clamp_dmx(segment[1] if len(segment) > 1 else 0)
            blue = clamp_dmx(segment[2] if len(segment) > 2 else 0)
            zone_rgb.append((red, green, blue, 0))
        while len(zone_rgb) < 8:
            zone_rgb.append((0, 0, 0, 0))
        return zone_rgb

    def _wall_wash_average_rgbw(self, zone_rgb):
        if not zone_rgb:
            return (0, 0, 0, 0)
        count = max(1, len(zone_rgb))
        return (
            clamp_dmx(round(sum(int(segment[0]) for segment in zone_rgb) / count)),
            clamp_dmx(round(sum(int(segment[1]) for segment in zone_rgb) / count)),
            clamp_dmx(round(sum(int(segment[2]) for segment in zone_rgb) / count)),
            0,
        )

    def _one_shot_intensity(self, cue_id, progress):
        progress = clamp_unit(progress)
        if cue_id == "audience_riser":
            if progress >= 0.98:
                return 0.0
            if progress <= 0.02:
                return 0.0
            return clamp_unit((min(progress, 0.90) - 0.02) / 0.88)
        if cue_id == "white_hit":
            if progress <= 0.12:
                return 1.0
            return clamp_unit(1.0 - ((progress - 0.12) / 0.88)) ** 0.36
        if cue_id == "color_burst":
            if progress >= 0.92:
                return 0.0
            return 0.70 + 0.30 * math.sin(min(1.0, progress / 0.92) * math.pi)
        if cue_id == "snap_fan":
            if progress >= 0.86:
                return 0.0
            if progress <= 0.10:
                return 1.0
            return clamp_unit(1.0 - ((progress - 0.10) / 0.76)) ** 0.24
        if cue_id == "mirror_bounce":
            if progress >= 0.96:
                return 0.0
            swing = 0.5 + 0.5 * wave_sine(progress * 4.0)
            return 0.52 + swing * 0.48
        if cue_id == "par_chase_burst":
            if progress >= 0.96:
                return 0.0
            return 1.0
        return 0.0

    def _one_shot_rgbw(self, cue_id, slot_context, progress):
        alternate = float(slot_context.get("group_alternate", slot_context.get("alternate", 1.0)))
        role = str(slot_context.get("role", "static"))
        if cue_id == "white_hit":
            return (255, 255, 255, 255)
        if cue_id == "audience_riser":
            white = clamp_dmx(round(80 + min(1.0, progress / 0.88) * 140))
            return (255, 180, 70, white)
        if cue_id == "color_burst":
            return (255, 40, 150, 0) if alternate >= 0 else (0, 180, 255, 0)
        if cue_id == "snap_fan":
            return (255, 255, 255, 180)
        if cue_id == "mirror_bounce":
            return (255, 0, 190, 0) if alternate >= 0 else (0, 190, 255, 0)
        if cue_id == "par_chase_burst":
            if role == "moving":
                return (255, 170, 50, 0)
            return (0, 120, 255, 0) if alternate >= 0 else (255, 0, 160, 0)
        return None

    def _one_shot_zone_rgb(self, cue_id, slot_context, progress):
        if cue_id == "white_hit":
            return [(255, 255, 255, 255)] * 8
        if cue_id == "audience_riser":
            build = clamp_unit(min(progress, 0.90) / 0.90)
            inner = (
                clamp_dmx(round(90 + build * 165)),
                clamp_dmx(round(50 + build * 150)),
                clamp_dmx(round(20 + build * 120)),
                0,
            )
            outer = (
                clamp_dmx(round(10 + build * 80)),
                clamp_dmx(round(4 + build * 36)),
                clamp_dmx(round(build * 24)),
                0,
            )
            return [outer, outer, inner, inner, inner, inner, outer, outer]
        if cue_id == "color_burst":
            color_a = (255, 40, 150, 0)
            color_b = (0, 180, 255, 0)
            return [color_a if index % 2 == 0 else color_b for index in range(8)]
        if cue_id == "par_chase_burst":
            step = int(math.floor(progress * 8.0)) % 8
            trailing = (step - 1) % 8
            segments = []
            for index in range(8):
                if index == step:
                    segments.append((0, 140, 255, 0))
                elif index == trailing:
                    segments.append((0, 50, 140, 0))
                else:
                    segments.append((0, 0, 0, 0))
            if int(slot_context.get("member_index", 0)) % 2 == 1:
                segments.reverse()
            return segments
        return None

    def _one_shot_motion_for_config(self, cue_id, progress, slot_context, config, beat_value):
        if cue_id == "audience_riser":
            role_count = max(1, int(slot_context.get("role_count", slot_context.get("member_count", 1))))
            role_index = int(slot_context.get("role_index", slot_context.get("member_index", 0)))
            start_positions = [158, 164, 170, 176]
            end_positions = [135, 158, 182, 205]
            if role_count == 2:
                start_positions = [164, 172]
                end_positions = [148, 192]
            elif role_count <= 1:
                start_positions = [166]
                end_positions = [170]
            slot_position = min(len(start_positions) - 1, role_index if role_count > 1 else 0)
            move = clamp_unit(min(progress, 0.98) / 0.98)
            pan = round(
                start_positions[slot_position]
                + (end_positions[slot_position] - start_positions[slot_position]) * move
            )
            tilt = round(127 + (0 - 127) * move)
            return {
                "pan": clamp_dmx(pan),
                "tilt": clamp_dmx(tilt),
                "pan_tilt_speed": 32,
            }

        motion_map = {
            "snap_fan": "drop_snap_fan",
            "mirror_bounce": "mirror_bounce_show",
        }
        motion_name = motion_map.get(cue_id)
        if not motion_name:
            return None
        motion = styled_phrase_motion(
            "one_shot",
            float(beat_value or 0.0),
            motion_name,
            slot_context,
            0.92 if cue_id == "mirror_bounce" else 0.78,
            config,
        )
        return maybe_apply_member_mirror(
            motion,
            slot_context,
            cue_id == "mirror_bounce",
            config=config,
        )

    def _apply_one_shot_cue_to_effective_slot(self, effective, auto_show, osc, slot_context, capabilities):
        cue_id = one_shot_cue_name(auto_show.get("one_shot_cue"))
        if cue_id == "none" or not auto_show.get("one_shot_active"):
            return effective
        progress = clamp_unit(auto_show.get("one_shot_progress") or 0.0)
        role = str(slot_context.get("role", "static"))
        intensity = self._one_shot_intensity(cue_id, progress)

        effective["_one_shot_cue_id"] = cue_id
        effective["_one_shot_cue_progress"] = progress
        effective["osc_strobe_enabled"] = False
        effective["strobe"] = 0

        rgbw = self._one_shot_rgbw(cue_id, slot_context, progress)
        if rgbw is not None:
            effective["_auto_show_rgbw"] = rgbw
            effective["_force_rgbw_override"] = True
            effective["color"] = {
                "red": int(rgbw[0]),
                "green": int(rgbw[1]),
                "blue": int(rgbw[2]),
                "white": int(rgbw[3]),
            }

        zone_rgb = self._one_shot_zone_rgb(cue_id, slot_context, progress)
        if role == "wash" and zone_rgb is not None:
            effective["_auto_show_zone_rgb"] = zone_rgb
            effective["_auto_show_rgbw"] = self._wall_wash_average_rgbw(zone_rgb)

        if cue_id == "par_chase_burst" and role == "par":
            effective["_auto_show_rhythm_mode"] = "pair_swap"
            effective["beat_pulse_enabled"] = True
            effective["beat_depth"] = 255
            effective["beat_decay_ms"] = 90
            effective["dimmer"] = max(effective["dimmer"], 230)
            return effective

        effective["beat_pulse_enabled"] = False
        effective["_auto_show_rhythm_mode"] = "full_on"

        if role == "moving" and cue_id in {"audience_riser", "snap_fan", "mirror_bounce"}:
            if cue_id == "snap_fan":
                effective["pan_tilt_speed"] = 0
            elif cue_id == "mirror_bounce":
                effective["pan_tilt_speed"] = 24
            else:
                effective["pan_tilt_speed"] = 32

        if cue_id == "par_chase_burst":
            effective["dimmer"] = clamp_dmx(round((220 if role == "moving" else 255) * intensity))
        else:
            base_peak = 255 if role != "wash" else 220
            effective["dimmer"] = clamp_dmx(round(base_peak * intensity))
        return effective

    def _live_override_active(self, auto_show):
        return bool(
            live_override_color_name(auto_show.get("override_color")) != "none"
            or auto_show.get("override_manual_strobe")
            or auto_show.get("override_audience_sweep")
            or auto_show.get("override_all_on")
            or auto_show.get("override_par_chase")
            or auto_show.get("override_par_snake")
            or auto_show.get("one_shot_active")
        )

    def _live_override_rainbow_rgbw(self, osc, slot_context):
        palette = [
            (255, 0, 0, 0),
            (255, 220, 0, 0),
            (0, 255, 0, 0),
            (0, 255, 255, 0),
            (0, 80, 255, 0),
            (180, 0, 255, 0),
            (255, 120, 0, 0),
            (255, 255, 255, 255),
        ]
        beat_value = osc.get("beat_value")
        beat_step = int(math.floor(float(beat_value or 0.0)))
        fixture_index = int(
            slot_context.get(
                "global_index",
                slot_context.get("group_index", slot_context.get("member_index", 0)),
            )
        )
        return palette[(beat_step + fixture_index) % len(palette)]

    def _live_override_rgbw_for_slot(self, override_color, slot_context, osc):
        color_name = live_override_color_name(override_color)
        if color_name == "none":
            return None
        if color_name != "rainbow":
            return LIVE_OVERRIDE_COLORS[color_name]

        return self._live_override_rainbow_rgbw(osc, slot_context)

    def _live_override_zone_rgb_for_slot(self, override_color, slot_context, osc):
        color_name = live_override_color_name(override_color)
        if color_name == "none":
            return None
        if color_name == "rainbow":
            rgbw = self._live_override_rainbow_rgbw(osc, slot_context)
            return [rgbw] * 8
        rgbw = LIVE_OVERRIDE_COLORS[color_name]
        return [rgbw] * 8

    def _slot_key_base_for_fixture(self, fixture_id):
        label_base = fixture_preset(fixture_id)["label_base"].lower()
        normalized = "".join(ch if ch.isalnum() else "_" for ch in label_base).strip("_")
        if not normalized:
            normalized = "fixture"
        return normalized

    def _next_slot_id(self, config, fixture_id):
        base = self._slot_key_base_for_fixture(fixture_id)
        if base not in config["slots"]:
            return base
        suffix = 2
        while f"{base}_{suffix}" in config["slots"]:
            suffix += 1
        return f"{base}_{suffix}"

    def _next_slot_label(self, config, label_base):
        used = {slot_config["label"] for slot_config in config["slots"].values()}
        if label_base not in used:
            return label_base
        suffix = 2
        while f"{label_base} {suffix}" in used:
            suffix += 1
        return f"{label_base} {suffix}"

    def _next_available_address(self, config, fixture, mode_name):
        footprint = int(find_mode(fixture, mode_name)["footprint"])
        ranges = []
        for slot_id, slot_config in config["slots"].items():
            slot_range = self._range_for_slot(slot_id, slot_config)
            if slot_range:
                ranges.append((slot_range["address"], slot_range["last_channel"]))
        candidate = 1
        for start, end in sorted(ranges):
            if candidate + footprint - 1 < start:
                return candidate
            candidate = max(candidate, end + 1)
        if candidate + footprint - 1 <= DMX_CHANNELS:
            return candidate
        return max(1, DMX_CHANNELS - footprint + 1)

    def _range_for_slot(self, slot_id, config):
        try:
            fixture = find_fixture(FIXTURE_LIBRARY, config["fixture"])
            mode = find_mode(fixture, config["mode"])
            address = int(config["address"])
            return {
                "slot_id": slot_id,
                "label": config["label"],
                "enabled": config["enabled"],
                "fixture_label": f"{fixture['manufacturer']} {fixture['model']}",
                "mode": mode["name"],
                "address": address,
                "last_channel": address + int(mode["footprint"]) - 1,
            }
        except Exception:
            return None

    def _fixture_motion_ranges(self, fixture):
        pan_range = float(fixture.get("pan_range") or 180.0)
        tilt_range = float(fixture.get("tilt_range") or 90.0)
        return max(90.0, pan_range), max(45.0, tilt_range)

    @staticmethod
    def _dmx_to_degrees(value, axis_range):
        return ((float(value) / 255.0) - 0.5) * float(axis_range)

    @staticmethod
    def _degrees_to_dmx(value, axis_range):
        axis_range = max(1.0, float(axis_range))
        normalized = (float(value) / axis_range) + 0.5
        return clamp_dmx(round(normalized * 255.0))

    @staticmethod
    def _degrees_to_dmx16(value, axis_range):
        axis_range = max(1.0, float(axis_range))
        normalized = (float(value) / axis_range) + 0.5
        normalized = max(0.0, min(1.0, normalized))
        return max(0, min(65535, int(round(normalized * 65535.0))))

    @staticmethod
    def _apply_axis_calibration(logical_degrees, axis_range, invert, offset_deg, span_percent):
        calibrated = float(logical_degrees) * max(0.01, float(span_percent) / 100.0)
        if invert:
            calibrated *= -1.0
        calibrated += float(offset_deg)
        half_range = max(1.0, float(axis_range) / 2.0)
        return max(-half_range, min(half_range, calibrated))

    @staticmethod
    def _remove_axis_calibration(calibrated_degrees, axis_range, invert, offset_deg, span_percent):
        logical = float(calibrated_degrees) - float(offset_deg)
        if invert:
            logical *= -1.0
        logical /= max(0.01, float(span_percent) / 100.0)
        half_range = max(1.0, float(axis_range) / 2.0)
        return max(-half_range, min(half_range, logical))

    def _axis_motion_profile(self, axis_range, speed_value, axis_name):
        speed_ratio = 1.0 - clamp_unit(float(speed_value or 0) / 255.0)
        if axis_name == "pan":
            # Realistic, but still visibly responsive for compact moving heads:
            # full 540 degree travel usually lands around 3-7 seconds depending on speed.
            fast_travel_seconds = 2.8
            slow_travel_seconds = 5.2
        else:
            # Tilt travel is typically faster than pan on these fixtures.
            fast_travel_seconds = 1.7
            slow_travel_seconds = 3.3
        travel_seconds = slow_travel_seconds - (
            (slow_travel_seconds - fast_travel_seconds) * speed_ratio
        )
        max_speed = float(axis_range) / max(0.5, travel_seconds)
        max_accel = max_speed * (1.08 + speed_ratio * 0.62)
        response_window = max(0.18, 0.42 - speed_ratio * 0.12)
        return max_speed, max_accel, response_window

    @staticmethod
    def _step_motion_axis(current, velocity, target, dt, max_speed, max_accel, response_window):
        if dt <= 0:
            return current, velocity

        delta = target - current
        if abs(delta) < 0.01 and abs(velocity) < 0.01:
            return target, 0.0

        desired_velocity = max(
            -max_speed,
            min(max_speed, delta / max(response_window, dt)),
        )
        if desired_velocity > velocity:
            velocity = min(desired_velocity, velocity + max_accel * dt)
        else:
            velocity = max(desired_velocity, velocity - max_accel * dt)

        next_value = current + velocity * dt
        if (target - current) == 0 or ((target - current) > 0) != ((target - next_value) > 0):
            next_value = target
            velocity = 0.0
        return next_value, velocity

    def _realized_motion(self, slot_id, fixture, config, desired_pan, desired_tilt, motion_active, now, advance=True):
        pan_range, tilt_range = self._fixture_motion_ranges(fixture)
        logical_target_pan_deg = self._dmx_to_degrees(desired_pan, pan_range)
        logical_target_tilt_deg = self._dmx_to_degrees(desired_tilt, tilt_range)
        target_pan_deg = self._apply_axis_calibration(
            logical_target_pan_deg,
            pan_range,
            bool(config.get("pan_invert")),
            int(config.get("pan_offset_deg", 0) or 0),
            int(config.get("pan_span_percent", 100) or 100),
        )
        target_tilt_deg = self._apply_axis_calibration(
            logical_target_tilt_deg,
            tilt_range,
            bool(config.get("tilt_invert")),
            int(config.get("tilt_offset_deg", 0) or 0),
            int(config.get("tilt_span_percent", 100) or 100),
        )
        speed_value = int(config.get("pan_tilt_speed", 0) or 0)
        state = self.motion_states.get(slot_id)

        if state is None:
            state = {
                "pan_deg": target_pan_deg,
                "tilt_deg": target_tilt_deg,
                "pan_velocity": 0.0,
                "tilt_velocity": 0.0,
                "updated_at": now,
            }
            self.motion_states[slot_id] = state

        current_pan_deg = float(state.get("pan_deg", target_pan_deg))
        current_tilt_deg = float(state.get("tilt_deg", target_tilt_deg))
        pan_velocity = float(state.get("pan_velocity", 0.0))
        tilt_velocity = float(state.get("tilt_velocity", 0.0))
        pan_speed_dps = abs(pan_velocity)
        tilt_speed_dps = abs(tilt_velocity)

        if advance:
            dt = max(1.0 / 240.0, min(0.20, now - float(state.get("updated_at", now))))
            pan_profile = self._axis_motion_profile(pan_range, speed_value, "pan")
            tilt_profile = self._axis_motion_profile(tilt_range, speed_value, "tilt")
            current_pan_deg, pan_velocity = self._step_motion_axis(
                current_pan_deg,
                pan_velocity,
                target_pan_deg,
                dt,
                *pan_profile,
            )
            current_tilt_deg, tilt_velocity = self._step_motion_axis(
                current_tilt_deg,
                tilt_velocity,
                target_tilt_deg,
                dt,
                *tilt_profile,
            )
            pan_speed_dps = abs(pan_velocity)
            tilt_speed_dps = abs(tilt_velocity)
            state.update(
                {
                    "pan_deg": current_pan_deg,
                    "tilt_deg": current_tilt_deg,
                    "pan_velocity": pan_velocity,
                    "tilt_velocity": tilt_velocity,
                    "updated_at": now,
                }
            )

        still_moving = (
            abs(target_pan_deg - current_pan_deg) > 0.35
            or abs(target_tilt_deg - current_tilt_deg) > 0.35
            or pan_speed_dps > 0.5
            or tilt_speed_dps > 0.5
        )
        logical_current_pan_deg = self._remove_axis_calibration(
            current_pan_deg,
            pan_range,
            bool(config.get("pan_invert")),
            int(config.get("pan_offset_deg", 0) or 0),
            int(config.get("pan_span_percent", 100) or 100),
        )
        logical_current_tilt_deg = self._remove_axis_calibration(
            current_tilt_deg,
            tilt_range,
            bool(config.get("tilt_invert")),
            int(config.get("tilt_offset_deg", 0) or 0),
            int(config.get("tilt_span_percent", 100) or 100),
        )
        pan_16bit = self._degrees_to_dmx16(current_pan_deg, pan_range)
        tilt_16bit = self._degrees_to_dmx16(current_tilt_deg, tilt_range)

        return {
            "pan": (pan_16bit >> 8) & 0xFF,
            "pan_fine": pan_16bit & 0xFF,
            "tilt": (tilt_16bit >> 8) & 0xFF,
            "tilt_fine": tilt_16bit & 0xFF,
            "target_pan": clamp_dmx(desired_pan),
            "target_tilt": clamp_dmx(desired_tilt),
            "pan_range": pan_range,
            "tilt_range": tilt_range,
            "pan_degrees": current_pan_deg,
            "tilt_degrees": current_tilt_deg,
            "target_pan_degrees": target_pan_deg,
            "target_tilt_degrees": target_tilt_deg,
            "logical_pan_degrees": logical_current_pan_deg,
            "logical_tilt_degrees": logical_current_tilt_deg,
            "logical_target_pan_degrees": logical_target_pan_deg,
            "logical_target_tilt_degrees": logical_target_tilt_deg,
            "pan_speed_dps": pan_speed_dps,
            "tilt_speed_dps": tilt_speed_dps,
            "motion_active": bool(motion_active or still_moving),
        }

    def _render_values(self, now, advance_motion=True, config=None, osc=None, auto_show=None):
        config = config or self._clean_full_config(dict(self.config))
        osc = osc or self.osc.snapshot_for_render()
        auto_show = auto_show or self._auto_show_state(osc, config["auto_show"])
        return self._render_values_with_context(
            now,
            config,
            osc,
            auto_show,
            advance_motion=advance_motion,
        )

    def _build_slot_previews(self, config, osc, now, auto_show=None):
        auto_show = auto_show or self._auto_show_state(osc, config.get("auto_show", {}))
        return {
            slot_id: self._preview_for_slot(
                slot_id,
                slot_config,
                osc,
                now,
                full_config=config,
                auto_show=auto_show,
            )
            for slot_id, slot_config in config["slots"].items()
        }

    def _render_values_with_context(self, now, config, osc, auto_show, advance_motion=True):
        if config["blackout_active"]:
            self.conflicts = []
            return {}
        self._log_auto_show_transition(auto_show, osc)
        merged_values = {}
        owners = {}
        conflicts = []
        for slot_id in config["slot_order"]:
            slot_config = config["slots"][slot_id]
            if not slot_config["enabled"]:
                continue
            effective_slot_config = self._effective_slot_config(
                slot_id, slot_config, osc, auto_show, full_config=config
            )
            self._log_slot_trigger_state(slot_id, effective_slot_config, auto_show, osc)
            slot_values = self._render_slot_values(
                slot_id,
                effective_slot_config,
                osc,
                now,
                advance_motion=advance_motion,
            )
            for channel, value in slot_values.items():
                previous_owner = owners.get(channel)
                if previous_owner and previous_owner != slot_id:
                    conflicts.append(
                        {
                            "channel": channel,
                            "first": previous_owner,
                            "second": slot_id,
                        }
                    )
                owners[channel] = slot_id
                merged_values[channel] = value
        self.conflicts = conflicts
        return merged_values

    def _log_auto_show_transition(self, auto_show, osc):
        signature = (
            bool(auto_show.get("enabled")),
            str(auto_show.get("style")),
            str(auto_show.get("phrase_bucket")),
            str(auto_show.get("cue_label")),
            str(auto_show.get("rhythm_mode")),
            bool(auto_show.get("beat_pulse")),
            bool(auto_show.get("strobe_window")),
            bool(auto_show.get("external_strobe")),
            str((auto_show.get("waveform_analysis") or {}).get("state", "neutral")),
        )
        if signature == self.last_auto_show_signature:
            return
        self.last_auto_show_signature = signature
        self.debug_log.log(
            "AUTOSHOW",
            enabled=auto_show.get("enabled"),
            style=auto_show.get("style"),
            phrase=osc.get("phrase_current"),
            cue=auto_show.get("cue_label"),
            rhythm=auto_show.get("rhythm_mode"),
            beat=auto_show.get("beat_pulse"),
            strobe=auto_show.get("strobe_window"),
            external_strobe=auto_show.get("external_strobe"),
            waveform=(auto_show.get("waveform_analysis") or {}).get("state", "neutral"),
            mood=osc.get("mood"),
            bank=osc.get("color_bank"),
        )

    def _log_slot_trigger_state(self, slot_id, config, auto_show, osc):
        slot_context = config.get("_slot_context") or {}
        role = slot_context.get("role", "static")
        signature = (
            str(config.get("_auto_show_motion_name", "")),
            str(config.get("_auto_show_rhythm_mode", "")),
            bool(config.get("beat_pulse_enabled")),
            bool(config.get("osc_strobe_enabled")),
            bool(osc.get("strobe_active")),
            int(config.get("strobe", 0) or 0),
        )
        if self.last_slot_trigger_signatures.get(slot_id) == signature:
            return
        self.last_slot_trigger_signatures[slot_id] = signature
        self.debug_log.log(
            "SLOT_TRIGGER",
            slot=slot_id,
            label=config.get("label"),
            role=role,
            motion=config.get("_auto_show_motion_name"),
            rhythm=config.get("_auto_show_rhythm_mode"),
            beat=config.get("beat_pulse_enabled"),
            osc_strobe=config.get("osc_strobe_enabled"),
            strobe_active=osc.get("strobe_active"),
            cue=auto_show.get("cue_label"),
        )

    def _external_strobe_gate(self, osc, role):
        count_in = osc.get("strobe_count_in")
        active = bool(osc.get("strobe_active"))
        if active:
            return True
        if count_in not in (1, 2):
            return False

        age = osc.get("beat_phase_age_seconds")
        if age is None:
            last_beat_at = osc.get("last_beat_at")
            if not last_beat_at:
                return False
            age = time.time() - last_beat_at

        beat_value = osc.get("beat_value")
        if beat_value is None:
            return False

        section = phrase_bucket(osc.get("phrase_current"))
        beat_step = int(math.floor(float(beat_value))) % 8

        if count_in in (1, 2):
            hit_steps = (0, 2, 4, 6)
            if section == "drop":
                open_window = 0.18 if role in ("moving", "par") else 0.14
            elif section in ("build", "chorus"):
                open_window = 0.16 if role in ("moving", "par") else 0.12
            else:
                open_window = 0.14 if role in ("moving", "par") else 0.10
        else:
            return False

        return beat_step in hit_steps and float(age) <= open_window

    def _effective_strobe_state(self, config, osc):
        strobe = int(config.get("strobe", 0) or 0)
        external_strobe_applied = False
        role = str((config.get("_slot_context") or {}).get("role", "static"))
        if (
            config["sync_enabled"]
            and config["osc_strobe_enabled"]
            and self._external_strobe_gate(osc, role)
        ):
            strobe_floor = 235 if role in ("par", "moving") else 220
            strobe = max(strobe, strobe_floor)
            external_strobe_applied = True
        return strobe, external_strobe_applied

    def _motion_uses_locked_rgbw(self, motion, config):
        if not motion or bool(config.get("_force_rgbw_override")):
            return False
        return bool(motion.get("lock_color"))

    def _effective_brightness_with_motion(self, config, motion, osc, now):
        rhythm_brightness = self._brightness_for_config(config, osc, now)
        if not motion or motion.get("dimmer") is None:
            return rhythm_brightness

        motion_dimmer = clamp_dmx(motion.get("dimmer"))
        configured_dimmer = max(1, int(config.get("dimmer", 0) or 0))
        rhythm_ratio = max(0.0, float(rhythm_brightness) / float(configured_dimmer))
        return clamp_dmx(round(motion_dimmer * rhythm_ratio))

    def _render_slot_values(self, slot_id, config, osc, now, advance_motion=True):
        fixture = find_fixture(FIXTURE_LIBRARY, config["fixture"])
        mode = find_mode(fixture, config["mode"])
        address = int(config["address"])
        last_channel = address + int(mode["footprint"]) - 1
        if last_channel > DMX_CHANNELS:
            raise ValueError(
                f"{config['label']} ends at channel {last_channel}, outside DMX universe"
            )

        motion = self._motion_for_config(slot_id, config, osc)
        capabilities = self._capabilities_for_slot(config)
        if self._motion_uses_locked_rgbw(motion, config):
            rgbw = tuple(motion.get("rgbw", self._rgbw_for_config(config, osc)))
        else:
            rgbw = self._rgbw_for_config(config, osc)
        brightness = self._effective_brightness_with_motion(config, motion, osc, now)
        if capabilities.get("dimmer"):
            output_rgbw = tuple(clamp_dmx(component) for component in rgbw)
        else:
            output_rgbw = tuple(round(component * brightness / 255) for component in rgbw)
        zone_rgb = config.get("_auto_show_zone_rgb")
        output_zone_rgb = None
        if zone_rgb is not None:
            output_zone_rgb = [
                (
                    round(int(segment[0]) * brightness / 255),
                    round(int(segment[1]) * brightness / 255),
                    round(int(segment[2]) * brightness / 255),
                    round(int(segment[3]) * brightness / 255) if len(segment) > 3 else 0,
                )
                for segment in zone_rgb
            ]
        desired_pan = motion["pan"] if motion else config["pan"]
        desired_tilt = motion["tilt"] if motion else config["tilt"]
        realized_motion = self._realized_motion(
            slot_id,
            fixture,
            config,
            desired_pan,
            desired_tilt,
            bool(motion),
            now,
            advance=advance_motion,
        )

        strobe_input = int(config.get("strobe", 0) or 0)
        if motion and motion.get("strobe") is not None:
            strobe_input = max(strobe_input, clamp_dmx(motion.get("strobe")))
        strobe_config = config if strobe_input == int(config.get("strobe", 0) or 0) else {**config, "strobe": strobe_input}
        strobe, external_strobe_applied = self._effective_strobe_state(strobe_config, osc)
        program_value = (
            clamp_dmx(motion.get("program"))
            if motion and motion.get("program") is not None
            else config["program"]
        )
        speed_value = (
            clamp_dmx(motion.get("speed"))
            if motion and motion.get("speed") is not None
            else config["speed"]
        )
        previous_strobe_state = self.last_slot_strobe_outputs.get(slot_id)
        current_strobe_state = (external_strobe_applied, int(strobe))
        if previous_strobe_state != current_strobe_state:
            self.last_slot_strobe_outputs[slot_id] = current_strobe_state
            self.debug_log.log(
                "SLOT_STROBE",
                slot=slot_id,
                label=config.get("label"),
                active=external_strobe_applied,
                value=strobe,
            )

        use_fine_pan_tilt = bool(config.get("use_fine_pan_tilt", True))
        return values_for_fixture(
            mode,
            address,
            output_rgbw,
            brightness,
            realized_motion["pan"],
            realized_motion["tilt"],
            pan_fine=realized_motion.get("pan_fine", 0) if use_fine_pan_tilt else 0,
            tilt_fine=realized_motion.get("tilt_fine", 0) if use_fine_pan_tilt else 0,
            strobe=strobe,
            speed=speed_value,
            program=program_value,
            auto_mode=0,
            pan_tilt_speed=config["pan_tilt_speed"],
            reset=0,
            zone_rgb=output_zone_rgb,
        )

    def _preview_for_slot(self, slot_id, config, osc, now, full_config=None, auto_show=None):
        full_config = full_config or self._clean_full_config(dict(self.config))
        auto_show = auto_show or self._auto_show_state(
            osc, full_config.get("auto_show", {})
        )
        effective_config = self._effective_slot_config(
            slot_id,
            config,
            osc,
            auto_show,
            full_config=full_config,
        )
        fixture = find_fixture(FIXTURE_LIBRARY, effective_config["fixture"])
        motion = self._motion_for_config(slot_id, effective_config, osc)
        desired_pan = motion["pan"] if motion else effective_config["pan"]
        desired_tilt = motion["tilt"] if motion else effective_config["tilt"]
        realized_motion = self._realized_motion(
            slot_id,
            fixture,
            effective_config,
            desired_pan,
            desired_tilt,
            bool(motion),
            now,
            advance=False,
        )
        rgbw = (
            tuple(motion.get("rgbw", self._rgbw_for_config(effective_config, osc)))
            if self._motion_uses_locked_rgbw(motion, effective_config)
            else self._rgbw_for_config(effective_config, osc)
        )
        brightness = 0
        if effective_config["enabled"]:
            brightness = self._effective_brightness_with_motion(
                effective_config,
                motion,
                osc,
                now,
            )
        output_rgbw = tuple(round(component * brightness / 255) for component in rgbw)
        strobe_input = int(effective_config.get("strobe", 0) or 0)
        if motion and motion.get("strobe") is not None:
            strobe_input = max(strobe_input, clamp_dmx(motion.get("strobe")))
        strobe_config = (
            effective_config
            if strobe_input == int(effective_config.get("strobe", 0) or 0)
            else {**effective_config, "strobe": strobe_input}
        )
        strobe, external_strobe_applied = self._effective_strobe_state(strobe_config, osc)
        return {
            "enabled": bool(effective_config["enabled"]),
            "red": output_rgbw[0],
            "green": output_rgbw[1],
            "blue": output_rgbw[2],
            "white": output_rgbw[3],
            "brightness": brightness,
            "strobe": strobe,
            "strobe_active": bool(strobe > 0 and effective_config["enabled"]),
            "strobe_external": external_strobe_applied,
            "pan": realized_motion["pan"],
            "tilt": realized_motion["tilt"],
            "target_pan": realized_motion["target_pan"],
            "target_tilt": realized_motion["target_tilt"],
            "pan_range": realized_motion["pan_range"],
            "tilt_range": realized_motion["tilt_range"],
            "pan_degrees": realized_motion["pan_degrees"],
            "tilt_degrees": realized_motion["tilt_degrees"],
            "target_pan_degrees": realized_motion["target_pan_degrees"],
            "target_tilt_degrees": realized_motion["target_tilt_degrees"],
            "logical_pan_degrees": realized_motion["logical_pan_degrees"],
            "logical_tilt_degrees": realized_motion["logical_tilt_degrees"],
            "logical_target_pan_degrees": realized_motion["logical_target_pan_degrees"],
            "logical_target_tilt_degrees": realized_motion["logical_target_tilt_degrees"],
            "pan_speed_dps": realized_motion["pan_speed_dps"],
            "tilt_speed_dps": realized_motion["tilt_speed_dps"],
            "pan_tilt_speed": effective_config["pan_tilt_speed"],
            "motion_active": realized_motion["motion_active"],
        }

    def _auto_show_state(self, osc, auto_show_config):
        config = self._clean_auto_show_config(auto_show_config)
        now = time.time()
        override_phrase = auto_show_phrase_override_name(config.get("override_phrase"))
        override_color = live_override_color_name(config.get("override_color"))
        override_energy = live_override_energy_name(config.get("override_energy"))
        override_manual_strobe = bool(config.get("override_manual_strobe"))
        override_audience_sweep = bool(config.get("override_audience_sweep"))
        override_all_on = bool(config.get("override_all_on"))
        override_par_chase = bool(config.get("override_par_chase"))
        override_par_snake = bool(config.get("override_par_snake"))
        one_shot = self._resolved_one_shot_cue_state(osc, now)
        audience_pan_focus_enabled = bool(config.get("audience_pan_focus_enabled", True))
        try:
            audience_pan_min = clamp_dmx(int(config.get("audience_pan_min", 135)))
        except (TypeError, ValueError):
            audience_pan_min = 135
        try:
            audience_pan_max = clamp_dmx(int(config.get("audience_pan_max", 205)))
        except (TypeError, ValueError):
            audience_pan_max = 205
        if audience_pan_max < audience_pan_min:
            audience_pan_min, audience_pan_max = audience_pan_max, audience_pan_min
        default_turn_min, default_turn_max = _default_turn_audience_pan_limits(
            audience_pan_min,
            audience_pan_max,
        )
        try:
            audience_turn_pan_min = clamp_dmx(
                int(config.get("audience_turn_pan_min", default_turn_min))
            )
        except (TypeError, ValueError):
            audience_turn_pan_min = default_turn_min
        try:
            audience_turn_pan_max = clamp_dmx(
                int(config.get("audience_turn_pan_max", default_turn_max))
            )
        except (TypeError, ValueError):
            audience_turn_pan_max = default_turn_max
        if audience_turn_pan_max < audience_turn_pan_min:
            audience_turn_pan_min, audience_turn_pan_max = (
                audience_turn_pan_max,
                audience_turn_pan_min,
            )
        try:
            audience_tilt_split = clamp_dmx(int(config.get("audience_tilt_split", 127)))
        except (TypeError, ValueError):
            audience_tilt_split = 127
        override_active = bool(
            override_color != "none"
            or override_manual_strobe
            or override_audience_sweep
            or override_all_on
            or override_par_chase
            or override_par_snake
            or one_shot
        )
        style_name = config["style"]
        style = auto_show_style(style_name)
        osc_effective = dict(osc)
        if override_phrase != "none":
            osc_effective["phrase_current"] = override_phrase
        self._prewarm_track_show_plans(style_name, osc_effective)
        section = (
            override_phrase
            if override_phrase != "none"
            else phrase_bucket(osc_effective.get("phrase_current"))
        )
        beat_value = float(osc.get("beat_value") or 0.0)
        beat_step = int(math.floor(beat_value)) % 4 + 1
        bpm = float(osc.get("bpm") or 0.0)
        bpm_factor = clamp_unit((bpm - 92.0) / 48.0) if bpm > 0 else 0.45
        mood = osc.get("mood")
        mood_factor = mood_factor_from_value(mood)
        effective_mood_factor = auto_show_refined_mood_factor(
            override_energy,
            mood_factor,
        )
        waveform_analysis = osc.get("waveform_analysis") or {}
        waveform_bands = osc_waveform_band_profile(osc_effective)
        waveform_lookahead_2 = osc_waveform_lookahead_profile(osc_effective, 2)
        waveform_lookahead_4 = osc_waveform_lookahead_profile(osc_effective, 4)
        drum_profile = osc_drum_profile(osc_effective)
        current_band_activity = weighted_band_activity(waveform_bands) or 0.0
        lookahead_activity_2 = waveform_lookahead_2.get("activity")
        lookahead_activity_4 = waveform_lookahead_4.get("activity")
        anticipation = clamp_unit(
            max(
                0.0,
                (lookahead_activity_2 or current_band_activity) - current_band_activity,
                ((lookahead_activity_4 or current_band_activity) - current_band_activity) * 0.75,
            )
        )
        waveform_energy = osc.get("waveform_energy")
        waveform_factor = (
            clamp_unit(waveform_energy)
            if waveform_energy is not None
            else None
        )
        live_behavior_section, outro_activity = self._resolved_behavior_section(
            section,
            beat_value,
            osc_effective,
            waveform_factor=waveform_factor,
            waveform_bands=waveform_bands,
            waveform_lookahead_2=waveform_lookahead_2,
            waveform_lookahead_4=waveform_lookahead_4,
            drum_profile=drum_profile,
            waveform_analysis=waveform_analysis,
        )
        planned_scene = self._planned_scene_variants(style_name, osc_effective)
        behavior_section = (
            str(planned_scene.get("section") or live_behavior_section)
            if planned_scene
            else live_behavior_section
        )
        profile = auto_show_profile(behavior_section)
        scene = planned_scene or auto_show_scene_variants(style_name, behavior_section, osc)
        track_theme = auto_show_track_theme(scene["theme_name"])
        base_energy = clamp_unit(
            profile["energy"]
            + (bpm_factor - 0.5) * 0.18
            + (effective_mood_factor - 0.5) * 0.10
            + style["energy_bias"]
            + float(track_theme.get("energy_bias", 0.0))
        )
        if waveform_factor is not None:
            base_energy = clamp_unit(base_energy + (waveform_factor - 0.5) * 0.05)
        if waveform_bands["has_data"]:
            base_energy = clamp_unit(
                base_energy
                + ((waveform_bands["low"] or 0.0) - 0.5) * 0.06
                + ((waveform_bands["mid"] or 0.0) - 0.5) * 0.025
                + ((waveform_bands["high"] or 0.0) - 0.5) * 0.015
            )
        if anticipation > 0.0 and behavior_section in {"build", "chorus", "drop", "down", "outro"}:
            base_energy = clamp_unit(base_energy + anticipation * 0.035)
        base_energy = clamp_unit(
            base_energy
            + float(waveform_analysis.get("lift") or 0.0) * 0.06
            + float(waveform_analysis.get("transient") or 0.0) * 0.03
            + drum_profile["impact"] * 0.04
            + drum_profile["sparkle"] * 0.015
        )
        base_energy = apply_live_energy_override(
            override_energy,
            base_energy,
            low_target=0.34,
            mid_target=0.58,
            high_target=0.86,
            mix=0.72,
        )
        pulse_name = auto_show_refined_pulse_name(
            behavior_section,
            scene["pulse_name"],
            style_name,
            osc_effective,
            effective_mood_factor,
            base_energy,
            override_energy,
        )
        movement_seed = clamp_unit(
            profile["motion"]
            + style["motion_bias"]
            + float(track_theme.get("motion_bias", 0.0))
            + ((waveform_factor - 0.5) * 0.025 if waveform_factor is not None else 0.0)
            + float(waveform_analysis.get("volatility") or 0.0) * 0.025
            + drum_profile["motion"] * 0.05
            + drum_profile["sparkle"] * 0.02
            + (anticipation * 0.045 if behavior_section in {"build", "chorus", "drop", "down", "outro"} else 0.0)
        )
        movement_seed = apply_live_energy_override(
            override_energy,
            movement_seed,
            low_target=0.28,
            mid_target=0.50,
            high_target=0.76,
            mix=0.62,
        )
        motion_name = auto_show_refined_motion_name(
            behavior_section,
            scene["motion_name"],
            style_name,
            osc_effective,
            base_energy,
            movement_seed,
            override_energy,
        )
        pulse_profile = AUTO_SHOW_PULSE_PROFILES.get(
            pulse_name, AUTO_SHOW_PULSE_PROFILES["medium"]
        )
        energy = base_energy
        movement = clamp_unit(movement_seed + pulse_profile["movement"])
        pulse_amount = clamp_unit(
            profile["pulse"]
            + style["pulse_bias"]
            + float(track_theme.get("pulse_bias", 0.0))
            + ((waveform_factor - 0.5) * 0.02 if waveform_factor is not None else 0.0)
            + max(0.0, float(waveform_analysis.get("transient") or 0.0) - 0.06) * 0.05
            + drum_profile["impact"] * 0.06
            + drum_profile["snare"] * 0.04
            + (anticipation * 0.025 if behavior_section in {"build", "chorus", "drop"} else 0.0)
        )
        pulse_amount = apply_live_energy_override(
            override_energy,
            pulse_amount,
            low_target=0.18,
            mid_target=0.42,
            high_target=0.74,
            mix=0.66,
        )
        rhythm_mode = str(pulse_profile.get("mode", "full_on"))
        dynamic_level = rhythm_mode != "none"
        beat_pulse = rhythm_mode in {"beat_flash", "drop_blinder", "strong_pulse"}
        external_strobe = bool(osc.get("strobe_active"))
        imminent_strobe = (
            osc.get("strobe_count_in") is not None
            and int(osc.get("strobe_count_in") or 0) <= 2
        )
        strobe_window = bool(
            external_strobe
            or (
                profile["strobe"]
                and style["strobe_bias"] > -0.5
                and (
                    energy > 0.90
                    or pulse_name in {"beat_flash", "drop_blinder"}
                    or imminent_strobe
                    or drum_profile["impact"] >= 0.46
                )
            )
        )
        if override_energy == "low" and not external_strobe:
            strobe_window = False
        elif override_energy == "high" and not external_strobe:
            strobe_window = bool(
                strobe_window
                or (
                    behavior_section in {"build", "chorus", "drop"}
                    and (
                        energy >= 0.76
                        or pulse_name in {"beat_flash", "drop_blinder", "chase", "snake", "double_hit", "gallop"}
                        or drum_profile["impact"] >= 0.36
                    )
                )
            )
        color_source = auto_show_color_source(style_name, behavior_section, osc_effective)
        manual_color = auto_show_manual_color(style_name, behavior_section, osc_effective)
        if override_phrase != "none":
            section_label = f"{section.title()} Override"
        elif behavior_section != section:
            section_label = f"{section.title()} -> {behavior_section.title()}"
        elif live_behavior_section != section:
            section_label = f"{section.title()} -> {live_behavior_section.title()}"
        else:
            section_label = section.title()
        cue_label = (
            f"{style['label']} • {scene['theme_label']} • {section_label} • "
            f"{scene['look_label']} / {scene['color_profile_label']} / {titleize_variant(motion_name)}"
            f"{' Mirror' if scene.get('mirror_within_group') else ''} / {scene['texture_label']} / {titleize_variant(pulse_name)}"
        )
        override_parts = []
        if override_phrase != "none":
            override_parts.append(f"Phrase {auto_show_phrase_override_label(override_phrase)}")
        if override_color != "none":
            override_parts.append(live_override_color_label(override_color))
        if override_energy != "none":
            override_parts.append(f"{live_override_energy_label(override_energy)} Energy")
        if override_manual_strobe:
            override_parts.append("Manual Strobe")
        if override_audience_sweep:
            override_parts.append("Audience Sweep")
        if override_all_on:
            override_parts.append("All On")
        if override_par_chase:
            override_parts.append("PAR Chase")
        if override_par_snake:
            override_parts.append("PAR Snake")
        if one_shot:
            override_parts.append(f"Cue {one_shot['label']}")
        if override_parts:
            cue_label += " • Override: " + " / ".join(override_parts)
        return {
            "enabled": bool(config["enabled"]),
            "available": override_active or not bool(osc.get("stale")),
            "style": style_name,
            "style_label": style["label"],
            "audience_pan_focus_enabled": audience_pan_focus_enabled,
            "audience_pan_min": audience_pan_min,
            "audience_pan_max": audience_pan_max,
            "audience_turn_pan_min": audience_turn_pan_min,
            "audience_turn_pan_max": audience_turn_pan_max,
            "audience_tilt_split": audience_tilt_split,
            "phrase_bucket": section,
            "override_phrase": override_phrase,
            "override_phrase_label": auto_show_phrase_override_label(override_phrase),
            "behavior_bucket": behavior_section,
            "live_behavior_bucket": live_behavior_section,
            "outro_activity": outro_activity if section == "outro" else None,
            "beat_step": beat_step,
            "cue_label": cue_label,
            "color_source": color_source,
            "energy": energy,
            "waveform_energy": waveform_factor,
            "waveform_bands": {
                "low": waveform_bands["low"],
                "mid": waveform_bands["mid"],
                "high": waveform_bands["high"],
            },
            "waveform_lookahead": {
                "2": {
                    "low": waveform_lookahead_2["low"],
                    "mid": waveform_lookahead_2["mid"],
                    "high": waveform_lookahead_2["high"],
                },
                "4": {
                    "low": waveform_lookahead_4["low"],
                    "mid": waveform_lookahead_4["mid"],
                    "high": waveform_lookahead_4["high"],
                },
            },
            "waveform_analysis": waveform_analysis,
            "drum_signals": {
                "kick": drum_profile["kick"],
                "snare": drum_profile["snare"],
                "hihat": drum_profile["hihat"],
                "impact": drum_profile["impact"],
                "sparkle": drum_profile["sparkle"],
                "motion": drum_profile["motion"],
            },
            "anticipation": anticipation,
            "movement": movement,
            "beat_pulse": beat_pulse,
            "dynamic_level": dynamic_level,
            "rhythm_mode": rhythm_mode,
            "dimmer_fx_name": pulse_name,
            "dimmer_fx_label": titleize_variant(pulse_name),
            "strobe_window": strobe_window,
            "external_strobe": external_strobe,
            "beat_depth": clamp_dmx(
                round(70 + pulse_amount * 140 + pulse_profile["depth"])
            ),
            "beat_decay_ms": max(
                60,
                min(520, int(round(220 - energy * 110 + pulse_profile["decay"]))),
            ),
            "manual_color": {
                "red": int(manual_color[0]),
                "green": int(manual_color[1]),
                "blue": int(manual_color[2]),
                "white": int(manual_color[3]),
            },
            "theme_name": scene["theme_name"],
            "theme_label": scene["theme_label"],
            "look_name": scene["look_name"],
            "color_profile_name": scene["color_profile_name"],
            "color_profile_label": scene["color_profile_label"],
            "motion_name": motion_name,
            "texture_name": scene["texture_name"],
            "wash_cue_name": scene["wash_cue_name"],
            "wash_cue_label": auto_show_wall_wash_cue(scene["wash_cue_name"])["label"],
            "mirror_within_group": bool(scene.get("mirror_within_group")),
            "pulse_name": pulse_name,
            "accent_name": scene["accent_name"],
            "track_plan_active": bool(planned_scene),
            "track_plan_segment_index": scene.get("plan_segment_index"),
            "track_plan_section": scene.get("section") if planned_scene else None,
            "track_plan_phrase": scene.get("plan_phrase") if planned_scene else None,
            "track_plan_start_seconds": scene.get("plan_start_seconds") if planned_scene else None,
            "track_plan_end_seconds": scene.get("plan_end_seconds") if planned_scene else None,
            "override_active": override_active,
            "override_color": override_color,
            "override_color_label": live_override_color_label(override_color),
            "override_energy": override_energy,
            "override_energy_label": live_override_energy_label(override_energy),
            "override_manual_strobe": override_manual_strobe,
            "override_audience_sweep": override_audience_sweep,
            "override_all_on": override_all_on,
            "override_par_chase": override_par_chase,
            "override_par_snake": override_par_snake,
            "one_shot_active": bool(one_shot),
            "one_shot_cue": one_shot["id"] if one_shot else "none",
            "one_shot_label": one_shot["label"] if one_shot else "None",
            "one_shot_progress": one_shot["progress"] if one_shot else 0.0,
        }

    def _resolved_behavior_section(
        self,
        section,
        beat_value,
        osc,
        waveform_factor=None,
        waveform_bands=None,
        waveform_lookahead_2=None,
        waveform_lookahead_4=None,
        drum_profile=None,
        waveform_analysis=None,
    ):
        if section != "outro":
            self.outro_behavior_state = None
            return section, None

        activity_raw = auto_show_outro_activity_score(
            osc,
            waveform_factor=waveform_factor,
            waveform_bands=waveform_bands,
            waveform_lookahead_2=waveform_lookahead_2,
            waveform_lookahead_4=waveform_lookahead_4,
            drum_profile=drum_profile,
            waveform_analysis=waveform_analysis,
        )

        levels = ["outro", "verse", "build", "chorus"]
        previous = self.outro_behavior_state or {}
        previous_smoothed = previous.get("activity")
        try:
            previous_smoothed = (
                None if previous_smoothed is None else clamp_unit(float(previous_smoothed))
            )
        except (TypeError, ValueError):
            previous_smoothed = None
        smoothed = activity_raw if previous_smoothed is None else clamp_unit(previous_smoothed * 0.76 + activity_raw * 0.24)
        current = previous.get("section")

        if current not in levels:
            current = auto_show_outro_bucket_for_activity(smoothed)
            self.outro_behavior_state = {
                "section": current,
                "activity": smoothed,
                "lock_until_beat": float(beat_value) + 8.0,
            }
            return current, smoothed

        lock_until_beat = float(previous.get("lock_until_beat") or 0.0)
        if float(beat_value) < lock_until_beat:
            self.outro_behavior_state = {
                "section": current,
                "activity": smoothed,
                "lock_until_beat": lock_until_beat,
            }
            return current, smoothed

        if current == "outro":
            if smoothed >= 0.82:
                next_section = "chorus"
            elif smoothed >= 0.66:
                next_section = "build"
            elif smoothed >= 0.54:
                next_section = "verse"
            else:
                next_section = "outro"
        elif current == "verse":
            if smoothed >= 0.86:
                next_section = "chorus"
            elif smoothed >= 0.70:
                next_section = "build"
            elif smoothed < 0.42:
                next_section = "outro"
            else:
                next_section = "verse"
        elif current == "build":
            if smoothed >= 0.88:
                next_section = "chorus"
            elif smoothed < 0.38:
                next_section = "outro"
            elif smoothed < 0.52:
                next_section = "verse"
            else:
                next_section = "build"
        else:
            if smoothed < 0.40:
                next_section = "outro"
            elif smoothed < 0.54:
                next_section = "verse"
            elif smoothed < 0.68:
                next_section = "build"
            else:
                next_section = "chorus"

        if next_section != current:
            lock_until_beat = float(beat_value) + 8.0

        self.outro_behavior_state = {
            "section": next_section,
            "activity": smoothed,
            "lock_until_beat": lock_until_beat,
        }
        return next_section, smoothed

    def _effective_slot_config(self, slot_id, config, osc, auto_show, full_config=None):
        effective = {**config, "color": dict(config["color"])}
        full_config = full_config or self._clean_full_config(dict(self.config))
        override_active = self._live_override_active(auto_show)
        if ((not auto_show["enabled"] and not override_active) or not config["enabled"] or (not auto_show["available"] and not override_active)):
            return effective
        if not config["sync_enabled"]:
            return effective

        capabilities = self._capabilities_for_slot(config)
        slot_context = self._slot_context(full_config, slot_id, config)
        role = slot_context["role"]
        energy = auto_show["energy"]
        movement = auto_show["movement"]
        section = auto_show.get("behavior_bucket", auto_show["phrase_bucket"])
        style_name = auto_show.get("style", "adaptive")
        theme_name = auto_show.get("theme_name", TRACK_SHOW_THEME_SEQUENCE[0])
        track_theme = auto_show_track_theme(theme_name)
        look_name = auto_show.get("look_name", "bank_echo")
        color_profile_name = auto_show.get("color_profile_name", "yellow_blue")
        motion_name = auto_show.get("motion_name", "center")
        texture_name = auto_show.get("texture_name", "steady")
        accent_name = auto_show.get("accent_name", "center")
        pulse_name = auto_show.get("pulse_name", "medium")
        rhythm_mode = auto_show.get("rhythm_mode", "full_on")
        override_energy = live_override_energy_name(auto_show.get("override_energy"))
        role_profiles = {
            "moving": {"base": 96, "span": 128, "energy_bias": 0.08, "pulse": 26, "decay": -40},
            "par": {"base": 84, "span": 142, "energy_bias": -0.04, "pulse": -6, "decay": 32},
            "wash": {"base": 76, "span": 136, "energy_bias": -0.12, "pulse": -22, "decay": 78},
            "static": {"base": 88, "span": 138, "energy_bias": -0.02, "pulse": -4, "decay": 18},
        }
        role_profile = role_profiles.get(role, role_profiles["static"])

        effective["sync_enabled"] = True
        effective["color_source"] = auto_show["color_source"]
        effective["color"] = dict(auto_show["manual_color"])
        effective["beat_pulse_enabled"] = auto_show["dynamic_level"]
        effective["osc_strobe_enabled"] = auto_show["strobe_window"] and capabilities["strobe"]
        effective["strobe"] = 0
        effective["speed"] = 0
        effective["program"] = 0
        effective["_slot_context"] = slot_context
        effective["_auto_show_movement"] = movement
        effective["_auto_show_motion_name"] = motion_name
        motion_profile = auto_show_motion_profile(motion_name)
        effective["_auto_show_member_mirror"] = bool(
            motion_profile.get("member_mirror")
            or (auto_show.get("mirror_within_group") and motion_name in AUTO_SHOW_MEMBER_MIRROR_MOTIONS)
        )
        effective["_auto_show_theme_name"] = theme_name
        effective["_auto_show_look_name"] = look_name
        effective["_auto_show_color_profile_name"] = color_profile_name
        effective["_auto_show_texture_name"] = texture_name
        effective["_auto_show_accent_name"] = accent_name
        effective["_auto_show_pulse_name"] = pulse_name
        effective["_auto_show_energy"] = energy
        effective["_auto_show_rhythm_mode"] = rhythm_mode
        effective["_auto_show_audience_pan_focus_enabled"] = bool(
            auto_show.get("audience_pan_focus_enabled", True)
        )
        try:
            effective["_auto_show_audience_pan_min"] = clamp_dmx(
                int(auto_show.get("audience_pan_min", 135))
            )
        except (TypeError, ValueError):
            effective["_auto_show_audience_pan_min"] = 135
        try:
            effective["_auto_show_audience_pan_max"] = clamp_dmx(
                int(auto_show.get("audience_pan_max", 205))
            )
        except (TypeError, ValueError):
            effective["_auto_show_audience_pan_max"] = 205
        default_turn_min, default_turn_max = _default_turn_audience_pan_limits(
            effective["_auto_show_audience_pan_min"],
            effective["_auto_show_audience_pan_max"],
        )
        try:
            effective["_auto_show_audience_turn_pan_min"] = clamp_dmx(
                int(auto_show.get("audience_turn_pan_min", default_turn_min))
            )
        except (TypeError, ValueError):
            effective["_auto_show_audience_turn_pan_min"] = default_turn_min
        try:
            effective["_auto_show_audience_turn_pan_max"] = clamp_dmx(
                int(auto_show.get("audience_turn_pan_max", default_turn_max))
            )
        except (TypeError, ValueError):
            effective["_auto_show_audience_turn_pan_max"] = default_turn_max
        if effective["_auto_show_audience_turn_pan_max"] < effective["_auto_show_audience_turn_pan_min"]:
            (
                effective["_auto_show_audience_turn_pan_min"],
                effective["_auto_show_audience_turn_pan_max"],
            ) = (
                effective["_auto_show_audience_turn_pan_max"],
                effective["_auto_show_audience_turn_pan_min"],
            )
        try:
            effective["_auto_show_audience_tilt_split"] = clamp_dmx(
                int(auto_show.get("audience_tilt_split", 127))
            )
        except (TypeError, ValueError):
            effective["_auto_show_audience_tilt_split"] = 127
        if role == "par":
            effective["_auto_show_texture_name"] = "steady"
            effective["_auto_show_rhythm_mode"] = auto_show_par_rhythm_mode(
                section,
                rhythm_mode,
                style_name,
                osc,
                slot_context,
                override_energy,
            )
        elif role == "moving":
            effective["_auto_show_texture_name"] = "steady"
            effective["_auto_show_rhythm_mode"] = auto_show_moving_rhythm_mode(
                section,
                rhythm_mode,
                style_name,
                osc,
                slot_context,
                energy,
                movement,
                override_energy,
            )

        base_rgbw = self._resolved_sync_rgbw(effective, osc)
        effective["_auto_show_rgbw"] = self._auto_show_rgbw_for_slot(
            base_rgbw, slot_context, auto_show
        )
        if role == "wash":
            zone_rgb = self._wall_wash_zone_rgb_for_slot(slot_context, auto_show, osc)
            effective["_auto_show_zone_rgb"] = zone_rgb
            effective["_auto_show_rgbw"] = self._wall_wash_average_rgbw(zone_rgb)

        slot_energy = energy + role_profile["energy_bias"]
        slot_energy += float(track_theme.get("energy_bias", 0.0)) * (0.45 if role == "moving" else 0.28)
        if role == "moving":
            slot_energy += slot_context.get("group_edge_bias", slot_context["edge_bias"]) * 0.04
        elif role == "par":
            slot_energy = 0.0
        elif role == "wash":
            slot_energy -= slot_context.get("group_edge_bias", slot_context["edge_bias"]) * 0.05
            slot_energy += slot_context.get("group_alternate", slot_context["alternate"]) * 0.04
        slot_energy = clamp_unit(slot_energy)

        if role == "par":
            par_section_dimmer = {
                "intro": 180,
                "verse": 210,
                "build": 228,
                "chorus": 255,
                "drop": 255,
                "down": 170,
                "break": 132,
                "outro": 118,
                "unknown": 210,
            }
            effective["dimmer"] = int(par_section_dimmer.get(section, 210))
        else:
            effective["dimmer"] = clamp_dmx(
                round(role_profile["base"] + role_profile["span"] * slot_energy)
            )
        effective["dimmer"] = clamp_dmx(
            effective["dimmer"]
            + self._accent_dimmer_offset(role, slot_context, accent_name, movement)
        )
        if role == "par":
            effective["dimmer"] = int(par_section_dimmer.get(section, 210))
        group_seed_unit = float(slot_context.get("group_seed_unit", slot_context.get("seed_unit", 0.0)))
        member_seed_unit = float(slot_context.get("member_seed_unit", slot_context.get("seed_unit", 0.0)))
        dimmer_variation = group_seed_unit * (10 if role == "moving" else 16 if role == "par" else 12)
        dimmer_variation += member_seed_unit * (4 if role == "moving" else 6 if role == "par" else 5)
        if role == "moving":
            dimmer_variation += slot_context.get("group_alternate", slot_context["alternate"]) * 8
            dimmer_variation += slot_context.get("group_edge_bias", slot_context["edge_bias"]) * 6
            dimmer_variation += slot_context.get("member_centered", 0.0) * 3
        elif role == "par":
            dimmer_variation = 0.0
        elif role == "wash":
            dimmer_variation += slot_context.get("group_alternate", slot_context["alternate"]) * 7
            dimmer_variation -= slot_context.get("group_edge_bias", slot_context["edge_bias"]) * 8
            dimmer_variation += slot_context.get("member_centered", 0.0) * 2
        if rhythm_mode in {"chase", "chase_whole"}:
            chase_spread = slot_context.get("group_centered", slot_context["centered"]) * (
                18 if role == "moving" else 24
            )
            dimmer_variation += chase_spread
        elif rhythm_mode == "stagger":
            dimmer_variation += slot_context.get("group_alternate", slot_context["alternate"]) * (
                16 if role != "wash" else 10
            )
        elif rhythm_mode == "split":
            dimmer_variation += slot_context.get("member_alternate", slot_context["alternate"]) * (
                18 if role == "par" else 8
            )
        elif rhythm_mode == "ladder":
            dimmer_variation += slot_context.get("member_centered", 0.0) * (
                -14 if role == "par" else -6
            )
        elif rhythm_mode == "ripple":
            dimmer_variation += group_seed_unit * (12 if role == "par" else 5)
        effective["dimmer"] = clamp_dmx(round(effective["dimmer"] + dimmer_variation))
        if role == "moving" and section in ("build", "chorus", "drop"):
            effective["dimmer"] = clamp_dmx(
                round(
                    effective["dimmer"]
                    + 6
                    + movement * 12
                    + slot_context.get("group_alternate", slot_context["alternate"]) * 10
                    - slot_context.get("group_edge_bias", slot_context["edge_bias"]) * 8
                )
            )
        elif role == "par" and section == "drop":
            effective["dimmer"] = clamp_dmx(max(effective["dimmer"], 220))
        elif role in ("par", "wash") and section in ("break", "outro"):
            effective["dimmer"] = clamp_dmx(round(effective["dimmer"] * 0.82))

        pulse_depth = auto_show["beat_depth"] + role_profile["pulse"]
        if role == "moving":
            pulse_depth += round(slot_context.get("group_edge_bias", slot_context["edge_bias"]) * 16)
        elif role == "wash":
            pulse_depth -= round(slot_context.get("group_center_bias", slot_context["center_bias"]) * 12)
        rhythm_mode = effective["_auto_show_rhythm_mode"]
        effective["beat_pulse_enabled"] = rhythm_mode != "none"
        if rhythm_mode == "none":
            pulse_depth = 0
        elif rhythm_mode == "breathe":
            pulse_depth = round(pulse_depth * 0.16)
        elif rhythm_mode == "lift":
            pulse_depth = clamp_dmx(round(30 + pulse_depth * 0.20))
        elif rhythm_mode == "hit":
            pulse_depth = clamp_dmx(
                round(124 + energy * 56 + movement * 24)
            )
        elif rhythm_mode == "cut":
            pulse_depth = clamp_dmx(
                round(176 + energy * 42 + movement * 18)
            )
        elif rhythm_mode in {"snake", "snake_whole"}:
            pulse_depth += 20 if role == "moving" else 10
        elif rhythm_mode in {"chase", "chase_whole"}:
            pulse_depth += 30 if role == "par" else 20 if role != "moving" else 10
        elif rhythm_mode == "stagger":
            pulse_depth += 24 if role == "par" else 14
        elif rhythm_mode == "split":
            pulse_depth += 26 if role == "par" else 12
        elif rhythm_mode == "ladder":
            pulse_depth += 22 if role == "par" else 10
        elif rhythm_mode == "ripple":
            pulse_depth += 18 if role == "par" else 8
        elif rhythm_mode == "bloom":
            pulse_depth = round(pulse_depth * 0.22)
        effective["beat_depth"] = clamp_dmx(pulse_depth)
        effective["beat_decay_ms"] = max(
            60,
            min(
                650,
                auto_show["beat_decay_ms"]
                + role_profile["decay"]
                + (-90 if role == "moving" and rhythm_mode == "cut" else 0)
                + (-48 if role == "moving" and rhythm_mode == "hit" else 0)
                + (-36 if role == "par" and rhythm_mode == "chase" else 0)
                + (-12 if role == "par" and rhythm_mode == "stagger" else 0),
            ),
        )

        if role == "moving" and capabilities["pan_tilt_speed"]:
            section_speed_base = {
                "intro": 82,
                "verse": 56,
                "build": 40,
                "chorus": 28,
                "drop": 22,
                "down": 64,
                "break": 72,
                "outro": 96,
                "unknown": 52,
            }
            speed_static = motion_profile.get("pan_tilt_speed_static")
            speed_min = motion_profile.get("speed_min")
            speed_max = motion_profile.get("speed_max")
            if speed_static is not None:
                speed_base = int(speed_static)
            elif speed_min is not None and speed_max is not None:
                speed_min = int(speed_min)
                speed_max = int(speed_max)
                if speed_max < speed_min:
                    speed_min, speed_max = speed_max, speed_min
                speed_span = speed_max - speed_min
                speed_base = speed_max - (movement * speed_span)
            else:
                speed_base = section_speed_base.get(section, 72)
                speed_adjust = movement * -16 + abs(
                    slot_context.get("group_centered", slot_context["centered"])
                ) * 4
                speed_base = speed_base + speed_adjust
            effective["pan_tilt_speed"] = clamp_dmx(round(speed_base))
            speed_cap = _full_tilt_motion_speed_cap(motion_profile, section)
            if speed_cap is not None:
                effective["pan_tilt_speed"] = clamp_dmx(
                    min(int(effective["pan_tilt_speed"]), int(speed_cap))
                )
            if section in ("break", "intro", "outro", "down"):
                if section == "outro":
                    effective["tilt"] = 184
                elif section == "down":
                    effective["tilt"] = 176
                else:
                    effective["tilt"] = 170
            elif section == "drop":
                effective["tilt"] = 110
            else:
                effective["tilt"] = 136

        override_color = live_override_color_name(auto_show.get("override_color"))
        if override_color != "none":
            override_rgbw = self._live_override_rgbw_for_slot(override_color, slot_context, osc)
            if override_rgbw is not None:
                effective["_auto_show_rgbw"] = override_rgbw
                effective["_force_rgbw_override"] = True
                effective["color"] = {
                    "red": int(override_rgbw[0]),
                    "green": int(override_rgbw[1]),
                    "blue": int(override_rgbw[2]),
                    "white": int(override_rgbw[3]),
                }
            if role == "wash":
                override_zone_rgb = self._live_override_zone_rgb_for_slot(
                    override_color, slot_context, osc
                )
                if override_zone_rgb is not None:
                    effective["_auto_show_zone_rgb"] = override_zone_rgb
                    effective["_auto_show_rgbw"] = self._wall_wash_average_rgbw(
                        override_zone_rgb
                    )

        if role == "par":
            if auto_show.get("override_par_snake"):
                effective["_auto_show_rhythm_mode"] = "par_snake"
                effective["_auto_show_texture_name"] = "steady"
                effective["beat_pulse_enabled"] = True
                effective["dimmer"] = max(effective["dimmer"], 220)
            elif auto_show.get("override_par_chase"):
                effective["_auto_show_rhythm_mode"] = "pair_swap"
                effective["_auto_show_texture_name"] = "steady"
                effective["beat_pulse_enabled"] = True
                effective["dimmer"] = max(effective["dimmer"], 220)

        if auto_show.get("override_audience_sweep") and role == "moving":
            override_motion_profile = auto_show_motion_profile("live_audience_tilt_sweep")
            effective["_auto_show_motion_name"] = "live_audience_tilt_sweep"
            effective["_auto_show_member_mirror"] = False
            effective["_live_override_audience_sweep"] = True
            if override_motion_profile.get("pan_tilt_speed_static") is not None:
                effective["pan_tilt_speed"] = clamp_dmx(
                    int(override_motion_profile["pan_tilt_speed_static"])
                )
            effective["dimmer"] = max(effective["dimmer"], 220)

        if auto_show.get("override_all_on"):
            effective["_auto_show_rhythm_mode"] = "full_on"
            effective["beat_pulse_enabled"] = False
            effective["dimmer"] = 255

        if auto_show.get("override_manual_strobe") and capabilities["strobe"]:
            effective["osc_strobe_enabled"] = False
            effective["strobe"] = max(int(effective.get("strobe", 0) or 0), 220)
            effective["dimmer"] = max(effective["dimmer"], 255 if role != "wash" else 220)

        if auto_show.get("one_shot_active"):
            effective = self._apply_one_shot_cue_to_effective_slot(
                effective,
                auto_show,
                osc,
                slot_context,
                capabilities,
            )

        return effective

    def _rgbw_for_config(self, config, osc):
        if "_auto_show_rgbw" in config:
            return tuple(config["_auto_show_rgbw"])
        return self._resolved_sync_rgbw(config, osc)

    def _brightness_for_config(self, config, osc, now):
        dimmer = config["dimmer"]
        if not config["sync_enabled"]:
            return dimmer
        mode = str(config.get("_auto_show_rhythm_mode", "full_on"))
        slot_context = config.get("_slot_context") or {}
        role = str(slot_context.get("role", "static"))
        texture_multiplier = self._texture_multiplier(config, osc, now)
        par_pair_index = 0
        if role == "par":
            par_member_count = max(1, int(slot_context.get("member_count", 1)))
            par_member_index = int(slot_context.get("member_index", 0))
            par_pair_index = min(par_member_index, par_member_count - 1 - par_member_index)

        if mode in ("none", "full_on") or not config["beat_pulse_enabled"]:
            return clamp_dmx(round(dimmer * texture_multiplier))

        beat_value = float(osc.get("beat_value") or 0.0)
        cycle_16 = (beat_value % 16.0) / 16.0
        cycle_32 = (beat_value % 32.0) / 32.0
        age = osc.get("beat_phase_age_seconds")
        if age is None:
            last_beat_at = osc.get("last_beat_at")
            age = (now - last_beat_at) if last_beat_at else None

        def beat_envelope(local_decay):
            if age is None:
                return 0.0
            return max(0.0, 1.0 - (age / local_decay)) if local_decay > 0 else 0.0

        texture_blend = {
            "moving": 0.12,
            "par": 0.30,
            "wash": 0.22,
            "static": 0.18,
        }.get(role, 0.18)

        direct_multiplier = None
        if mode == "low_glow":
            direct_multiplier = 0.30
        elif mode == "medium":
            direct_multiplier = 0.68
        elif mode == "fade_in":
            direct_multiplier = 0.16 + 0.84 * cycle_32
        elif mode == "fade_out":
            direct_multiplier = 1.0 - 0.84 * cycle_32
        elif mode == "ramp_up":
            direct_multiplier = 0.35 + 0.65 * cycle_16
        elif mode == "ramp_down":
            direct_multiplier = 1.0 - 0.65 * cycle_16
        elif mode == "breathing":
            pair_phase = par_pair_index * 1.0 if role == "par" else 0.0
            direct_multiplier = 0.32 + 0.36 * (
                0.5 + 0.5 * wave_sine((beat_value + pair_phase) / 4.0)
            )
        elif mode == "soft_pulse":
            pair_phase = par_pair_index * 1.0 if role == "par" else 0.0
            direct_multiplier = 0.55 + 0.25 * (
                0.5 + 0.5 * wave_sine((beat_value + pair_phase) / 2.0)
            )
        elif mode == "strong_pulse":
            envelope = beat_envelope(max(0.08, config["beat_decay_ms"] / 1000.0))
            if role == "moving":
                direct_multiplier = 1.0 if envelope >= 0.22 else 0.0
            else:
                direct_multiplier = 0.12 + 0.88 * (envelope ** 0.42)
        elif mode == "beat_flash":
            envelope = beat_envelope(max(0.05, config["beat_decay_ms"] / 1000.0))
            if role == "moving":
                direct_multiplier = 1.0 if envelope >= 0.26 else 0.0
            else:
                direct_multiplier = envelope ** 0.24
        elif mode == "offbeat_flash":
            pair_phase = par_pair_index * 0.5 if role == "par" else 0.0
            off_phase = (beat_value + 0.5 + pair_phase) % 1.0
            if off_phase <= 0.18:
                if role == "moving":
                    direct_multiplier = 1.0
                else:
                    direct_multiplier = max(0.0, 1.0 - (off_phase / 0.18))
            else:
                direct_multiplier = 0.0
        elif mode == "drop_blinder":
            downbeat = int(math.floor(beat_value)) % 4 == 0
            if downbeat:
                envelope = beat_envelope(max(0.06, config["beat_decay_ms"] / 1000.0))
                if role == "moving":
                    direct_multiplier = 1.0 if envelope >= 0.20 else 0.0
                else:
                    direct_multiplier = 0.18 + 0.82 * (envelope ** 0.18)
            else:
                direct_multiplier = 0.12
        elif mode == "blackout_hit":
            downbeat = int(math.floor(beat_value)) % 4 == 0
            if downbeat and age is not None and age <= 0.10:
                direct_multiplier = 0.0
            else:
                direct_multiplier = 1.0
        elif mode == "tremolo":
            direct_multiplier = 0.35 + 0.65 * (0.5 + 0.5 * wave_sine(beat_value * 4.0))

        if direct_multiplier is not None:
            multiplier = max(0.0, min(1.08, direct_multiplier))
            multiplier *= (1.0 - texture_blend) + texture_multiplier * texture_blend
            multiplier = max(0.0, min(1.08, multiplier))
            return clamp_dmx(round(dimmer * multiplier))

        decay = config["beat_decay_ms"] / 1000.0
        movement_scale = float(config.get("_auto_show_movement", 0.0) or 0.0)
        envelope = self._rhythm_envelope(
            mode,
            osc.get("beat_value"),
            slot_context,
            movement_scale,
            osc,
            now,
            decay,
            float(config.get("_auto_show_energy", 0.0) or 0.0),
        )

        depth = clamp_unit(config["beat_depth"] / 255.0)
        if mode == "breathe":
            center = 0.94 + depth * 0.02
            swing = 0.02 + depth * 0.05
            multiplier = center + (envelope - 0.5) * 2.0 * swing
        elif mode == "lift":
            baseline = 0.80
            multiplier = baseline + 0.20 * envelope
        elif mode == "hit":
            baseline = max(0.08, 0.40 - depth * 0.34)
            multiplier = baseline + (1.0 - baseline) * envelope
        elif mode == "cut":
            baseline = max(0.0, 0.18 - depth * 0.24)
            multiplier = baseline + (1.0 - baseline) * envelope
        elif mode in {"pair_swap", "pair_hold", "pair_bounce", "par_snake"}:
            multiplier = 1.0 if envelope >= 0.5 else 0.0
        elif mode in {"snake", "snake_whole"}:
            multiplier = 1.0 if envelope >= 0.5 else 0.0
        elif mode == "stagger":
            baseline = max(0.40, 1.0 - depth * 0.68)
            multiplier = baseline + depth * 0.60 * envelope
        elif mode in {"chase", "chase_whole"}:
            multiplier = 1.0 if envelope >= 0.5 else 0.0
        elif mode == "split":
            baseline = max(0.42, 1.0 - depth * 0.62)
            multiplier = baseline + depth * 0.58 * envelope
        elif mode == "ladder":
            baseline = max(0.46, 1.0 - depth * 0.58)
            multiplier = baseline + depth * 0.52 * envelope
        elif mode == "ripple":
            baseline = max(0.52, 1.0 - depth * 0.44)
            multiplier = baseline + depth * 0.36 * envelope
        elif mode == "bloom":
            baseline = max(0.58, 1.0 - depth * 0.34)
            multiplier = baseline + depth * 0.22 * envelope
        elif mode == "gate":
            baseline = 0.78
            multiplier = baseline + 0.22 * (envelope ** 0.55)
        else:
            baseline = 0.80
            multiplier = baseline + 0.20 * envelope

        multiplier *= (1.0 - texture_blend) + texture_multiplier * texture_blend
        multiplier = max(0.0, min(1.08, multiplier))
        return clamp_dmx(round(dimmer * multiplier))

    def _motion_for_config(self, slot_id, config, osc):
        if not config["sync_enabled"]:
            return None
        fixture = find_fixture(FIXTURE_LIBRARY, config["fixture"])
        mode = find_mode(fixture, config["mode"])
        capabilities = mode_capabilities(mode)
        if not capabilities["pan"] or not capabilities["tilt"]:
            return None
        one_shot_cue_id = one_shot_cue_name(config.get("_one_shot_cue_id"))
        phrase = osc.get("phrase_current")
        if not phrase and (config.get("_live_override_audience_sweep") or one_shot_cue_id != "none"):
            phrase = "override"
        if not phrase:
            return None
        beat_value = osc.get("beat_value")
        if beat_value is None and (config.get("_live_override_audience_sweep") or one_shot_cue_id != "none"):
            beat_value = time.time() * 0.9
        slot_context = config.get("_slot_context")
        movement_scale = float(config.get("_auto_show_movement", 0.0) or 0.0)
        if one_shot_cue_id != "none":
            motion = self._one_shot_motion_for_config(
                one_shot_cue_id,
                float(config.get("_one_shot_cue_progress", 0.0) or 0.0),
                slot_context or {},
                config,
                beat_value,
            )
            if motion:
                return _apply_audience_pan_focus_to_motion(motion, slot_context, config=config)
        motion_name = config.get("_auto_show_motion_name")
        if motion_name:
            motion = styled_phrase_motion(
                phrase,
                beat_value,
                motion_name,
                slot_context,
                movement_scale,
                config,
            )
            motion = maybe_apply_member_mirror(
                motion,
                slot_context,
                bool(config.get("_auto_show_member_mirror")),
                config=config,
            )
            return _apply_audience_pan_focus_to_motion(motion, slot_context, config=config)
        phase_offset = 0.0
        if slot_context and slot_context.get("group_count", slot_context.get("role_count", 1)) > 1:
            phase_offset = (
                slot_context.get("group_centered", slot_context["centered"]) * (0.48 + movement_scale * 0.70)
                + slot_context.get("group_alternate", slot_context["alternate"]) * 0.14
            )
        motion = phrase_motion(phrase, (beat_value or 0.0) + phase_offset)
        if not motion or not slot_context or slot_context.get("group_count", slot_context.get("role_count", 1)) <= 1:
            return motion

        pan = motion["pan"]
        tilt = motion["tilt"]
        if slot_context.get("group_alternate", slot_context["alternate"]) < 0:
            pan = 254 - pan
        pan = clamp_dmx(
            round(
                pan
                + slot_context.get("group_centered", slot_context["centered"]) * (18 + movement_scale * 28)
                + slot_context.get("member_centered", 0.0) * 8
            )
        )
        tilt = clamp_dmx(
            round(
                tilt
                - slot_context.get("group_edge_bias", slot_context["edge_bias"]) * (8 + movement_scale * 12)
                + slot_context.get("member_centered", 0.0) * 4
            )
        )
        motion = {
            "pan": pan,
            "tilt": tilt,
            "pan_tilt_speed": motion["pan_tilt_speed"],
        }
        motion = maybe_apply_member_mirror(
            motion,
            slot_context,
            bool(config.get("_auto_show_member_mirror")),
            config=config,
        )
        return _apply_audience_pan_focus_to_motion(motion, slot_context, config=config)

    def _send_loop(self):
        while True:
            with self.lock:
                if not self.running or not self.dmx:
                    return
                dmx = self.dmx
                fps = self.fps
                try:
                    render_now = time.time()
                    config = self._clean_full_config(dict(self.config))
                    osc = self.osc.snapshot_for_render()
                    auto_show = self._auto_show_state(osc, config["auto_show"])
                    values = self._render_values(
                        render_now,
                        config=config,
                        osc=osc,
                        auto_show=auto_show,
                    )
                    self.current_values = values
                    self.current_slot_previews = self._build_slot_previews(
                        config,
                        osc,
                        render_now,
                        auto_show=auto_show,
                    )
                except Exception as exc:
                    self.error = str(exc)
                    values = dict(self.current_values)

            started = time.monotonic()
            try:
                dmx.send(values)
                with self.lock:
                    self.error = None
                    self.last_sent = time.time()
            except Exception as exc:
                with self.lock:
                    self.error = str(exc)
                time.sleep(0.25)
            elapsed = time.monotonic() - started
            time.sleep(max(0, (1 / fps) - elapsed))


OSC = OscListener()
DMX = DmxController(OSC)


def serial_ports():
    try:
        from serial.tools import list_ports
    except ModuleNotFoundError:
        return []
    ports = []
    for port in list_ports.comports():
        details = []
        if port.manufacturer:
            details.append(port.manufacturer)
        if port.product:
            details.append(port.product)
        label = port.device
        if details:
            label = f"{label} ({', '.join(details)})"
        ports.append(
            {
                "device": port.device,
                "label": label,
                "manufacturer": port.manufacturer,
                "product": port.product,
                "serial_number": port.serial_number,
            }
        )
    return ports


def primary_lan_ip():
    candidates = []
    with suppress(Exception):
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            udp.connect(("8.8.8.8", 80))
            candidates.append(udp.getsockname()[0])
        finally:
            udp.close()
    with suppress(Exception):
        hostname_ip = socket.gethostbyname(socket.gethostname())
        candidates.append(hostname_ip)
    for candidate in candidates:
        if (
            candidate
            and candidate != "127.0.0.1"
            and "." in candidate
            and not candidate.startswith("169.254.")
        ):
            return candidate
    return None


def default_remote_access_config():
    return {
        "require_token": True,
        "token": secrets.token_urlsafe(24),
        "pairing_code": "".join(secrets.choice("0123456789") for _ in range(6)),
    }


def load_remote_access_config():
    if REMOTE_ACCESS_PATH.exists():
        with suppress(Exception):
            payload = json.loads(REMOTE_ACCESS_PATH.read_text(encoding="utf-8"))
            token = str((payload or {}).get("token") or "").strip()
            require_token = bool((payload or {}).get("require_token", True))
            pairing_code = str((payload or {}).get("pairing_code") or "").strip()
            if token:
                return {
                    "require_token": require_token,
                    "token": token,
                    "pairing_code": pairing_code if pairing_code.isdigit() and len(pairing_code) == 6 else default_remote_access_config()["pairing_code"],
                }
    config = default_remote_access_config()
    save_remote_access_config(config)
    return config


def save_remote_access_config(config):
    payload = {
        "require_token": bool(config.get("require_token", True)),
        "token": str(config.get("token") or "").strip(),
        "pairing_code": str(config.get("pairing_code") or "").strip(),
    }
    if not payload["token"]:
        payload["token"] = secrets.token_urlsafe(24)
    if not (payload["pairing_code"].isdigit() and len(payload["pairing_code"]) == 6):
        payload["pairing_code"] = "".join(secrets.choice("0123456789") for _ in range(6))
    REMOTE_ACCESS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def tailscale_ipv4():
    tailscale_path = shutil.which("tailscale")
    if not tailscale_path:
        for candidate in ("/opt/homebrew/bin/tailscale", "/usr/local/bin/tailscale"):
            if Path(candidate).exists():
                tailscale_path = candidate
                break
    if not tailscale_path:
        return None
    with suppress(Exception):
        completed = subprocess.run(
            [tailscale_path, "ip", "-4"],
            capture_output=True,
            check=True,
            text=True,
            timeout=1.5,
        )
        for line in completed.stdout.splitlines():
            ip = line.strip()
            if ip.startswith("100.") and "." in ip:
                return ip
    return None


def is_loopback_client(address):
    text = str(address or "").strip()
    return text in ("127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost")


def remote_access_token():
    config = REMOTE_ACCESS_CONFIG or {}
    token = str(config.get("token") or "").strip()
    return token or None


def remote_access_requires_token():
    config = REMOTE_ACCESS_CONFIG or {}
    return bool(config.get("require_token", True))


def remote_access_pairing_code():
    config = REMOTE_ACCESS_CONFIG or {}
    code = str(config.get("pairing_code") or "").strip()
    return code if code.isdigit() and len(code) == 6 else None


def remote_access_state():
    local_url = f"http://127.0.0.1:{SERVER_PORT}/remote"
    lan_ip = primary_lan_ip()
    tailscale_ip = tailscale_ipv4()
    bind_host = SERVER_HOST
    token = remote_access_token()
    token_suffix = f"?token={token}" if token and remote_access_requires_token() else ""
    if bind_host in ("0.0.0.0", "::"):
        lan_url = f"http://{lan_ip}:{SERVER_PORT}/remote{token_suffix}" if lan_ip else None
    elif bind_host in ("127.0.0.1", "localhost"):
        lan_url = None
    else:
        lan_url = f"http://{bind_host}:{SERVER_PORT}/remote{token_suffix}"
    tailscale_url = (
        f"http://{tailscale_ip}:{SERVER_PORT}/remote{token_suffix}"
        if tailscale_ip
        else None
    )
    preferred_url = tailscale_url or lan_url or (f"{local_url}{token_suffix}" if token_suffix else local_url)
    return {
        "enabled": bind_host not in ("127.0.0.1", "localhost"),
        "bind_host": bind_host,
        "port": SERVER_PORT,
        "path": "/remote",
        "local_url": f"{local_url}{token_suffix}" if token_suffix else local_url,
        "lan_url": lan_url,
        "tailscale_url": tailscale_url,
        "preferred_url": preferred_url,
        "auth_required": bool(token_suffix),
    }


def full_state():
    osc_state = OSC.state()
    return {
        "app": {"name": "BeatBeam DMX", "api_schema_version": API_SCHEMA_VERSION},
        "dmx": DMX.state(),
        "osc": osc_state,
        "remote": remote_access_state(),
        "source": {
            "mode": "external_osc",
            "app": "Live BPM Trigger",
            "port": OSC.port,
            "expected_destination": f"127.0.0.1:{OSC.port}",
            "last_source": (osc_state.get("last_message") or {}).get("source"),
        },
    }


def remote_state():
    osc_state = OSC.state()
    dmx_state = DMX.state()
    return {
        "dmx": {
            "connected": dmx_state.get("connected", False),
            "blackout_active": dmx_state.get("blackout_active", False),
            "active_slot": dmx_state.get("active_slot", "head"),
            "auto_show": dmx_state.get("auto_show", {}),
        },
        "osc": {
            "bpm": osc_state.get("bpm"),
            "beat_display": osc_state.get("beat_display"),
            "phrase_current": osc_state.get("phrase_current"),
            "phrase_next": osc_state.get("phrase_next"),
            "track_title": osc_state.get("track_title"),
            "track_artist": osc_state.get("track_artist"),
            "stale": osc_state.get("stale", True),
        },
    }


class AppHandler(BaseHTTPRequestHandler):
    server_version = "BeatBeamDMX/0.1"
    protocol_version = "HTTP/1.1"

    def request_context(self):
        parsed = urlparse(self.path)
        query = {}
        raw_query = parsed.query or ""
        if raw_query:
            for pair in raw_query.split("&"):
                if not pair:
                    continue
                key, _, value = pair.partition("=")
                query[key] = value
        return parsed.path, query

    def is_authorized_remote_request(self, query):
        client_ip = self.client_address[0] if self.client_address else ""
        if is_loopback_client(client_ip):
            return True
        if not remote_access_requires_token():
            return True
        expected = remote_access_token()
        if not expected:
            return True
        provided = (
            self.headers.get("X-BeatBeam-Token")
            or self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            or query.get("token")
        )
        return str(provided or "").strip() == expected

    def deny_remote_request(self, path):
        if path.startswith("/api/"):
            self.send_json({"error": "remote access token required"}, status=403)
            return
        body = (
            "<!doctype html><html><body style='font-family:system-ui;background:#111;color:#eee;padding:24px'>"
            "<h1>Access denied</h1><p>Open de volledige remote-URL vanuit BeatBeam, inclusief token.</p>"
            "</body></html>"
        ).encode("utf-8")
        self.send_response(403)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path, query = self.request_context()
        if path in ("/remote", "/live-remote") and not self.is_authorized_remote_request(query):
            self.deny_remote_request(path)
            return
        if path.startswith("/api/") and not self.is_authorized_remote_request(query):
            self.deny_remote_request(path)
            return
        if path == "/api/remote-state":
            self.send_json(remote_state())
            return
        if path == "/api/remote-events":
            self.send_event_stream(remote_state)
            return
        if path == "/api/state":
            self.send_json(full_state())
            return
        if path == "/api/ports":
            self.send_json({"ports": serial_ports()})
            return
        if path == "/api/fixtures":
            self.send_json({"fixtures": load_fixture_profiles()})
            return
        if path == "/":
            path = "/index.html"
        elif path in ("/remote", "/live-remote"):
            path = "/remote.html"
        self.send_static(path)

    def do_POST(self):
        path, query = self.request_context()
        if path.startswith("/api/") and not self.is_authorized_remote_request(query):
            self.deny_remote_request(path)
            return
        try:
            payload = self.read_json()
            if path == "/api/dmx/connect":
                DMX.connect(payload["port"], payload.get("fps", DEFAULT_DMX_FPS))
                self.send_json(full_state())
                return
            if path == "/api/dmx/disconnect":
                DMX.disconnect()
                self.send_json(full_state())
                return
            if path == "/api/dmx/update":
                DMX.update_config(payload)
                self.send_json(full_state())
                return
            if path == "/api/dmx/trigger-cue":
                DMX.trigger_one_shot_cue(payload.get("cue_id"))
                self.send_json(full_state())
                return
            if path == "/api/dmx/add-slot":
                DMX.add_slot(payload["fixture_id"], payload.get("mode"))
                self.send_json(full_state())
                return
            if path == "/api/dmx/remove-slot":
                DMX.remove_slot(payload["slot_id"])
                self.send_json(full_state())
                return
            if path == "/api/dmx/blackout":
                DMX.blackout()
                self.send_json(full_state())
                return
        except Exception as exc:
            self.send_json({"error": str(exc), "state": full_state()}, status=400)
            return
        self.send_json({"error": "not found"}, status=404)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_event_stream(self, payload_provider, interval_seconds=0.05):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        last_payload = None
        last_keepalive_at = 0.0
        try:
            while True:
                payload = payload_provider()
                encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
                if encoded != last_payload:
                    chunk = f"event: state\ndata: {encoded}\n\n".encode("utf-8")
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    last_payload = encoded
                    last_keepalive_at = time.time()
                elif time.time() - last_keepalive_at >= 10.0:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    last_keepalive_at = time.time()
                time.sleep(interval_seconds)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return

    def send_static(self, route_path):
        relative = route_path.lstrip("/")
        target = (STATIC_DIR / relative).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            self.send_error(404)
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")


def shutdown():
    DMX.disconnect()
    OSC.stop()


def main():
    parser = argparse.ArgumentParser(description="BeatBeam DMX local controller")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=DEFAULT_HTTP_PORT)
    parser.add_argument("--osc-port", type=int, default=DEFAULT_OSC_PORT)
    args = parser.parse_args()

    global SERVER_HOST, SERVER_PORT, REMOTE_ACCESS_CONFIG
    SERVER_HOST = str(args.host)
    SERVER_PORT = int(args.port)
    REMOTE_ACCESS_CONFIG = load_remote_access_config()
    OSC.port = args.osc_port
    OSC.start()
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    TRIGGER_LOG.log("BACKEND_START", host=args.host, port=args.port, osc_port=args.osc_port)
    print(f"BeatBeam DMX running at http://{args.host}:{args.port}")
    print(f"OSC input listening on UDP {args.osc_port}")
    print(f"Trigger log: {TRIGGER_LOG_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()
        server.server_close()


atexit.register(shutdown)


if __name__ == "__main__":
    main()
