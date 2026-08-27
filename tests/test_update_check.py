from pncp_desktop.update_check import UpdateInfo, _version_tuple


def test_version_tuple_accepts_release_tag() -> None:
    assert _version_tuple("v1.12.3") == (1, 12, 3)


def test_update_info_detects_only_newer_release() -> None:
    newer = UpdateInfo("0.2.0", "0.3.0", "https://example.test")
    same = UpdateInfo("0.2.0", "v0.2.0", "https://example.test")
    assert newer.available is True
    assert same.available is False
