import type { SchemaPreset, ExampleData } from "./types";

function buildFullLegalSchema(): SchemaPreset {
  const promptDescription = `Estrai informazioni strutturate da questo documento legale italiano.
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
Fornisci attributi significativi per aggiungere contesto a ogni estrazione.`;

  const examples: ExampleData[] = [
    {
      text: `TRIBUNALE DI MILANO
Sezione III Civile
R.G. n. 12345/2024

SENTENZA

Il Giudice Dott.ssa Maria Verdi, nella causa promossa da:

Mario Rossi, C.F. RSSMRA80A01F205X, rappresentato e difeso dall'Avv. Giuseppe Bianchi del Foro di Milano,

ATTORE

contro

Alfa S.r.l., in persona del legale rappresentante pro tempore, rappresentata e difesa dall'Avv. Laura Neri del Foro di Milano,

CONVENUTA

ha pronunciato la seguente sentenza.

Con atto di citazione notificato in data 15 marzo 2024, l'attore conveniva in giudizio la societa' Alfa S.r.l. chiedendo la condanna al risarcimento del danno pari a Euro 50.000,00 ai sensi dell'art. 2043 c.c., oltre interessi legali e rivalutazione monetaria.

All'udienza del 10 luglio 2024, le parti precisavano le conclusioni.

P.Q.M.

Il Tribunale, definitivamente pronunciando, condanna la convenuta Alfa S.r.l. al pagamento in favore dell'attore della somma di Euro 35.000,00 a titolo di risarcimento danni, oltre Euro 5.000,00 per spese di lite.`,
      extractions: [
        { extraction_class: "tribunale", extraction_text: "TRIBUNALE DI MILANO", attributes: { sezione: "III Civile", numero_rg: "12345/2024" } },
        { extraction_class: "giudice", extraction_text: "Dott.ssa Maria Verdi", attributes: { ruolo: "giudice_unico" } },
        { extraction_class: "parte_attore", extraction_text: "Mario Rossi", attributes: { tipo: "persona_fisica", codice_fiscale: "RSSMRA80A01F205X" } },
        { extraction_class: "avvocato", extraction_text: "Avv. Giuseppe Bianchi", attributes: { rappresenta: "attore", foro: "Milano" } },
        { extraction_class: "parte_convenuto", extraction_text: "Alfa S.r.l.", attributes: { tipo: "persona_giuridica" } },
        { extraction_class: "avvocato", extraction_text: "Avv. Laura Neri", attributes: { rappresenta: "convenuta", foro: "Milano" } },
        { extraction_class: "data_deposito", extraction_text: "15 marzo 2024", attributes: { tipo: "notifica_citazione" } },
        { extraction_class: "domanda", extraction_text: "condanna al risarcimento del danno pari a Euro 50.000,00", attributes: { tipo: "risarcimento_danni", importo_richiesto: "50.000,00" } },
        { extraction_class: "riferimento_normativo", extraction_text: "art. 2043 c.c.", attributes: { fonte: "codice_civile", materia: "responsabilita_extracontrattuale" } },
        { extraction_class: "data_udienza", extraction_text: "10 luglio 2024", attributes: { tipo: "precisazione_conclusioni" } },
        { extraction_class: "dispositivo", extraction_text: "condanna la convenuta Alfa S.r.l. al pagamento in favore dell'attore della somma di Euro 35.000,00 a titolo di risarcimento danni", attributes: { esito: "accoglimento_parziale" } },
        { extraction_class: "importo", extraction_text: "Euro 35.000,00", attributes: { tipo: "risarcimento_danni", valuta: "EUR" } },
        { extraction_class: "importo", extraction_text: "Euro 5.000,00", attributes: { tipo: "spese_di_lite", valuta: "EUR" } },
      ],
    },
  ];

  return {
    name: "full_legal",
    description: "Schema completo per documenti legali italiani",
    promptDescription,
    examples,
  };
}

function buildPartiesDatesSchema(): SchemaPreset {
  const promptDescription = `Estrai solo le parti processuali e le date rilevanti dal documento legale.
Identifica: attore, convenuto, avvocati, giudice e tutte le date menzionate.
Usa il testo esatto dal documento. Non parafrasare.`;

  const examples: ExampleData[] = [
    {
      text: `Nella causa RG 5678/2023 tra Marco Bianchi, attore, rappresentato dall'Avv. Anna Rossi, e Beta S.p.A., convenuta, il Giudice Dott. Luigi Verdi ha fissato udienza per il 20 settembre 2023.`,
      extractions: [
        { extraction_class: "parte_attore", extraction_text: "Marco Bianchi", attributes: { tipo: "persona_fisica" } },
        { extraction_class: "avvocato", extraction_text: "Avv. Anna Rossi", attributes: { rappresenta: "attore" } },
        { extraction_class: "parte_convenuto", extraction_text: "Beta S.p.A.", attributes: { tipo: "persona_giuridica" } },
        { extraction_class: "giudice", extraction_text: "Dott. Luigi Verdi", attributes: { ruolo: "giudice_unico" } },
        { extraction_class: "data_udienza", extraction_text: "20 settembre 2023", attributes: { tipo: "udienza" } },
      ],
    },
  ];

  return {
    name: "parties_dates",
    description: "Schema semplificato: solo parti e date",
    promptDescription,
    examples,
  };
}

function buildInvoiceSchema(): SchemaPreset {
  const promptDescription = `Estrai informazioni strutturate da questa fattura italiana.
Identifica e classifica in ordine di apparizione:

- FORNITORE: ragione sociale, partita IVA, codice fiscale, indirizzo, PEC, REA
- CLIENTE: ragione sociale, partita IVA, codice fiscale, indirizzo, codice destinatario SDI
- NUMERO FATTURA: numero progressivo e serie
- DATA FATTURA: data di emissione
- DATA SCADENZA: date di scadenza pagamento
- RIGA: descrizione prodotto/servizio, quantita', prezzo unitario, aliquota IVA, totale riga
- TOTALE IMPONIBILE: totale imponibile per aliquota IVA
- IVA: importo IVA per aliquota
- TOTALE FATTURA: totale complessivo della fattura
- MODALITA PAGAMENTO: metodo di pagamento (bonifico, assegno, contanti, ecc.)
- BANCA: coordinate bancarie per pagamento
- NOTE: note aggiuntive o condizioni particolari

Usa il testo esatto dal documento per ogni estrazione.
Non parafrasare e non sovrapporre le entita'.
Fornisci attributi significativi per aggiungere contesto a ogni estrazione.`;

  const examples: ExampleData[] = [
    {
      text: `FATTURA N. 001/2024
Data: 15 gennaio 2024

FORNITORE
Tech Solutions S.r.l.
Via Roma 123, 20121 Milano (MI)
P.IVA: IT12345678901

CLIENTE
Acme Corporation S.p.A.
Via Garibaldi 45, 10121 Torino (TO)
P.IVA: IT98765432109

DETTAGLIO PRESTAZIONI

1. Consulenza informatica - sviluppo software
   Quantita': 40 ore, Prezzo unitario: EUR 80,00, IVA: 22%, Totale: EUR 3.200,00

TOTALE FATTURA: EUR 4.514,00

Pagamento: Bonifico bancario entro 30 giorni
IBAN: IT60 X054 2811 1010 0000 0123 456`,
      extractions: [
        { extraction_class: "numero_fattura", extraction_text: "001/2024", attributes: { numero: "001", serie: "2024" } },
        { extraction_class: "data_fattura", extraction_text: "15 gennaio 2024", attributes: { formato: "gg mese aaaa" } },
        { extraction_class: "fornitore", extraction_text: "Tech Solutions S.r.l.", attributes: { tipo: "societa", forma_giuridica: "S.r.l." } },
        { extraction_class: "cliente", extraction_text: "Acme Corporation S.p.A.", attributes: { tipo: "societa", forma_giuridica: "S.p.A." } },
        { extraction_class: "riga", extraction_text: "Consulenza informatica - sviluppo software", attributes: { quantita: "40 ore", prezzo_unitario: "EUR 80,00", aliquota_iva: "22%", totale_riga: "EUR 3.200,00" } },
        { extraction_class: "totale_fattura", extraction_text: "EUR 4.514,00", attributes: { valuta: "EUR" } },
        { extraction_class: "modalita_pagamento", extraction_text: "Bonifico bancario entro 30 giorni", attributes: { metodo: "bonifico", termine: "30 giorni" } },
        { extraction_class: "iban", extraction_text: "IT60 X054 2811 1010 0000 0123 456", attributes: { tipo: "IBAN" } },
      ],
    },
  ];

  return {
    name: "invoice",
    description: "Schema completo per fatture italiane",
    promptDescription,
    examples,
  };
}

function buildBankStatementSchema(): SchemaPreset {
  const promptDescription = `Estrai informazioni strutturate da questo estratto conto bancario italiano.
Il documento puo' contenere PIU' estratti conto consecutivi (pagine diverse).
Identifica e classifica:

- BANCA: nome dell'istituto bancario (UNA SOLA VOLTA)
- TITOLARE: nome del correntista intestatario del conto (UNA SOLA VOLTA)
- CONTO: numero di conto corrente e IBAN (UNA SOLA VOLTA)
- ESTRATTO_CONTO: numero e periodo di OGNI rendiconto
- SALDO_INIZIALE: saldo all'inizio di OGNI periodo
- SALDO_FINALE: saldo al termine di OGNI periodo
- MOVIMENTO: ogni singolo movimento del conto con data, descrizione, importo e tipo
- TOTALE_ADDEBITI: totale degli addebiti di OGNI periodo
- TOTALE_ACCREDITI: totale degli accrediti di OGNI periodo

Dati fissi (banca, titolare, conto): estraili UNA SOLA VOLTA.
Dati variabili (estratto_conto, saldi, movimenti, totali): estraili tutti.

Usa il testo esatto dal documento per ogni estrazione.
Non parafrasare e non sovrapporre le entita'.`;

  const examples: ExampleData[] = [
    {
      text: `INTESA SANPAOLO
ESTRATTO CONTO N. 003/2024
AL 30.09.2024
C/C N. 50381/1000/00002230

Saldo iniziale al 30.06.2024  + 3.086,87

Data Operazione  Data Valuta  Descrizione                      Addebiti   Accrediti
01.07.2024       01.07.2024   Stipendio o Pensione                          1.886,03
02.07.2024       30.06.2024   Spese emis. B/C                      0,70

Totali                                                          6.327,20   7.050,08

Saldo finale al 30.09.2024  a Vostro credito  + 3.809,75`,
      extractions: [
        { extraction_class: "banca", extraction_text: "INTESA SANPAOLO", attributes: { tipo: "istituto_bancario" } },
        { extraction_class: "estratto_conto", extraction_text: "ESTRATTO CONTO N. 003/2024", attributes: { numero: "003/2024", data_chiusura: "30.09.2024" } },
        { extraction_class: "conto", extraction_text: "50381/1000/00002230", attributes: { tipo: "conto_corrente" } },
        { extraction_class: "saldo_iniziale", extraction_text: "+ 3.086,87", attributes: { data: "30.06.2024", valuta: "EUR", segno: "credito" } },
        { extraction_class: "movimento", extraction_text: "Stipendio o Pensione", attributes: { data_operazione: "01.07.2024", data_valuta: "01.07.2024", importo: "1.886,03", tipo: "accredito" } },
        { extraction_class: "movimento", extraction_text: "Spese emis. B/C", attributes: { data_operazione: "02.07.2024", data_valuta: "30.06.2024", importo: "0,70", tipo: "addebito" } },
        { extraction_class: "totale_addebiti", extraction_text: "6.327,20", attributes: { valuta: "EUR" } },
        { extraction_class: "totale_accrediti", extraction_text: "7.050,08", attributes: { valuta: "EUR" } },
        { extraction_class: "saldo_finale", extraction_text: "+ 3.809,75", attributes: { data: "30.09.2024", valuta: "EUR", segno: "credito" } },
      ],
    },
  ];

  return {
    name: "estratto_conto",
    description: "Schema per estratti conto bancari italiani",
    promptDescription,
    examples,
  };
}

function buildCustomSchema(): SchemaPreset {
  return {
    name: "custom",
    description: "Schema personalizzato (configurabile nelle impostazioni)",
    promptDescription: `Estrai informazioni strutturate da questo documento.
Identifica e classifica le entita' principali presenti nel testo.

Usa il testo esatto dal documento per ogni estrazione.
Non parafrasare e non sovrapporre le entita'.
Fornisci attributi significativi per aggiungere contesto a ogni estrazione.`,
    examples: [],
  };
}

const SCHEMA_REGISTRY: Record<string, () => SchemaPreset> = {
  full_legal: buildFullLegalSchema,
  parties_dates: buildPartiesDatesSchema,
  invoice: buildInvoiceSchema,
  estratto_conto: buildBankStatementSchema,
  custom: buildCustomSchema,
};

export function getSchemaPreset(name: string): SchemaPreset | null {
  if (name === "none") return null;
  const builder = SCHEMA_REGISTRY[name];
  if (!builder) {
    throw new Error(
      `Schema '${name}' non trovato. Disponibili: ${Object.keys(SCHEMA_REGISTRY).join(", ")}`
    );
  }
  return builder();
}

export function getAvailableSchemas(): string[] {
  return Object.keys(SCHEMA_REGISTRY);
}
