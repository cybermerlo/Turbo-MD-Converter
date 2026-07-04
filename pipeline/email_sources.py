"""Email source readers: EML and MSG with shared attachment handling."""

import email
import email.policy
import tempfile
from collections.abc import Callable
from pathlib import Path

from pipeline.models import EmailAttachmentDocument


def _html_part_to_text(html: str) -> str:
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return html
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator="\n", strip=True)


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
            # Due allegati con lo stesso nome (es. più "image001.png" inline)
            # non devono sovrascriversi: disambigua col prefisso dell'indice.
            if att_path.exists():
                att_path = Path(tmpdir) / f"{i}_{safe_name}"
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


# PEC (Posta Elettronica Certificata): la busta di trasporto certificata avvolge il
# messaggio VERO in un allegato message/rfc822 chiamato `postacert.eml`, accanto ai
# metadati `daticert.xml` e alla firma `smime.p7s`. Il messaggio reale (mittente,
# oggetto, allegati) sta in postacert.eml: e' quello che va estratto.
_PEC_INNER_NAME = "postacert.eml"
_PEC_NOISE_NAMES = {"daticert.xml", "smime.p7s"}


def _find_pec_inner(msg):
    """Se `msg` e' una PEC, ritorna il messaggio ORIGINALE nidificato (l'allegato
    `postacert.eml`), altrimenti None. Riconosciuto per nome file, quindi non tocca
    le email normali che inoltrano un altro messaggio (message/rfc822) come allegato."""
    for part in msg.walk():
        if (part.get_filename() or "").lower() != _PEC_INNER_NAME:
            continue
        inner = None
        try:
            inner = part.get_content()
        except Exception:
            inner = None
        if not hasattr(inner, "walk"):
            payload = part.get_payload()
            inner = payload[0] if isinstance(payload, list) and payload else None
        if hasattr(inner, "walk"):
            return inner
    return None


def _message_to_parts(
    msg,
    file_path: Path,
    process_attachment: Callable[[Path], str],
    emit_log: Callable[[str, str], None],
    cancel_event=None,
) -> tuple[str, list[EmailAttachmentDocument]]:
    """Estrae `(testo, allegati)` da un `email.message.Message`: header + corpo
    (plain/html) + allegati espliciti. Condiviso tra l'.eml top-level e il
    `postacert.eml` nidificato di una PEC. Scarta i metadati/firma della busta PEC
    (`daticert.xml`, `smime.p7s`), che non sono documenti."""
    parts: list[str] = []
    for header in ("date", "from", "to", "cc", "subject"):
        value = msg.get(header, "").strip()
        if value:
            parts.append(f"{header.capitalize()}: {value}")
    if parts:
        parts.append("")

    plain_bodies: list[str] = []
    html_bodies: list[str] = []
    for part in msg.walk():
        disposition = part.get_content_disposition()
        has_filename = bool(part.get_filename())
        if disposition == "attachment" or has_filename:
            continue
        try:
            body = part.get_content()
        except Exception:
            continue
        if not body or not str(body).strip():
            continue
        content_type = part.get_content_type()
        if content_type == "text/plain":
            plain_bodies.append(str(body))
        elif content_type == "text/html":
            html_bodies.append(_html_part_to_text(str(body)))

    bodies = plain_bodies or html_bodies
    for body in bodies:
        if body and body.strip():
            parts.append(body)

    att_list: list[tuple[str, bytes]] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        disposition = part.get_content_disposition()
        filename = part.get_filename()
        if (filename or "").lower() in _PEC_NOISE_NAMES:
            continue  # metadati/firma della busta PEC, non un documento
        is_explicit_attachment = disposition in {"attachment", "inline"} and bool(filename)
        if is_explicit_attachment:
            raw_name = filename or f"allegato_{len(att_list) + 1}"
            payload = part.get_payload(decode=True)
            if payload:
                att_list.append((raw_name, payload))

    attachment_docs = _process_attachment_list(
        file_path, att_list, process_attachment, emit_log, cancel_event,
    )
    return "\n".join(parts), attachment_docs


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
    inner = _find_pec_inner(msg)
    if inner is not None:
        emit_log(
            f"PEC rilevata in {file_path.name}: estraggo il messaggio originale "
            "(postacert.eml), scarto la busta di trasporto.", "INFO",
        )
        body, atts = _message_to_parts(
            inner, file_path, process_attachment, emit_log, cancel_event)
        note = "PEC - messaggio originale (busta di trasporto certificata rimossa)"
        return (f"{note}\n\n{body}" if body else note), atts
    return _message_to_parts(
        msg, file_path, process_attachment, emit_log, cancel_event)


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
