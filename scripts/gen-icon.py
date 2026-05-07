"""Generate a minimal 512x512 purple source PNG for cargo tauri icon."""
import zlib, struct, pathlib

def make_png(width: int, height: int, r: int, g: int, b: int) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        payload = tag + data
        return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw_rows = b"".join(b"\x00" + bytes([r, g, b]) * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw_rows, 9))
        + chunk(b"IEND", b"")
    )

out = pathlib.Path(__file__).parent.parent / "src-tauri" / "icons" / "app-icon.png"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(make_png(512, 512, 168, 85, 247))  # #a855f7 purple
print(f"Written: {out}")
