from __future__ import annotations

import logging
import time
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

from capper_monitor.calibration import CalibrationError
from capper_monitor.config import WebConfig

from .frame_buffer import FrameBuffer

_TEMPLATE_DIR = Path(__file__).parent / "templates"

_MJPEG_BOUNDARY = b"--frame"


def create_app(frame_buffer: FrameBuffer, web_config: WebConfig, commands=None) -> Flask:
    """commands が None の場合は調整・シャットダウンAPIを受け付けない。
    調整は web.calibration_enabled、シャットダウンは web.shutdown_enabled で別々に有効にする。"""
    app = Flask(__name__, template_folder=str(_TEMPLATE_DIR))
    calibration_enabled = commands is not None and web_config.calibration_enabled
    shutdown_enabled = commands is not None and web_config.shutdown_enabled

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/calibrate")
    def calibrate():
        return render_template(
            "calibrate.html", calibration_enabled=calibration_enabled, shutdown_enabled=shutdown_enabled
        )

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

    def run_command(name: str, **kwargs):
        if name == "shutdown":
            if not shutdown_enabled:
                return jsonify(ok=False, error="シャットダウン機能は無効です（web.shutdown_enabled: false）"), 403
        elif not calibration_enabled:
            return jsonify(ok=False, error="調整機能は無効です（web.calibration_enabled: false）"), 403
        try:
            result = commands.submit(name, **kwargs)
        except CalibrationError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        except FutureTimeoutError:
            return jsonify(ok=False, error="カメラから応答がありません。カメラの接続を確認してください。"), 504
        return jsonify(ok=True, **result)

    @app.route("/api/roi", methods=["POST"])
    def api_roi():
        body = request.get_json(silent=True) or {}
        try:
            values = {key: float(body[key]) for key in ("x", "y", "w", "h")}
        except (KeyError, TypeError, ValueError):
            return jsonify(ok=False, error="ROIの指定が不正です"), 400
        return run_command("set_roi", **values)

    @app.route("/api/motion_roi", methods=["POST"])
    def api_motion_roi():
        body = request.get_json(silent=True) or {}
        try:
            values = {key: float(body[key]) for key in ("x", "y", "w", "h")}
        except (KeyError, TypeError, ValueError):
            return jsonify(ok=False, error="範囲の指定が不正です"), 400
        return run_command("set_motion_roi", **values)

    @app.route("/api/motion_ratio", methods=["POST"])
    def api_motion_ratio():
        body = request.get_json(silent=True) or {}
        try:
            value = float(body["value"])
        except (KeyError, TypeError, ValueError):
            return jsonify(ok=False, error="しきい値の指定が不正です"), 400
        return run_command("set_motion_ratio", value=value)

    @app.route("/api/shutdown", methods=["POST"])
    def api_shutdown():
        return run_command("shutdown")

    @app.route("/api/threshold", methods=["POST"])
    def api_threshold():
        body = request.get_json(silent=True) or {}
        try:
            value = float(body["value"])
        except (KeyError, TypeError, ValueError):
            return jsonify(ok=False, error="しきい値の指定が不正です"), 400
        return run_command("set_threshold", value=value)

    @app.route("/api/baseline", methods=["POST"])
    def api_baseline():
        return run_command("capture_baseline")

    @app.route("/api/alignment", methods=["POST"])
    def api_alignment():
        return run_command("capture_alignment")

    @app.route("/api/save", methods=["POST"])
    def api_save():
        return run_command("save")

    return app


def run_server(app: Flask, host: str, port: int) -> None:
    # スマホ画面が毎秒ポーリングするため、アクセスログをそのまま出すとSDカードへの
    # 書き込みが膨らむ。エラーのみ残す。
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    app.run(host=host, port=port, threaded=True, use_reloader=False, debug=False)
