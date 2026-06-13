"""Shared file-type constants for the document pipeline."""

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp", ".gif")
AUDIO_EXTENSIONS = (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".mp4", ".opus")
ARCHIVE_EXTENSIONS = (".zip", ".7z", ".tar", ".tgz")

# ".wachat" è il pacchetto conversazione WhatsApp (zip: trascrizione + media),
# costruito dall'importatore WhatsApp e letto come singolo input → singolo MD.
DIRECT_READ_FORMATS = frozenset((
    ".txt", ".eml", ".msg", ".md", ".docx", ".html", ".htm", ".rtf",
    ".p7m", ".zip", ".7z", ".tar", ".tgz", ".wachat",
))
