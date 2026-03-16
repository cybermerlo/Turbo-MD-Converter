"""Settings dialog window."""

from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from config.defaults import DEFAULT_OCR_PROMPT, SCHEMA_PRESET_NAMES, AVAILABLE_OCR_MODELS
from config.settings import AppConfig
from extraction.schemas import get_schema_preset, get_available_schemas


class SchemaEditorWindow(ctk.CTkToplevel):
    """Window for editing a schema's prompt description."""

    def __init__(self, master, schema_name: str, prompt_text: str,
                 on_save: callable):
        super().__init__(master)
        self.title(f"Editor Schema: {schema_name}")
        self.geometry("700x550")
        self.resizable(True, True)
        self.transient(master)
        self.grab_set()

        self.schema_name = schema_name
        self.on_save = on_save

        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(padx=15, pady=(15, 5), fill="x")

        ctk.CTkLabel(
            header,
            text=f"Prompt di estrazione: {schema_name}",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(side="left")

        # Info label
        ctk.CTkLabel(
            self,
            text="Modifica il prompt che guida l'LLM nell'estrazione strutturata.\n"
                 "Il prompt descrive quali entita' estrarre e come classificarle.",
            font=ctk.CTkFont(size=11),
            text_color="gray60",
            justify="left",
        ).pack(padx=15, pady=(0, 5), anchor="w")

        # Text editor
        self.text_editor = ctk.CTkTextbox(
            self, font=ctk.CTkFont(family="Courier", size=12),
            wrap="word",
        )
        self.text_editor.pack(padx=15, pady=5, fill="both", expand=True)
        self.text_editor.insert("1.0", prompt_text)

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(padx=15, pady=10, fill="x")

        ctk.CTkButton(
            btn_frame, text="Salva", command=self._save, width=100,
        ).pack(side="right", padx=(5, 0))

        ctk.CTkButton(
            btn_frame, text="Annulla", command=self.destroy, width=100,
            fg_color="gray40", hover_color="gray30",
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
        self.geometry("650x550")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self.config = config
        self.on_save = on_save

        # Tab view
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(padx=15, pady=(15, 5), fill="both", expand=True)

        self._build_api_tab()
        self._build_ocr_tab()
        self._build_extraction_tab()
        self._build_output_tab()

        # Save / Cancel buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(padx=15, pady=10, fill="x")

        ctk.CTkButton(
            btn_frame, text="Salva", command=self._save, width=100,
        ).pack(side="right", padx=(5, 0))

        ctk.CTkButton(
            btn_frame, text="Annulla", command=self.destroy, width=100,
            fg_color="gray40", hover_color="gray30",
        ).pack(side="right")

    def _build_api_tab(self) -> None:
        tab = self.tabview.add("API")

        ctk.CTkLabel(tab, text="Chiave API Gemini:").pack(
            padx=10, pady=(10, 2), anchor="w"
        )
        self.api_key_entry = ctk.CTkEntry(tab, show="*", width=400)
        self.api_key_entry.pack(padx=10, pady=2, anchor="w")
        self.api_key_entry.insert(0, self.config.gemini_api_key)

        self.show_key_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            tab, text="Mostra chiave",
            variable=self.show_key_var,
            command=self._toggle_key_visibility,
        ).pack(padx=10, pady=5, anchor="w")

        ctk.CTkLabel(
            tab, text="La stessa chiave viene usata per OCR (Gemini) e LangExtract.",
            font=ctk.CTkFont(size=11), text_color="gray60",
        ).pack(padx=10, pady=(10, 0), anchor="w")

    def _build_ocr_tab(self) -> None:
        tab = self.tabview.add("OCR")

        ctk.CTkLabel(tab, text="Prompt OCR:").pack(padx=10, pady=(10, 2), anchor="w")
        self.ocr_prompt_text = ctk.CTkTextbox(tab, height=200, font=ctk.CTkFont(size=12))
        self.ocr_prompt_text.pack(padx=10, pady=2, fill="both", expand=True)
        self.ocr_prompt_text.insert("1.0", self.config.ocr_prompt)

        btn_frame = ctk.CTkFrame(tab, fg_color="transparent")
        btn_frame.pack(padx=10, pady=5, fill="x")

        ctk.CTkButton(
            btn_frame, text="Ripristina Default",
            command=self._reset_ocr_prompt, width=140,
            fg_color="gray40", hover_color="gray30",
        ).pack(side="left")

        # Model selector
        model_frame = ctk.CTkFrame(tab, fg_color="transparent")
        model_frame.pack(padx=10, pady=5, fill="x")

        ctk.CTkLabel(model_frame, text="Modello OCR:").pack(side="left", padx=(0, 10))
        self.ocr_model_menu = ctk.CTkOptionMenu(
            model_frame, values=AVAILABLE_OCR_MODELS, width=250,
        )
        current_model = self.config.ocr_model_id if self.config.ocr_model_id in AVAILABLE_OCR_MODELS else AVAILABLE_OCR_MODELS[0]
        self.ocr_model_menu.set(current_model)
        self.ocr_model_menu.pack(side="left")

        # DPI slider
        dpi_frame = ctk.CTkFrame(tab, fg_color="transparent")
        dpi_frame.pack(padx=10, pady=5, fill="x")

        ctk.CTkLabel(dpi_frame, text="DPI:").pack(side="left", padx=(0, 10))
        self.dpi_label = ctk.CTkLabel(dpi_frame, text=str(self.config.page_dpi))
        self.dpi_label.pack(side="right")

        self.dpi_slider = ctk.CTkSlider(
            dpi_frame, from_=100, to=400, number_of_steps=6,
            command=lambda v: self.dpi_label.configure(text=str(int(v))),
        )
        self.dpi_slider.set(self.config.page_dpi)
        self.dpi_slider.pack(side="left", fill="x", expand=True, padx=5)

    def _build_extraction_tab(self) -> None:
        tab = self.tabview.add("Estrazione")

        # Schema selector
        schema_row = ctk.CTkFrame(tab, fg_color="transparent")
        schema_row.pack(padx=10, pady=(10, 5), fill="x")

        ctk.CTkLabel(schema_row, text="Schema di estrazione:").pack(
            side="left", padx=(0, 10)
        )
        self.schema_menu = ctk.CTkOptionMenu(
            schema_row, values=SCHEMA_PRESET_NAMES, width=200,
            command=self._on_schema_changed,
        )
        self.schema_menu.set(self.config.active_schema)
        self.schema_menu.pack(side="left")

        # Schema prompt preview (read-only)
        ctk.CTkLabel(
            tab, text="Prompt dello schema (anteprima):",
            font=ctk.CTkFont(size=12),
        ).pack(padx=10, pady=(5, 2), anchor="w")

        self.schema_preview = ctk.CTkTextbox(
            tab, height=120, font=ctk.CTkFont(size=11),
            state="disabled", wrap="word",
            text_color="gray70",
        )
        self.schema_preview.pack(padx=10, pady=2, fill="both", expand=True)

        # Edit schema button
        self.edit_schema_btn = ctk.CTkButton(
            tab, text="Modifica Schema",
            command=self._open_schema_editor, width=140,
        )
        self.edit_schema_btn.pack(padx=10, pady=5, anchor="w")

        # Load the current schema preview
        self._on_schema_changed(self.config.active_schema)

        # Extraction passes
        passes_frame = ctk.CTkFrame(tab, fg_color="transparent")
        passes_frame.pack(padx=10, pady=5, fill="x")

        ctk.CTkLabel(passes_frame, text="Passaggi di estrazione:").pack(
            side="left", padx=(0, 10)
        )
        self.passes_label = ctk.CTkLabel(
            passes_frame, text=str(self.config.extraction_passes)
        )
        self.passes_label.pack(side="right")

        self.passes_slider = ctk.CTkSlider(
            passes_frame, from_=1, to=5, number_of_steps=4,
            command=lambda v: self.passes_label.configure(text=str(int(v))),
        )
        self.passes_slider.set(self.config.extraction_passes)
        self.passes_slider.pack(side="left", fill="x", expand=True, padx=5)

        # Max workers
        workers_frame = ctk.CTkFrame(tab, fg_color="transparent")
        workers_frame.pack(padx=10, pady=5, fill="x")

        ctk.CTkLabel(workers_frame, text="Worker paralleli:").pack(
            side="left", padx=(0, 10)
        )
        self.workers_label = ctk.CTkLabel(
            workers_frame, text=str(self.config.max_workers)
        )
        self.workers_label.pack(side="right")

        self.workers_slider = ctk.CTkSlider(
            workers_frame, from_=1, to=30, number_of_steps=29,
            command=lambda v: self.workers_label.configure(text=str(int(v))),
        )
        self.workers_slider.set(self.config.max_workers)
        self.workers_slider.pack(side="left", fill="x", expand=True, padx=5)

    def _on_schema_changed(self, schema_name: str) -> None:
        """Update the schema preview when schema selection changes."""
        prompt_text = self._get_schema_prompt(schema_name)

        self.schema_preview.configure(state="normal")
        self.schema_preview.delete("1.0", "end")
        if prompt_text:
            self.schema_preview.insert("1.0", prompt_text)
        else:
            self.schema_preview.insert("1.0", "(Nessuno schema selezionato)")
        self.schema_preview.configure(state="disabled")

        # Enable/disable edit button
        if schema_name == "none":
            self.edit_schema_btn.configure(state="disabled")
        else:
            self.edit_schema_btn.configure(state="normal")

    def _get_schema_prompt(self, schema_name: str) -> str:
        """Get the prompt description for a schema."""
        if schema_name == "none":
            return ""

        # Check for custom override first
        custom_prompts = getattr(self.config, "custom_schema_prompts", {})
        if schema_name in custom_prompts:
            return custom_prompts[schema_name]

        # Load from preset
        try:
            schema = get_schema_preset(schema_name)
            if schema:
                return schema.prompt_description
        except KeyError:
            pass
        return ""

    def _open_schema_editor(self) -> None:
        """Open the schema editor window."""
        schema_name = self.schema_menu.get()
        if schema_name == "none":
            return

        prompt_text = self._get_schema_prompt(schema_name)
        SchemaEditorWindow(
            self, schema_name, prompt_text,
            on_save=self._on_schema_prompt_saved,
        )

    def _on_schema_prompt_saved(self, schema_name: str, prompt_text: str) -> None:
        """Called when a schema prompt is saved from the editor."""
        if not hasattr(self.config, "custom_schema_prompts"):
            self.config.custom_schema_prompts = {}
        self.config.custom_schema_prompts[schema_name] = prompt_text

        # Refresh preview
        self._on_schema_changed(schema_name)

    def _build_output_tab(self) -> None:
        tab = self.tabview.add("Output")

        ctk.CTkLabel(tab, text="Cartella di output:").pack(
            padx=10, pady=(10, 2), anchor="w"
        )

        dir_frame = ctk.CTkFrame(tab, fg_color="transparent")
        dir_frame.pack(padx=10, pady=2, fill="x")

        self.output_dir_entry = ctk.CTkEntry(dir_frame, width=350)
        self.output_dir_entry.pack(side="left", padx=(0, 5))
        self.output_dir_entry.insert(0, self.config.output_directory)

        ctk.CTkButton(
            dir_frame, text="Sfoglia", width=80,
            command=self._browse_output_dir,
        ).pack(side="left")

        ctk.CTkLabel(
            tab, text="Lascia vuoto per salvare nella stessa cartella del PDF.",
            font=ctk.CTkFont(size=11), text_color="gray60",
        ).pack(padx=10, pady=(2, 10), anchor="w")

        self.include_ocr_var = ctk.BooleanVar(value=self.config.include_ocr_text_in_output)
        ctk.CTkCheckBox(
            tab, text="Includi testo OCR nel Markdown",
            variable=self.include_ocr_var,
        ).pack(padx=10, pady=5, anchor="w")

        # Subfolder name
        subfolder_sep = ctk.CTkFrame(tab, height=1, fg_color="gray50")
        subfolder_sep.pack(padx=10, pady=(10, 5), fill="x")

        ctk.CTkLabel(
            tab, text="Sottocartella per i file MD",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(padx=10, pady=(5, 2), anchor="w")

        ctk.CTkLabel(
            tab,
            text="Nome della sottocartella usata quando l'opzione \"Salva MD in sottocartella\" è attiva.",
            font=ctk.CTkFont(size=11), text_color="gray60",
            justify="left",
        ).pack(padx=10, pady=(0, 5), anchor="w")

        self.subfolder_name_entry = ctk.CTkEntry(tab, width=300)
        self.subfolder_name_entry.pack(padx=10, pady=(0, 5), anchor="w")
        self.subfolder_name_entry.insert(0, self.config.output_subfolder_name)

        # File renaming options
        rename_sep = ctk.CTkFrame(tab, height=1, fg_color="gray50")
        rename_sep.pack(padx=10, pady=(10, 5), fill="x")

        ctk.CTkLabel(
            tab, text="Rinomina automatica file",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(padx=10, pady=(5, 2), anchor="w")

        ctk.CTkLabel(
            tab,
            text="Formato: YYYYMMDD - Descrizione del contenuto.ext\n"
                 "Ricavato automaticamente dai dati estratti (nessuna chiamata LLM aggiuntiva).\n"
                 "Richiede che sia attivo uno schema di estrazione (non 'none').",
            font=ctk.CTkFont(size=11), text_color="gray60",
            justify="left",
        ).pack(padx=10, pady=(0, 5), anchor="w")

        self.rename_md_var = ctk.BooleanVar(value=self.config.rename_output_md)
        ctk.CTkCheckBox(
            tab, text="Rinomina file MD di output",
            variable=self.rename_md_var,
        ).pack(padx=10, pady=2, anchor="w")

        self.rename_pdf_var = ctk.BooleanVar(value=self.config.rename_source_pdf)
        ctk.CTkCheckBox(
            tab, text="Rinomina file PDF sorgente",
            variable=self.rename_pdf_var,
        ).pack(padx=10, pady=2, anchor="w")

    def _toggle_key_visibility(self) -> None:
        show = "" if self.show_key_var.get() else "*"
        self.api_key_entry.configure(show=show)

    def _reset_ocr_prompt(self) -> None:
        self.ocr_prompt_text.delete("1.0", "end")
        self.ocr_prompt_text.insert("1.0", DEFAULT_OCR_PROMPT)

    def _browse_output_dir(self) -> None:
        folder = filedialog.askdirectory(title="Seleziona cartella di output")
        if folder:
            self.output_dir_entry.delete(0, "end")
            self.output_dir_entry.insert(0, folder)

    def _save(self) -> None:
        """Apply settings and close."""
        self.config.gemini_api_key = self.api_key_entry.get().strip()
        self.config.langextract_api_key = self.config.gemini_api_key
        self.config.ocr_prompt = self.ocr_prompt_text.get("1.0", "end").strip()
        self.config.ocr_model_id = self.ocr_model_menu.get()
        self.config.extraction_model_id = self.ocr_model_menu.get()
        self.config.page_dpi = int(self.dpi_slider.get())
        self.config.active_schema = self.schema_menu.get()
        self.config.extraction_passes = int(self.passes_slider.get())
        self.config.max_workers = int(self.workers_slider.get())
        self.config.output_directory = self.output_dir_entry.get().strip()
        self.config.include_ocr_text_in_output = self.include_ocr_var.get()
        subfolder_name = self.subfolder_name_entry.get().strip()
        if subfolder_name:
            self.config.output_subfolder_name = subfolder_name
        self.config.rename_output_md = self.rename_md_var.get()
        self.config.rename_source_pdf = self.rename_pdf_var.get()

        self.on_save(self.config)
        self.destroy()
