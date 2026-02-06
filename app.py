import os
import sys
import threading
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtCore import QUrl
from api import app as flask_app

# Rendering mode:
# - default: performance-oriented (hardware acceleration)
# - set REGM_SAFE_RENDER=1 for compatibility mode on glitchy GPUs
if os.environ.get("REGM_SAFE_RENDER") == "1":
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing")
    os.environ.setdefault("QT_OPENGL", "software")
else:
    os.environ.setdefault(
        "QTWEBENGINE_CHROMIUM_FLAGS",
        "--enable-gpu-rasterization --enable-zero-copy --ignore-gpu-blocklist",
    )
    os.environ.setdefault("QT_OPENGL", "desktop")

# Start Flask backend in background
threading.Thread(target=lambda: flask_app.run(port=5000, debug=False, use_reloader=False), daemon=True).start()

# Start Qt WebEngine frontend
qt_app = QApplication(sys.argv)
view = QWebEngineView()
view.setWindowTitle("Emulation Center - PS3 Style")
view.resize(1280, 720)
view.load(QUrl("http://localhost:5000"))
view.show()

sys.exit(qt_app.exec())
