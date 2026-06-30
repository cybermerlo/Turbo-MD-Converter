# Reimportazione chat WhatsApp — piano (DB locale WhatsApp Desktop)

Stato: **spike di fattibilità** (fase 0). Branch: `claude/whatsapp-web-import`.

## Obiettivo
Permettere all'utente di selezionare una chat e i messaggi/media che vuole, da
usare come input per la conversione in Markdown. Selezione **agevole anche con
molti messaggi**. Vincoli dell'utente: **niente export manuale**, **nessun
rischio ban** del numero, va bene avere solo i **messaggi recenti** (~ultimo mese).

## Perché leggere il DB locale di WhatsApp Desktop (e non le alternative)
Sintesi della ricerca (giugno 2026):

- **WhatsApp Web / companion via libreria** (neonize/whatsmeow, Baileys): un
  dispositivo collegato riceve solo una **finestra recente**; lo storico vecchio
  on-demand è **silenziosamente ignorato** per i companion (bug 2025-2026) e i
  media >~30 giorni **scadono** sui server. Soprattutto: rischio **ban reale e
  non azzerabile** anche in sola lettura (fingerprinting di protocollo). → escluso
  per il vincolo "no ban".
- **Export nativo** (`.txt`/`.zip`): a rischio zero e quasi completo, ma
  **manuale** e una chat alla volta. → escluso dall'utente.
- **Cloud API ufficiale**: non può accedere allo storico personale. → inutile.
- **DB locale di WhatsApp Desktop (scelto)**: è l'**app ufficiale** a
  sincronizzarsi (tiene la finestra recente, che ci basta); noi leggiamo solo i
  **file locali già presenti sul PC**. Nessuna connessione non ufficiale ai
  server → **nessun meccanismo di ban**. Niente USB/adb, niente export manuale.

## Costi noti del percorso scelto
1. **Cifratura**: archivio SQLite cifrato (SQLite Encryption Extension). Le chiavi
   derivano dall'**ODUID** (`HKLM\SYSTEM\CurrentControlSet\Services\TPM\ODUID`,
   valore `RandomSeed`) → tipicamente serve **un'elevazione admin** una volta
   (poi si può cacheare la chiave derivata).
2. **DPAPI-NG** (build WebView2) per proteggere lo `staticKey`: non è la classica
   `CryptUnprotectData`; va gestita via `ncrypt.dll`.
3. **Nessuna libreria Python pronta**: l'implementazione di riferimento è
   **ZAPiXDESK** (PowerShell/.NET, mantenuta, supporta sia UWP sia WebView2).
   Porteremo/incapsuleremo la sua logica.
4. **Fragilità**: Meta ha riscritto l'architettura due volte in 2 anni
   (Electron → UWP → **WebView2 dal 9 dic 2025**). Va aggiornato quando cambia il
   formato; ci agganciamo agli aggiornamenti di ZAPiXDESK come riferimento.

### Varianti note dei file (sotto `%LOCALAPPDATA%\Packages\5319275A.WhatsAppDesktop_*\LocalState`)
- **WebView2 (attuale)**: `genericStorageDB` (messaggi), `nativeSettings.db`
  (chiavi), `session.db`. Protezione: DPAPI-NG + ODUID.
- **UWP/WinUI (~2023-2025)**: `message.db` (+ `-wal`), `nondb_settings*.dat`.
- Media recenti: `...\LocalState\shared\transfers`.

## Piano a fasi
- **Fase 0 — spike diagnostico (questo commit)**: `tools/wa_desktop_probe.py`,
  script **read-only** (niente decifratura, niente modifiche) che fotografa
  l'installazione reale dell'utente: variante, file DB presenti (e se appaiono
  cifrati), cache media, leggibilità dell'ODUID (e se serve admin), presenza di
  DPAPI-NG. Serve a sapere su quale variante costruire il decryptor.
- **Fase 1 — decryptor**: per la variante confermata dallo spike, decifrare e
  leggere i messaggi recenti + media (porting/incapsulamento di ZAPiXDESK).
- **Fase 2 — selettore + pipeline**: UI di selezione ergonomica (filtri
  data/mittente/tipo/ricerca, **lista virtualizzata**, range-select,
  "seleziona tutto il filtrato") sui dati decifrati → pacchetto unico →
  pipeline esistente → un MD (OCR foto + trascrizione note vocali).

## Come eseguire lo spike (fase 0)
Sul PC Windows con WhatsApp Desktop installato e con almeno un accesso fatto:

```
python tools/wa_desktop_probe.py
```

Eseguilo prima da utente normale; se segnala che l'ODUID richiede privilegi,
rieseguilo da un prompt **Amministratore**. Poi incolla l'output (c'è un blocco
JSON pronto da copiare).

## Note legali/privacy
Si leggono **dati dell'utente, sul PC dell'utente**. Nessuna connessione ai
server WhatsApp → nessun vettore di ban. Resta un'area grigia rispetto ai ToS
(aggiramento di una misura di cifratura): da gestire con consenso esplicito.
