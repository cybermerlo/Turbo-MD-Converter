"""Sottoinsieme vendorizzato di ``ccl_chromium_reader`` (lettura IndexedDB).

NON è il pacchetto upstream completo: include solo la catena necessaria a leggere
l'IndexedDB di Chromium (LevelDB + deserializzazione V8/Blink). Questo ``__init__``
è volutamente **minimale**: NON importa nulla, così l'import del lettore IndexedDB
non trascina i moduli upstream che dipendono da ``Brotli`` (cache/filesystem),
che qui non servono.

Uso:

    from whatsapp._vendor.ccl_chromium_reader import ccl_chromium_indexeddb

Provenienza, versione e patch locali: vedi ``README.md`` in questa cartella.
"""
