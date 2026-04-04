"""Settings dialog window."""

from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from config.defaults import DEFAULT_OCR_PROMPT, DEFAULT_RENAME_PROMPT, SCHEMA_PRESET_NAMES, AVAILABLE_OCR_MODELS
from config.settings import AppConfig
from extraction.schemas import get_schema_preset, get_available_schemas


def _section_header(parent, text: str) -> None:
    """Render a divider + bold section title."""
    ctk.CTkFrame(parent, height=1, fg_color="gray30").pack(padx=10, pady=(10, 5), fill="x")
    ctk.CTkLabel(
        parent, text=text,
        font=ctk.CTkFont(size=13, weight="bold"),
    ).pack(padx=10, pady=(0, 4), anchor="w")


def _hint(parent, text: str) -> None:
    ctk.CTkLabel(
        parent, text=text,
        font=ctk.CTkFont(size=11),
        text_color="gray55",
        justify="left",
        wraplength=580,
    ).pack(padx=10, pady=(0, 6), anchor="w")


class SchemaEditorWindow(ctk.CTkToplevel):
    """Window for editing a schema's prompt description."""

    def __init__(self, master, schema_name: str, prompt_text: str, on_save: callable):
        super().__init__(master)
        self.title(f"Editor — {schema_name}")
        self.geometry("700x540")
        self.resizable(True, True)
        self.transient(master)
        self.grab_set()

        self.schema_name = schema_name
        self.on_save = on_save

        ctk.CTkLabel(
            self,
            text=f"Prompt di estrazione: {schema_name}",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(padx=15, pady=(15, 2), anchor="w")

        _hint_ = ctk.CTkLabel(
            self,
            text="Modifica il prompt che guida il modello nell'estrazione strutturata.",
            font=ctk.CTkFont(size=11),
            text_color="gray55",
        )
        _hint_.pack(padx=15, pady=(0, 8), anchor="w")

        self.text_editor = ctk.CTkTextbox(
            self, font=ctk.CTkFont(family="Consolas", size=12), wrap="word",
        )
        self.text_editor.pack(padx=15, pady=(0, 8), fill="both", expand=True)
        self.text_editor.insert("1.0", prompt_text)

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(padx=15, pady=(0, 12), fill="x")

        ctk.CTkButton(btn_frame, text="Salva", command=self._save, width=100).pack(
            side="right", padx=(5, 0)
        )
        ctk.CTkButton(
            btn_frame, text="Annulla", command=self.destroy, width=100,
            fg_color="transparent", border_width=1,
        ).pack(side="right")

    def _save(self) -> None:
        text = self.text_editor.get("1.0", "end").strip()
        self.on_save(self.schema_name, text)
        self.destroy()


class SettingsWindow(ctk.CTkToplevel):
    """Modal settings dialog."""

    def __init__(self, master, config: AppConfig, on_save: callable):
        super().__init__(master)
        self.title("Impostazioni")
        self.geometry("660x640")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self.config = config
        self.on_save = on_save

        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(padx=15, pady=(12, 5), fill="both", expand=True)

        self._build_api_tab()
        self._build_ocr_tab()
        self._build_extraction_tab()
        self._build_output_tab()

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(padx=15, pady=(0, 12), fill="x")

        ctk.CTkButton(btn_frame, text="Salva", command=self._save, width=100).pack(
            side="right", padx=(5, 0)
        )
        ctk.CTkButton(
            btn_frame, text="Annulla", command=self.destroy, width=100,
            fg_color="transparent", border_width=1,
        ).pack(side="right")

    # ─── Tabs ────────────────────────────────────────────────────────────────

    def _build_api_tab(self) -> None:
        tab = self.tabview.add("API")

        ctk.CTkLabel(tab, text="Chiave API Gemini").pack(padx=10, pady=(12, 2), anchor="w")

        key_row = ctk.CTkFrame(tab, fg_color="transparent")
        key_row.pack(padx=10, pady=(0, 4), fill="x")

        self.api_key_entry = ctk.CTkEntry(key_row, show="*", width=380)
        self.api_key_entry.pack(side="left", padx=(0, 8))
        self.api_key_entry.insert(0, self.config.gemini_api_key)

        self.show_key_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            key_row, text="Mostra",
            variable=self.show_key_var,
            command=self._toggle_key_visibility,
            width=80,
        ).pack(side="left")

        _hint(
            tab,
            "La stessa chiave viene usata per OCR (Gemini Vision) e per l'estrazione strutturata (LangExtract).",
        )

        _section_header(tab, "Mistral (trascrizione audio)")

        ctk.CTkLabel(tab, text="Chiave API Mistral").pack(padx=10, pady=(0, 2), anchor="w")

        mistral_key_row = ctk.CTkFrame(tab, fg_color="transparent")
        mistral_key_row.pack(padx=10, pady=(0, 4), fill="x")

        self.mistral_key_entry = ctk.CTkEntry(mistral_key_row, show="*", width=380)
        self.mistral_key_entry.pack(side="left", padx=(0, 8))
        self.mistral_key_entry.insert(0, self.config.mistral_api_key)

        self.show_mistral_key_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            mistral_key_row, text="Mostra",
            variable=self.show_mistral_key_var,
            command=self._toggle_mistral_key_visibility,
            width=80,
        ).pack(side="left")

        _hint(
            tab,
            "Chiave API Mistral per la trascrizione di file audio (MP3, WAV, FLAC, M4A, OGG) via Voxtral Small. "
            "Ottienila su: console.mistral.ai",
        )

    def _build_ocr_tab(self) -> None:
        tab = self.tabview.add("OCR")

        # Model
        model_row = ctk.CTkFrame(tab, fg_color="transparent")
        model_row.pack(padx=10, pady=(12, 6), fill="x")

        ctk.CTkLabel(model_row, text="Modello:").pack(side="left", padx=(0, 10))
        self.ocr_model_menu = ctk.CTkOptionMenu(model_row, values=AVAILABLE_OCR_MODELS, width=260)
        current_model = (
            self.config.ocr_model_id
            if self.config.ocr_model_id in AVAILABLE_OCR_MODELS
            else AVAILABLE_OCR_MODELS[0]
        )
        self.ocr_model_menu.set(current_model)
        self.ocr_model_menu.pack(side="left")

        # DPI
        dpi_row = ctk.CTkFrame(tab, fg_color="transparent")
        dpi_row.pack(padx=10, pady=(0, 6), fill="x")

        ctk.CTkLabel(dpi_row, text="Risoluzione (DPI):").pack(side="left", padx=(0, 10))
        self.dpi_label = ctk.CTkLabel(dpi_row, text=str(self.config.page_dpi), width=40)
        self.dpi_label.pack(side="right")
        self.dpi_slider = ctk.CTkSlider(
            dpi_row, from_=100, to=400, number_of_steps=6,
            command=lambda v: self.dpi_label.configure(text=str(int(v))),
        )
        self.dpi_slider.set(self.config.page_dpi)
        self.dpi_slider.pack(side="left", fill="x", expand=True, padx=5)

        _hint(tab, "200 DPI è il valore consigliato. Valori più alti aumentano la qualità ma rallentano l'elaborazione.")

        # Smart text detection
        _section_header(tab, "Ottimizzazione costi")

        self.smart_detect_var = ctk.BooleanVar(value=self.config.smart_text_detection)
        ctk.CTkCheckBox(
            tab,
            text="Rileva automaticamente pagine con testo selezionabile (salta l'OCR dove non serve)",
            variable=self.smart_detect_var,
        ).pack(padx=10, pady=(0, 4), anchor="w")
        _hint(
            tab,
            "Se attivo, le pagine con testo nativo vengono estratte direttamente senza chiamate API, "
            "riducendo i costi. Ideale per documenti digitali; nei PDF scansionati non ha effetto.",
        )

        # OCR Prompt
        _section_header(tab, "Prompt OCR")

        self.ocr_prompt_text = ctk.CTkTextbox(
            tab, height=130, font=ctk.CTkFont(family="Consolas", size=11),
        )
        self.ocr_prompt_text.pack(padx=10, pady=(0, 4), fill="both", expand=True)
        self.ocr_prompt_text.insert("1.0", self.config.ocr_prompt)

        ctk.CTkButton(
            tab, text="Ripristina predefinito",
            command=self._reset_ocr_prompt, width=160,
            fg_color="transparent", border_width=1,
        ).pack(padx=10, pady=(0, 8), anchor="w")

    def _build_extraction_tab(self) -> None:
        tab = self.tabview.add("Estrazione")

        # Schema selector
        schema_row = ctk.CTkFrame(tab, fg_color="transparent")
        schema_row.pack(padx=10, pady=(12, 4), fill="x")

        ctk.CTkLabel(schema_row, text="Schema:").pack(side="left", padx=(0, 10))
        self.schema_menu = ctk.CTkOptionMenu(
            schema_row, values=SCHEMA_PRESET_NAMES, width=200,
            command=self._on_schema_changed,
        )
        self.schema_menu.set(self.config.active_schema)
        self.schema_menu.pack(side="left")

        self.edit_schema_btn = ctk.CTkButton(
            schema_row, text="Modifica prompt",
            command=self._open_schema_editor, width=130,
        )
        self.edit_schema_btn.pack(side="right")

        # Schema preview
        ctk.CTkLabel(
            tab, text="Anteprima prompt:",
            font=ctk.CTkFont(size=11), text_color="gray55",
        ).pack(padx=10, pady=(4, 2), anchor="w")

        self.schema_preview = ctk.CTkTextbox(
            tab, height=100, font=ctk.CTkFont(family="Consolas", size=10),
            state="disabled", wrap="word", text_color="gray65",
        )
        self.schema_preview.pack(padx=10, pady=(0, 8), fill="x")
        self._on_schema_changed(self.config.active_schema)

        # Extraction passes
        _section_header(tab, "Parametri avanzati")

        passes_row = ctk.CTkFrame(tab, fg_color="transparent")
        passes_row.pack(padx=10, pady=(0, 6), fill="x")

        ctk.CTkLabel(passes_row, text="Passaggi di estrazione:").pack(side="left", padx=(0, 10))
        self.passes_label = ctk.CTkLabel(passes_row, text=str(self.config.extraction_passes), width=30)
        self.passes_label.pack(side="right")
        self.passes_slider = ctk.CTkSlider(
            passes_row, from_=1, to=5, number_of_steps=4,
            command=lambda v: self.passes_label.configure(text=str(int(v))),
        )
        self.passes_slider.set(self.config.extraction_passes)
        self.passes_slider.pack(side="left", fill="x", expand=True, padx=5)

        _hint(tab, "Più passaggi aumentano la copertura dell'estrazione, ma moltiplicano il costo API.")

        # Workers
        workers_row = ctk.CTkFrame(tab, fg_color="transparent")
        workers_row.pack(padx=10, pady=(0, 6), fill="x")

        ctk.CTkLabel(workers_row, text="Worker paralleli:").pack(side="left", padx=(0, 10))
        self.workers_label = ctk.CTkLabel(workers_row, text=str(self.config.max_workers), width=30)
        self.workers_label.pack(side="right")
        self.workers_slider = ctk.CTkSlider(
            workers_row, from_=1, to=30, number_of_steps=29,
            command=lambda v: self.workers_label.configure(text=str(int(v))),
        )
        self.workers_slider.set(self.config.max_workers)
        self.workers_slider.pack(side="left", fill="x", expand=True, padx=5)

        _hint(tab, "Numero di chunk elaborati in parallelo da LangExtract.")

    def _build_output_tab(self) -> None:
        tab = self.tabview.add("Output")

        # Output directory
        ctk.CTkLabel(tab, text="Cartella di output").pack(padx=10, pady=(12, 2), anchor="w")

        dir_row = ctk.CTkFrame(tab, fg_color="transparent")
        dir_row.pack(padx=10, pady=(0, 2), fill="x")

        self.output_dir_entry = ctk.CTkEntry(dir_row, width=360)
        self.output_dir_entry.pack(side="left", padx=(0, 6))
        self.output_dir_entry.insert(0, self.config.output_directory)

        ctk.CTkButton(
            dir_row, text="Sfoglia…", width=80, command=self._browse_output_dir,
        ).pack(side="left")

        _hint(tab, "Lascia vuoto per salvare i file nella stessa cartella del documento sorgente.")

        self.include_ocr_var = ctk.BooleanVar(value=self.config.include_ocr_text_in_output)
        ctk.CTkCheckBox(
            tab, text="Includi il testo OCR nel file Markdown",
            variable=self.include_ocr_var,
        ).pack(padx=10, pady=(0, 8), anchor="w")

        # Subfolder
        _section_header(tab, "Sottocartella per i file Markdown")

        _hint(
            tab,
            'Nome della sottocartella usata quando l\'opzione "Salva in sottocartella" è attiva nella finestra principale.',
        )

        self.subfolder_name_entry = ctk.CTkEntry(tab, width=300)
        self.subfolder_name_entry.pack(padx=10, pady=(0, 8), anchor="w")
        self.subfolder_name_entry.insert(0, self.config.output_subfolder_name)

        # Rename prompt
        _section_header(tab, "Prompt rinomina automatica")

        _hint(
            tab,
            "Prompt usato per ricavare data e descrizione dal testo. "
            "Il file viene rinominato nel formato «YYYYMMDD - Descrizione.ext».",
        )

        btn_row = ctk.CTkFrame(tab, fg_color="transparent")
        btn_row.pack(padx=10, pady=(0, 8), anchor="w")

        ctk.CTkButton(
            btn_row, text="Modifica prompt", width=160,
            command=self._open_rename_prompt_editor,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            btn_row, text="Ripristina predefinito", width=160,
            command=self._reset_rename_prompt,
            fg_color="transparent", border_width=1,
        ).pack(side="left")

    # ─── Schema helpers ───────────────────────────────────────────────────────

    def _on_schema_changed(self, schema_name: str) -> None:
        prompt_text = self._get_schema_prompt(schema_name)
        self.schema_preview.configure(state="normal")
        self.schema_preview.delete("1.0", "end")
        self.schema_preview.insert("1.0", prompt_text or "(Nessuno schema selezionato)")
        self.schema_preview.configure(state="disabled")
        self.edit_schema_btn.configure(state="normal")

    def _get_schema_prompt(self, schema_name: str) -> str:
        custom_prompts = getattr(self.config, "custom_schema_prompts", {})
        if schema_name in custom_prompts:
            return custom_prompts[schema_name]
        try:
            schema = get_schema_preset(schema_name)
            if schema:
                return schema.prompt_description
        except KeyError:
            pass
        return ""

    def _open_schema_editor(self) -> None:
        schema_name = self.schema_menu.get()
        SchemaEditorWindow(
            self, schema_name, self._get_schema_prompt(schema_name),
            on_save=self._on_schema_prompt_saved,
        )

    def _on_schema_prompt_saved(self, schema_name: str, prompt_text: str) -> None:
        if not hasattr(self.config, "custom_schema_prompts"):
            self.config.custom_schema_prompts = {}
        self.config.custom_schema_prompts[schema_name] = prompt_text
        self._on_schema_changed(schema_name)

    # ─── Other helpers ────────────────────────────────────────────────────────

    def _toggle_key_visibility(self) -> None:
        self.api_key_entry.configure(show="" if self.show_key_var.get() else "*")

    def _toggle_mistral_key_visibility(self) -> None:
        self.mistral_key_entry.configure(show="" if self.show_mistral_key_var.get() else "*")

    def _reset_ocr_prompt(self) -> None:
        self.ocr_prompt_text.delete("1.0", "end")
        self.ocr_prompt_text.insert("1.0", DEFAULT_OCR_PROMPT)

    def _browse_output_dir(self) -> None:
        folder = filedialog.askdirectory(title="Seleziona cartella di output")
        if folder:
            self.output_dir_entry.delete(0, "end")
            self.output_dir_entry.insert(0, folder)

    def _open_rename_prompt_editor(self) -> None:
        prompt_text = self.config.rename_prompt or DEFAULT_RENAME_PROMPT
        SchemaEditorWindow(
            self, "Prompt Rinomina", prompt_text,
            on_save=self._on_rename_prompt_saved,
        )

    def _on_rename_prompt_saved(self, _name: str, prompt_text: str) -> None:
        self.config.rename_prompt = prompt_text

    def _reset_rename_prompt(self) -> None:
        self.config.rename_prompt = ""

    # ─── Save ────────────────────────────────────────────────────────────────

    def _save(self) -> None:
        self.config.gemini_api_key = self.api_key_entry.get().strip()
        self.config.langextract_api_key = self.config.gemini_api_key
        self.config.mistral_api_key = self.mistral_key_entry.get().strip()
        self.config.ocr_prompt = self.ocr_prompt_text.get("1.0", "end").strip()
        self.config.ocr_model_id = self.ocr_model_menu.get()
        self.config.extraction_model_id = self.ocr_model_menu.get()
        self.config.page_dpi = int(self.dpi_slider.get())
        self.config.smart_text_detection = self.smart_detect_var.get()
        self.config.active_schema = self.schema_menu.get()
        self.config.extraction_passes = int(self.passes_slider.get())
        self.config.max_workers = int(self.workers_slider.get())
        self.config.output_directory = self.output_dir_entry.get().strip()
        self.config.include_ocr_text_in_output = self.include_ocr_var.get()
        subfolder_name = self.subfolder_name_entry.get().strip()
        if subfolder_name:
            self.config.output_subfolder_name = subfolder_name
        self.on_save(self.config)
        self.destroy()
