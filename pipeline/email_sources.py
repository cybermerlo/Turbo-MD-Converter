"""Email source readers: EML and MSG with shared attachment handling."""

import email
import email.policy
import tempfile
from collections.abc import Callable
from pathlib import Path

from pipeline.models import EmailAttachmentDocument


def join_email_and_attachments(
    body_text: str,
    attachments: list[EmailAttachmentDocument],
) -> str:
    parts = [body_text] if body_text else []
    for attachment in attachments:
        parts.append(
            f"\n\n--- ALLEGATO {attachment.index}: {attachment.filename} ---\n\n"
        )
        parts.append(attachment.text)
    return "\n".join(parts)


def _process_attachment_list(
    file_path: Path,
    att_list: list[tuple[str, bytes]],
    process_attachment: Callable[[Path], str],
    emit_log: Callable[[str, str], None],
    cancel_event=None,
) -> list[EmailAttachmentDocument]:
    if att_list:
        names = ", ".join(name for name, _ in att_list)
        emit_log(
            f"Trovati {len(att_list)} allegati in {file_path.name}: {names}",
            "INFO",
        )

    attachment_docs: list[EmailAttachmentDocument] = []
    if not att_list:
        return attachment_docs

    with tempfile.TemporaryDirectory() as tmpdir:
        for i, (name, data) in enumerate(att_list, 1):
            if cancel_event and cancel_event.is_set():
                break
            safe_name = Path(name).name or f"allegato_{i}"
            att_path = Path(tmpdir) / safe_name
            att_path.write_bytes(data)
            emit_log(
                f"Elaborazione allegato {i}/{len(att_list)}: {name}",
                "INFO",
            )
            att_text = process_attachment(att_path)
            if att_text:
                attachment_docs.append(EmailAttachmentDocument(
                    index=i,
                    filename=name,
                    text=att_text,
                ))
    return attachment_docs


def extract_eml_parts(
    file_path: Path,
    process_attachment: Callable[[Path], str],
    emit_log: Callable[[str, str], None],
    cancel_event=None,
) -> tuple[str, list[EmailAttachmentDocument]]:
    msg = email.message_from_bytes(
        file_path.read_bytes(),
        policy=email.policy.default,
    )

    parts: list[str] = []
    for header in ("date", "from", "to", "cc", "subject"):
        value = msg.get(header, "").strip()
        if value:
            parts.append(f"{header.capitalize()}: {value}")
    if parts:
        parts.append("")

    for part in msg.walk():
        if (
            part.get_content_type() == "text/plain"
            and part.get_content_disposition() != "attachment"
        ):
            try:
                body = part.get_content()
                if body and body.strip():
                    parts.append(body)
            except Exception:
                pass

    att_list: list[tuple[str, bytes]] = []
    for part in msg.walk():
        if part.get_content_disposition() == "attachment":
            raw_name = part.get_filename() or f"allegato_{len(att_list) + 1}"
            payload = part.get_payload(decode=True)
            if payload:
                att_list.append((raw_name, payload))

    attachment_docs = _process_attachment_list(
        file_path, att_list, process_attachment, emit_log, cancel_event,
    )
    return "\n".join(parts), attachment_docs


def extract_msg_parts(
    file_path: Path,
    process_attachment: Callable[[Path], str],
    emit_log: Callable[[str, str], None],
    cancel_event=None,
) -> tuple[str, list[EmailAttachmentDocument]]:
    import extract_msg

    parts: list[str] = []
    att_list: list[tuple[str, bytes]] = []

    with extract_msg.openMsg(file_path) as msg:
        header_map = [
            ("Date", msg.date),
            ("From", msg.sender),
            ("To", msg.to),
            ("Cc", msg.cc),
            ("Subject", msg.subject),
        ]
        for label, value in header_map:
            if value and str(value).strip():
                parts.append(f"{label}: {value}")
        if parts:
            parts.append("")

        body = msg.body
        if body and body.strip():
            parts.append(body)

        for attachment in msg.attachments:
            name = (
                getattr(attachment, "longFilename", None)
                or getattr(attachment, "shortFilename", None)
                or f"allegato_{len(att_list) + 1}"
            )
            data = getattr(attachment, "data", None)
            if data:
                att_list.append((name, data))

    attachment_docs = _process_attachment_list(
        file_path, att_list, process_attachment, emit_log, cancel_event,
    )
    return "\n".join(parts), attachment_docs
