from __future__ import annotations

import time
from pathlib import Path

from flask import Flask, Response, jsonify, render_template

from capper_monitor.config import WebConfig

from .frame_buffer import FrameBuffer

_TEMPLATE_DIR = Path(__file__).parent / "templates"

_MJPEG_BOUNDARY = b"--frame"


def create_app(frame_buffer: FrameBuffer, web_config: WebConfig) -> Flask:
    app = Flask(__name__, template_folder=str(_TEMPLATE_DIR))

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/status")
    def status():
        return jsonify(frame_buffer.get_status())

    @app.route("/stream.mjpg")
    def stream():
        def generate():
            interval = 1.0 / web_config.stream_fps
            while True:
                frame = frame_buffer.get_frame()
                if frame is not None:
                    yield (
                        _MJPEG_BOUNDARY
                        + b"\r\nContent-Type: image/jpeg\r\n\r\n"
                        + frame
                        + b"\r\n"
                    )
                time.sleep(interval)

        return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")

    return app


def run_server(app: Flask, host: str, port: int) -> None:
    app.run(host=host, port=port, threaded=True, use_reloader=False, debug=False)
