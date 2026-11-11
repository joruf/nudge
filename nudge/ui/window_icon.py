"""The application icon, drawn in code rather than shipped as an image.

An icon is normally a binary file in the repository, and normally that is fine. Here it is not:
Nudge has to run where `pip install` fails, which is also where an image library to convert or
scale an icon is missing. So the icon is a handful of signed distance fields rendered to PNG with
`zlib` and `struct` -- both in the standard library -- and cached as files on first start.

What it draws: a pointer with two ripples leaving its tip. That is what the program does, once per
interval, for as long as it is switched on.

The rendered files serve three consumers:

* Tk, as `_NET_WM_ICON`, which is what a Linux panel reads to put an icon on a running window
* the `.desktop` entry, through the hicolor icon theme
* Windows, as an `.ico`, which is the only icon format a shortcut understands
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path
from typing import Callable, Sequence

from ..paths import ICON_BASENAME, IS_FROZEN, RESOURCES_DIR, cache_dir

#: Written next to the .desktop template. The first entry is the one a .desktop file points at.
ICON_SIZES: tuple[int, ...] = (256, 128, 64, 48)

#: Sizes an .ico carries. Windows picks per context: 256 for the large view, 16 for the title bar.
ICO_SIZES: tuple[int, ...] = (256, 128, 64, 48, 32, 16)

#: Sizes handed to Tk for _NET_WM_ICON. Tk writes all of them in a single XChangeProperty request,
#: and X refuses a request above 65535 words of four bytes. A 256x256 image alone needs 65538, so
#: including it leaves the property empty and the taskbar without any icon at all -- silently.
#: 128 + 64 + 48 comes to about 89 KB and covers every panel size in use.
WINDOW_ICON_SIZES: tuple[int, ...] = (128, 64, 48)

#: Handed to tk.Tk(className=...), which publishes it as the class part of WM_CLASS. Tk normalises
#: it to "first letter upper, rest lower" -- which "Nudge" already is -- and StartupWMClass in the
#: .desktop file must match that exactly, or the panel shows a second, iconless taskbar entry
#: beside the launcher instead of marking the launcher as running.
WM_CLASS_NAME = "Nudge"
WM_CLASS_PUBLISHED = WM_CLASS_NAME[:1].upper() + WM_CLASS_NAME[1:].lower()

# Palette. The blue is the interface accent, so the icon and the window agree on what colour the
# program is.
TILE_TOP: tuple[int, int, int] = (0x6D, 0x9F, 0xFF)
TILE_BOTTOM: tuple[int, int, int] = (0x1F, 0x4F, 0xD8)
POINTER: tuple[int, int, int] = (0xFF, 0xFF, 0xFF)

# Geometry in unit coordinates: 0..1 across the tile, y pointing down.
_TILE_RADIUS = 0.22
_TILE_HALF = 0.48

_TIP: tuple[float, float] = (0.225, 0.335)
_AXIS: tuple[float, float] = (0.5514, 0.8342)      # unit vector, down and to the right
_HEAD_LENGTH = 0.300
_HEAD_HALF_WIDTH = 0.158
_TAIL_FROM = 0.255                                  # along the axis, overlapping the head
_TAIL_TO = 0.640
_TAIL_RADIUS = 0.064

#: Ripples leaving the tip: (radius, first angle, last angle, thickness, alpha). Angles are degrees
#: in screen orientation, so a negative one points upwards. They straddle the direction at right
#: angles to the pointer, which is where a motion line belongs, and stop short of the tile edge.
_RIPPLES: tuple[tuple[float, float, float, float, float], ...] = (
    (0.275, -64.0, -2.0, 0.032, 0.95),
    (0.380, -50.0, -4.0, 0.028, 0.70),
)


# --- signed distance fields ---------------------------------------------------------------------
# Every shape answers one question: how far is this pixel from my edge, negative on the inside.
# Anti-aliasing is then a matter of turning that distance into a coverage value, and combining
# shapes is a matter of taking a minimum. No polygon rasteriser required.


def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else (1.0 if value > 1.0 else value)


def _coverage(distance: float, edge: float) -> float:
    """How much of a pixel a shape covers, given its distance from the edge."""
    return _clamp01(0.5 - distance / edge)


def _sdf_rounded_rect(x: float, y: float, cx: float, cy: float,
                      half_w: float, half_h: float, radius: float) -> float:
    dx = abs(x - cx) - (half_w - radius)
    dy = abs(y - cy) - (half_h - radius)
    return math.hypot(max(dx, 0.0), max(dy, 0.0)) + min(max(dx, dy), 0.0) - radius


def _sdf_capsule(x: float, y: float, start: tuple[float, float],
                 end: tuple[float, float], radius: float) -> float:
    ax, ay = start
    ex, ey = end[0] - ax, end[1] - ay
    wx, wy = x - ax, y - ay
    length_squared = ex * ex + ey * ey
    if length_squared <= 0.0:
        return math.hypot(wx, wy) - radius
    t = _clamp01((wx * ex + wy * ey) / length_squared)
    return math.hypot(wx - t * ex, wy - t * ey) - radius


def _sdf_polyline(x: float, y: float, points: Sequence[tuple[float, float]],
                  radius: float) -> float:
    """Distance to a chain of capsules, which is how the curved ripples are drawn."""
    best = 1.0e9
    for index in range(len(points) - 1):
        best = min(best, _sdf_capsule(x, y, points[index], points[index + 1], radius))
    return best


def _sdf_convex_polygon(x: float, y: float, points: Sequence[tuple[float, float]]) -> float:
    """Distance to a convex polygon, exact along the edges and conservative at the corners.

    The winding is detected rather than assumed: a polygon written down the other way round would
    otherwise come out inside-out, and there is no way to see that in the source.
    """
    count = len(points)
    area = sum(
        points[i][0] * points[(i + 1) % count][1] - points[(i + 1) % count][0] * points[i][1]
        for i in range(count)
    )
    sign = 1.0 if area > 0.0 else -1.0
    worst = -1.0e9
    for index in range(count):
        ax, ay = points[index]
        bx, by = points[(index + 1) % count]
        ex, ey = bx - ax, by - ay
        length = math.hypot(ex, ey) or 1.0
        nx, ny = sign * ey / length, -sign * ex / length
        worst = max(worst, (x - ax) * nx + (y - ay) * ny)
    return worst


def _mix(a: tuple[float, float, float], b: tuple[int, int, int],
         amount: float) -> tuple[float, float, float]:
    return (a[0] + (b[0] - a[0]) * amount,
            a[1] + (b[1] - a[1]) * amount,
            a[2] + (b[2] - a[2]) * amount)


# --- the drawing --------------------------------------------------------------------------------

Layer = tuple[Callable[[float, float], float], tuple[int, int, int], float]


def _along_axis(distance: float) -> tuple[float, float]:
    return _TIP[0] + _AXIS[0] * distance, _TIP[1] + _AXIS[1] * distance


def _ripple_points(radius: float, first: float, last: float,
                   segments: int = 16) -> list[tuple[float, float]]:
    """Points along an arc centred on the pointer tip, to be joined by capsules."""
    step = (last - first) / segments
    points = []
    for index in range(segments + 1):
        angle = math.radians(first + step * index)
        points.append((_TIP[0] + radius * math.cos(angle), _TIP[1] + radius * math.sin(angle)))
    return points


def _layers() -> list[Layer]:
    """The shapes of the icon in painting order."""
    base = _along_axis(_HEAD_LENGTH)
    perpendicular = (-_AXIS[1], _AXIS[0])
    barb_a = (base[0] + perpendicular[0] * _HEAD_HALF_WIDTH,
              base[1] + perpendicular[1] * _HEAD_HALF_WIDTH)
    barb_b = (base[0] - perpendicular[0] * _HEAD_HALF_WIDTH,
              base[1] - perpendicular[1] * _HEAD_HALF_WIDTH)
    head = (_TIP, barb_b, barb_a)
    tail = (_along_axis(_TAIL_FROM), _along_axis(_TAIL_TO))

    layers: list[Layer] = [
        (lambda x, y: _sdf_convex_polygon(x, y, head), POINTER, 1.0),
        (lambda x, y: _sdf_capsule(x, y, tail[0], tail[1], _TAIL_RADIUS), POINTER, 1.0),
    ]
    for radius, first, last, thickness, alpha in _RIPPLES:
        points = _ripple_points(radius, first, last)
        layers.append((
            lambda x, y, p=points, r=thickness: _sdf_polyline(x, y, p, r),
            POINTER,
            alpha,
        ))
    return layers


def render_icon_rows(size: int) -> list[bytes]:
    """Render the icon into raw RGBA scanlines.

    Args:
        size: Edge length of the square icon in pixels.

    Returns:
        list[bytes]: One RGBA row per pixel line.
    """
    if size < 8:
        raise ValueError("icon size must be at least 8 pixels")

    edge = 1.5 / size
    layers = _layers()
    rows: list[bytes] = []

    for pixel_y in range(size):
        y = (pixel_y + 0.5) / size
        row = bytearray()
        for pixel_x in range(size):
            x = (pixel_x + 0.5) / size
            tile = _coverage(
                _sdf_rounded_rect(x, y, 0.5, 0.5, _TILE_HALF, _TILE_HALF, _TILE_RADIUS), edge
            )
            if tile <= 0.0:
                row += b"\x00\x00\x00\x00"
                continue

            colour = _mix(TILE_TOP, TILE_BOTTOM, _clamp01(x * 0.3 + y * 0.7))
            for distance_fn, ink, alpha in layers:
                weight = _coverage(distance_fn(x, y), edge) * alpha
                if weight > 0.0:
                    colour = _mix(colour, ink, weight)

            row += bytes((int(colour[0] + 0.5), int(colour[1] + 0.5), int(colour[2] + 0.5),
                          int(tile * 255.0 + 0.5)))
        rows.append(bytes(row))
    return rows


# --- file formats -------------------------------------------------------------------------------


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def encode_png(rows: Sequence[bytes], width: int, height: int) -> bytes:
    """Encode RGBA scanlines as an eight bit RGBA PNG."""
    raw = b"".join(b"\x00" + row for row in rows)
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", header)
            + _png_chunk(b"IDAT", zlib.compress(raw, 9))
            + _png_chunk(b"IEND", b""))


def render_icon_png(size: int) -> bytes:
    """The icon at one size, as PNG bytes."""
    return encode_png(render_icon_rows(size), size, size)


def render_icon_ico(sizes: Sequence[int] = ICO_SIZES) -> bytes:
    """The icon as a Windows .ico carrying several sizes.

    The images are stored as PNG rather than as device independent bitmaps, which every Windows
    since Vista reads, and which means the PNG encoder above is the only encoder needed.
    """
    images = [render_icon_png(size) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    directory = b""
    for size, image in zip(sizes, images):
        # 256 does not fit in a byte and is written as 0, which the format defines as 256.
        edge = 0 if size >= 256 else size
        directory += struct.pack("<BBBBHHII", edge, edge, 0, 0, 1, 32, len(image), offset)
        offset += len(image)
    return header + directory + b"".join(images)


# --- cached files -------------------------------------------------------------------------------


def icon_directories() -> list[Path]:
    """Where rendered icons are looked for and written, preferred first.

    `resources/` next to the program is the normal home. The cache directory is the fallback for
    a clone the user cannot write to -- a shared checkout, or one unpacked read-only.
    """
    if IS_FROZEN:
        # resources/ is inside the unpacked files of the executable and gone when it exits.
        return [cache_dir()]
    return [RESOURCES_DIR, cache_dir()]


def icon_path(size: int, directory: Path | None = None) -> Path:
    base = RESOURCES_DIR if directory is None else directory
    return base / f"{ICON_BASENAME}-{size}.png"


def find_icon_file(size: int) -> Path | None:
    """An already rendered icon of that size, if there is one."""
    for directory in icon_directories():
        candidate = icon_path(size, directory)
        if candidate.is_file():
            return candidate
    return None


def ensure_icon_files(sizes: Sequence[int] = ICON_SIZES, force: bool = False) -> list[Path]:
    """Make sure the icon files exist, and return the ones that do.

    Only missing sizes are rendered, so a normal start does no work at all.

    Args:
        sizes: Which sizes to provide.
        force: Render again even where a file is already there.

    Returns:
        list[Path]: Every icon file now available, in the order asked for.
    """
    available: list[Path] = []
    for size in sizes:
        existing = None if force else find_icon_file(size)
        if existing is not None:
            available.append(existing)
            continue

        data: bytes | None = None
        for directory in icon_directories():
            try:
                if data is None:
                    data = render_icon_png(size)
                directory.mkdir(parents=True, exist_ok=True)
                target = icon_path(size, directory)
                target.write_bytes(data)
                available.append(target)
                break
            except OSError:
                continue
    return available


def primary_icon_file() -> Path | None:
    """The largest icon, rendering it if it is not there yet."""
    paths = ensure_icon_files()
    for path in paths:
        if path.name == f"{ICON_BASENAME}-{ICON_SIZES[0]}.png":
            return path
    return paths[0] if paths else None


def ensure_ico_file() -> Path | None:
    """The multi-size .ico a Windows shortcut points at."""
    for directory in icon_directories():
        candidate = directory / f"{ICON_BASENAME}.ico"
        if candidate.is_file():
            return candidate
    data: bytes | None = None
    for directory in icon_directories():
        try:
            if data is None:
                data = render_icon_ico()
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / f"{ICON_BASENAME}.ico"
            target.write_bytes(data)
            return target
        except OSError:
            continue
    return None


def apply_window_icon(window) -> bool:
    """Give a window its icon, for the title bar and the taskbar.

    Args:
        window: A Tk root or Toplevel.

    Returns:
        bool: True when at least one size was accepted.
    """
    import tkinter as tk

    images = []
    for path in ensure_icon_files(sizes=WINDOW_ICON_SIZES):
        try:
            images.append(tk.PhotoImage(master=window, file=str(path)))
        except Exception:
            continue
    if not images:
        return False

    try:
        window.iconphoto(True, *images)
    except Exception:
        try:
            window.iconphoto(True, images[0])
        except Exception:
            return False

    # Tk does not own the images; without a reference they are collected and the icon vanishes.
    window._nudge_icons = images  # type: ignore[attr-defined]
    return True


if __name__ == "__main__":
    for created in ensure_icon_files(force=True):
        print(created)
