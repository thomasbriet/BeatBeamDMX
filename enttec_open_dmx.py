#!/usr/bin/env python3
import argparse
import ctypes
import json
import os
import signal
import sys
import time
from contextlib import suppress
from pathlib import Path


DMX_CHANNELS = 512
PROFILE_PATH = Path(__file__).with_name("fixtures.json")
PRESET_COLORS = {
    "red": (255, 0, 0, 0),
    "green": (0, 255, 0, 0),
    "blue": (0, 0, 255, 0),
    "white": (255, 255, 255, 255),
    "warm-white": (255, 180, 80, 120),
    "cyan": (0, 255, 255, 0),
    "magenta": (255, 0, 255, 0),
    "yellow": (255, 255, 0, 0),
}


FT_OPEN_BY_SERIAL_NUMBER = 1
FT_OK = 0
FT_PURGE_RX = 1
FT_PURGE_TX = 2
FT_FLOW_NONE = 0x0000
FT_BITS_8 = 8
FT_STOP_BITS_2 = 2
FT_PARITY_NONE = 0


def candidate_ftd2xx_library_paths():
    return [
        os.environ.get("FTD2XX_LIBRARY"),
        "/Applications/rekordbox 7/rekordbox.app/Contents/MacOS/libftd2xx.dylib",
        "/Applications/SoundSwitch.app/Contents/Frameworks/libftd2xx.dylib",
        "/usr/local/lib/libftd2xx.dylib",
    ]


def load_ftd2xx_library():
    for raw_path in candidate_ftd2xx_library_paths():
        if not raw_path:
            continue
        path = Path(raw_path)
        if not path.exists():
            continue
        lib = ctypes.CDLL(str(path))
        lib.FT_Open.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
        lib.FT_Open.restype = ctypes.c_ulong
        lib.FT_OpenEx.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        lib.FT_OpenEx.restype = ctypes.c_ulong
        lib.FT_Close.argtypes = [ctypes.c_void_p]
        lib.FT_Close.restype = ctypes.c_ulong
        lib.FT_ResetDevice.argtypes = [ctypes.c_void_p]
        lib.FT_ResetDevice.restype = ctypes.c_ulong
        lib.FT_Purge.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        lib.FT_Purge.restype = ctypes.c_ulong
        lib.FT_SetUSBParameters.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
        ]
        lib.FT_SetUSBParameters.restype = ctypes.c_ulong
        lib.FT_SetChars.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ubyte,
            ctypes.c_ubyte,
            ctypes.c_ubyte,
            ctypes.c_ubyte,
        ]
        lib.FT_SetChars.restype = ctypes.c_ulong
        lib.FT_SetTimeouts.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
        ]
        lib.FT_SetTimeouts.restype = ctypes.c_ulong
        lib.FT_SetLatencyTimer.argtypes = [ctypes.c_void_p, ctypes.c_ubyte]
        lib.FT_SetLatencyTimer.restype = ctypes.c_ulong
        lib.FT_SetFlowControl.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ushort,
            ctypes.c_ubyte,
            ctypes.c_ubyte,
        ]
        lib.FT_SetFlowControl.restype = ctypes.c_ulong
        lib.FT_SetDataCharacteristics.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ubyte,
            ctypes.c_ubyte,
            ctypes.c_ubyte,
        ]
        lib.FT_SetDataCharacteristics.restype = ctypes.c_ulong
        lib.FT_SetBaudRate.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        lib.FT_SetBaudRate.restype = ctypes.c_ulong
        lib.FT_Write.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        lib.FT_Write.restype = ctypes.c_ulong
        lib.FT_SetBreakOn.argtypes = [ctypes.c_void_p]
        lib.FT_SetBreakOn.restype = ctypes.c_ulong
        lib.FT_SetBreakOff.argtypes = [ctypes.c_void_p]
        lib.FT_SetBreakOff.restype = ctypes.c_ulong
        return str(path), lib
    return None, None


def extract_ftdi_serial(port: str):
    name = Path(port).name
    for prefix in ("cu.usbserial-", "tty.usbserial-"):
        if name.startswith(prefix):
            return name[len(prefix) :]
    return None


def require_ft_status(status, action):
    if status != FT_OK:
        raise RuntimeError(f"{action} failed with FT_STATUS {status}")


class EnttecOpenDmxD2xx:
    def __init__(self, port: str, channels: int = DMX_CHANNELS):
        lib_path, lib = load_ftd2xx_library()
        if not lib:
            raise RuntimeError("FTDI D2XX library not found")
        self.channels = channels
        self.lib = lib
        self.lib_path = lib_path
        self.handle = ctypes.c_void_p()
        serial_number = extract_ftdi_serial(port)
        if serial_number:
            status = self.lib.FT_OpenEx(
                ctypes.c_char_p(serial_number.encode("ascii")),
                FT_OPEN_BY_SERIAL_NUMBER,
                ctypes.byref(self.handle),
            )
        else:
            status = self.lib.FT_Open(0, ctypes.byref(self.handle))
        require_ft_status(status, "FT_Open")
        require_ft_status(self.lib.FT_ResetDevice(self.handle), "FT_ResetDevice")
        require_ft_status(
            self.lib.FT_Purge(self.handle, FT_PURGE_RX | FT_PURGE_TX),
            "FT_Purge",
        )
        require_ft_status(
            self.lib.FT_SetUSBParameters(self.handle, 512, 512),
            "FT_SetUSBParameters",
        )
        require_ft_status(
            self.lib.FT_SetChars(self.handle, 0, 0, 0, 0),
            "FT_SetChars",
        )
        require_ft_status(
            self.lib.FT_SetTimeouts(self.handle, 100, 100),
            "FT_SetTimeouts",
        )
        require_ft_status(
            self.lib.FT_SetLatencyTimer(self.handle, 2),
            "FT_SetLatencyTimer",
        )
        require_ft_status(
            self.lib.FT_SetFlowControl(self.handle, FT_FLOW_NONE, 0, 0),
            "FT_SetFlowControl",
        )
        require_ft_status(
            self.lib.FT_SetDataCharacteristics(
                self.handle,
                FT_BITS_8,
                FT_STOP_BITS_2,
                FT_PARITY_NONE,
            ),
            "FT_SetDataCharacteristics",
        )
        require_ft_status(
            self.lib.FT_SetBaudRate(self.handle, 250000),
            "FT_SetBaudRate",
        )

    def close(self):
        if self.handle:
            with suppress(Exception):
                self.lib.FT_Close(self.handle)
            self.handle = None

    def send(self, values):
        frame = bytearray(self.channels + 1)
        for channel, value in values.items():
            if not 1 <= channel <= self.channels:
                raise ValueError(f"channel {channel} is outside 1-{self.channels}")
            frame[channel] = max(0, min(255, int(value)))

        require_ft_status(self.lib.FT_SetBreakOn(self.handle), "FT_SetBreakOn")
        time.sleep(0.001)
        require_ft_status(self.lib.FT_SetBreakOff(self.handle), "FT_SetBreakOff")
        time.sleep(0.0001)
        written = ctypes.c_ulong()
        buffer = (ctypes.c_ubyte * len(frame)).from_buffer_copy(frame)
        require_ft_status(
            self.lib.FT_Write(
                self.handle,
                ctypes.cast(buffer, ctypes.c_void_p),
                len(frame),
                ctypes.byref(written),
            ),
            "FT_Write",
        )
        if written.value != len(frame):
            raise RuntimeError(f"FT_Write wrote {written.value} bytes, expected {len(frame)}")


class EnttecOpenDmxSerial:
    def __init__(self, port: str, channels: int = DMX_CHANNELS):
        serial = require_pyserial()
        self.channels = channels
        self.serial = serial.Serial(
            port=port,
            baudrate=250000,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_TWO,
            timeout=0,
            write_timeout=0.1,
        )

    def close(self):
        self.serial.close()

    def send(self, values):
        frame = bytearray(self.channels + 1)
        for channel, value in values.items():
            if not 1 <= channel <= self.channels:
                raise ValueError(f"channel {channel} is outside 1-{self.channels}")
            frame[channel] = max(0, min(255, int(value)))

        self.serial.break_condition = True
        time.sleep(0.000176)
        self.serial.break_condition = False
        time.sleep(0.000016)
        self.serial.write(frame)


class EnttecOpenDmx:
    """Minimal sender for Enttec Open DMX USB / FTDI-style DMX interfaces."""

    def __init__(self, port: str, channels: int = DMX_CHANNELS):
        if not 1 <= channels <= DMX_CHANNELS:
            raise ValueError("channels must be between 1 and 512")
        self.channels = channels
        self.port = port
        self.backend = "serial"
        self.transport = None
        d2xx_error = None
        if extract_ftdi_serial(port):
            try:
                self.transport = EnttecOpenDmxD2xx(port, channels)
                self.backend = "ftd2xx"
            except Exception as exc:
                d2xx_error = exc
        if self.transport is None:
            self.transport = EnttecOpenDmxSerial(port, channels)
            if d2xx_error:
                self.backend = f"serial-fallback ({d2xx_error})"

    def close(self):
        self.transport.close()

    def send(self, values):
        self.transport.send(values)


def list_serial_ports():
    try:
        from serial.tools import list_ports
    except ModuleNotFoundError:
        print("pyserial is not installed. Run: python -m pip install -r requirements.txt")
        return

    ports = list(list_ports.comports())
    if not ports:
        print("No serial ports found.")
        return

    for port in ports:
        details = []
        if port.manufacturer:
            details.append(port.manufacturer)
        if port.product:
            details.append(port.product)
        if port.serial_number:
            details.append(f"serial={port.serial_number}")
        suffix = f" ({', '.join(details)})" if details else ""
        print(f"{port.device}{suffix}")


def require_pyserial():
    try:
        import serial
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "pyserial is not installed. Run: python -m pip install -r requirements.txt"
        ) from exc
    return serial


def clamp_dmx(value):
    return max(0, min(255, int(value)))


def load_fixture_profiles(path=PROFILE_PATH):
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data["fixtures"]


def find_fixture(fixtures, fixture_id):
    for fixture in fixtures:
        if fixture["id"] == fixture_id:
            return fixture
    raise ValueError(f"unknown fixture id: {fixture_id}")


def find_mode(fixture, mode_name):
    for mode in fixture["modes"]:
        if mode["name"].lower() == mode_name.lower():
            return mode
    names = ", ".join(mode["name"] for mode in fixture["modes"])
    raise ValueError(f"{fixture['id']} has no mode {mode_name!r}; available: {names}")


def list_fixtures():
    for fixture in load_fixture_profiles():
        modes = ", ".join(
            f"{mode['name']} ({mode['footprint']}ch)" for mode in fixture["modes"]
        )
        print(f"{fixture['id']}: {fixture['manufacturer']} {fixture['model']} - {modes}")


def parse_rgb(rgb_text):
    if rgb_text in PRESET_COLORS:
        return PRESET_COLORS[rgb_text]

    parts = rgb_text.split(",")
    if len(parts) not in (3, 4):
        raise argparse.ArgumentTypeError(
            "expected a preset color or R,G,B / R,G,B,W values"
        )
    values = tuple(clamp_dmx(part.strip()) for part in parts)
    if len(values) == 3:
        values = values + (0,)
    return values


def values_for_fixture(
    mode,
    start_address,
    rgb,
    dimmer,
    pan,
    tilt,
    pan_fine=0,
    tilt_fine=0,
    strobe=0,
    speed=0,
    program=0,
    color_program=None,
    color_speed=None,
    auto_mode=0,
    pan_tilt_speed=0,
    reset=0,
    zone_rgb=None,
    extra_values=None,
):
    red, green, blue, white = rgb
    values = {}
    component_values = {
        "red": red,
        "green": green,
        "blue": blue,
        "white": white,
        "coolwhite": white,
    }
    extra_values = dict(extra_values or {})

    def native_value(channel, value):
        """Map BeatBeam's semantic 0..255 value to a profile's DMX domain."""
        semantic = clamp_dmx(value)
        try:
            native_max = int(channel.get("native_max", 255))
        except (TypeError, ValueError):
            native_max = 255
        native_max = max(0, min(255, native_max))
        return clamp_dmx(round(semantic * native_max / 255))

    for channel in mode["channels"]:
        absolute = start_address + channel["offset"] - 1
        channel_type = channel["type"]

        if channel_type == "color":
            zone_index = channel.get("zone")
            if zone_rgb is not None and zone_index is not None:
                with suppress(Exception):
                    zone_value = zone_rgb[max(0, int(zone_index) - 1)]
                    zone_red = int(zone_value[0]) if len(zone_value) > 0 else 0
                    zone_green = int(zone_value[1]) if len(zone_value) > 1 else 0
                    zone_blue = int(zone_value[2]) if len(zone_value) > 2 else 0
                    zone_white = int(zone_value[3]) if len(zone_value) > 3 else 0
                    zone_components = {
                        "red": zone_red,
                        "green": zone_green,
                        "blue": zone_blue,
                        "white": zone_white,
                        "coolwhite": zone_white,
                    }
                    values[absolute] = native_value(channel, zone_components.get(channel.get("component", ""), 0))
                    continue
            values[absolute] = native_value(channel, component_values.get(channel.get("component", ""), 0))
        elif channel_type == "intensity":
            values[absolute] = native_value(channel, dimmer)
        elif channel_type == "pan":
            values[absolute] = clamp_dmx(pan)
        elif channel_type == "tilt":
            values[absolute] = clamp_dmx(tilt)
        elif channel_type == "pan_fine":
            values[absolute] = clamp_dmx(pan_fine)
        elif channel_type == "tilt_fine":
            values[absolute] = clamp_dmx(tilt_fine)
        elif channel_type == "program":
            values[absolute] = clamp_dmx(program)
        elif channel_type == "color_program":
            values[absolute] = clamp_dmx(program if color_program is None else color_program)
        elif channel_type == "auto_mode":
            values[absolute] = clamp_dmx(auto_mode)
        elif channel_type == "reset":
            values[absolute] = clamp_dmx(reset)
        elif channel_type == "speed":
            values[absolute] = clamp_dmx(speed)
        elif channel_type == "color_speed":
            values[absolute] = clamp_dmx(speed if color_speed is None else color_speed)
        elif channel_type == "strobe":
            values[absolute] = native_value(channel, strobe)
        elif channel_type == "pan_tilt_speed":
            values[absolute] = clamp_dmx(pan_tilt_speed)
        elif channel_type == "custom":
            control_id = str(
                channel.get("control")
                or channel.get("id")
                or channel.get("name")
                or f"custom_{channel.get('offset', absolute)}"
            )
            default_value = channel.get("default", 0)
            values[absolute] = native_value(channel, extra_values.get(control_id, default_value))

    return values


def parse_channel_value(items):
    values = {}
    for item in items:
        if "=" not in item:
            raise argparse.ArgumentTypeError(f"expected CHANNEL=VALUE, got {item!r}")
        channel, value = item.split("=", 1)
        values[int(channel)] = int(value)
    return values


def fixture_test(port, fixture_id, mode_name, address, rgb, dimmer, pan, tilt, fps):
    if not 1 <= address <= DMX_CHANNELS:
        raise ValueError("address must be between 1 and 512")

    fixture = find_fixture(load_fixture_profiles(), fixture_id)
    mode = find_mode(fixture, mode_name)
    last_channel = address + mode["footprint"] - 1
    if last_channel > DMX_CHANNELS:
        raise ValueError(
            f"{fixture_id} {mode_name} at address {address} ends at {last_channel}"
        )

    values = values_for_fixture(mode, address, rgb, dimmer, pan, tilt)
    print(
        f"Holding {fixture['manufacturer']} {fixture['model']} "
        f"{mode['name']} at DMX {address}-{last_channel}"
    )
    hold_values(port, values, fps)


def hold_values(port, values, fps):
    dmx = EnttecOpenDmx(port)
    running = True

    def stop(_signum, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    interval = 1 / fps
    try:
        while running:
            started = time.monotonic()
            dmx.send(values)
            time.sleep(max(0, interval - (time.monotonic() - started)))
    finally:
        with suppress(Exception):
            for _ in range(5):
                dmx.send({})
                time.sleep(interval)
        dmx.close()


def rgb_test(port, start_channel, fps):
    colors = [
        {start_channel: 255, start_channel + 1: 0, start_channel + 2: 0},
        {start_channel: 0, start_channel + 1: 255, start_channel + 2: 0},
        {start_channel: 0, start_channel + 1: 0, start_channel + 2: 255},
        {start_channel: 255, start_channel + 1: 255, start_channel + 2: 255},
    ]

    dmx = EnttecOpenDmx(port)
    running = True

    def stop(_signum, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    interval = 1 / fps
    color_index = 0
    next_change = 0.0
    try:
        while running:
            now = time.monotonic()
            if now >= next_change:
                color_index = (color_index + 1) % len(colors)
                next_change = now + 1.0
            started = time.monotonic()
            dmx.send(colors[color_index])
            time.sleep(max(0, interval - (time.monotonic() - started)))
    finally:
        with suppress(Exception):
            for _ in range(5):
                dmx.send({})
                time.sleep(interval)
        dmx.close()


def main():
    parser = argparse.ArgumentParser(description="Enttec Open DMX USB test tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="list serial ports")
    subparsers.add_parser("fixtures", help="list known fixture profiles and modes")

    hold = subparsers.add_parser("hold", help="continuously hold DMX channel values")
    hold.add_argument("--port", required=True, help="serial port, e.g. /dev/cu.usbserial-...")
    hold.add_argument("--fps", type=float, default=30.0, help="DMX refresh rate")
    hold.add_argument("values", nargs="+", help="channel assignments, e.g. 1=255 2=0 3=0")

    rgb = subparsers.add_parser("rgb-test", help="cycle RGB values on three channels")
    rgb.add_argument("--port", required=True, help="serial port, e.g. /dev/cu.usbserial-...")
    rgb.add_argument("--start-channel", type=int, default=1, help="first RGB channel")
    rgb.add_argument("--fps", type=float, default=30.0, help="DMX refresh rate")

    fixture = subparsers.add_parser(
        "fixture-test", help="test a known fixture profile by mode and start address"
    )
    fixture.add_argument("--port", required=True, help="serial port, e.g. /dev/cu.usbserial-...")
    fixture.add_argument("--fixture", required=True, help="fixture id from the fixtures command")
    fixture.add_argument("--mode", required=True, help="fixture mode/personality name")
    fixture.add_argument("--address", type=int, required=True, help="fixture DMX start address")
    fixture.add_argument(
        "--color",
        type=parse_rgb,
        default=PRESET_COLORS["red"],
        help="preset color or R,G,B/R,G,B,W values",
    )
    fixture.add_argument("--dimmer", type=int, default=255, help="dimmer value for modes that have one")
    fixture.add_argument("--pan", type=int, default=127, help="pan value for moving heads")
    fixture.add_argument("--tilt", type=int, default=127, help="tilt value for moving heads")
    fixture.add_argument("--fps", type=float, default=30.0, help="DMX refresh rate")

    args = parser.parse_args()

    if args.command == "list":
        list_serial_ports()
        return 0

    if args.command == "fixtures":
        list_fixtures()
        return 0

    if args.command == "hold":
        hold_values(args.port, parse_channel_value(args.values), args.fps)
        return 0

    if args.command == "rgb-test":
        rgb_test(args.port, args.start_channel, args.fps)
        return 0

    if args.command == "fixture-test":
        fixture_test(
            args.port,
            args.fixture,
            args.mode,
            args.address,
            args.color,
            args.dimmer,
            args.pan,
            args.tilt,
            args.fps,
        )
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
