"""Importazione conversazioni WhatsApp dal backup locale Android (via adb).

Moduli:
- adb_bridge:       lettura dati dal telefono collegato via USB (adb)
- backup_decryptor: decifratura di msgstore.db.crypt15 (wa-crypt-tools)
- msgstore_reader:  lettura del database SQLite (elenco chat + messaggi)
- package_builder:  costruzione del pacchetto ".wachat" (trascrizione + media)
"""
