import json
import logging

import pytest

from app.core.logging import (
    ContextFilter,
    JsonFormatter,
    TextFormatter,
    bind_context,
    get_context,
    log_context,
    reset_context,
)


def make_record(msg="hello %s", args=("world",), level=logging.INFO, exc_info=None, **extra):
    record = logging.LogRecord("radar.test", level, __file__, 10, msg, args, exc_info)
    for k, v in extra.items():
        setattr(record, k, v)
    ContextFilter().filter(record)
    return record


def test_json_formatter_includes_message_context_and_extras():
    with log_context(request_id="req-1", run_id="run-9", source="devpost"):
        record = make_record(duration_ms=12.5)
    line = json.loads(JsonFormatter().format(record))

    assert line["message"] == "hello world"
    assert line["level"] == "INFO"
    assert line["logger"] == "radar.test"
    assert line["request_id"] == "req-1" and line["run_id"] == "run-9" and line["source"] == "devpost"
    assert line["duration_ms"] == 12.5
    assert line["ts"].endswith("+00:00")


def test_json_formatter_serialises_exceptions():
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        import sys
        record = make_record(msg="failed", args=(), level=logging.ERROR, exc_info=sys.exc_info())
    line = json.loads(JsonFormatter().format(record))
    assert line["exc_type"] == "RuntimeError"
    assert "boom" in line["exc"]


def test_json_lines_are_single_line():
    record = make_record(msg="multi\nline", args=())
    assert "\n" not in JsonFormatter().format(record)


def test_text_formatter_appends_context():
    with log_context(run_id="run-1"):
        record = make_record()
    assert "run_id=run-1" in TextFormatter().format(record)


def test_context_nests_and_resets():
    with log_context(request_id="outer"):
        with log_context(run_id="r1"):
            assert get_context() == {"request_id": "outer", "run_id": "r1"}
        assert get_context() == {"request_id": "outer"}
    assert get_context() == {}


def test_bind_and_reset_token():
    token = bind_context(task_id="t-1")
    assert get_context()["task_id"] == "t-1"
    reset_context(token)
    assert "task_id" not in get_context()


def test_unknown_context_keys_are_rejected():
    with pytest.raises(ValueError):
        bind_context(password="nope")
