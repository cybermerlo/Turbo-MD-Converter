"""Wizard modale: importa una conversazione WhatsApp dal backup locale Android.

Flusso: rileva il dispositivo (adb) → copia e decifra il backup → cerca e
seleziona una chat (con filtro date opzionale) → scarica solo i suoi media →
costruisce un pacchetto ".wachat" che viene aggiunto come singolo input.

Le operazioni lunghe (adb, decifratura, lettura DB, download media) girano su un
thread separato; i risultati rientrano nel thread Tk via `self.after`.
"""

from __future__ import annotations

import atexit
import calendar
import re
import shutil
import tempfile
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from config.settings import AppConfig
from gui import theme
from whatsapp.adb_bridge import (
    WA_SHARED_ROOT,
    AdbBridge,
    AdbError,
)
from whatsapp.backup_decryptor import decrypt_msgstore
from whatsapp.msgstore_reader import ChatSummary, MsgStoreReader
from whatsapp.package_builder import BuildStats, TranscriptEntry, build_wachat

_MAX_ROWS = 80  # limita le righe disegnate per non bloccare la UI


def _fmt_ts(ms: int, with_time: bool = True) -> str:
    try:
        dt = datetime.fromtimestamp(ms / 1000)
    except (OverflowError, OSError, ValueError):
        return "?"
    return dt.strftime("%Y-%m-%d %H:%M" if with_time else "%Y-%m-%d")


def _parse_day(text: str, end_of_day: bool = False) -> int | None:
    text = (text or "").strip()
    if not text:
        return None
    dt = datetime.strptime(text, "%Y-%m-%d")
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59, microsecond=999000)
    return int(dt.timestamp() * 1000)


def _sanitize_filename(name: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*\n\r\t]+', " ", name or "").strip()
    safe = re.sub(r"\s+", " ", safe)
    return (safe or "chat")[:80]


# Cache di sessione: evita di ripetere pull+decifratura ad ogni apertura del
# wizard. Persiste finché l'app è aperta; il pulsante «Aggiorna» forza il re-pull.
_SESSION_CACHE: dict = {"adb": None, "reader": None, "chats": None}


_SESSION_DIRNAME = "TurboMD_WhatsApp"


def _session_base() -> Path:
    """Cartella temporanea di sessione (db decifrato + pacchetti .wachat)."""
    base = Path(tempfile.gettempdir()) / _SESSION_DIRNAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def _cleanup_session_dir() -> None:
    """Alla chiusura dell'app rimuove il DB decifrato e i pacchetti temporanei."""
    try:
        shutil.rmtree(Path(tempfile.gettempdir()) / _SESSION_DIRNAME,
                      ignore_errors=True)
    except Exception:
        pass


atexit.register(_cleanup_session_dir)


class _CalendarPopup(ctk.CTkToplevel):
    """Mini calendario per scegliere una data (start/fine)."""

    _WD = ["Lu", "Ma", "Me", "Gi", "Ve", "Sa", "Do"]
    _MONTHS = ["", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
               "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]

    def __init__(self, master, initial: date, on_pick):
        super().__init__(master)
        self.title("Scegli data")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        try:
            self.configure(fg_color=theme.PAPER)
        except Exception:
            pass
        self.on_pick = on_pick
        self._year = initial.year
        self._month = initial.month
        self._build()

    def _build(self):
        for w in self.winfo_children():
            w.destroy()
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=(10, 4))
        ctk.CTkButton(
            header, text="‹", width=34, command=self._prev,
            fg_color=theme.CARD, text_color=theme.INK, hover_color=theme.PAPER_2,
            border_width=1, border_color=theme.RULE,
        ).pack(side="left")
        ctk.CTkLabel(
            header, text=f"{self._MONTHS[self._month]} {self._year}",
            font=theme.font(13, "bold"), text_color=theme.INK,
        ).pack(side="left", expand=True)
        ctk.CTkButton(
            header, text="›", width=34, command=self._next,
            fg_color=theme.CARD, text_color=theme.INK, hover_color=theme.PAPER_2,
            border_width=1, border_color=theme.RULE,
        ).pack(side="right")

        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(padx=10, pady=(0, 10))
        for i, wd in enumerate(self._WD):
            ctk.CTkLabel(grid, text=wd, width=36, font=theme.font(10, "bold"),
                         text_color=theme.INK_3).grid(row=0, column=i, padx=1, pady=1)
        weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(
            self._year, self._month)
        for r, week in enumerate(weeks, start=1):
            for c, day in enumerate(week):
                if day == 0:
                    continue
                ctk.CTkButton(
                    grid, text=str(day), width=36, height=30,
                    fg_color=theme.CARD, text_color=theme.INK,
                    hover_color=theme.AMBER_SOFT, border_width=1,
                    border_color=theme.RULE, corner_radius=4, font=theme.font(11),
                    command=lambda d=day: self._pick(d),
                ).grid(row=r, column=c, padx=1, pady=1)

    def _prev(self):
        self._month -= 1
        if self._month < 1:
            self._month, self._year = 12, self._year - 1
        self._build()

    def _next(self):
        self._month += 1
        if self._month > 12:
            self._month, self._year = 1, self._year + 1
        self._build()

    def _pick(self, day: int):
        try:
            self.on_pick(date(self._year, self._month, day))
        finally:
            self.destroy()


class WhatsAppImportWindow(ctk.CTkToplevel):
    def __init__(self, master, config: AppConfig, on_package_ready):
        super().__init__(master)
        self.title("Importa da WhatsApp")
        self.geometry("740x620")
        self.minsize(640, 540)
        self.transient(master)
        self.grab_set()
        try:
            self.configure(fg_color=theme.PAPER)
        except Exception:
            pass

        self.config = config
        self.on_package_ready = on_package_ready

        self._work_dir = Path(tempfile.mkdtemp(prefix="wachat_"))
        self._adb: AdbBridge | None = None
        self._reader: MsgStoreReader | None = None
        self._chats: list[ChatSummary] = []
        self._selected_chat: ChatSummary | None = None
        self._chat_rows: list[tuple[ChatSummary, ctk.CTkFrame]] = []
        self._date_range: tuple[int | None, int | None] = (None, None)
        self._package_path: Path | None = None
        self._busy = False
        self._cancel = threading.Event()

        # ── Scaffold: header · body · status · footer ────────────────────
        self.title_lbl = ctk.CTkLabel(
            self, text="", font=theme.font(16, "bold"), text_color=theme.INK,
            anchor="w",
        )
        self.title_lbl.pack(fill="x", padx=20, pady=(16, 2))

        self.subtitle_lbl = ctk.CTkLabel(
            self, text="", font=theme.font(11), text_color=theme.INK_3,
            anchor="w", justify="left", wraplength=680,
        )
        self.subtitle_lbl.pack(fill="x", padx=20, pady=(0, 8))

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=20, pady=(0, 6))

        self.progress = ctk.CTkProgressBar(self, mode="indeterminate")
        self.status_lbl = ctk.CTkLabel(
            self, text="", font=theme.font(11), text_color=theme.INK_2,
            anchor="w", justify="left", wraplength=680,
        )
        self.status_lbl.pack(fill="x", padx=20, pady=(0, 4))

        self.footer = ctk.CTkFrame(self, fg_color="transparent")
        self.footer.pack(fill="x", padx=20, pady=(0, 14))

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # Riusa l'estrazione già fatta in questa sessione (niente re-pull/decrypt).
        if self._cache_ready():
            self._adb = _SESSION_CACHE["adb"]
            self._reader = _SESSION_CACHE["reader"]
            self._chats = _SESSION_CACHE["chats"]
            self._goto_select()
        else:
            self._goto_device()

    @staticmethod
    def _cache_ready() -> bool:
        reader = _SESSION_CACHE.get("reader")
        if not (reader and _SESSION_CACHE.get("adb") and _SESSION_CACHE.get("chats")):
            return False
        try:
            return Path(reader.db_path).exists()
        except Exception:
            return False

    # ── Infrastruttura UI ────────────────────────────────────────────────
    def _clear(self, frame) -> None:
        for w in frame.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

    def _set_head(self, title: str, subtitle: str = "") -> None:
        self.title_lbl.configure(text=title)
        self.subtitle_lbl.configure(text=subtitle)

    def _set_status(self, text: str, level: str = "info") -> None:
        color = {
            "info": theme.INK_2, "ok": "#2a5e36",
            "warn": "#7a5418", "err": theme.ERR,
        }.get(level, theme.INK_2)
        self.status_lbl.configure(text=text, text_color=color)

    def _post_status(self, text: str, level: str = "info") -> None:
        """Aggiorna lo stato dal thread di lavoro."""
        self.after(0, lambda: self._set_status(text, level))

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self.progress.pack(fill="x", padx=20, pady=(2, 4),
                               before=self.status_lbl)
            self.progress.start()
        else:
            self.progress.stop()
            self.progress.pack_forget()

    def _run_bg(self, fn, on_success, on_error=None) -> None:
        self._set_busy(True)

        def worker():
            try:
                result = fn()
            except Exception as e:  # marshalled to UI thread
                self.after(0, lambda err=e: self._bg_finish(on_error, err, True))
                return
            self.after(0, lambda res=result: self._bg_finish(on_success, res, False))

        threading.Thread(target=worker, daemon=True).start()

    def _bg_finish(self, cb, arg, is_error: bool) -> None:
        self._set_busy(False)
        if cb is None:
            if is_error:
                self._set_status(str(arg), "err")
            return
        cb(arg)

    # ── Step 1: dispositivo ──────────────────────────────────────────────
    def _goto_device(self) -> None:
        self._clear(self.body)
        self._clear(self.footer)
        self._set_head(
            "1. Collega il telefono",
            "Importa le tue conversazioni dal backup locale di WhatsApp su Android. "
            "Tutto avviene in locale: nessun dato lascia il tuo computer.",
        )

        steps = (
            "• Abilita il «Debug USB» (Impostazioni Android → Opzioni sviluppatore).\n"
            "• Collega il telefono al PC via cavo USB e sbloccalo.\n"
            "• In WhatsApp tieni attivo il backup cifrato end-to-end e tieni a portata "
            "la chiave a 64 cifre.\n"
            "• La chiave va inserita una volta in Impostazioni → WhatsApp."
        )
        ctk.CTkLabel(
            self.body, text=steps, font=theme.font(12), text_color=theme.INK_2,
            justify="left", anchor="w", wraplength=680,
        ).pack(fill="x", pady=(4, 12), anchor="w")

        if not (self.config.whatsapp_backup_key or "").strip():
            ctk.CTkLabel(
                self.body,
                text="⚠ Chiave di backup non impostata. Aprila in "
                     "Impostazioni → WhatsApp prima di continuare.",
                font=theme.font(11, "bold"), text_color=theme.ERR,
                justify="left", anchor="w", wraplength=680,
            ).pack(fill="x", pady=(0, 8), anchor="w")

        detect_btn = theme.ghost_button(
            self.body, "Rileva dispositivo", command=self._detect_device,
            height=34, width=200,
        )
        detect_btn.pack(anchor="w", pady=(0, 4))

        self._next_btn = theme.amber_button(
            self.footer, "Avanti", width=120, command=self._goto_extract,
        )
        self._next_btn.pack(side="right")
        self._next_btn.configure(state="disabled")
        theme.ghost_button(
            self.footer, "Annulla", width=120, command=self._on_close,
        ).pack(side="right", padx=(0, 8))

    def _detect_device(self) -> None:
        if self._busy:
            return
        if not (self.config.whatsapp_backup_key or "").strip():
            self._set_status(
                "Imposta prima la chiave di backup in Impostazioni → WhatsApp.",
                "err",
            )
            return
        self._set_status("Ricerca del dispositivo…")

        def work():
            bridge = AdbBridge(self.config.adb_path)
            device = bridge.require_device()
            return bridge, device

        def ok(result):
            self._adb, device = result
            self._set_status(f"Dispositivo pronto: {device.serial}", "ok")
            self._next_btn.configure(state="normal")

        def err(e):
            self._adb = None
            self._next_btn.configure(state="disabled")
            self._set_status(str(e), "err")

        self._run_bg(work, ok, err)

    # ── Step 2: estrazione DB ────────────────────────────────────────────
    def _goto_extract(self) -> None:
        if self._adb is None:
            self._set_status("Rileva prima il dispositivo.", "err")
            return
        self._clear(self.body)
        self._clear(self.footer)
        self._set_head(
            "2. Estrazione del backup",
            "Copio e decifro il database dei messaggi. Può richiedere qualche minuto.",
        )
        theme.ghost_button(
            self.footer, "Annulla", width=120, command=self._on_close,
        ).pack(side="right")

        def work():
            db_dir = _session_base() / "db"
            db_dir.mkdir(parents=True, exist_ok=True)
            self._post_status("Copia del backup dal telefono…")
            enc = self._adb.pull_msgstore(db_dir)
            self._post_status("Decifratura del backup…")
            db_path = db_dir / "msgstore.db"
            decrypt_msgstore(enc, self.config.whatsapp_backup_key, db_path)
            self._post_status("Lettura della rubrica…")
            try:
                contacts = self._adb.read_contacts()
            except Exception:
                contacts = {}
            self._post_status("Lettura delle conversazioni…")
            reader = MsgStoreReader(db_path, contacts=contacts)
            chats = reader.list_chats()
            return reader, chats

        def ok(result):
            self._reader, self._chats = result
            if not self._chats:
                self._set_status("Nessuna conversazione trovata nel backup.", "warn")
                self._add_retry_footer(self._goto_extract)
                return
            _SESSION_CACHE["adb"] = self._adb
            _SESSION_CACHE["reader"] = self._reader
            _SESSION_CACHE["chats"] = self._chats
            self._set_status(f"{len(self._chats)} conversazioni trovate.", "ok")
            self._goto_select()

        def err(e):
            self._set_status(str(e), "err")
            self._add_retry_footer(self._goto_extract)

        self._run_bg(work, ok, err)

    def _add_retry_footer(self, retry_cmd) -> None:
        self._clear(self.footer)
        theme.amber_button(
            self.footer, "Riprova", width=120, command=retry_cmd,
        ).pack(side="right")
        theme.ghost_button(
            self.footer, "Indietro", width=120, command=self._goto_device,
        ).pack(side="right", padx=(0, 8))

    # ── Step 3: selezione chat + filtro date ─────────────────────────────
    def _goto_select(self) -> None:
        self._clear(self.body)
        self._clear(self.footer)
        self._selected_chat = None
        self._set_head(
            "3. Scegli la conversazione",
            "Cerca per nome o numero, seleziona una chat e (facoltativo) limita "
            "il periodo. Per impostazione predefinita viene importata l'intera "
            "conversazione.",
        )

        search_row = ctk.CTkFrame(self.body, fg_color="transparent")
        search_row.pack(fill="x", pady=(2, 6))
        self._search_entry = ctk.CTkEntry(
            search_row, placeholder_text="Cerca conversazione…",
        )
        self._search_entry.pack(fill="x")
        self._search_entry.bind("<KeyRelease>", lambda _e: self._refresh_list())

        self._list_frame = ctk.CTkScrollableFrame(
            self.body, fg_color=theme.PAPER, height=260,
        )
        self._list_frame.pack(fill="both", expand=True, pady=(0, 6))

        # Filtro periodo: preset rapidi + intervallo personalizzato
        ctk.CTkLabel(self.body, text="Periodo da importare:",
                     font=theme.font(11), text_color=theme.INK_3).pack(
            anchor="w", pady=(2, 2))
        self._preset_btn = ctk.CTkSegmentedButton(
            self.body,
            values=["Tutto", "Oggi", "Ieri", "7 giorni", "30 giorni"],
            command=self._apply_date_preset,
            selected_color=theme.AMBER, selected_hover_color=theme.AMBER_DEEP,
        )
        self._preset_btn.set("Oggi")
        self._preset_btn.pack(fill="x", pady=(0, 4))

        date_row = ctk.CTkFrame(self.body, fg_color="transparent")
        date_row.pack(fill="x", pady=(0, 2))
        ctk.CTkLabel(date_row, text="Personalizzato:", font=theme.font(11),
                     text_color=theme.INK_3).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(date_row, text="Da", font=theme.font(11),
                     text_color=theme.INK_3).pack(side="left")
        self._date_from = ctk.CTkEntry(date_row, width=110,
                                       placeholder_text="AAAA-MM-GG")
        self._date_from.pack(side="left", padx=(4, 2))
        theme.ghost_button(
            date_row, "📅", width=34,
            command=lambda: self._open_calendar(self._date_from),
        ).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(date_row, text="A", font=theme.font(11),
                     text_color=theme.INK_3).pack(side="left")
        self._date_to = ctk.CTkEntry(date_row, width=110, placeholder_text="oggi")
        self._date_to.pack(side="left", padx=(4, 2))
        theme.ghost_button(
            date_row, "📅", width=34,
            command=lambda: self._open_calendar(self._date_to),
        ).pack(side="left")
        # Modifica manuale → l'intervallo personalizzato ha la precedenza.
        self._date_from.bind("<KeyRelease>", self._on_date_edit)
        self._date_to.bind("<KeyRelease>", self._on_date_edit)

        self._count_lbl = ctk.CTkLabel(
            self.body,
            text="Seleziona una conversazione per vederne la dimensione.",
            font=theme.font(11, "bold"), text_color=theme.INK_2, anchor="w",
        )
        self._count_lbl.pack(anchor="w", pady=(6, 0))

        self._import_btn = theme.amber_button(
            self.footer, "Importa conversazione", width=200,
            command=self._start_build,
        )
        self._import_btn.pack(side="right")
        self._import_btn.configure(state="disabled")
        theme.ghost_button(
            self.footer, "Annulla", width=120, command=self._on_close,
        ).pack(side="right", padx=(0, 8))
        theme.ghost_button(
            self.footer, "Aggiorna", width=110, command=self._refresh_from_phone,
        ).pack(side="left")

        self._refresh_list()
        self._apply_date_preset("Oggi")  # periodo predefinito: oggi

    def _refresh_list(self) -> None:
        self._clear(self._list_frame)
        self._chat_rows = []
        query = (self._search_entry.get() or "").strip().lower()

        if query:
            matches = [
                c for c in self._chats
                if query in c.name.lower()
                or query in c.jid.lower()
                or query in (c.last_text or "").lower()
            ]
        else:
            matches = self._chats

        for chat in matches[:_MAX_ROWS]:
            self._add_chat_row(chat)

        if len(matches) > _MAX_ROWS:
            ctk.CTkLabel(
                self._list_frame,
                text=f"…e altre {len(matches) - _MAX_ROWS}. Affina la ricerca.",
                font=theme.font(10), text_color=theme.INK_3,
            ).pack(pady=6)
        elif not matches:
            ctk.CTkLabel(
                self._list_frame, text="Nessuna conversazione corrispondente.",
                font=theme.font(11), text_color=theme.INK_3,
            ).pack(pady=20)

    def _add_chat_row(self, chat: ChatSummary) -> None:
        row = ctk.CTkFrame(
            self._list_frame, fg_color=theme.CARD, corner_radius=6,
            border_width=1, border_color=theme.RULE,
        )
        row.pack(fill="x", padx=4, pady=2)

        name_lbl = ctk.CTkLabel(
            row, text=(chat.name or "")[:48], font=theme.font(12, "bold"),
            text_color=theme.INK, anchor="w", justify="left",
        )
        name_lbl.pack(fill="x", padx=10, pady=(6, 0), anchor="w")

        meta_bits = [_fmt_ts(chat.last_ts, with_time=False), f"{chat.count} msg"]
        if chat.is_group:
            meta_bits.insert(0, "gruppo")
        snippet = (chat.last_text or "").strip()
        if snippet:
            meta_bits.append(snippet[:60])
        meta_lbl = ctk.CTkLabel(
            row, text="  ·  ".join(meta_bits), font=theme.font(10),
            text_color=theme.INK_3, anchor="w", justify="left",
        )
        meta_lbl.pack(fill="x", padx=10, pady=(0, 6), anchor="w")

        for w in (row, name_lbl, meta_lbl):
            w.bind("<Button-1>", lambda _e, c=chat: self._select_chat(c))
            w.bind("<Enter>", lambda _e, fr=row: self._hover_row(fr, True))
            w.bind("<Leave>", lambda _e, fr=row: self._hover_row(fr, False))
        self._chat_rows.append((chat, row))

    def _hover_row(self, row, entering: bool) -> None:
        if self._row_of(self._selected_chat) is row:
            return
        row.configure(fg_color=theme.PAPER_2 if entering else theme.CARD)

    def _row_of(self, chat):
        for c, row in self._chat_rows:
            if c is chat:
                return row
        return None

    def _select_chat(self, chat: ChatSummary) -> None:
        self._selected_chat = chat
        for c, row in self._chat_rows:
            sel = c is chat
            row.configure(
                border_color=theme.AMBER if sel else theme.RULE,
                border_width=2 if sel else 1,
                fg_color=theme.AMBER_SOFT if sel else theme.CARD,
            )
        self._import_btn.configure(state="normal")
        self._set_status(f"Selezionata: {chat.name} ({chat.count} messaggi).")
        self._update_count_indicator()

    def _open_calendar(self, entry) -> None:
        try:
            init = datetime.strptime(entry.get().strip(), "%Y-%m-%d").date()
        except ValueError:
            init = date.today()

        def on_pick(d):
            entry.delete(0, "end")
            entry.insert(0, d.isoformat())
            self._preset_btn.set("Tutto")
            self._update_count_indicator()

        _CalendarPopup(self, init, on_pick)

    def _refresh_from_phone(self) -> None:
        if self._busy:
            return
        if self._adb is None:
            self._goto_device()
        else:
            self._goto_extract()

    def _apply_date_preset(self, value: str) -> None:
        today = date.today()
        starts = {
            "Tutto": None,
            "Oggi": today,
            "Ieri": today - timedelta(days=1),
            "7 giorni": today - timedelta(days=7),
            "30 giorni": today - timedelta(days=30),
        }
        start = starts.get(value)
        self._date_from.delete(0, "end")
        self._date_to.delete(0, "end")  # "fino a oggi" → campo «A» vuoto
        if start:
            self._date_from.insert(0, start.isoformat())
        self._update_count_indicator()

    def _on_date_edit(self, _e=None) -> None:
        self._preset_btn.set("Tutto")
        self._update_count_indicator()

    def _update_count_indicator(self) -> None:
        lbl = getattr(self, "_count_lbl", None)
        if lbl is None or self._selected_chat is None or self._reader is None:
            return
        try:
            from_ms = _parse_day(self._date_from.get())
            to_ms = _parse_day(self._date_to.get(), end_of_day=True)
        except ValueError:
            lbl.configure(text="Date incomplete (formato AAAA-MM-GG).")
            return
        try:
            msg_n, media_n = self._reader.count_range(
                self._selected_chat, from_ms, to_ms)
        except Exception:
            lbl.configure(text="")
            return
        period = self._period_label(from_ms, to_ms)
        lbl.configure(
            text=f"≈ {msg_n} messaggi · {media_n} media  ({period})")

    # ── Step 4: costruzione pacchetto ────────────────────────────────────
    def _start_build(self) -> None:
        if self._selected_chat is None or self._busy:
            return
        try:
            from_ms = _parse_day(self._date_from.get())
            to_ms = _parse_day(self._date_to.get(), end_of_day=True)
        except ValueError:
            self._set_status("Data non valida. Usa il formato AAAA-MM-GG.", "err")
            return
        if from_ms and to_ms and from_ms > to_ms:
            self._set_status("La data «Da» è successiva alla data «A».", "err")
            return
        self._date_range = (from_ms, to_ms)

        # Alert per conversazioni molto grandi (tempo di elaborazione + costo API).
        try:
            msg_n, media_n = self._reader.count_range(
                self._selected_chat, from_ms, to_ms)
        except Exception:
            msg_n, media_n = 0, 0
        if msg_n >= 8000 or media_n >= 400:
            proceed = messagebox.askyesno(
                "Conversazione molto grande",
                f"La selezione contiene circa {msg_n} messaggi e {media_n} media.\n\n"
                "L'elaborazione (OCR delle immagini e trascrizione degli audio) "
                "può richiedere molto tempo e un costo API non trascurabile.\n\n"
                "Vuoi procedere comunque?\n"
                "Suggerimento: usa il filtro «Periodo» per ridurre la selezione.",
                icon="warning", parent=self,
            )
            if not proceed:
                return

        self._goto_build()

    def _goto_build(self) -> None:
        self._clear(self.body)
        self._clear(self.footer)
        self._cancel.clear()
        chat = self._selected_chat
        self._set_head(
            "4. Costruzione del pacchetto",
            f"Estrazione di «{chat.name}» e download dei media…",
        )
        theme.ghost_button(
            self.footer, "Annulla", width=120, command=self._cancel.set,
        ).pack(side="right")

        from_ms, to_ms = self._date_range
        period_label = self._period_label(from_ms, to_ms)

        def work():
            self._adb.require_device()  # telefono necessario per scaricare i media
            self._post_status("Lettura messaggi…")
            messages = self._reader.read_messages(chat, from_ms, to_ms)
            if not messages:
                raise RuntimeError("Nessun messaggio nel periodo selezionato.")

            media_dir = self._work_dir / "media"
            media_dir.mkdir(parents=True, exist_ok=True)
            total_media = sum(1 for m in messages if m.media_relpath)

            entries: list[TranscriptEntry] = []
            seq = 0
            voice = 0
            missing = 0
            pulled_ok = 0
            for msg in messages:
                if self._cancel.is_set():
                    raise RuntimeError("Operazione annullata.")
                media_name = None
                if msg.media_relpath:
                    seq += 1
                    base = _sanitize_filename(Path(msg.media_relpath).name)
                    media_name = f"{seq:04d}-{base}"
                    remote = self._remote_media_path(msg.media_relpath)
                    self._post_status(
                        f"Download media {seq}/{total_media}: {base}")
                    local = self._adb.try_pull(remote, media_dir / media_name)
                    if local is None:
                        missing += 1
                    else:
                        pulled_ok += 1
                        if self._is_voice(msg.media_relpath, msg.media_mime):
                            voice += 1
                entries.append(TranscriptEntry(
                    ts_label=_fmt_ts(msg.ts),
                    sender=msg.sender_label,
                    text=msg.text,
                    media_name=media_name,
                ))

            self._post_status("Creazione del pacchetto…")
            stats = BuildStats(
                message_count=len(messages),
                media_count=pulled_ok,
                voice_note_count=voice,
                missing_media=missing,
            )
            output_path = self._output_path(chat, from_ms, to_ms)
            build_wachat(output_path, self._chat_header_name(chat), period_label,
                         entries, media_dir, stats)
            return output_path, stats

        self._run_bg(work, self._build_done, self._build_error)

    def _build_done(self, result) -> None:
        output_path, stats = result
        self._package_path = output_path
        self._goto_done(stats)

    def _build_error(self, e) -> None:
        self._set_status(str(e), "err")
        self._clear(self.footer)
        theme.amber_button(
            self.footer, "Torna alle chat", width=160, command=self._goto_select,
        ).pack(side="right")
        theme.ghost_button(
            self.footer, "Chiudi", width=120, command=self._on_close,
        ).pack(side="right", padx=(0, 8))

    # ── Step 5: fine ─────────────────────────────────────────────────────
    def _goto_done(self, stats: BuildStats) -> None:
        self._clear(self.body)
        self._clear(self.footer)
        self._set_head("5. Pronto", "Il pacchetto è stato creato.")

        summary = (
            f"Conversazione: {self._selected_chat.name}\n"
            f"Messaggi: {stats.message_count}\n"
            f"Media scaricati: {stats.media_count}"
            + (f" (di cui {stats.voice_note_count} note vocali)"
               if stats.voice_note_count else "")
            + (f"\nMedia non più presenti sul telefono: {stats.missing_media}"
               if stats.missing_media else "")
            + f"\n\nFile: {self._package_path}"
        )
        ctk.CTkLabel(
            self.body, text=summary, font=theme.font(12), text_color=theme.INK_2,
            justify="left", anchor="w", wraplength=680,
        ).pack(fill="x", pady=(6, 8), anchor="w")
        ctk.CTkLabel(
            self.body,
            text="Premi «Aggiungi» per inserirlo nell'elenco: poi avvia la "
                 "conversione come per gli altri file (testo, immagini e note "
                 "vocali finiranno in un unico Markdown).",
            font=theme.font(11), text_color=theme.INK_3,
            justify="left", anchor="w", wraplength=680,
        ).pack(fill="x", pady=(0, 6), anchor="w")

        self._set_status("Pacchetto creato correttamente.", "ok")
        theme.amber_button(
            self.footer, "Aggiungi all'elenco", width=200, command=self._finish,
        ).pack(side="right")
        theme.ghost_button(
            self.footer, "Chiudi", width=120, command=self._on_close,
        ).pack(side="right", padx=(0, 8))

    def _finish(self) -> None:
        if self._package_path and callable(self.on_package_ready):
            try:
                self.on_package_ready(self._package_path)
            except Exception:
                pass
        self._on_close()

    # ── Helpers ──────────────────────────────────────────────────────────
    @staticmethod
    def _remote_media_path(relpath: str) -> str:
        rp = relpath.replace("\\", "/")
        if rp.startswith("/"):
            return rp
        return f"{WA_SHARED_ROOT}/{rp}"

    @staticmethod
    def _is_voice(relpath: str, mime: str | None) -> bool:
        low = (relpath or "").lower()
        if low.endswith(".opus") or "ptt" in low or "voice" in low:
            return True
        return bool(mime) and mime.startswith("audio")

    @staticmethod
    def _chat_header_name(chat: ChatSummary) -> str:
        """Per le chat 1:1 con nome risolto, aggiunge il numero per tracciabilità."""
        user = chat.jid.split("@")[0] if chat.jid else ""
        num = f"+{user}" if user.isdigit() else ""
        if num and not chat.is_group and num not in chat.name:
            return f"{chat.name} ({num})"
        return chat.name

    @staticmethod
    def _period_label(from_ms: int | None, to_ms: int | None) -> str:
        if not from_ms and not to_ms:
            return "intera conversazione"
        start = _fmt_ts(from_ms, with_time=False) if from_ms else "inizio"
        end = _fmt_ts(to_ms, with_time=False) if to_ms else "oggi"
        return f"{start} – {end}"

    def _output_path(self, chat: ChatSummary,
                     from_ms: int | None, to_ms: int | None) -> Path:
        # Il .wachat è un intermedio: lo teniamo in una cartella temporanea
        # nascosta; l'MD convertito andrà invece in Download/Turbo MD Converter.
        out_dir = _session_base() / "packages"
        out_dir.mkdir(parents=True, exist_ok=True)
        if from_ms or to_ms:
            slug = f"{_fmt_ts(from_ms, False) if from_ms else 'inizio'}_a_" \
                   f"{_fmt_ts(to_ms, False) if to_ms else 'oggi'}"
        else:
            slug = "completa"
        base = f"WhatsApp - {_sanitize_filename(chat.name)} - {slug}"
        candidate = out_dir / f"{base}.wachat"
        i = 2
        while candidate.exists():
            candidate = out_dir / f"{base} ({i}).wachat"
            i += 1
        return candidate

    def _on_close(self) -> None:
        self._cancel.set()
        try:
            self.grab_release()
        except Exception:
            pass
        shutil.rmtree(self._work_dir, ignore_errors=True)
        self.destroy()
