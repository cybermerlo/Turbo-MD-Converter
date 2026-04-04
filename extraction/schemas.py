"""Italian legal document extraction schemas for LangExtract."""

import textwrap
from dataclasses import dataclass

import langextract as lx


@dataclass
class SchemaPreset:
    """A named extraction schema with prompt and examples."""
    name: str
    description: str
    prompt_description: str
    examples: list[lx.data.ExampleData]


def build_full_legal_schema() -> SchemaPreset:
    """Comprehensive Italian legal document schema with 13 extraction classes."""

    prompt_description = textwrap.dedent("""\
        Estrai informazioni strutturate da questo documento legale italiano.
        Identifica e classifica in ordine di apparizione:

        - TRIBUNALE: nome del tribunale, sezione, numero di ruolo (RG)
        - PARTI: attore, convenuto (persone fisiche o giuridiche)
        - AVVOCATI: difensori delle parti con indicazione di chi rappresentano
        - GIUDICE: giudice/i assegnati alla causa
        - DATE: data di deposito, data udienza, data sentenza
        - DOMANDE: richieste giudiziali formulate dalle parti
        - FATTI: fatti contestati o accertati
        - DISPOSITIVO: decisioni, ordini, sentenze del giudice
        - IMPORTI: somme di denaro, risarcimenti, spese legali
        - RIFERIMENTI NORMATIVI: articoli di legge, codici, decreti citati

        Usa il testo esatto dal documento per ogni estrazione.
        Non parafrasare e non sovrapporre le entita'.
        Fornisci attributi significativi per aggiungere contesto a ogni estrazione.""")

    example_text_1 = textwrap.dedent("""\
        TRIBUNALE DI MILANO
        Sezione III Civile
        R.G. n. 12345/2024

        SENTENZA

        Il Giudice Dott.ssa Maria Verdi, nella causa promossa da:

        Mario Rossi, C.F. RSSMRA80A01F205X, rappresentato e difeso \
        dall'Avv. Giuseppe Bianchi del Foro di Milano,

        ATTORE

        contro

        Alfa S.r.l., in persona del legale rappresentante pro tempore, \
        rappresentata e difesa dall'Avv. Laura Neri del Foro di Milano,

        CONVENUTA

        ha pronunciato la seguente sentenza.

        Con atto di citazione notificato in data 15 marzo 2024, l'attore \
        conveniva in giudizio la societa' Alfa S.r.l. chiedendo la condanna \
        al risarcimento del danno pari a Euro 50.000,00 ai sensi dell'art. \
        2043 c.c., oltre interessi legali e rivalutazione monetaria.

        All'udienza del 10 luglio 2024, le parti precisavano le conclusioni.

        P.Q.M.

        Il Tribunale, definitivamente pronunciando, condanna la convenuta \
        Alfa S.r.l. al pagamento in favore dell'attore della somma di Euro \
        35.000,00 a titolo di risarcimento danni, oltre Euro 5.000,00 per \
        spese di lite.""")

    example_extractions_1 = [
        lx.data.Extraction(
            extraction_class="tribunale",
            extraction_text="TRIBUNALE DI MILANO",
            attributes={"sezione": "III Civile", "numero_rg": "12345/2024"},
        ),
        lx.data.Extraction(
            extraction_class="giudice",
            extraction_text="Dott.ssa Maria Verdi",
            attributes={"ruolo": "giudice_unico"},
        ),
        lx.data.Extraction(
            extraction_class="parte_attore",
            extraction_text="Mario Rossi",
            attributes={"tipo": "persona_fisica", "codice_fiscale": "RSSMRA80A01F205X"},
        ),
        lx.data.Extraction(
            extraction_class="avvocato",
            extraction_text="Avv. Giuseppe Bianchi",
            attributes={"rappresenta": "attore", "foro": "Milano"},
        ),
        lx.data.Extraction(
            extraction_class="parte_convenuto",
            extraction_text="Alfa S.r.l.",
            attributes={"tipo": "persona_giuridica"},
        ),
        lx.data.Extraction(
            extraction_class="avvocato",
            extraction_text="Avv. Laura Neri",
            attributes={"rappresenta": "convenuta", "foro": "Milano"},
        ),
        lx.data.Extraction(
            extraction_class="data_deposito",
            extraction_text="15 marzo 2024",
            attributes={"tipo": "notifica_citazione"},
        ),
        lx.data.Extraction(
            extraction_class="domanda",
            extraction_text="condanna al risarcimento del danno pari a Euro 50.000,00",
            attributes={"tipo": "risarcimento_danni", "importo_richiesto": "50.000,00"},
        ),
        lx.data.Extraction(
            extraction_class="riferimento_normativo",
            extraction_text="art. 2043 c.c.",
            attributes={"fonte": "codice_civile", "materia": "responsabilita_extracontrattuale"},
        ),
        lx.data.Extraction(
            extraction_class="data_udienza",
            extraction_text="10 luglio 2024",
            attributes={"tipo": "precisazione_conclusioni"},
        ),
        lx.data.Extraction(
            extraction_class="dispositivo",
            extraction_text="condanna la convenuta Alfa S.r.l. al pagamento in favore dell'attore della somma di Euro 35.000,00 a titolo di risarcimento danni",
            attributes={"esito": "accoglimento_parziale"},
        ),
        lx.data.Extraction(
            extraction_class="importo",
            extraction_text="Euro 35.000,00",
            attributes={"tipo": "risarcimento_danni", "valuta": "EUR"},
        ),
        lx.data.Extraction(
            extraction_class="importo",
            extraction_text="Euro 5.000,00",
            attributes={"tipo": "spese_di_lite", "valuta": "EUR"},
        ),
    ]

    examples = [
        lx.data.ExampleData(
            text=example_text_1,
            extractions=example_extractions_1,
        ),
    ]

    return SchemaPreset(
        name="full_legal",
        description="Schema completo per documenti legali italiani",
        prompt_description=prompt_description,
        examples=examples,
    )


def build_parties_dates_schema() -> SchemaPreset:
    """Simplified schema extracting only parties and dates."""

    prompt_description = textwrap.dedent("""\
        Estrai solo le parti processuali e le date rilevanti dal documento legale.
        Identifica: attore, convenuto, avvocati, giudice e tutte le date menzionate.
        Usa il testo esatto dal documento. Non parafrasare.""")

    example_text = textwrap.dedent("""\
        Nella causa RG 5678/2023 tra Marco Bianchi, attore, rappresentato \
        dall'Avv. Anna Rossi, e Beta S.p.A., convenuta, il Giudice Dott. \
        Luigi Verdi ha fissato udienza per il 20 settembre 2023.""")

    examples = [
        lx.data.ExampleData(
            text=example_text,
            extractions=[
                lx.data.Extraction(
                    extraction_class="parte_attore",
                    extraction_text="Marco Bianchi",
                    attributes={"tipo": "persona_fisica"},
                ),
                lx.data.Extraction(
                    extraction_class="avvocato",
                    extraction_text="Avv. Anna Rossi",
                    attributes={"rappresenta": "attore"},
                ),
                lx.data.Extraction(
                    extraction_class="parte_convenuto",
                    extraction_text="Beta S.p.A.",
                    attributes={"tipo": "persona_giuridica"},
                ),
                lx.data.Extraction(
                    extraction_class="giudice",
                    extraction_text="Dott. Luigi Verdi",
                    attributes={"ruolo": "giudice_unico"},
                ),
                lx.data.Extraction(
                    extraction_class="data_udienza",
                    extraction_text="20 settembre 2023",
                    attributes={"tipo": "udienza"},
                ),
            ],
        ),
    ]

    return SchemaPreset(
        name="parties_dates",
        description="Schema semplificato: solo parti e date",
        prompt_description=prompt_description,
        examples=examples,
    )


def build_invoice_schema() -> SchemaPreset:
    """Schema completo per l'estrazione dati da fatture italiane."""

    prompt_description = textwrap.dedent("""\
        Estrai informazioni strutturate da questa fattura italiana.
        Identifica e classifica in ordine di apparizione:

        - FORNITORE: ragione sociale, partita IVA, codice fiscale, indirizzo, PEC, REA
        - CLIENTE: ragione sociale, partita IVA, codice fiscale, indirizzo, codice destinatario SDI
        - NUMERO FATTURA: numero progressivo e serie
        - DATA FATTURA: data di emissione
        - DATA SCADENZA: date di scadenza pagamento
        - RIGA: descrizione prodotto/servizio, quantità, prezzo unitario, aliquota IVA, totale riga
        - TOTALE IMPONIBILE: totale imponibile per aliquota IVA
        - IVA: importo IVA per aliquota
        - TOTALE FATTURA: totale complessivo della fattura
        - MODALITA PAGAMENTO: metodo di pagamento (bonifico, assegno, contanti, ecc.)
        - BANCA: coordinate bancarie per pagamento
        - NOTE: note aggiuntive o condizioni particolari

        Usa il testo esatto dal documento per ogni estrazione.
        Non parafrasare e non sovrapporre le entità.
        Fornisci attributi significativi per aggiungere contesto a ogni estrazione.""")

    example_text_1 = textwrap.dedent("""\
        FATTURA N. 001/2024
        Data: 15 gennaio 2024

        FORNITORE
        Tech Solutions S.r.l.
        Via Roma 123, 20121 Milano (MI)
        P.IVA: IT12345678901
        C.F.: 12345678901
        REA: MI-1234567
        PEC: amministrazione@techsolutions.it

        CLIENTE
        Acme Corporation S.p.A.
        Via Garibaldi 45, 10121 Torino (TO)
        P.IVA: IT98765432109
        C.F.: 98765432109
        Codice Destinatario: ABCDEFG

        DETTAGLIO PRESTAZIONI

        1. Consulenza informatica - sviluppo software
           Quantità: 40 ore
           Prezzo unitario: € 80,00
           Aliquota IVA: 22%
           Totale: € 3.200,00

        2. Manutenzione server
           Quantità: 1 mese
           Prezzo unitario: € 500,00
           Aliquota IVA: 22%
           Totale: € 500,00

        RIEPILOGO IVA
        Imponibile 22%: € 3.700,00
        IVA 22%: € 814,00

        TOTALE FATTURA: € 4.514,00

        MODALITÀ DI PAGAMENTO
        Bonifico bancario entro 30 giorni dalla data di fattura
        Scadenza: 14 febbraio 2024

        BANCA
        Banca Popolare
        IBAN: IT60 X054 2811 1010 0000 0123 456
        BIC: BPOPITRRXXX

        Note: Fattura emessa ai sensi dell'art. 1, comma 2, DPR 633/72""")

    example_extractions_1 = [
        lx.data.Extraction(
            extraction_class="numero_fattura",
            extraction_text="001/2024",
            attributes={"numero": "001", "serie": "2024", "tipo": "fattura"},
        ),
        lx.data.Extraction(
            extraction_class="data_fattura",
            extraction_text="15 gennaio 2024",
            attributes={"formato": "gg mese aaaa"},
        ),
        lx.data.Extraction(
            extraction_class="fornitore",
            extraction_text="Tech Solutions S.r.l.",
            attributes={"tipo": "societa", "forma_giuridica": "S.r.l."},
        ),
        lx.data.Extraction(
            extraction_class="partita_iva_fornitore",
            extraction_text="IT12345678901",
            attributes={"tipo": "P.IVA"},
        ),
        lx.data.Extraction(
            extraction_class="codice_fiscale_fornitore",
            extraction_text="12345678901",
            attributes={"tipo": "C.F."},
        ),
        lx.data.Extraction(
            extraction_class="indirizzo_fornitore",
            extraction_text="Via Roma 123, 20121 Milano (MI)",
            attributes={"tipo": "sede_legale"},
        ),
        lx.data.Extraction(
            extraction_class="rea",
            extraction_text="MI-1234567",
            attributes={"ufficio": "Milano"},
        ),
        lx.data.Extraction(
            extraction_class="pec_fornitore",
            extraction_text="amministrazione@techsolutions.it",
            attributes={"tipo": "PEC"},
        ),
        lx.data.Extraction(
            extraction_class="cliente",
            extraction_text="Acme Corporation S.p.A.",
            attributes={"tipo": "societa", "forma_giuridica": "S.p.A."},
        ),
        lx.data.Extraction(
            extraction_class="partita_iva_cliente",
            extraction_text="IT98765432109",
            attributes={"tipo": "P.IVA"},
        ),
        lx.data.Extraction(
            extraction_class="codice_fiscale_cliente",
            extraction_text="98765432109",
            attributes={"tipo": "C.F."},
        ),
        lx.data.Extraction(
            extraction_class="indirizzo_cliente",
            extraction_text="Via Garibaldi 45, 10121 Torino (TO)",
            attributes={"tipo": "sede_legale"},
        ),
        lx.data.Extraction(
            extraction_class="codice_destinatario",
            extraction_text="ABCDEFG",
            attributes={"tipo": "SDI"},
        ),
        lx.data.Extraction(
            extraction_class="riga",
            extraction_text="Consulenza informatica - sviluppo software",
            attributes={
                "quantita": "40 ore",
                "prezzo_unitario": "€ 80,00",
                "aliquota_iva": "22%",
                "totale_riga": "€ 3.200,00",
            },
        ),
        lx.data.Extraction(
            extraction_class="riga",
            extraction_text="Manutenzione server",
            attributes={
                "quantita": "1 mese",
                "prezzo_unitario": "€ 500,00",
                "aliquota_iva": "22%",
                "totale_riga": "€ 500,00",
            },
        ),
        lx.data.Extraction(
            extraction_class="totale_imponibile",
            extraction_text="€ 3.700,00",
            attributes={"aliquota_iva": "22%"},
        ),
        lx.data.Extraction(
            extraction_class="iva",
            extraction_text="€ 814,00",
            attributes={"aliquota": "22%", "imponibile": "€ 3.700,00"},
        ),
        lx.data.Extraction(
            extraction_class="totale_fattura",
            extraction_text="€ 4.514,00",
            attributes={"valuta": "EUR"},
        ),
        lx.data.Extraction(
            extraction_class="modalita_pagamento",
            extraction_text="Bonifico bancario entro 30 giorni dalla data di fattura",
            attributes={"metodo": "bonifico", "termine": "30 giorni"},
        ),
        lx.data.Extraction(
            extraction_class="data_scadenza",
            extraction_text="14 febbraio 2024",
            attributes={"tipo": "scadenza_pagamento"},
        ),
        lx.data.Extraction(
            extraction_class="banca",
            extraction_text="Banca Popolare",
            attributes={"tipo": "istituto_bancario"},
        ),
        lx.data.Extraction(
            extraction_class="iban",
            extraction_text="IT60 X054 2811 1010 0000 0123 456",
            attributes={"tipo": "IBAN"},
        ),
        lx.data.Extraction(
            extraction_class="bic",
            extraction_text="BPOPITRRXXX",
            attributes={"tipo": "BIC"},
        ),
        lx.data.Extraction(
            extraction_class="note",
            extraction_text="Fattura emessa ai sensi dell'art. 1, comma 2, DPR 633/72",
            attributes={"tipo": "riferimento_normativo"},
        ),
    ]

    examples = [
        lx.data.ExampleData(
            text=example_text_1,
            extractions=example_extractions_1,
        ),
    ]

    return SchemaPreset(
        name="invoice",
        description="Schema completo per fatture italiane",
        prompt_description=prompt_description,
        examples=examples,
    )



def build_bank_statement_schema() -> SchemaPreset:
    """Schema per estratti conto bancari italiani."""

    prompt_description = textwrap.dedent("""\
        Estrai informazioni strutturate da questo estratto conto bancario italiano.
        Il documento puo' contenere PIU' estratti conto consecutivi (pagine diverse).
        Identifica e classifica:

        - BANCA: nome dell'istituto bancario (estrailo UNA SOLA VOLTA, anche se
          appare in piu' pagine come intestazione ripetuta)
        - TITOLARE: nome del correntista intestatario del conto (UNA SOLA VOLTA)
        - CONTO: numero di conto corrente e IBAN (UNA SOLA VOLTA, anche se ripetuto
          in piu' pagine)
        - ESTRATTO_CONTO: numero e periodo di OGNI rendiconto (es. N. 003/2024).
          Estraili tutti perche' ogni estratto ha numero e periodo diverso.
        - SALDO_INIZIALE: saldo all'inizio di OGNI periodo (uno per estratto conto)
        - SALDO_FINALE: saldo al termine di OGNI periodo (uno per estratto conto).
          Negli attributi includi il numero dell'estratto conto di riferimento.
        - MOVIMENTO: ogni singolo movimento del conto (addebito o accredito),
          con data operazione, data valuta, descrizione, importo e tipo (addebito/accredito)
        - TOTALE_ADDEBITI: totale degli addebiti di OGNI periodo
        - TOTALE_ACCREDITI: totale degli accrediti di OGNI periodo

        IMPORTANTE - Regole di deduplicazione:
        - Dati fissi (banca, titolare, conto): estraili UNA SOLA VOLTA.
          Non ripetere la stessa entita' solo perche' appare in piu' pagine.
        - Dati variabili (estratto_conto, saldi, movimenti, totali): estraili
          tutti perche' sono diversi per ogni periodo.

        Usa il testo esatto dal documento per ogni estrazione.
        Non parafrasare e non sovrapporre le entita'.
        Per ogni movimento includi importo e tipo (addebito/accredito) negli attributi.""")

    example_text = textwrap.dedent("""\
        INTESA SANPAOLO
        ESTRATTO CONTO N. 003/2024
        AL 30.09.2024
        C/C N. 50381/1000/00000000

        Dettaglio movimenti del conto corrente.

        Saldo iniziale al 30.06.2024  + 3.000,00

        Data Operazione  Data Valuta  Descrizione                      Addebiti   Accrediti
        01.07.2024       01.07.2024   Stipendio o Pensione                          1.500,00
                                     PENSIONE N5400/XXX/00000000/XX RATA07/24
                                     ROSSI MARIO
        02.07.2024       30.06.2024   Spese emis. B/C                      1,50
        16.07.2024       16.07.2024   Bonifico a Vostro favore                       500,00
                                     MITT.: BIANCHI GIOVANNI
        16.07.2024       16.07.2024   Pagamento Utenze                  1.200,00
                                     GESTORE ENERGIA SPA

        Totali                                                          1.201,50   2.000,00

        Saldo finale al 30.09.2024  a Vostro credito  + 3.798,50""")

    example_extractions = [
        lx.data.Extraction(
            extraction_class="banca",
            extraction_text="INTESA SANPAOLO",
            attributes={"tipo": "istituto_bancario"},
        ),
        lx.data.Extraction(
            extraction_class="estratto_conto",
            extraction_text="ESTRATTO CONTO N. 003/2024",
            attributes={"numero": "003/2024", "data_chiusura": "30.09.2024"},
        ),
        lx.data.Extraction(
            extraction_class="conto",
            extraction_text="50381/1000/00000000",
            attributes={"tipo": "conto_corrente"},
        ),
        lx.data.Extraction(
            extraction_class="saldo_iniziale",
            extraction_text="+ 3.000,00",
            attributes={"data": "30.06.2024", "valuta": "EUR", "segno": "credito",
                         "estratto_conto_ref": "003/2024"},
        ),
        lx.data.Extraction(
            extraction_class="movimento",
            extraction_text="Stipendio o Pensione",
            attributes={
                "data_operazione": "01.07.2024",
                "data_valuta": "01.07.2024",
                "importo": "1.500,00",
                "tipo": "accredito",
                "descrizione_extra": "PENSIONE N5400/XXX/00000000/XX RATA07/24 ROSSI MARIO",
            },
        ),
        lx.data.Extraction(
            extraction_class="movimento",
            extraction_text="Spese emis. B/C",
            attributes={
                "data_operazione": "02.07.2024",
                "data_valuta": "30.06.2024",
                "importo": "1,50",
                "tipo": "addebito",
            },
        ),
        lx.data.Extraction(
            extraction_class="movimento",
            extraction_text="Bonifico a Vostro favore",
            attributes={
                "data_operazione": "16.07.2024",
                "data_valuta": "16.07.2024",
                "importo": "500,00",
                "tipo": "accredito",
                "mittente": "BIANCHI GIOVANNI",
            },
        ),
        lx.data.Extraction(
            extraction_class="movimento",
            extraction_text="Pagamento Utenze",
            attributes={
                "data_operazione": "16.07.2024",
                "data_valuta": "16.07.2024",
                "importo": "1.200,00",
                "tipo": "addebito",
                "beneficiario": "GESTORE ENERGIA SPA",
            },
        ),
        lx.data.Extraction(
            extraction_class="totale_addebiti",
            extraction_text="1.201,50",
            attributes={"valuta": "EUR"},
        ),
        lx.data.Extraction(
            extraction_class="totale_accrediti",
            extraction_text="2.000,00",
            attributes={"valuta": "EUR"},
        ),
        lx.data.Extraction(
            extraction_class="saldo_finale",
            extraction_text="+ 3.798,50",
            attributes={"data": "30.09.2024", "valuta": "EUR", "segno": "credito",
                         "estratto_conto_ref": "003/2024"},
        ),
    ]

    examples = [
        lx.data.ExampleData(
            text=example_text,
            extractions=example_extractions,
        ),
    ]

    return SchemaPreset(
        name="estratto_conto",
        description="Schema per estratti conto bancari italiani",
        prompt_description=prompt_description,
        examples=examples,
    )


# Registry of available schema presets
_SCHEMA_REGISTRY: dict[str, callable] = {
    "full_legal": build_full_legal_schema,
    "parties_dates": build_parties_dates_schema,
    "invoice": build_invoice_schema,
    "estratto_conto": build_bank_statement_schema,
}


def build_custom_schema() -> SchemaPreset:
    """Empty custom schema that users can configure via the settings editor."""
    prompt_description = textwrap.dedent("""\
        Estrai informazioni strutturate da questo documento.
        Identifica e classifica le entita' principali presenti nel testo.

        Usa il testo esatto dal documento per ogni estrazione.
        Non parafrasare e non sovrapporre le entita'.
        Fornisci attributi significativi per aggiungere contesto a ogni estrazione.""")

    return SchemaPreset(
        name="custom",
        description="Schema personalizzato (configurabile nelle impostazioni)",
        prompt_description=prompt_description,
        examples=[],
    )


# Add custom to the registry
_SCHEMA_REGISTRY["custom"] = build_custom_schema


def get_schema_preset(name: str) -> SchemaPreset | None:
    """Get a schema preset by name.

    Returns None if name is "none" (no structured extraction).

    Raises:
        KeyError: If the schema name is not found.
    """
    if name == "none":
        return None

    builder = _SCHEMA_REGISTRY.get(name)
    if not builder:
        available = ", ".join(_SCHEMA_REGISTRY.keys())
        raise KeyError(f"Schema '{name}' non trovato. Disponibili: {available}")
    return builder()


def get_available_schemas() -> list[str]:
    """Return list of available schema preset names."""
    return list(_SCHEMA_REGISTRY.keys())
