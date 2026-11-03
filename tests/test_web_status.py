from capper_monitor.config import WebConfig
from capper_monitor.web.frame_buffer import FrameBuffer
from capper_monitor.web.server import create_app


def test_status_endpoint_returns_current_state():
    buffer = FrameBuffer()
    buffer.update_status(state="steady", reason="line_detected", timestamp=123.0)
    app = create_app(buffer, WebConfig())
    client = app.test_client()

    response = client.get("/status")
    assert response.status_code == 200
    data = response.get_json()
    assert data["state"] == "steady"
    assert data["reason"] == "line_detected"
    assert data["timestamp"] == 123.0


def test_index_page_renders():
    buffer = FrameBuffer()
    app = create_app(buffer, WebConfig())
    client = app.test_client()

    response = client.get("/")
    assert response.status_code == 200
    assert b"stream.mjpg" in response.data


def test_stream_endpoint_returns_multipart_content_type():
    buffer = FrameBuffer()
    buffer.update_frame(b"fake-jpeg-bytes")
    app = create_app(buffer, WebConfig())
    client = app.test_client()

    response = client.get("/stream.mjpg")
    assert response.status_code == 200
    assert "multipart/x-mixed-replace" in response.content_type
