"""Visual theme — paper warm + amber accent (Turbo MD Converter redesign)."""

from __future__ import annotations
import customtkinter as ctk

PAPER       = "#f5efe6"
PAPER_2     = "#efe7da"
CARD        = "#fbf7f0"
CARD_2      = "#ffffff"
RULE        = "#e3d9c8"
RULE_STRONG = "#cdbfa6"

INK    = "#1c1814"
INK_2  = "#4a423a"
INK_3  = "#8a7e6e"
INK_4  = "#b8ad9b"

AMBER       = "#c08a3a"
AMBER_DEEP  = "#9a6a25"
AMBER_SOFT  = "#f3e8d3"

OK         = "#3f8d4f"
OK_SOFT    = "#e6f0e0"
WARN       = "#c08a3a"
WARN_SOFT  = "#f3e8d3"
ERR        = "#b04a36"
ERR_SOFT   = "#f5e1dc"
INFO       = "#4a6e9c"
INFO_SOFT  = "#dee5ee"

STATUS_COLORS = {
    "queue": (PAPER_2, RULE,        INK_3),
    "run":   (INFO_SOFT, "#bcc8db", "#2c4366"),
    "ok":    (OK_SOFT,  "#bcd1ad", "#2a5e36"),
    "warn":  (WARN_SOFT, "#dcc59a", "#7a5418"),
    "err":   (ERR_SOFT, "#dca99c", "#7a2e1d"),
}

BADGE_COLORS = {
    "PDF": ("#f8e6e1", "#8a3a28"),
    "IMG": ("#e7eee2", "#3d6132"),
    "AUD": ("#ece4f3", "#543d70"),
    "MP4": ("#ece4f3", "#543d70"),
    "DOC": ("#e2eaf3", "#2c4a6e"),
    "DOCX":("#e2eaf3", "#2c4a6e"),
    "EML": (PAPER_2, INK_2),
    "MSG": (PAPER_2, INK_2),
    "TXT": (PAPER_2, INK_2),
    "MD":  (PAPER_2, INK_2),
    "HTML":(PAPER_2, INK_2),
    "RTF": (PAPER_2, INK_2),
    "P7M": ("#efe5d2", "#6b5418"),
    "ZIP": ("#efe5d2", "#6b5418"),
    "7Z":  ("#efe5d2", "#6b5418"),
    "TAR": ("#efe5d2", "#6b5418"),
}

EXT_TO_BADGE = {
    ".pdf": "PDF",
    ".jpg": "IMG", ".jpeg": "IMG", ".png": "IMG", ".webp": "IMG",
    ".tiff": "IMG", ".tif": "IMG", ".bmp": "IMG", ".gif": "IMG",
    ".mp3": "AUD", ".wav": "AUD", ".flac": "AUD", ".m4a": "AUD", ".ogg": "AUD",
    ".mp4": "MP4",
    ".docx": "DOCX",
    ".eml": "EML", ".msg": "MSG",
    ".txt": "TXT", ".md": "MD",
    ".html": "HTML", ".htm": "HTML",
    ".rtf": "RTF",
    ".p7m": "P7M",
    ".zip": "ZIP", ".7z": "7Z", ".tar": "TAR", ".tgz": "TAR",
}


def _pick_family(candidates):
    try:
        from tkinter import font as tkfont
        installed = set(tkfont.families())
        for c in candidates:
            if c in installed:
                return c
    except Exception:
        pass
    return candidates[-1]


_UI_FAMILY = None
_MONO_FAMILY = None


def ui_family():
    global _UI_FAMILY
    if _UI_FAMILY is None:
        _UI_FAMILY = _pick_family(["Inter", "Segoe UI", "Helvetica Neue", "Helvetica", "Arial"])
    return _UI_FAMILY


def mono_family():
    global _MONO_FAMILY
    if _MONO_FAMILY is None:
        _MONO_FAMILY = _pick_family(["JetBrains Mono", "Consolas", "Menlo", "Courier New", "Courier"])
    return _MONO_FAMILY


def font(size=13, weight="normal", mono=False):
    fam = mono_family() if mono else ui_family()
    return ctk.CTkFont(family=fam, size=size, weight=weight)


def section_label(parent, text):
    return ctk.CTkLabel(parent, text=text.upper(), font=font(10, "bold"),
                        text_color=INK_3, anchor="w")


def hairline(parent, color=RULE):
    return ctk.CTkFrame(parent, height=1, fg_color=color, corner_radius=0)


def install_theme():
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")


def amber_button(parent, text, command=None, **kwargs):
    return ctk.CTkButton(parent, text=text, command=command,
                         fg_color=AMBER, hover_color=AMBER_DEEP,
                         text_color="#ffffff", border_width=0,
                         corner_radius=6, font=font(13, "bold"), **kwargs)


def ink_button(parent, text, command=None, **kwargs):
    return ctk.CTkButton(parent, text=text, command=command,
                         fg_color=INK, hover_color="#000000",
                         text_color=PAPER, border_width=0,
                         corner_radius=6, font=font(13, "bold"), **kwargs)


def ghost_button(parent, text, command=None, **kwargs):
    return ctk.CTkButton(parent, text=text, command=command,
                         fg_color=CARD, hover_color=PAPER_2,
                         text_color=INK, border_width=1, border_color=RULE,
                         corner_radius=6, font=font(12), **kwargs)


def danger_button(parent, text, command=None, **kwargs):
    return ctk.CTkButton(parent, text=text, command=command,
                         fg_color=ERR, hover_color="#8c3a2a",
                         text_color="#ffffff", border_width=0,
                         corner_radius=6, font=font(13, "bold"), **kwargs)
