"""
ICCSFlux Demo Launcher

Serves the standard dashboard build with demo mode injected at runtime.
No MQTT broker, no DAQ service, no backend required.

Injects <script>window.ICCSFLUX_DEMO_MODE=true;</script> into every
index.html response so the Vue app suppresses the connection overlay
and auto-logs in as admin — regardless of which build is in www/.
"""

import sys
import time
import threading
import webbrowser
import http.server
import socket
import tkinter as tk
import tkinter.font as tkfont
import tkinter.messagebox as mb
from pathlib import Path

# Locate www/ relative to executable or script
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).parent
else:
    ROOT = Path(__file__).parent.parent

WWW_DIR = ROOT / "www"
PREFERRED_PORT = 5173

_DEMO_SCRIPT = b'<script>window.ICCSFLUX_DEMO_MODE=true;</script>'


class _DemoHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WWW_DIR), **kwargs)

    def log_message(self, fmt, *args):
        pass

    def _serve_index(self):
        """Serve index.html with the demo mode flag injected."""
        index = WWW_DIR / "index.html"
        if not index.exists():
            self.send_error(404)
            return
        content = index.read_bytes()
        # Inject before </head> so the flag is set before Vue initialises
        content = content.replace(b'</head>', _DEMO_SCRIPT + b'</head>', 1)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        # Aggressive cache busting — prevents Edge/Chrome serving a stale cached page
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        # Serve index.html (with injection) for root and any non-asset path
        # This handles Vue Router history-mode navigation
        path = self.path.split("?")[0].split("#")[0]
        if path == "/" or path == "/index.html":
            self._serve_index()
            return
        # For asset files (.js, .css, .png, etc.) use normal static serving
        # If the file doesn't exist, fall back to index.html (SPA routing)
        file_path = WWW_DIR / path.lstrip("/")
        if not file_path.exists() or file_path.is_dir():
            self._serve_index()
            return
        super().do_GET()


def _find_free_port(preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise OSError("No free port found in range")


def main():
    if not WWW_DIR.exists():
        root = tk.Tk()
        root.withdraw()
        mb.showerror(
            "ICCSFlux Demo",
            f"Dashboard files not found:\n{WWW_DIR}\n\nPlease rebuild the demo.",
        )
        return

    try:
        port = _find_free_port(PREFERRED_PORT)
        server = http.server.HTTPServer(("127.0.0.1", port), _DemoHandler)
    except Exception as e:
        root = tk.Tk()
        root.withdraw()
        mb.showerror("ICCSFlux Demo", f"Failed to start server:\n{e}")
        return

    # Add timestamp to bust any stale browser cache on first open
    url = f"http://localhost:{port}"
    open_url = f"{url}?_t={int(time.time())}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    webbrowser.open(open_url)

    # Launcher window
    root = tk.Tk()
    root.title("ICCSFlux Demo")
    root.geometry("340x165")
    root.resizable(False, False)
    try:
        root.iconbitmap(str(ROOT / "icon.ico"))
    except Exception:
        pass

    bold = tkfont.Font(family="Segoe UI", size=12, weight="bold")
    small = tkfont.Font(family="Segoe UI", size=9)
    dim = tkfont.Font(family="Segoe UI", size=9)

    tk.Label(root, text="ICCSFlux — Demo Mode", font=bold).pack(pady=(20, 4))
    tk.Label(root, text=f"Dashboard:  {url}", font=small, fg="#444").pack()
    tk.Label(root, text="No hardware or services required.", font=dim, fg="#888").pack(pady=(2, 0))

    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=14)
    tk.Button(btn_frame, text="Open Dashboard", width=16,
              command=lambda: webbrowser.open(url)).pack(side="left", padx=6)
    tk.Button(btn_frame, text="Exit", width=10,
              command=root.destroy).pack(side="left", padx=6)

    root.mainloop()
    server.shutdown()


if __name__ == "__main__":
    main()
