"""Google Drive sync for .txt tag files.

First run: opens browser for OAuth. Requires ~/.promptgen/client_secrets.json
downloaded from a Google Cloud project with the Drive API enabled.
Subsequent runs: uses cached refresh token, only downloads changed files
(md5 checksum compare).
"""
from pathlib import Path

from .paths import CLIENT_SECRETS_PATH, TOKEN_PATH, lora_cache_dir


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


def sync(lora: str, drive_folder: str) -> tuple[int, int]:
    """Sync .txt files from Drive folder to local cache. Returns (downloaded, skipped)."""
    drive = _drive()
    folder_id = _resolve_folder(drive, drive_folder)

    q = f"'{folder_id}' in parents and trashed = false and title contains '.txt'"
    remote = drive.ListFile({"q": q}).GetList()

    cache = lora_cache_dir(lora)
    downloaded = skipped = 0
    for f in remote:
        title = f["title"]
        if not title.endswith(".txt"):
            continue
        local = cache / title
        remote_md5 = f.get("md5Checksum")
        if local.exists() and remote_md5:
            import hashlib
            local_md5 = hashlib.md5(local.read_bytes()).hexdigest()
            if local_md5 == remote_md5:
                skipped += 1
                continue
        f.GetContentFile(str(local))
        downloaded += 1
    return downloaded, skipped


def local_dataset_from_cache(lora: str) -> Path:
    return lora_cache_dir(lora)
