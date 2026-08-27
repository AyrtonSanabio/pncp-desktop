from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

RELEASES_API_URL = "https://api.github.com/repos/AyrtonSanabio/pncp-desktop/releases/latest"


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    release_url: str

    @property
    def available(self) -> bool:
        return _version_tuple(self.latest_version) > _version_tuple(self.current_version)


def _version_tuple(value: str) -> tuple[int, ...]:
    clean = value.strip().lower().removeprefix("v").split("-", 1)[0]
    try:
        return tuple(int(part) for part in clean.split("."))
    except ValueError:
        return (0,)


def check_latest_release(current_version: str, timeout: float = 3.0) -> UpdateInfo:
    request = urllib.request.Request(
        RELEASES_API_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "pncp-desktop"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        payload = json.load(response)
    return UpdateInfo(
        current_version=current_version,
        latest_version=str(payload["tag_name"]).removeprefix("v"),
        release_url=str(payload["html_url"]),
    )
