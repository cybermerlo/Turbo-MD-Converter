"""Progress bars and cost tracking display."""

import customtkinter as ctk


class ProgressFrame(ctk.CTkFrame):
    """Shows OCR and extraction progress with cost info."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        # OCR Progress
        self.ocr_label = ctk.CTkLabel(
            self, text="OCR: In attesa...",
            font=ctk.CTkFont(weight="bold"),
        )
        self.ocr_label.pack(padx=10, pady=(10, 2), anchor="w")

        self.ocr_progress = ctk.CTkProgressBar(self)
        self.ocr_progress.pack(padx=10, pady=2, fill="x")
        self.ocr_progress.set(0)

        # Extraction Progress
        self.ext_label = ctk.CTkLabel(
            self, text="Estrazione: In attesa...",
            font=ctk.CTkFont(weight="bold"),
        )
        self.ext_label.pack(padx=10, pady=(10, 2), anchor="w")

        self.ext_progress = ctk.CTkProgressBar(self)
        self.ext_progress.pack(padx=10, pady=2, fill="x")
        self.ext_progress.set(0)

        # Cost display
        self.cost_label = ctk.CTkLabel(
            self, text="Costo: $0.0000 | Token: 0",
            font=ctk.CTkFont(size=12),
        )
        self.cost_label.pack(padx=10, pady=(10, 2), anchor="w")

        # Detailed cost breakdown
        self.cost_detail_label = ctk.CTkLabel(
            self, text="",
            font=ctk.CTkFont(size=11),
            text_color="gray60",
        )
        self.cost_detail_label.pack(padx=10, pady=(0, 5), anchor="w")

    def update_ocr(self, page_num: int, total_pages: int, success: bool) -> None:
        """Update OCR progress bar and label."""
        progress = (page_num + 1) / total_pages if total_pages > 0 else 0
        self.ocr_progress.set(progress)

        status = "OK" if success else "ERRORE"
        self.ocr_label.configure(
            text=f"OCR: Pagina {page_num + 1}/{total_pages} [{status}]"
        )

    def update_extraction_start(self, text_length: int, schema: str) -> None:
        """Show extraction has started."""
        self.ext_label.configure(
            text=f"Estrazione in corso... ({text_length:,} caratteri, schema: {schema})"
        )
        self.ext_progress.configure(mode="indeterminate")
        self.ext_progress.start()

    def update_extraction_complete(self, count: int) -> None:
        """Show extraction is complete."""
        self.ext_progress.stop()
        self.ext_progress.configure(mode="determinate")
        self.ext_progress.set(1.0)
        self.ext_label.configure(
            text=f"Estrazione completata: {count} entita' estratte"
        )

    def update_cost(self, total_tokens: int, cost_usd: float) -> None:
        """Update cost display."""
        self.cost_label.configure(
            text=f"Costo: ${cost_usd:.4f} | Token: {total_tokens:,}"
        )

    def update_cost_breakdown(self, cost_info: dict) -> None:
        """Show detailed cost breakdown by phase."""
        ocr = cost_info.get("ocr", {})
        ext = cost_info.get("extraction", {})

        parts = []
        if ocr.get("cost_usd", 0) > 0:
            parts.append(f"OCR: ${ocr['cost_usd']:.4f}")
        if ext.get("cost_usd", 0) > 0:
            parts.append(f"Estrazione: ~${ext['cost_usd']:.4f} (stimato)")

        if parts:
            self.cost_detail_label.configure(text=" | ".join(parts))

    def reset(self) -> None:
        """Reset all progress indicators."""
        self.ocr_progress.set(0)
        self.ocr_label.configure(text="OCR: In attesa...")
        self.ext_progress.stop()
        self.ext_progress.configure(mode="determinate")
        self.ext_progress.set(0)
        self.ext_label.configure(text="Estrazione: In attesa...")
        self.cost_label.configure(text="Costo: $0.0000 | Token: 0")
        self.cost_detail_label.configure(text="")
