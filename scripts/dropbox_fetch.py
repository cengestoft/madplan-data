#!/usr/bin/env python3
"""Download the private raw-data file from Dropbox for the history import (GitHub Actions, temporary storage only).

SECURITY RULES (this repository is PUBLIC, so Actions logs are public):
  * OAuth refresh-token flow; credentials come from environment variables (GitHub secrets) only and are never printed.
  * No sharing links. The file is read with the authenticated Dropbox API (files/get_metadata + files/download).
  * Nothing from the file content is ever printed. Errors show only an HTTP status or a fixed message, never a response body.
  * The destination must be OUTSIDE the git working tree (use $RUNNER_TEMP); the file is written with mode 0600.
  * Size, JSON array shape and Dropbox content_hash are verified; on any mismatch the file is deleted and the step fails.

Environment: DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN, DROPBOX_RAW_PATH (default /latest-canonical.json: path inside the Dropbox App Folder)
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, subprocess, sys, urllib.error, urllib.parse, urllib.request
from pathlib import Path

BLOCK = 4 * 1024 * 1024  # Dropbox content_hash block size
TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
META_URL = "https://api.dropboxapi.com/2/files/get_metadata"
DOWNLOAD_URL = "https://content.dropboxapi.com/2/files/download"
DEFAULT_PATH = "/latest-canonical.json"  # Dropbox App Folder: API paths are relative to the app folder root
MIN_BYTES = 50 * 1024 * 1024  # a real latest-canonical.json is hundreds of MB; anything tiny is an empty or wrong file


class BlockHasher:
    """Dropbox content_hash: SHA-256 over the concatenated SHA-256 digests of each 4 MiB block."""

    def __init__(self):
        self.overall, self.buf, self.size = hashlib.sha256(), b"", 0

    def update(self, data: bytes):
        self.size += len(data)
        self.buf += data
        while len(self.buf) >= BLOCK:
            self.overall.update(hashlib.sha256(self.buf[:BLOCK]).digest())
            self.buf = self.buf[BLOCK:]

    def hexdigest(self) -> str:
        overall = self.overall.copy()
        if self.buf:
            overall.update(hashlib.sha256(self.buf).digest())
        return overall.hexdigest()


def content_hash_of_file(path) -> str:
    h = BlockHasher()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class DropboxError(SystemExit):
    pass


def _fail(msg: str):
    raise DropboxError(f"ERROR: {msg}")


SAFE_WORDS = {  # fixed Dropbox error vocabulary; anything else is reported as "other" (never echo free text)
    "invalid_grant", "invalid_client", "invalid_request", "unauthorized_client", "unsupported_grant_type", "invalid_access_token",
    "expired_access_token", "invalid_refresh_token", "path", "not_found", "malformed_path", "not_file", "not_folder", "restricted_content",
    "no_permission", "missing_scope", "too_many_requests", "too_many_write_operations", "rate_limit", "internal_server_error",
    "user", "team", "app", "other", "unsupported_file", "disallowed_name", "lookup_failed", "access_error", "email_not_verified"}


def safe_error_code(body: bytes) -> str:
    """Reduce a Dropbox error body to a fixed-vocabulary code such as 'path/not_found' or 'invalid_grant'. Nothing else is ever returned."""
    try:
        doc = json.loads(body.decode("utf-8", "replace"))
        raw = doc.get("error_summary") or doc.get("error") or ""
    except Exception:
        return ""
    if not isinstance(raw, str):
        return ""
    parts = [p for p in re.split(r"[/.]", raw)[:4] if p]
    return "/".join(p if p in SAFE_WORDS else "other" for p in parts)


def _request(urlopen, req, what):
    try:
        return urlopen(req, timeout=300)
    except urllib.error.HTTPError as e:
        code = ""
        try:
            code = safe_error_code(e.read(4096))
        except Exception:
            pass
        _fail(f"{what} failed with HTTP {e.code}" + (f" ({code})" if code else ""))  # never include the response body
    except Exception as e:  # network errors: only the exception class, never its text
        _fail(f"{what} failed ({type(e).__name__})")


def get_access_token(env, urlopen=urllib.request.urlopen) -> str:
    for name in ("DROPBOX_APP_KEY", "DROPBOX_APP_SECRET", "DROPBOX_REFRESH_TOKEN"):
        if not env.get(name):
            _fail(f"missing secret {name}")
    body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": env["DROPBOX_REFRESH_TOKEN"],
                                   "client_id": env["DROPBOX_APP_KEY"], "client_secret": env["DROPBOX_APP_SECRET"]}).encode()
    resp = _request(urlopen, urllib.request.Request(TOKEN_URL, data=body, method="POST"), "Dropbox token request")
    token = json.loads(resp.read().decode("utf-8")).get("access_token")
    if not token:
        _fail("Dropbox token response had no access_token")
    print(f"::add-mask::{token}")  # belt and braces: GitHub masks it if it ever appears in a log
    return token


def _api_arg(path: str) -> str:
    return json.dumps({"path": path}, ensure_ascii=True)  # header values must be ASCII (ø -> ø)


def get_metadata(token, path, urlopen=urllib.request.urlopen) -> dict:
    req = urllib.request.Request(META_URL, data=json.dumps({"path": path}).encode("utf-8"), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    meta = json.loads(_request(urlopen, req, "Dropbox metadata request").read().decode("utf-8"))
    if meta.get(".tag") != "file":
        _fail("Dropbox path is not a file")
    return meta


def outside_git_tree(dest: Path) -> bool:
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, cwd=dest.parent if dest.parent.exists() else None)
        if top.returncode != 0:
            return True
        return Path(top.stdout.strip()).resolve() not in [dest.resolve(), *dest.resolve().parents]
    except Exception:
        return True


def check_json_array(path: Path):
    """Cheap shape check without loading 350 MB: it must start with '[' and end with ']'. The importer parses the whole file."""
    with open(path, "rb") as fh:
        head = fh.read(4096).lstrip()
        fh.seek(max(0, path.stat().st_size - 4096))
        tail = fh.read().rstrip()
    if not head.startswith(b"[") or not tail.endswith(b"]"):
        _fail("downloaded file is not a JSON array")


def fetch(env, dest: Path, expected_size=None, min_bytes=MIN_BYTES, urlopen=urllib.request.urlopen) -> dict:
    dest = Path(dest)
    if not outside_git_tree(dest):
        _fail("destination is inside the git working tree; use a temporary directory")
    path = env.get("DROPBOX_RAW_PATH") or DEFAULT_PATH
    print(f"Dropbox-sti: {path}")  # a path, not a secret; shown so a wrong DROPBOX_RAW_PATH variable is visible in the log
    token = get_access_token(env, urlopen)
    meta = get_metadata(token, path, urlopen)
    size, remote_hash = int(meta.get("size", -1)), meta.get("content_hash")
    if size < min_bytes:
        _fail(f"remote file is too small ({size} bytes)")
    if expected_size is not None and size != int(expected_size):
        _fail(f"remote size {size} differs from expected {expected_size}")
    if not remote_hash:
        _fail("Dropbox returned no content_hash")
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(DOWNLOAD_URL, method="POST", headers={"Authorization": f"Bearer {token}", "Dropbox-API-Arg": _api_arg(path)})
    resp = _request(urlopen, req, "Dropbox download")
    hasher = BlockHasher()
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            for chunk in iter(lambda: resp.read(1024 * 1024), b""):
                hasher.update(chunk)
                out.write(chunk)
        if hasher.size != size:
            _fail(f"downloaded {hasher.size} bytes, expected {size}")
        if hasher.hexdigest() != remote_hash:
            _fail("content_hash mismatch (file changed or corrupt)")
        check_json_array(dest)
    except BaseException:
        dest.unlink(missing_ok=True)  # never leave a partial or unverified raw file behind
        raise
    return {"bytes": size, "content_hash_prefix": remote_hash[:8], "verified": True}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", required=True, help="temporary path OUTSIDE the repository, e.g. $RUNNER_TEMP/raw/latest-canonical.json")
    ap.add_argument("--expected-size", type=int, help="fail if the remote file has a different size")
    a = ap.parse_args()
    print(json.dumps(fetch(os.environ, Path(a.dest), a.expected_size)))


if __name__ == "__main__":
    main()
