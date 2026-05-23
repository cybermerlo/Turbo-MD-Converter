"""Archive extraction: ZIP, 7Z, TAR."""

import tarfile as tarfile_mod
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

from pipeline.constants import ARCHIVE_EXTENSIONS


def extract_archive_text(
    file_path: Path,
    process_member: Callable[[Path], str],
    emit_log: Callable[[str, str], None],
    cancel_event=None,
) -> str:
    """Extract and process all files inside a ZIP, 7Z or TAR archive."""
    suffix = file_path.suffix.lower()
    name_lower = file_path.name.lower()
    members: list[tuple[str, bytes]] = []

    try:
        if suffix == ".zip":
            with zipfile.ZipFile(file_path) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    members.append((info.filename, zf.read(info.filename)))

        elif suffix == ".7z":
            import py7zr

            with py7zr.SevenZipFile(file_path, mode="r") as zf:
                for name, bio in zf.read().items():
                    members.append((name, bio.read()))

        elif suffix in (".tar", ".tgz") or name_lower.endswith(
            (".tar.gz", ".tar.bz2", ".tar.xz")
        ):
            with tarfile_mod.open(file_path) as tf:
                for member in tf.getmembers():
                    if not member.isfile():
                        continue
                    fobj = tf.extractfile(member)
                    if fobj:
                        members.append((member.name, fobj.read()))

    except Exception as e:
        raise RuntimeError(
            f"Impossibile aprire l'archivio '{file_path.name}': {e}"
        ) from e

    if not members:
        emit_log(
            f"Archivio '{file_path.name}' vuoto o senza file supportati",
            "WARNING",
        )
        return ""

    members = [
        (name, data)
        for name, data in members
        if not Path(name).name.startswith((".", "__", "~"))
    ]

    emit_log(
        f"Archivio '{file_path.name}': {len(members)} file da elaborare",
        "INFO",
    )

    parts: list[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for i, (name, data) in enumerate(members, 1):
            if cancel_event and cancel_event.is_set():
                break
            base = Path(name).name
            dest = tmp / base
            if dest.exists():
                dest = tmp / f"{i}_{base}"
            dest.write_bytes(data)
            emit_log(
                f"Elaborazione {i}/{len(members)} da archivio: {name}",
                "INFO",
            )
            text = process_member(dest)
            if text:
                parts.append(f"\n\n--- FILE {i}: {name} ---\n\n")
                parts.append(text)

    return "\n".join(parts)


def is_archive_path(path: Path) -> bool:
    suffix = path.suffix.lower()
    name_lower = path.name.lower()
    return suffix in ARCHIVE_EXTENSIONS or name_lower.endswith(
        (".tar.gz", ".tar.bz2", ".tar.xz")
    )
