"""Progress bars and cost tracking display."""

import customtkinter as ctk


def _section_label(parent, text: str) -> ctk.CTkLabel:
    return ctk.CTkLabel(
        parent, text=text.upper(),
        font=ctk.CTkFont(size=10, weight="bold"),
        text_color="gray60",
    )


class ProgressFrame(ctk.CTkFrame):
    """Shows OCR and extraction progress with cost info."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(padx=12, pady=(10, 10), fill="x")

        # ── OCR row ──────────────────────────────────────────────────────────
        ocr_header = ctk.CTkFrame(inner, fg_color="transparent")
        ocr_header.pack(fill="x", pady=(0, 2))

        _section_label(ocr_header, "OCR").pack(side="left")
        self.ocr_label = ctk.CTkLabel(
            ocr_header, text="In attesa",
            font=ctk.CTkFont(size=12),
            text_color="gray70",
        )
        self.ocr_label.pack(side="right")

        self.ocr_progress = ctk.CTkProgressBar(inner)
        self.ocr_progress.pack(fill="x", pady=(0, 8))
        self.ocr_progress.set(0)

        # ── Extraction row ───────────────────────────────────────────────────
        ext_header = ctk.CTkFrame(inner, fg_color="transparent")
        ext_header.pack(fill="x", pady=(0, 2))

        _section_label(ext_header, "Estrazione").pack(side="left")
        self.ext_label = ctk.CTkLabel(
            ext_header, text="In attesa",
            font=ctk.CTkFont(size=12),
            text_color="gray70",
        )
        self.ext_label.pack(side="right")

        self.ext_progress = ctk.CTkProgressBar(inner)
        self.ext_progress.pack(fill="x", pady=(0, 8))
        self.ext_progress.set(0)

        # ── Cost row ─────────────────────────────────────────────────────────
        cost_row = ctk.CTkFrame(inner, fg_color="transparent")
        cost_row.pack(fill="x")

        _section_label(cost_row, "Costo").pack(side="left")
        self.cost_label = ctk.CTkLabel(
            cost_row, text="$0.0000",
            font=ctk.CTkFont(size=12),
        )
        self.cost_label.pack(side="right")

        self.cost_detail_label = ctk.CTkLabel(
            inner, text="",
            font=ctk.CTkFont(size=11),
            text_color="gray60",
        )
        self.cost_detail_label.pack(anchor="e")

    # ─── Update methods ───────────────────────────────────────────────────────

    def update_ocr(self, page_num: int, total_pages: int, success: bool) -> None:
        progress = (page_num + 1) / total_pages if total_pages > 0 else 0
        self.ocr_progress.set(progress)
        status = "" if success else " ✗"
        self.ocr_label.configure(
            text=f"Pag. {page_num + 1} / {total_pages}{status}",
            text_color="gray70" if success else "orange",
        )

    def update_extraction_start(self, text_length: int, schema: str) -> None:
        self.ext_label.configure(
            text=f"Avvio  ·  {text_length:,} car.  ·  {schema}",
            text_color="gray70",
        )
        self.ext_progress.set(0)

    def update_extraction_progress(
        self,
        chunks_done: int, total_chunks: int,
        chars_processed: int, total_chars: int,
        pass_num: int, total_passes: int,
    ) -> None:
        progress = chunks_done / total_chunks if total_chunks > 0 else 0
        if total_passes > 1:
            pass_weight = 1.0 / total_passes
            progress = (pass_num - 1) * pass_weight + progress * pass_weight

        self.ext_progress.set(min(progress, 1.0))

        if total_passes > 1:
            self.ext_label.configure(
                text=f"Chunk {chunks_done}/{total_chunks}  ·  pass {pass_num}/{total_passes}",
                text_color="gray70",
            )
        else:
            self.ext_label.configure(
                text=f"Chunk {chunks_done} / {total_chunks}  ·  {chars_processed:,} car.",
                text_color="gray70",
            )

    def update_extraction_complete(self, count: int) -> None:
        self.ext_progress.set(1.0)
        noun = "entità" if count != 1 else "entità"
        self.ext_label.configure(
            text=f"Completata  ·  {count} {noun} estratte",
            text_color="gray70",
        )

    def update_cost(self, total_tokens: int, cost_usd: float) -> None:
        tok_str = f"{total_tokens:,}" if total_tokens else "0"
        self.cost_label.configure(text=f"${cost_usd:.4f}  ·  {tok_str} token")

    def update_cost_breakdown(self, cost_info: dict) -> None:
        ocr = cost_info.get("ocr", {})
        ext = cost_info.get("extraction", {})
        parts = []
        if ocr.get("cost_usd", 0) > 0:
            parts.append(f"OCR ${ocr['cost_usd']:.4f}")
        if ext.get("cost_usd", 0) > 0:
            parts.append(f"estrazione ~${ext['cost_usd']:.4f}")
        if parts:
            self.cost_detail_label.configure(text="  ·  ".join(parts))

    def reset(self) -> None:
        self.ocr_progress.set(0)
        self.ocr_label.configure(text="In attesa", text_color="gray70")
        self.ext_progress.set(0)
        self.ext_label.configure(text="In attesa", text_color="gray70")
        self.cost_label.configure(text="$0.0000")
        self.cost_detail_label.configure(text="")
