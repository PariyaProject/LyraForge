"""Generate cross-platform LyraForge desktop icon binaries from the SVG masters.

Produces:
- ``packaging/icons/lyraforge.png`` (512x512 RGBA transparent PNG)
- ``packaging/icons/lyraforge.ico`` (multi-resolution Windows ICO: 16..256 PNG layers)
- ``packaging/icons/lyraforge.icns`` (macOS Retina iconset compiled with ``iconutil``)

Uses Python stdlib, headless Chrome DevTools Protocol (for crisp transparent SVG
rasterization without adding third-party Python dependencies), and macOS ``sips`` +
``iconutil`` when generating ``.icns`` on macOS.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ICONS_DIR = ROOT / "packaging" / "icons"
MAC_SVG = ICONS_DIR / "lyraforge.svg"
WIN_SVG = ICONS_DIR / "lyraforge-win.svg"

WIN_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICONSET_SLOTS: tuple[tuple[str, int], ...] = (
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
)


def _find_chrome() -> str:
    env_chrome = os.environ.get("CHROME_PATH")
    if env_chrome and Path(env_chrome).is_file():
        return env_chrome
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome") or "",
        shutil.which("chromium") or "",
        shutil.which("msedge") or "",
    ]
    for cand in candidates:
        if cand and Path(cand).is_file():
            return cand
    raise FileNotFoundError("Chrome/Chromium binary not found; set CHROME_PATH to rasterize SVGs")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise EOFError("unexpected EOF on CDP websocket")
        buf.extend(chunk)
    return bytes(buf)


class _SimpleCdpClient:
    """Minimal RFC 6455 stdlib websocket client for localhost Chrome DevTools Protocol."""

    def __init__(self, ws_url: str) -> None:
        parsed = urllib.parse.urlparse(ws_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path or "/"
        self._sock = socket.create_connection((host, port), timeout=15.0)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii")
        self._sock.sendall(req)
        raw = b""
        while b"\r\n\r\n" not in raw:
            raw += self._sock.recv(4096)
        accept_expected = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        if accept_expected.encode("ascii") not in raw:
            raise RuntimeError("CDP WebSocket handshake failed")
        self._next_id = 1

    def close(self) -> None:
        self._sock.close()

    def _send_text(self, text: str) -> None:
        payload = text.encode("utf-8")
        mask = os.urandom(4)
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(bytes(header) + masked)

    def _recv_frame(self) -> tuple[int, bytes]:
        b1, b2 = _recv_exact(self._sock, 2)
        opcode = b1 & 0x0F
        masked = bool(b2 & 0x80)
        length = b2 & 0x7F
        if length == 126:
            (length,) = struct.unpack("!H", _recv_exact(self._sock, 2))
        elif length == 127:
            (length,) = struct.unpack("!Q", _recv_exact(self._sock, 8))
        mask = _recv_exact(self._sock, 4) if masked else b""
        data = _recv_exact(self._sock, length)
        if masked:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        return opcode, data

    def call(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        msg_id = self._next_id
        self._next_id += 1
        self._send_text(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        while True:
            opcode, data = self._recv_frame()
            if opcode == 0x8:
                raise RuntimeError("CDP websocket closed unexpectedly")
            if opcode != 0x1:
                continue
            msg = json.loads(data.decode("utf-8"))
            if msg.get("id") == msg_id:
                if "error" in msg:
                    raise RuntimeError(f"CDP {method} error: {msg['error']}")
                result = msg.get("result")
                return result if isinstance(result, dict) else {}


def _rasterize_svgs_with_chrome(tasks: list[tuple[Path, int, Path]]) -> None:
    chrome = _find_chrome()
    port = _free_port()
    with tempfile.TemporaryDirectory(prefix="lyraforge-chrome-icon-") as user_dir:
        proc = subprocess.Popen(
            [
                chrome,
                "--headless=new",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={user_dir}",
                "--no-sandbox",
                "--disable-gpu-sandbox",
                "--hide-scrollbars",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            targets: list[dict[str, str]] = []
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(  # noqa: S310
                        f"http://127.0.0.1:{port}/json/list", timeout=1.0
                    ) as resp:
                        raw = json.loads(resp.read().decode("utf-8"))
                        pages = [t for t in raw if t.get("type") == "page"]
                        if pages:
                            targets = pages
                            break
                except OSError:
                    time.sleep(0.1)
            if not targets:
                raise RuntimeError("Headless Chrome did not expose a debuggable page target")

            client = _SimpleCdpClient(targets[0]["webSocketDebuggerUrl"])
            try:
                client.call("Page.enable")
                client.call(
                    "Emulation.setDefaultBackgroundColorOverride",
                    {"color": {"r": 0, "g": 0, "b": 0, "a": 0}},
                )
                for svg_path, size, out_png in tasks:
                    svg_markup = svg_path.read_text(encoding="utf-8")
                    sized_svg = svg_markup.replace(
                        "<svg ", f'<svg width="{size}" height="{size}" ', 1
                    )
                    html = (
                        "<!doctype html><html><body style="
                        "'margin:0;padding:0;width:100vw;height:100vh;"
                        "overflow:hidden;background:transparent'>"
                        f"{sized_svg}"
                        "</body></html>"
                    )
                    client.call(
                        "Emulation.setDeviceMetricsOverride",
                        {
                            "width": size,
                            "height": size,
                            "deviceScaleFactor": 1,
                            "mobile": False,
                        },
                    )
                    data_url = "data:text/html;charset=utf-8," + urllib.parse.quote(html)
                    client.call("Page.navigate", {"url": data_url})
                    time.sleep(0.15)
                    shot = client.call(
                        "Page.captureScreenshot",
                        {"format": "png", "fromSurface": True},
                    )
                    png_bytes = base64.b64decode(str(shot["data"]))
                    out_png.parent.mkdir(parents=True, exist_ok=True)
                    out_png.write_bytes(png_bytes)
            finally:
                client.close()
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                proc.kill()


def pack_ico_from_pngs(png_by_size: dict[int, bytes], out_ico: Path) -> None:
    """Pack transparent RGBA PNG images into a valid Windows multi-size ICO binary."""
    sizes = sorted(png_by_size)
    count = len(sizes)
    offset = 6 + 16 * count
    entries = bytearray()
    payloads = bytearray()
    for size in sizes:
        data = png_by_size[size]
        width_byte = 0 if size >= 256 else size
        height_byte = 0 if size >= 256 else size
        entries.extend(
            struct.pack(
                "<BBBBHHII",
                width_byte,
                height_byte,
                0,
                0,
                1,
                32,
                len(data),
                offset,
            )
        )
        payloads.extend(data)
        offset += len(data)
    header = struct.pack("<HHH", 0, 1, count)
    out_ico.write_bytes(header + bytes(entries) + bytes(payloads))


def build_all_icons() -> None:
    """Regenerate PNG, Windows ICO, and macOS ICNS assets from SVG masters."""
    if not MAC_SVG.is_file() or not WIN_SVG.is_file():
        raise FileNotFoundError(f"Expected SVG masters at {MAC_SVG} and {WIN_SVG}")

    with tempfile.TemporaryDirectory(prefix="lyraforge-icons-work-") as tmp:
        work = Path(tmp)
        iconset_dir = work / "lyraforge.iconset"
        iconset_dir.mkdir(parents=True, exist_ok=True)

        master_png = ICONS_DIR / "lyraforge.png"
        ico_path = ICONS_DIR / "lyraforge.ico"
        icns_path = ICONS_DIR / "lyraforge.icns"

        tasks: list[tuple[Path, int, Path]] = [(MAC_SVG, 512, master_png)]
        win_png_paths: dict[int, Path] = {}
        for size in WIN_SIZES:
            target = work / f"win_{size}.png"
            win_png_paths[size] = target
            tasks.append((WIN_SVG, size, target))

        seen_sizes: dict[int, Path] = {}
        for filename, size in ICONSET_SLOTS:
            dest = iconset_dir / filename
            if size in seen_sizes:
                # Defer copy until after rasterization
                continue
            seen_sizes[size] = dest
            tasks.append((MAC_SVG, size, dest))

        _rasterize_svgs_with_chrome(tasks)

        for filename, size in ICONSET_SLOTS:
            dest = iconset_dir / filename
            if not dest.exists():
                shutil.copy2(seen_sizes[size], dest)

        win_payloads = {size: p.read_bytes() for size, p in win_png_paths.items()}
        pack_ico_from_pngs(win_payloads, ico_path)

        if sys.platform == "darwin":
            subprocess.run(
                ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns_path)],
                check=True,
            )
        else:
            print("Skipping iconutil (.icns generation requires macOS)", file=sys.stderr)

        print(f"Generated {master_png} ({master_png.stat().st_size} B)")
        print(f"Generated {ico_path} ({ico_path.stat().st_size} B, {len(WIN_SIZES)} layers)")
        if icns_path.is_file():
            print(f"Generated {icns_path} ({icns_path.stat().st_size} B)")


if __name__ == "__main__":
    build_all_icons()
