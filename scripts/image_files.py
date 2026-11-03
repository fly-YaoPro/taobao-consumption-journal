#!/usr/bin/env python3
"""Local raster container checks; no network or credentials. Full decoding still needs browser QA."""
import hashlib
import struct
import zlib


def image_info(path):
    """Check raster container structure, not semantic provenance or full decoding."""
    data = bytes(path) if isinstance(path, (bytes, bytearray)) else path.read_bytes()
    width = height = 0
    fmt = ""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        offset = 8
        ended = pixels = header = False
        while offset + 12 <= len(data):
            size = int.from_bytes(data[offset:offset + 4], "big")
            tag = data[offset + 4:offset + 8]
            end = offset + 12 + size
            if end > len(data):
                raise ValueError("truncated PNG chunk")
            body = data[offset + 8:offset + 8 + size]
            crc = int.from_bytes(data[end - 4:end], "big")
            if zlib.crc32(tag + body) & 0xffffffff != crc:
                raise ValueError("PNG checksum mismatch")
            if tag == b"IHDR":
                if header or offset != 8 or len(body) != 13:
                    raise ValueError("invalid PNG header")
                width, height = struct.unpack(">II", body[:8])
                header = True
            pixels |= tag == b"IDAT" and bool(body)
            if tag == b"IEND":
                ended = size == 0 and end == len(data)
                break
            offset = end
        if not (header and pixels and ended):
            raise ValueError("incomplete PNG container")
        fmt = "png"
    elif data.startswith(b"\xff\xd8"):
        if not data.endswith(b"\xff\xd9"):
            raise ValueError("truncated JPEG")
        offset = 2
        while offset + 4 <= len(data):
            if data[offset] != 0xff:
                break
            while offset < len(data) and data[offset] == 0xff:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]
            offset += 1
            if marker in (0xd9, 0xda):
                break
            if marker in (0x01, *range(0xd0, 0xd9)):
                continue
            size = int.from_bytes(data[offset:offset + 2], "big")
            if size < 2 or offset + size > len(data):
                raise ValueError("invalid JPEG segment")
            if marker in (0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf):
                if size < 8:
                    raise ValueError("invalid JPEG frame")
                height, width = struct.unpack(">HH", data[offset + 3:offset + 7])
            offset += size
        fmt = "jpeg"
    elif data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 14:
        if data[-1:] != b";" or b"," not in data[13:]:
            raise ValueError("truncated GIF")
        width, height = struct.unpack("<HH", data[6:10])
        fmt = "gif"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
        if int.from_bytes(data[4:8], "little") + 8 != len(data):
            raise ValueError("truncated WebP")
        offset = 12
        while offset + 8 <= len(data):
            tag = data[offset:offset + 4]
            size = int.from_bytes(data[offset + 4:offset + 8], "little")
            body = data[offset + 8:offset + 8 + size]
            if len(body) != size:
                raise ValueError("truncated WebP chunk")
            if tag == b"VP8X" and len(body) >= 10:
                width = int.from_bytes(body[4:7], "little") + 1
                height = int.from_bytes(body[7:10], "little") + 1
            elif tag == b"VP8 " and len(body) >= 10 and body[3:6] == b"\x9d\x01\x2a":
                width = int.from_bytes(body[6:8], "little") & 0x3fff
                height = int.from_bytes(body[8:10], "little") & 0x3fff
            elif tag == b"VP8L" and len(body) >= 5 and body[0] == 0x2f:
                bits = int.from_bytes(body[1:5], "little")
                width, height = (bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1
            offset += 8 + size + (size % 2)
        if offset != len(data):
            raise ValueError("invalid WebP chunks")
        fmt = "webp"
    else:
        raise ValueError("not a supported raster image (HTML, empty response or unknown format)")
    if width <= 1 or height <= 1:
        raise ValueError("missing dimensions or placeholder pixel")
    return {"format": fmt, "width": width, "height": height, "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}
