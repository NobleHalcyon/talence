from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import httpx

from robot.app.catalog.audit import now_iso


def _http_get_bytes(url: str, *, timeout: float = 60.0) -> bytes:
    resp = httpx.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.content


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def cache_print_face_image(
    con: sqlite3.Connection,
    *,
    print_id: str,
    face_key: str,
    source_url: str,
    data_root: Path | None = None,
    image_bytes: bytes | None = None,
) -> dict[str, str]:
    payload = image_bytes if image_bytes is not None else _http_get_bytes(source_url)
    digest = hashlib.sha256(payload).hexdigest()

    relative_path = Path("data") / "images" / digest[0:2] / digest[2:4] / f"{digest}.jpg"
    root = data_root if data_root is not None else (_repo_root() / "data")
    absolute_path = root / "images" / digest[0:2] / digest[2:4] / f"{digest}.jpg"
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    if not absolute_path.exists():
        absolute_path.write_bytes(payload)

    ts = now_iso()
    con.execute(
        """
        INSERT INTO print_face_images (
          id, print_id, face_key, source_url, sha256, local_path, mime_type, width, height, phash, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(print_id, face_key) DO UPDATE SET
          source_url = excluded.source_url,
          sha256 = excluded.sha256,
          local_path = excluded.local_path,
          mime_type = excluded.mime_type,
          width = excluded.width,
          height = excluded.height,
          phash = NULL,
          updated_at = excluded.updated_at
        """,
        (
            f"{print_id}:{face_key}",
            print_id,
            face_key,
            source_url,
            digest,
            str(relative_path).replace("\\", "/"),
            "image/jpeg",
            None,
            None,
            None,
            ts,
            ts,
        ),
    )
    con.commit()

    return {
        "sha256": digest,
        "local_path": str(relative_path).replace("\\", "/"),
        "absolute_path": str(absolute_path),
    }
