#!/usr/bin/env python3
"""Small GitHub API client for immutable release records and run-scoped artifacts."""

from __future__ import annotations

import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise ValueError("refusing a non-HTTPS GitHub download redirect")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if urllib.parse.urlsplit(req.full_url).hostname != urllib.parse.urlsplit(newurl).hostname:
            redirected.remove_header("Authorization")
        return redirected


class GitHub:
    def __init__(self, repository: str, token: str | None = None):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("invalid GitHub repository")
        self.repository = repository
        self.token = token if token is not None else os.environ.get("GH_TOKEN", os.environ.get("GITHUB_TOKEN", ""))
        self.opener = urllib.request.build_opener(SafeRedirect())

    def request(self, method: str, path: str, *, data: bytes | None = None,
                accept: str = "application/vnd.github+json", content_type: str = "application/json",
                missing: bool = False, limit: int = 16 * 1024 * 1024) -> bytes | None:
        url = path if path.startswith("https://") else "https://api.github.com" + path
        if urllib.parse.urlsplit(url).hostname not in {"api.github.com", "uploads.github.com"}:
            raise ValueError("untrusted GitHub API URL")
        headers = {"Accept": accept, "Content-Type": content_type, "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "dev-tool-images"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, data=data, method=method, headers=headers)
                with self.opener.open(req, timeout=60) as response:
                    raw = response.read(limit + 1)
                if len(raw) > limit:
                    raise ValueError("oversized GitHub response")
                return raw
            except urllib.error.HTTPError as error:
                if error.code == 404 and missing:
                    return None
                transient = error.code in {429, 500, 502, 503, 504} or (
                    error.code == 403 and (error.headers.get("X-RateLimit-Remaining") == "0" or error.headers.get("Retry-After")))
                if not transient or attempt == 3:
                    raise RuntimeError(f"GitHub {method} request failed (HTTP {error.code})") from None
            except (urllib.error.URLError, TimeoutError):
                if attempt == 3:
                    raise RuntimeError("GitHub request failed after 4 attempts") from None
            time.sleep(5 * 2 ** attempt + random.uniform(0, 2))
        raise RuntimeError("GitHub request exhausted its retry budget")

    def json(self, method: str, path: str, *, value=None, missing: bool = False):
        raw = self.request(method, path, data=json.dumps(value).encode() if value is not None else None, missing=missing)
        return json.loads(raw) if raw is not None else None

    @property
    def prefix(self) -> str:
        return f"/repos/{self.repository}"

    def pages(self, path: str):
        separator = "&" if "?" in path else "?"
        for page in range(1, 101):
            items = self.json("GET", f"{path}{separator}per_page=100&page={page}")
            yield from items
            if len(items) < 100:
                return
        raise RuntimeError("GitHub listing exceeded 100 pages")

    def release(self, tag: str) -> dict | None:
        return self.json("GET", f"{self.prefix}/releases/tags/{urllib.parse.quote(tag, safe='')}", missing=True)

    def release_record(self, release: dict) -> dict | None:
        assets = [asset for asset in release.get("assets", []) if asset["name"] == "release.json"]
        if not assets:
            return None
        if len(assets) != 1 or assets[0]["size"] > 65536:
            raise ValueError("invalid release record asset")
        raw = self.request("GET", f"{self.prefix}/releases/assets/{int(assets[0]['id'])}",
                           accept="application/octet-stream", limit=65536)
        return json.loads(raw)

    def save_record(self, record: dict) -> dict:
        release = self.release(record["release_tag"])
        if release is None:
            release = self.json("POST", f"{self.prefix}/releases", value={
                "tag_name": record["release_tag"], "target_commitish": record["revision"],
                "name": record["release_tag"], "draft": True,
                "body": "Verified tool image candidate. GHCR publication and ACR delivery are tracked by their workflow runs.",
            })
        previous = self.release_record(release)
        if previous is not None:
            if previous != record:
                raise ValueError("release record is immutable; refusing to replace it")
            return release
        path = f"https://uploads.github.com{self.prefix}/releases/{int(release['id'])}/assets?name=release.json"
        self.request("POST", path, data=(json.dumps(record, indent=2) + "\n").encode())
        return release

    def complete_release(self, release: dict) -> None:
        if release.get("draft"):
            self.json("PATCH", f"{self.prefix}/releases/{int(release['id'])}", value={"draft": False})

    def tag_revision(self, tag: str) -> str:
        reference = self.json("GET", f"{self.prefix}/git/ref/tags/{urllib.parse.quote(tag, safe='')}")
        target = reference["object"]
        for _ in range(5):
            if target["type"] == "commit":
                return target["sha"]
            if target["type"] != "tag":
                break
            target = self.json("GET", f"{self.prefix}/git/tags/{target['sha']}")["object"]
        raise ValueError("release tag does not resolve to a commit")

    def require_mainline(self, revision: str) -> None:
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("invalid source revision")
        comparison = self.json("GET", f"{self.prefix}/compare/master...{revision}")
        if comparison["status"] not in {"identical", "behind"}:
            raise ValueError("release source is not contained in master")

    def package_exists(self, image: str) -> bool:
        owner, repo = self.repository.split("/")
        repository = self.json("GET", self.prefix)
        prefix = "orgs" if repository["owner"]["type"] == "Organization" else "users"
        package = urllib.parse.quote(f"{repo}/{image}", safe="")
        return self.json("GET", f"/{prefix}/{owner}/packages/container/{package}", missing=True) is not None
