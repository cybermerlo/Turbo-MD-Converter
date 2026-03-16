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
        """Show extraction has started with chunk estimation."""
        self.ext_label.configure(
            text=f"Estrazione: avvio... ({text_length:,} caratteri, schema: {schema})"
        )
        self.ext_progress.set(0)

    def update_extraction_progress(
        self, chunks_done: int, total_chunks: int,
        chars_processed: int, total_chars: int,
        pass_num: int, total_passes: int,
    ) -> None:
        """Update extraction progress bar with chunk-level info."""
        progress = chunks_done / total_chunks if total_chunks > 0 else 0
        # When multiple passes, scale progress across all passes
        if total_passes > 1:
            pass_weight = 1.0 / total_passes
            progress = (pass_num - 1) * pass_weight + progress * pass_weight

        self.ext_progress.set(min(progress, 1.0))

        if total_passes > 1:
            self.ext_label.configure(
                text=(
                    f"Estrazione: chunk {chunks_done}/{total_chunks} "
                    f"({chars_processed:,}/{total_chars:,} car.) "
                    f"- pass {pass_num}/{total_passes}"
                )
            )
        else:
            self.ext_label.configure(
                text=(
                    f"Estrazione: chunk {chunks_done}/{total_chunks} "
                    f"({chars_processed:,}/{total_chars:,} car.)"
                )
            )

    def update_extraction_complete(self, count: int) -> None:
        """Show extraction is complete."""
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
        self.ext_progress.set(0)
        self.ext_label.configure(text="Estrazione: In attesa...")
        self.cost_label.configure(text="Costo: $0.0000 | Token: 0")
        self.cost_detail_label.configure(text="")
