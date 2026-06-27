"""Finestra di import chat da WhatsApp Desktop (v1: solo testo).

Legge il DB locale dell'app ufficiale WhatsApp Desktop (nessuna connessione,
nessun rischio ban), lascia scegliere una chat + intervallo date + ricerca, e
produce un Markdown che viene aggiunto agli input dell'app.
"""

from __future__ import annotations

import datetime as dt
import re
import threading
from pathlib import Path

import customtkinter as ctk

from gui import theme
from gui.resources import app_capture_dir


def _safe_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip() or "chat"


class WhatsAppImportWindow(ctk.CTkToplevel):
    """Wizard a finestra unica: carica chat → filtra → crea MD."""

    _RANGES = ("Tutto", "Ultimi 7 giorni", "Ultimi 30 giorni", "Personalizzato")

    def __init__(self, master, on_chat_ready):
        super().__init__(master)
        self._on_chat_ready = on_chat_ready
        self._reader = None
        self._chats: list = []
        self._selected = None
        self._closed = False
        self._row_buttons: dict = {}

        self.title("Importa da WhatsApp Desktop")
        self.geometry("760x600")
        self.minsize(640, 520)
        try:
            self.configure(fg_color=theme.PAPER)
        except Exception:
            pass
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        ctk.CTkLabel(
            self, text="Importa da WhatsApp Desktop",
            font=theme.font(16, "bold"), text_color=theme.INK,
        ).pack(padx=18, pady=(16, 2), anchor="w")
        ctk.CTkLabel(
            self,
            text="Legge i messaggi dall'app WhatsApp Desktop installata su questo "
                 "PC (solo locale, nessun rischio ban). Solo testo: niente mittente "
                 "per i gruppi né media.",
            font=theme.font(10), text_color=theme.INK_3,
            justify="left", wraplength=700,
        ).pack(padx=18, pady=(0, 8), anchor="w")

        self._status = ctk.CTkLabel(
            self, text="Decifratura in corso…",
            font=theme.font(11), text_color=theme.INK_3, anchor="w",
        )
        self._status.pack(padx=18, pady=(0, 4), fill="x")
        self._bar = ctk.CTkProgressBar(self, mode="indeterminate")
        self._bar.pack(padx=18, pady=(0, 8), fill="x")
        self._bar.start()

        # Ricerca nella lista chat
        self._chat_search = ctk.CTkEntry(self, placeholder_text="Cerca chat per nome…")
        self._chat_search.pack(padx=18, pady=(0, 6), fill="x")
        self._chat_search.bind("<KeyRelease>", lambda _e: self._render_chats())

        self._list = ctk.CTkScrollableFrame(self, fg_color=theme.CARD, height=220)
        self._list.pack(padx=18, pady=(0, 8), fill="both", expand=True)

        # Filtri messaggi
        filt = ctk.CTkFrame(self, fg_color="transparent")
        filt.pack(padx=18, pady=(0, 4), fill="x")
        ctk.CTkLabel(filt, text="Periodo:", font=theme.font(11),
                     text_color=theme.INK_2).pack(side="left")
        self._range_var = ctk.StringVar(value=self._RANGES[0])
        ctk.CTkOptionMenu(
            filt, values=list(self._RANGES), variable=self._range_var,
            width=170, command=lambda _v: self._on_range_changed(),
        ).pack(side="left", padx=(6, 10))
        self._since_entry = ctk.CTkEntry(filt, placeholder_text="da AAAA-MM-GG", width=120)
        self._until_entry = ctk.CTkEntry(filt, placeholder_text="a AAAA-MM-GG", width=120)
        self._since_entry.pack(side="left", padx=(0, 4))
        self._until_entry.pack(side="left")
        self._on_range_changed()

        srow = ctk.CTkFrame(self, fg_color="transparent")
        srow.pack(padx=18, pady=(4, 4), fill="x")
        ctk.CTkLabel(srow, text="Contiene testo:", font=theme.font(11),
                     text_color=theme.INK_2).pack(side="left")
        self._msg_search = ctk.CTkEntry(srow, placeholder_text="(facoltativo)")
        self._msg_search.pack(side="left", padx=(6, 0), fill="x", expand=True)

        # Azioni
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(padx=18, pady=(6, 14), fill="x")
        self._result = ctk.CTkLabel(actions, text="", font=theme.font(11),
                                    text_color=theme.INK_3, anchor="w")
        self._result.pack(side="left", fill="x", expand=True)
        theme.ghost_button(actions, "Chiudi", width=90,
                           command=self._on_close).pack(side="right", padx=(8, 0))
        self._create_btn = theme.amber_button(
            actions, "Crea MD", width=140, command=self._create)
        self._create_btn.pack(side="right")
        self._create_btn.configure(state="disabled")

        self.after(120, self._start_load)

    # ─── Helpers di thread ────────────────────────────────────────────────
    def _safe_after(self, fn, *a):
        if not self._closed:
            try:
                self.after(0, lambda: (None if self._closed else fn(*a)))
            except Exception:
                pass

    # ─── Caricamento chat ─────────────────────────────────────────────────
    def _start_load(self):
        threading.Thread(target=self._load_thread, daemon=True).start()

    def _load_thread(self):
        from whatsapp.desktop_crypto import WhatsAppDesktopError
        from whatsapp.desktop_reader import WhatsAppDesktopReader
        try:
            reader = WhatsAppDesktopReader()
            reader.open()
            chats = reader.list_chats()
            self._reader = reader
            self._safe_after(self._on_loaded, chats)
        except WhatsAppDesktopError as e:
            self._safe_after(self._on_load_error, str(e))
        except Exception as e:  # noqa: BLE001
            self._safe_after(self._on_load_error, f"Errore imprevisto: {e}")

    def _on_loaded(self, chats):
        self._chats = chats
        self._bar.stop()
        self._bar.pack_forget()
        self._status.configure(text=f"{len(chats)} chat trovate. Seleziona una chat.")
        self._render_chats()

    def _on_load_error(self, msg):
        self._bar.stop()
        self._bar.pack_forget()
        self._status.configure(text=f"Impossibile leggere WhatsApp Desktop: {msg}",
                               text_color="#b04a36")

    def _render_chats(self):
        for w in self._list.winfo_children():
            w.destroy()
        self._row_buttons = {}
        q = self._chat_search.get().strip().lower()
        shown = [c for c in self._chats if not q or q in c.name.lower()]
        for c in shown[:400]:
            last = (dt.datetime.fromtimestamp(c.last_ts).strftime("%d/%m/%Y")
                    if c.last_ts else "?")
            label = f"{c.name}   ·   {c.message_count} msg   ·   {last}"
            btn = ctk.CTkButton(
                self._list, text=label, anchor="w",
                fg_color=theme.PAPER_2, text_color=theme.INK,
                hover_color=theme.RULE, height=30,
                command=lambda ch=c: self._select(ch),
            )
            btn.pack(fill="x", padx=4, pady=2)
            self._row_buttons[c.chat_id] = btn
        if not shown:
            ctk.CTkLabel(self._list, text="Nessuna chat corrisponde alla ricerca.",
                         font=theme.font(11), text_color=theme.INK_4).pack(pady=20)

    def _select(self, chat):
        self._selected = chat
        for cid, btn in self._row_buttons.items():
            btn.configure(fg_color=theme.AMBER if cid == chat.chat_id else theme.PAPER_2)
        self._create_btn.configure(state="normal")
        self._result.configure(text=f"Selezionata: {chat.name}", text_color=theme.INK_3)

    # ─── Filtri data ──────────────────────────────────────────────────────
    def _on_range_changed(self):
        custom = self._range_var.get() == "Personalizzato"
        state = "normal" if custom else "disabled"
        self._since_entry.configure(state=state)
        self._until_entry.configure(state=state)

    def _compute_range(self):
        choice = self._range_var.get()
        now = dt.datetime.now()
        if choice == "Ultimi 7 giorni":
            return int((now - dt.timedelta(days=7)).timestamp()), None
        if choice == "Ultimi 30 giorni":
            return int((now - dt.timedelta(days=30)).timestamp()), None
        if choice == "Personalizzato":
            since = until = None
            s = self._since_entry.get().strip()
            u = self._until_entry.get().strip()
            if s:
                since = int(dt.datetime.strptime(s, "%Y-%m-%d").timestamp())
            if u:
                until = int(dt.datetime.strptime(u, "%Y-%m-%d").timestamp()) + 86399
            return since, until
        return None, None

    # ─── Creazione MD ─────────────────────────────────────────────────────
    def _create(self):
        if not self._selected or not self._reader:
            return
        try:
            since, until = self._compute_range()
        except ValueError:
            self._result.configure(text="Date non valide (usa AAAA-MM-GG).",
                                   text_color="#b04a36")
            return
        query = self._msg_search.get().strip() or None
        self._create_btn.configure(state="disabled")
        self._result.configure(text="Creazione in corso…", text_color=theme.INK_3)
        chat = self._selected
        threading.Thread(
            target=self._create_thread, args=(chat, since, until, query), daemon=True
        ).start()

    def _create_thread(self, chat, since, until, query):
        from whatsapp.desktop_reader import build_markdown
        try:
            msgs = self._reader.read_messages(chat.chat_id, since, until, query)
            md = build_markdown(chat, msgs)
            out = app_capture_dir() / f"WhatsApp - {_safe_name(chat.name)}.md"
            out.write_text(md, encoding="utf-8")
            self._safe_after(self._on_created, out, len(msgs))
        except Exception as e:  # noqa: BLE001
            self._safe_after(self._on_create_error, str(e))

    def _on_created(self, path: Path, n: int):
        self._create_btn.configure(state="normal")
        self._result.configure(text=f"Creato: {path.name} ({n} messaggi)",
                               text_color="#2a7d3a")
        if callable(self._on_chat_ready):
            self._on_chat_ready(path)

    def _on_create_error(self, msg):
        self._create_btn.configure(state="normal")
        self._result.configure(text=f"Errore: {msg}", text_color="#b04a36")

    # ─── Chiusura ─────────────────────────────────────────────────────────
    def _on_close(self):
        self._closed = True
        if self._reader:
            try:
                self._reader.close()
            except Exception:
                pass
            self._reader = None
        try:
            self.destroy()
        except Exception:
            pass
