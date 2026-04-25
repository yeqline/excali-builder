"""Helpers for resolving local image assets used in Markdown diagrams."""

import base64
import mimetypes
import re
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple


SUPPORTED_IMAGE_MIME_TYPES = {
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}
REMOTE_SOURCE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
SVG_LENGTH_PATTERN = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([A-Za-z%]*)\s*$")
SVG_UNIT_TO_PX = {
    "": 1.0,
    "cm": 96 / 2.54,
    "in": 96.0,
    "mm": 96 / 25.4,
    "pc": 16.0,
    "pt": 96 / 72,
    "px": 1.0,
}


@dataclass(frozen=True)
class LocalImageAsset:
    """Resolved local image with metadata needed for export."""

    path: Path
    relative_path: str
    mime_type: str
    width: int
    height: int


def resolve_local_image_asset(
    project_path: Path,
    markdown_file: Path,
    raw_src: str,
) -> LocalImageAsset:
    """Resolve a Markdown image source to a local project-relative asset."""
    normalized_src = _normalize_markdown_image_src(raw_src)
    if not normalized_src:
        raise ValueError("Image source cannot be empty")
    if normalized_src.startswith("data:") or REMOTE_SOURCE_PATTERN.match(normalized_src):
        raise ValueError("Only local image files are supported")

    resolved_path = (markdown_file.parent / normalized_src).resolve()
    project_root = project_path.resolve()
    try:
        relative_path = resolved_path.relative_to(project_root)
    except ValueError as exc:
        raise ValueError("Image source must stay inside the diagram folder") from exc

    if not resolved_path.exists() or not resolved_path.is_file():
        raise ValueError(f"Image source '{normalized_src}' does not exist")

    mime_type = get_image_mime_type(resolved_path)
    width, height = get_image_dimensions(resolved_path, mime_type)
    return LocalImageAsset(
        path=resolved_path,
        relative_path=relative_path.as_posix(),
        mime_type=mime_type,
        width=width,
        height=height,
    )


def get_image_mime_type(image_path: Path) -> str:
    """Return the supported MIME type for an image path."""
    suffix = image_path.suffix.lower()
    if suffix in SUPPORTED_IMAGE_MIME_TYPES:
        return SUPPORTED_IMAGE_MIME_TYPES[suffix]

    guessed_type, _ = mimetypes.guess_type(str(image_path))
    if guessed_type and guessed_type.startswith("image/"):
        return guessed_type

    raise ValueError(f"Unsupported image type for '{image_path.name}'")


def get_image_dimensions(image_path: Path, mime_type: str) -> Tuple[int, int]:
    """Read image dimensions using format-specific headers."""
    if mime_type == "image/svg+xml":
        return _get_svg_dimensions(image_path)

    data = image_path.read_bytes()
    if mime_type == "image/png":
        return _get_png_dimensions(data)
    if mime_type == "image/gif":
        return _get_gif_dimensions(data)
    if mime_type == "image/jpeg":
        return _get_jpeg_dimensions(data)
    if mime_type == "image/webp":
        return _get_webp_dimensions(data)

    raise ValueError(f"Unsupported image type for '{image_path.name}'")


def build_data_url(image_path: Path, mime_type: str) -> str:
    """Return a base64 data URL for a local image."""
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _normalize_markdown_image_src(raw_src: str) -> str:
    """Normalize a Markdown image destination."""
    src = raw_src.strip()
    if src.startswith("<") and src.endswith(">"):
        src = src[1:-1].strip()
    return src


def _get_png_dimensions(data: bytes) -> Tuple[int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Invalid PNG image")
    return struct.unpack(">II", data[16:24])


def _get_gif_dimensions(data: bytes) -> Tuple[int, int]:
    if len(data) < 10 or data[:6] not in {b"GIF87a", b"GIF89a"}:
        raise ValueError("Invalid GIF image")
    return struct.unpack("<HH", data[6:10])


def _get_jpeg_dimensions(data: bytes) -> Tuple[int, int]:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        raise ValueError("Invalid JPEG image")

    sof_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    index = 2
    while index < len(data):
        while index < len(data) and data[index] != 0xFF:
            index += 1
        while index < len(data) and data[index] == 0xFF:
            index += 1
        if index >= len(data):
            break

        marker = data[index]
        index += 1

        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if index + 1 >= len(data):
            break

        segment_length = struct.unpack(">H", data[index:index + 2])[0]
        if segment_length < 2 or index + segment_length > len(data):
            break
        if marker in sof_markers:
            if index + 7 > len(data):
                break
            height, width = struct.unpack(">HH", data[index + 3:index + 7])
            return width, height
        index += segment_length

    raise ValueError("Could not read JPEG dimensions")


def _get_webp_dimensions(data: bytes) -> Tuple[int, int]:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError("Invalid WebP image")

    chunk_type = data[12:16]
    if chunk_type == b"VP8X":
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        return width, height
    if chunk_type == b"VP8 ":
        if len(data) < 30 or data[23:26] != b"\x9d\x01\x2a":
            raise ValueError("Invalid VP8 WebP image")
        width = struct.unpack("<H", data[26:28])[0] & 0x3FFF
        height = struct.unpack("<H", data[28:30])[0] & 0x3FFF
        return width, height
    if chunk_type == b"VP8L":
        if len(data) < 25 or data[20] != 0x2F:
            raise ValueError("Invalid VP8L WebP image")
        b0, b1, b2, b3 = data[21:25]
        width = 1 + (((b1 & 0x3F) << 8) | b0)
        height = 1 + (((b3 & 0x0F) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6))
        return width, height

    raise ValueError("Unsupported WebP image encoding")


def _get_svg_dimensions(image_path: Path) -> Tuple[int, int]:
    try:
        root = ET.fromstring(image_path.read_text(encoding="utf-8"))
    except ET.ParseError as exc:
        raise ValueError("Invalid SVG image") from exc

    width = _parse_svg_length(root.get("width"))
    height = _parse_svg_length(root.get("height"))
    if width and height:
        return width, height

    view_box = root.get("viewBox")
    if view_box:
        parts = view_box.replace(",", " ").split()
        if len(parts) == 4:
            width = max(int(round(float(parts[2]))), 1)
            height = max(int(round(float(parts[3]))), 1)
            return width, height

    raise ValueError(
        f"SVG image '{image_path.name}' must define width/height or a viewBox"
    )


def _parse_svg_length(raw_value: str) -> int:
    if not raw_value:
        return 0

    match = SVG_LENGTH_PATTERN.match(raw_value)
    if not match:
        return 0

    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit == "%":
        return 0
    factor = SVG_UNIT_TO_PX.get(unit)
    if factor is None:
        return 0

    return max(int(round(value * factor)), 1)
