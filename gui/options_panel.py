"""Right-rail options panel — paper-themed, compact, with cost chart slot."""

from __future__ import annotations
from tkinter import filedialog

import customtkinter as ctk

from gui import theme
from gui.frames.progress_frame import CostChart
from config.defaults import AVAILABLE_OCR_MODELS, SCHEMA_PRESET_NAMES, normalize_ocr_model

_RENAME_MODE_LABELS = {"md": "Solo MD", "pdf": "Solo PDF", "both": "Entrambi"}
_RENAME_LABEL_TO_MODE = {v: k for k, v in _RENAME_MODE_LABELS.items()}


class _PillToggle(ctk.CTkFrame):
    """Compact iOS-style toggle for boolean options."""
    def __init__(self, master, variable: ctk.BooleanVar, command=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._var = variable
        self._command = command
        self._toggle_w, self._toggle_h = 36, 20
        self._canvas = ctk.CTkCanvas(self, width=self._toggle_w, height=self._toggle_h,
                                     bg=theme.PAPER, highlightthickness=0, bd=0)
        self._canvas.pack()
        self._canvas.bind("<Button-1>", self._toggle)
        self._trace_id = self._var.trace_add("write", lambda *_: self._draw_toggle())
        self._draw_toggle()

    def destroy(self):
        try:
            self._var.trace_remove("write", self._trace_id)
        except Exception:
            pass
        super().destroy()

    def _toggle(self, _e=None):
        if str(self.cget("cursor")) == "watch":
            return
        self._var.set(not self._var.get())
        if self._command:
            self._command()

    def _draw_toggle(self):
        c = self._canvas
        c.delete("all")
        on = bool(self._var.get())
        bg = theme.AMBER if on else theme.RULE_STRONG
        # rounded track
        r = self._toggle_h / 2
        c.create_oval(0, 0, self._toggle_h, self._toggle_h, fill=bg, outline="")
        c.create_oval(
            self._toggle_w - self._toggle_h, 0,
            self._toggle_w, self._toggle_h,
            fill=bg, outline="",
        )
        c.create_rectangle(r, 0, self._toggle_w - r, self._toggle_h, fill=bg, outline="")
        # knob
        kx = self._toggle_w - self._toggle_h + 1 if on else 1
        c.create_oval(kx, 1, kx + self._toggle_h - 2, self._toggle_h - 1,
                      fill="#ffffff", outline="")


def _toggle_row(parent, label_text, var, on_change, sublabel=""):
    row = ctk.CTkFrame(parent, fg_color="transparent")

    txt_col = ctk.CTkFrame(row, fg_color="transparent")
    txt_col.pack(side="left", fill="x", expand=True)
    ctk.CTkLabel(
        txt_col, text=label_text,
        font=theme.font(12, "bold"), text_color=theme.INK, anchor="w",
    ).pack(anchor="w")
    if sublabel:
        ctk.CTkLabel(
            txt_col, text=sublabel,
            font=theme.font(10), text_color=theme.INK_3, anchor="w",
        ).pack(anchor="w")

    pill = _PillToggle(row, variable=var, command=on_change)
    pill.pack(side="right")
    return row


class OptionsPanel(ctk.CTkFrame):
    """Right rail — operations, output destination, cost chart, primary CTA."""

    def __init__(self, master, config, on_change=None,
                 on_start=None, on_cancel=None,
                 on_open_settings=None, on_open_updates=None,
                 on_open_rename_context=None,
                 **kwargs):
        super().__init__(master, fg_color=theme.PAPER, corner_radius=0,
                         border_width=0, **kwargs)
        self.config = config
        self._on_change = on_change
        self._on_start = on_start
        self._on_cancel = on_cancel
        self._on_open_rename_context = on_open_rename_context

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)  # scroll area expands

        # ── Header (gear / updates) ───────────────────────────────────────
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 4))
        ctk.CTkLabel(
            head, text="OPZIONI",
            font=theme.font(10, "bold"), text_color=theme.INK_3, anchor="w",
        ).pack(side="left")

        if on_open_updates:
            theme.ghost_button(
                head, "Aggiornamenti",
                command=on_open_updates, width=110, height=24,
            ).pack(side="right", padx=(4, 0))
        if on_open_settings:
            theme.ghost_button(
                head, "Impostazioni",
                command=on_open_settings, width=110, height=24,
            ).pack(side="right")

        # ── Scrollable middle ─────────────────────────────────────────────
        scroll = ctk.CTkScrollableFrame(
            self, fg_color=theme.PAPER, corner_radius=0,
            scrollbar_fg_color=theme.PAPER,
            scrollbar_button_color=theme.RULE,
            scrollbar_button_hover_color=theme.INK_3,
        )
        scroll.grid(row=1, column=0, sticky="nsew", padx=8, pady=0)
        scroll.grid_columnconfigure(0, weight=1)
        theme.autohide_scrollable_frame(scroll)

        # Vars
        self.run_ocr_var = ctk.BooleanVar(value=config.run_ocr)
        self.run_extraction_var = ctk.BooleanVar(value=config.run_extraction)
        self.email_attachments_separate_var = ctk.BooleanVar(
            value=bool(getattr(config, "email_attachments_separate", False)))
        self.rename_files_var = ctk.BooleanVar(value=config.rename_files)
        self.final_error_check_var = ctk.BooleanVar(
            value=bool(getattr(config, "final_error_check", True)))
        self.rename_batch_context_var = ctk.BooleanVar(
            value=bool(getattr(config, "rename_use_batch_context", False)))
        self.model_var = ctk.StringVar(
            value=normalize_ocr_model(config.ocr_model_id))
        self.schema_var = ctk.StringVar(value=config.active_schema)
        self.rename_mode_var = ctk.StringVar(
            value=_RENAME_MODE_LABELS.get(config.rename_mode, "Entrambi"))
        self.output_mode_var = ctk.StringVar(value=config.output_mode)
        output_formats = getattr(config, "output_formats", ["markdown"])
        self.output_markdown_var = ctk.BooleanVar(value="markdown" in output_formats)
        self.output_json_var = ctk.BooleanVar(value="json" in output_formats)

        # ── Operations card ───────────────────────────────────────────────
        ops = ctk.CTkFrame(scroll, fg_color=theme.CARD, corner_radius=8,
                           border_width=1, border_color=theme.RULE)
        ops.grid(row=0, column=0, sticky="ew", padx=4, pady=(8, 8))
        ops.grid_columnconfigure(0, weight=1)

        theme.section_label(ops, "Operazioni").grid(
            row=0, column=0, sticky="w", padx=14, pady=(12, 6))

        ocr_row = _toggle_row(ops, "OCR — estrai testo", self.run_ocr_var,
                              on_change=self._fire_change,
                              sublabel="Estrazione testuale tramite Gemini")
        ocr_row.grid(row=1, column=0, sticky="ew", padx=14, pady=(4, 8))

        ext_row = _toggle_row(ops, "Estrazione strutturata", self.run_extraction_var,
                              on_change=self._fire_change,
                              sublabel="JSON conforme a uno schema")
        ext_row.grid(row=2, column=0, sticky="ew", padx=14, pady=(4, 4))

        email_att_row = _toggle_row(
            ops,
            "Allegati email separati",
            self.email_attachments_separate_var,
            on_change=self._fire_change,
            sublabel="Un Markdown per la mail e uno per ogni allegato",
        )
        email_att_row.grid(row=3, column=0, sticky="ew", padx=14, pady=(4, 4))

        # Schema picker (only relevant when extraction is on)
        schema_wrap = ctk.CTkFrame(ops, fg_color="transparent")
        schema_wrap.grid(row=4, column=0, sticky="ew", padx=14, pady=(0, 8))
        ctk.CTkLabel(
            schema_wrap, text="Schema",
            font=theme.font(10), text_color=theme.INK_3,
        ).pack(side="left", padx=(0, 8))
        self.schema_menu = ctk.CTkOptionMenu(
            schema_wrap, values=SCHEMA_PRESET_NAMES,
            variable=self.schema_var, width=160, height=26,
            font=theme.font(11),
            fg_color=theme.PAPER_2, button_color=theme.RULE_STRONG,
            button_hover_color=theme.INK_3, text_color=theme.INK,
            dropdown_fg_color=theme.CARD_2,
            dropdown_text_color=theme.INK,
            dropdown_hover_color=theme.PAPER_2,
            command=lambda _v: self._fire_change(),
        )
        self.schema_menu.pack(side="right")

        rename_row = _toggle_row(ops, "Rinomina file", self.rename_files_var,
                                 on_change=self._on_rename_changed,
                                 sublabel="Suggerimenti di nome dall'AI")
        rename_row.grid(row=5, column=0, sticky="ew", padx=14, pady=(4, 4))

        final_check_row = _toggle_row(
            ops,
            "Check finale errori OCR (LLM)",
            self.final_error_check_var,
            on_change=self._fire_change,
            sublabel="Verifica i file convertiti con il modello LLM",
        )
        final_check_row.grid(row=6, column=0, sticky="ew", padx=14, pady=(4, 4))

        # Rename mode + batch context
        self.rename_extra = ctk.CTkFrame(ops, fg_color="transparent")
        self.rename_extra.grid(row=7, column=0, sticky="ew", padx=14, pady=(0, 6))

        mode_wrap = ctk.CTkFrame(self.rename_extra, fg_color="transparent")
        mode_wrap.pack(fill="x")
        ctk.CTkLabel(
            mode_wrap, text="Modalità",
            font=theme.font(10), text_color=theme.INK_3,
        ).pack(side="left", padx=(0, 8))
        self.rename_mode_menu = ctk.CTkOptionMenu(
            mode_wrap, values=list(_RENAME_MODE_LABELS.values()),
            variable=self.rename_mode_var, width=120, height=26,
            font=theme.font(11),
            fg_color=theme.PAPER_2, button_color=theme.RULE_STRONG,
            button_hover_color=theme.INK_3, text_color=theme.INK,
            dropdown_fg_color=theme.CARD_2,
            dropdown_text_color=theme.INK,
            dropdown_hover_color=theme.PAPER_2,
            command=lambda _v: self._fire_change(),
        )
        self.rename_mode_menu.pack(side="right")

        ctx_wrap = ctk.CTkFrame(self.rename_extra, fg_color="transparent")
        ctx_wrap.pack(fill="x", pady=(6, 0))
        self.batch_ctx_cb = ctk.CTkCheckBox(
            ctx_wrap, text="Batch-context",
            variable=self.rename_batch_context_var,
            command=self._fire_change,
            checkbox_height=16, checkbox_width=16,
            corner_radius=3,
            border_width=1, border_color=theme.RULE_STRONG,
            fg_color=theme.AMBER, hover_color=theme.AMBER_DEEP,
            text_color=theme.INK_2,
            font=theme.font(11),
        )
        self.batch_ctx_cb.pack(side="left")

        self.ctx_btn = theme.ghost_button(
            ctx_wrap, "Contesto…",
            command=on_open_rename_context, width=110, height=24,
        )
        self.ctx_btn.pack(side="right")

        # ── AI model card ─────────────────────────────────────────────────
        model_card = ctk.CTkFrame(scroll, fg_color=theme.CARD, corner_radius=8,
                                  border_width=1, border_color=theme.RULE)
        model_card.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 8))
        model_card.grid_columnconfigure(0, weight=1)

        theme.section_label(model_card, "Modello AI").grid(
            row=0, column=0, sticky="w", padx=14, pady=(12, 6))

        self.model_menu = ctk.CTkOptionMenu(
            model_card, values=AVAILABLE_OCR_MODELS,
            variable=self.model_var, height=30,
            font=theme.font(12, mono=True),
            fg_color=theme.PAPER_2, button_color=theme.RULE_STRONG,
            button_hover_color=theme.INK_3, text_color=theme.INK,
            dropdown_fg_color=theme.CARD_2,
            dropdown_text_color=theme.INK,
            dropdown_hover_color=theme.PAPER_2,
            command=lambda _v: self._fire_change(),
        )
        self.model_menu.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))

        # ── Output destination card ───────────────────────────────────────
        out_card = ctk.CTkFrame(scroll, fg_color=theme.CARD, corner_radius=8,
                                border_width=1, border_color=theme.RULE)
        out_card.grid(row=2, column=0, sticky="ew", padx=4, pady=(0, 8))
        out_card.grid_columnconfigure(0, weight=1)

        theme.section_label(out_card, "Destinazione output").grid(
            row=0, column=0, sticky="w", padx=14, pady=(12, 6))

        modes = [
            ("accanto",       "Accanto al file originale"),
            ("sottocartella", f'Sottocartella "{config.output_subfolder_name}"'),
            ("cartella",      "Cartella specifica…"),
        ]
        for i, (value, label) in enumerate(modes):
            ctk.CTkRadioButton(
                out_card, text=label,
                variable=self.output_mode_var, value=value,
                font=theme.font(11), text_color=theme.INK_2,
                radiobutton_height=14, radiobutton_width=14,
                border_width_unchecked=1, border_width_checked=4,
                border_color=theme.RULE_STRONG,
                fg_color=theme.AMBER, hover_color=theme.AMBER_DEEP,
                command=self._on_output_mode_changed,
            ).grid(row=1+i, column=0, sticky="w", padx=20, pady=2)

        # Folder picker row
        self._cartella_row = ctk.CTkFrame(out_card, fg_color="transparent")
        self._cartella_row.grid(row=4, column=0, sticky="ew",
                                padx=14, pady=(4, 12))
        self._cartella_row.grid_columnconfigure(0, weight=1)
        self._cartella_label = ctk.CTkLabel(
            self._cartella_row,
            text=self._short_dir_label(config.output_directory),
            font=theme.font(10, mono=True), text_color=theme.INK_3,
            anchor="w",
        )
        self._cartella_label.grid(row=0, column=0, sticky="ew", padx=(6, 6))
        theme.ghost_button(
            self._cartella_row, "Scegli…",
            command=self._pick_output_folder, width=70, height=24,
        ).grid(row=0, column=1, sticky="e")

        formats_row = ctk.CTkFrame(out_card, fg_color="transparent")
        formats_row.grid(row=5, column=0, sticky="ew", padx=14, pady=(0, 12))
        ctk.CTkLabel(
            formats_row, text="Formati output",
            font=theme.font(10), text_color=theme.INK_3,
        ).pack(side="left", padx=(0, 8))
        self.output_md_cb = ctk.CTkCheckBox(
            formats_row,
            text="Markdown (.md)",
            variable=self.output_markdown_var,
            command=self._on_output_format_changed,
            checkbox_height=16, checkbox_width=16,
            corner_radius=3,
            border_width=1, border_color=theme.RULE_STRONG,
            fg_color=theme.AMBER, hover_color=theme.AMBER_DEEP,
            text_color=theme.INK_2,
            font=theme.font(11),
        )
        self.output_md_cb.pack(side="left", padx=(0, 12))
        self.output_json_cb = ctk.CTkCheckBox(
            formats_row,
            text="JSON (.json)",
            variable=self.output_json_var,
            command=self._on_output_format_changed,
            checkbox_height=16, checkbox_width=16,
            corner_radius=3,
            border_width=1, border_color=theme.RULE_STRONG,
            fg_color=theme.AMBER, hover_color=theme.AMBER_DEEP,
            text_color=theme.INK_2,
            font=theme.font(11),
        )
        self.output_json_cb.pack(side="left")

        # ── Cost chart ────────────────────────────────────────────────────
        self.cost_chart = CostChart(scroll)
        self.cost_chart.grid(row=3, column=0, sticky="ew", padx=4, pady=(0, 16))

        # ── CTA strip (sticky-ish at bottom of panel) ─────────────────────
        cta_wrap = ctk.CTkFrame(self, fg_color=theme.PAPER, corner_radius=0)
        cta_wrap.grid(row=2, column=0, sticky="ew")
        theme.hairline(cta_wrap).pack(fill="x", side="top")

        cta_inner = ctk.CTkFrame(cta_wrap, fg_color="transparent")
        cta_inner.pack(fill="x", padx=14, pady=12)
        cta_inner.grid_columnconfigure(0, weight=1)

        self.start_btn = theme.amber_button(
            cta_inner, "Elabora documenti",
            command=on_start, height=42,
        )
        self.start_btn.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.start_btn.configure(state="disabled")

        self.cancel_btn = theme.ghost_button(
            cta_inner, "Interrompi",
            command=on_cancel, height=30,
        )
        self.cancel_btn.grid(row=1, column=0, sticky="ew")
        self.cancel_btn.configure(state="disabled")

        # initial state
        self._on_output_mode_changed()
        self._refresh_states()

    # ─── Public ───────────────────────────────────────────────────────────
    def get_values(self):
        return {
            "run_ocr": self.run_ocr_var.get(),
            "run_extraction": self.run_extraction_var.get(),
            "email_attachments_separate": self.email_attachments_separate_var.get(),
            "rename_files": self.rename_files_var.get(),
            "final_error_check": self.final_error_check_var.get(),
            "rename_use_batch_context": self.rename_batch_context_var.get(),
            "model": self.model_var.get(),
            "schema": self.schema_var.get(),
            "rename_mode": _RENAME_LABEL_TO_MODE.get(self.rename_mode_var.get(), "both"),
            "output_mode": self.output_mode_var.get(),
            "output_formats": self._get_output_formats(),
        }

    def set_running(self, running: bool):
        self.start_btn.configure(state="disabled" if running else "normal")
        self.cancel_btn.configure(state="normal" if running else "disabled")

    def set_can_start(self, can_start: bool):
        if self.cancel_btn.cget("state") == "normal":
            return  # leave alone while running
        self.start_btn.configure(state="normal" if can_start else "disabled")

    def update_cost_rows(self, rows):
        self.cost_chart.update_data(rows)

    def sync_from_config(self, config):
        self.config = config
        self.run_ocr_var.set(config.run_ocr)
        self.run_extraction_var.set(config.run_extraction)
        self.email_attachments_separate_var.set(
            bool(getattr(config, "email_attachments_separate", False)))
        self.rename_files_var.set(config.rename_files)
        self.final_error_check_var.set(
            bool(getattr(config, "final_error_check", True)))
        self.rename_batch_context_var.set(
            bool(getattr(config, "rename_use_batch_context", False)))
        self.model_var.set(normalize_ocr_model(config.ocr_model_id))
        self.schema_var.set(config.active_schema)
        self.rename_mode_var.set(_RENAME_MODE_LABELS.get(config.rename_mode, "Entrambi"))
        self.output_mode_var.set(config.output_mode)
        output_formats = getattr(config, "output_formats", ["markdown"])
        self.output_markdown_var.set("markdown" in output_formats)
        self.output_json_var.set("json" in output_formats)
        self._cartella_label.configure(text=self._short_dir_label(config.output_directory))
        self._on_output_mode_changed()
        self._refresh_states()

    # ─── Internals ────────────────────────────────────────────────────────
    def _fire_change(self):
        self._refresh_states()
        if self._on_change:
            self._on_change()

    def _on_rename_changed(self):
        self._refresh_states()
        self._fire_change()

    def _refresh_states(self):
        ocr_on = self.run_ocr_var.get()
        ext_on = self.run_extraction_var.get()
        rename_on = self.rename_files_var.get()
        final_check_on = self.final_error_check_var.get()
        any_ai = ocr_on or ext_on or rename_on or final_check_on

        self.model_menu.configure(state="normal" if any_ai else "disabled")
        self.schema_menu.configure(state="normal" if ext_on else "disabled")
        self.rename_mode_menu.configure(state="normal" if rename_on else "disabled")
        self.batch_ctx_cb.configure(state="normal" if rename_on else "disabled")
        self.ctx_btn.configure(state="normal" if rename_on else "disabled")

    def _on_output_mode_changed(self):
        if self.output_mode_var.get() == "cartella":
            self._cartella_row.grid()
        else:
            self._cartella_row.grid_remove()
        self._fire_change()

    def _pick_output_folder(self):
        folder = filedialog.askdirectory(title="Seleziona cartella di output")
        if folder:
            self.config.output_directory = folder
            self._cartella_label.configure(text=self._short_dir_label(folder))
            self._fire_change()

    def _on_output_format_changed(self):
        if not self.output_markdown_var.get() and not self.output_json_var.get():
            self.output_markdown_var.set(True)
        self._fire_change()

    def _get_output_formats(self) -> list[str]:
        formats: list[str] = []
        if self.output_markdown_var.get():
            formats.append("markdown")
        if self.output_json_var.get():
            formats.append("json")
        return formats or ["markdown"]

    @staticmethod
    def _short_dir_label(path: str, maxlen: int = 38) -> str:
        if not path:
            return "Nessuna cartella selezionata"
        p = path.replace("\\", "/")
        return f"…{p[-(maxlen-1):]}" if len(p) > maxlen else p
