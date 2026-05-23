"""Shared file-type constants for the document pipeline."""

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp", ".gif")
AUDIO_EXTENSIONS = (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".mp4")
ARCHIVE_EXTENSIONS = (".zip", ".7z", ".tar", ".tgz")

DIRECT_READ_FORMATS = frozenset((
    ".txt", ".eml", ".msg", ".md", ".docx", ".html", ".htm", ".rtf",
    ".p7m", ".zip", ".7z", ".tar", ".tgz",
))
