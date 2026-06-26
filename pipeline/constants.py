"""Shared file-type constants for the document pipeline."""

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp", ".gif")
AUDIO_EXTENSIONS = (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".mp4", ".opus")
# Video veri e propri: vengono instradati al percorso "video" (trascrizione audio
# ElevenLabs + descrizione visiva Gemini), che ha precedenza sull'audio puro. Nota
# che ".mp4" è anche in AUDIO_EXTENSIONS: il routing video lo intercetta prima.
VIDEO_EXTENSIONS = (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi")
ARCHIVE_EXTENSIONS = (".zip", ".7z", ".tar", ".tgz")

# ".wachat" è il pacchetto conversazione WhatsApp (zip: trascrizione + media),
# costruito dall'importatore WhatsApp e letto come singolo input → singolo MD.
DIRECT_READ_FORMATS = frozenset((
    ".txt", ".eml", ".msg", ".md", ".docx", ".html", ".htm", ".rtf",
    ".p7m", ".zip", ".7z", ".tar", ".tgz", ".wachat",
))
