"""Unit tests for Phase 2 action parsing."""
import json

from app.phase2_cua.action_space import Click, DownloadLink, Finish, from_dict


def test_parse_click_action():
    d = {"type": "click", "x": 100, "y": 200, "description": "click me"}
    a = from_dict(d)
    assert isinstance(a, Click)
    assert a.x == 100 and a.y == 200


def test_parse_download_link():
    d = {"type": "download_link", "selector": "a.tender-doc", "description": "PDF 1"}
    a = from_dict(d)
    assert isinstance(a, DownloadLink)
    assert a.selector == "a.tender-doc"


def test_parse_finish():
    a = from_dict({"type": "finish", "reason": "done"})
    assert isinstance(a, Finish)


def test_parse_roundtrip_json():
    src = {"type": "click", "x": 10, "y": 20, "description": ""}
    s = json.dumps(src)
    a = from_dict(json.loads(s))
    assert isinstance(a, Click)
