"""Google Drive sync for .txt tag files.

First run: opens browser for OAuth. Requires ~/.promptgen/client_secrets.json
downloaded from a Google Cloud project with the Drive API enabled.
Subsequent runs: uses cached refresh token, only downloads changed files
(md5 checksum compare).
"""
import re
from pathlib import Path

from .paths import CLIENT_SECRETS_PATH, TOKEN_PATH, lora_cache_dir


_ID_RE = re.compile(r"[-\w]{25,}")


def extract_folder_id(value: str) -> str | None:
    """Return folder ID if value looks like a Drive ID or share URL, else None."""
    value = value.strip()
    if "drive.google.com" in value or value.startswith("https://"):
        m = re.search(r"/folders/([-\w]+)", value)
        if m:
            return m.group(1)
        m = re.search(r"[?&]id=([-\w]+)", value)
        if m:
            return m.group(1)
    if "/" not in value and _ID_RE.fullmatch(value):
        return value
    return None


def _drive():
    # Lazy import — pydrive2 not needed for local-only usage.
    from pydrive2.auth import GoogleAuth
    from pydrive2.drive import GoogleDrive

    if not CLIENT_SECRETS_PATH.exists():
        raise FileNotFoundError(
            f"Missing {CLIENT_SECRETS_PATH}. Create a Google Cloud project, "
            "enable the Drive API, create OAuth Desktop credentials, and save "
            "the client_secrets.json there."
        )

    gauth = GoogleAuth()
    gauth.settings.update({
        "client_config_backend": "file",
        "client_config_file": str(CLIENT_SECRETS_PATH),
        "save_credentials": True,
        "save_credentials_backend": "file",
        "save_credentials_file": str(TOKEN_PATH),
        "get_refresh_token": True,
        "oauth_scope": ["https://www.googleapis.com/auth/drive.readonly"],
    })
    if TOKEN_PATH.exists():
        gauth.LoadCredentialsFile(str(TOKEN_PATH))
    if gauth.credentials is None:
        gauth.LocalWebserverAuth()
    elif gauth.access_token_expired:
        gauth.Refresh()
    else:
        gauth.Authorize()
    gauth.SaveCredentialsFile(str(TOKEN_PATH))
    return GoogleDrive(gauth)


def _resolve_folder(drive, path: str) -> str:
    """Resolve a slash-separated Drive path to a folder ID (from My Drive root)."""
    parent = "root"
    for part in [p for p in path.split("/") if p]:
        q = (
            f"'{parent}' in parents and title = '{part}' "
            "and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        )
        matches = drive.ListFile({"q": q}).GetList()
        if not matches:
            raise FileNotFoundError(f"Drive folder not found: {path} (missing '{part}')")
        parent = matches[0]["id"]
    return parent


def list_folders(parent_id: str = "root") -> list[dict]:
    """Return [{id, title}] for subfolders of parent_id. Use 'root' for My Drive root."""
    drive = _drive()
    q = (
        f"'{parent_id}' in parents and trashed = false "
        "and mimeType = 'application/vnd.google-apps.folder'"
    )
    items = drive.ListFile({"q": q}).GetList()
    return sorted(
        [{"id": f["id"], "title": f["title"]} for f in items],
        key=lambda d: d["title"].lower(),
    )


def sync(lora: str, drive_folder: str, progress=None) -> tuple[int, int]:
    """Sync .txt files from Drive folder to local cache. Returns (downloaded, skipped).

    `drive_folder` may be a slash-path from My Drive root, a raw folder ID,
    or a full Drive share URL.
    `progress`, if given, called as progress(current, total, title).
    """
    drive = _drive()

    folder_id = extract_folder_id(drive_folder)
    if folder_id is None:
        folder_id = _resolve_folder(drive, drive_folder)

    q = f"'{folder_id}' in parents and trashed = false and title contains '.txt'"
    remote = [f for f in drive.ListFile({"q": q}).GetList() if f["title"].endswith(".txt")]
    total = len(remote)

    cache = lora_cache_dir(lora)
    downloaded = skipped = 0
    import hashlib
    for i, f in enumerate(remote, 1):
        title = f["title"]
        local = cache / title
        remote_md5 = f.get("md5Checksum")
        if local.exists() and remote_md5:
            local_md5 = hashlib.md5(local.read_bytes()).hexdigest()
            if local_md5 == remote_md5:
                skipped += 1
                if progress:
                    progress(i, total, f"skip {title}")
                continue
        f.GetContentFile(str(local))
        downloaded += 1
        if progress:
            progress(i, total, f"get  {title}")
    return downloaded, skipped


def local_dataset_from_cache(lora: str) -> Path:
    return lora_cache_dir(lora)
