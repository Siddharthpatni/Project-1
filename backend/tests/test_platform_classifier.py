"""Tests for the platform classifier ported from the dev branch.

The dev-branch classifier is the basis of the new DETERMINISTIC strategy.
These tests pin its behaviour so refactors can't silently regress the
~89% success rate the original achieved across 100+ domains.
"""
from app.phase3_integration import platform_classifier as pc


# ---------- URL classification ----------

def test_classify_dtvp_satellite_url():
    url = "https://vergabe.beispiel.de/Satellite/public/company/project/CXXX123/de/documents"
    assert pc.classify_url(url) == "dtvp"


def test_classify_dtvp_vmpsatellite_url():
    url = "https://vergabe.nrw.de/VMPSatellite/public/company/project/CXP9YL2YT0F/de/overview"
    assert pc.classify_url(url) == "dtvp"


def test_classify_dtvp_notice_form():
    url = "https://vergabe.beispiel.de/Satellite/notice/CXP9YL2YT0F"
    assert pc.classify_url(url) == "dtvp"


def test_classify_netserver_url():
    url = "https://vergabe.autobahn.de/NetServer/TenderingProcedureDetails?function=_Details&TenderOID=54321"
    assert pc.classify_url(url) == "netserver"


def test_classify_evergabe_de_url():
    assert pc.classify_url("https://www.evergabe.de/unterlagen/3378700") == "evergabe_de"


def test_classify_evergabe_online_url():
    assert pc.classify_url("https://www.evergabe-online.de/tenderdetails.html?id=858550") == "evergabe_online"


def test_classify_subreport_url():
    assert pc.classify_url("https://www.subreport.de/E12345") == "subreport"


def test_classify_unknown_url():
    assert pc.classify_url("https://random.example.com/something") == "unknown"


# ---------- HTML fallback classification ----------

def test_classify_html_finds_dtvp():
    """When the URL doesn't reveal the platform, HTML markers can."""
    url = "https://obscure.example.com/page"
    html = "<html><body>powered by VMPSatellite</body></html>"
    assert pc.classify_html(url, html) == "dtvp"


def test_classify_html_falls_back_to_url():
    """classify_html should prefer URL classification when it's confident."""
    url = "https://vergabe.beispiel.de/Satellite/public/company/project/CXP1/de/documents"
    assert pc.classify_html(url, "") == "dtvp"


def test_classify_html_returns_unknown_when_nothing_matches():
    assert pc.classify_html("https://x.example.com", "<html></html>") == "unknown"


# ---------- DTVP URL builders ----------

def test_extract_project_id_from_project_path():
    pid = pc.extract_project_id(
        "https://vergabe.example.com/Satellite/public/company/project/CXPABC123/de/documents"
    )
    assert pid == "CXPABC123"


def test_extract_project_id_from_notice_path():
    pid = pc.extract_project_id("https://vergabe.example.com/Satellite/notice/CXPABC123")
    assert pid == "CXPABC123"


def test_extract_project_id_none_for_unrelated():
    assert pc.extract_project_id("https://example.com/foo/bar") is None


def test_build_dtvp_zip_url_satellite():
    url = "https://vergabe.beispiel.de/Satellite/public/company/project/CXP1/de/documents"
    expected = (
        "https://vergabe.beispiel.de/Satellite/public/company/project/CXP1"
        "/de/documents/archive/Vergabeunterlagen_CXP1.zip"
    )
    assert pc.build_dtvp_zip_url(url) == expected


def test_build_dtvp_zip_url_vmpsatellite():
    url = "https://vergabe.nrw.de/VMPSatellite/notice/CXP9"
    expected = (
        "https://vergabe.nrw.de/VMPSatellite/public/company/project/CXP9"
        "/de/documents/archive/Vergabeunterlagen_CXP9.zip"
    )
    assert pc.build_dtvp_zip_url(url) == expected


def test_build_dtvp_zip_url_returns_none_without_project_id():
    # No /project/ or /notice/ segment at all → extract_project_id returns None.
    assert pc.build_dtvp_zip_url("https://example.com/some/other/path") is None


# ---------- Deterministic platform predicate ----------

def test_is_deterministic_dtvp_is_true():
    assert pc.is_deterministic("dtvp") is True


def test_is_deterministic_netserver_is_false():
    """NetServer needs page-state extraction → not deterministic from URL alone."""
    assert pc.is_deterministic("netserver") is False


def test_is_deterministic_unknown_is_false():
    assert pc.is_deterministic("unknown") is False


def test_build_download_url_dispatches_to_dtvp():
    url = "https://vergabe.x.de/Satellite/notice/CXPZ"
    out = pc.build_download_url("dtvp", url)
    assert out is not None
    assert out.endswith("Vergabeunterlagen_CXPZ.zip")


def test_build_download_url_for_non_deterministic_returns_none():
    out = pc.build_download_url("netserver", "https://x.de/NetServer/foo")
    assert out is None
