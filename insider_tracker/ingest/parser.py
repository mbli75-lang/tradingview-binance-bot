"""Parser för FI:s insynsregister-export.

Verifierat format (riktig hämtning 2026-07-15):
  * Innehåll: text/csv, teckenkodning UTF-16, separator ';'
  * Svensk decimal-komma i Volym/Pris ("375000,0", "0,07")
  * 22 kolumner (se COLUMNS nedan)

parse_record() normaliserar en rå FI-rad och applicerar konfigurerbara filter
(instrumenttyp, transaktionskaraktär, marknadsplats, status). Rader som filtreras
bort returnerar None.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass, asdict
from datetime import date, datetime

from insider_tracker.config import Config

# FI:s kolumnrubriker (svenska), i ordning.
COL_PUBLISH = "Publiceringsdatum"
COL_ISSUER = "Emittent"
COL_LEI = "LEI-kod"
COL_OBLIGATED = "Anmälningsskyldig"
COL_PDMR = "Person i ledande ställning"
COL_ROLE = "Befattning"
COL_RELATED = "Närstående"
COL_CORRECTION = "Korrigering"
COL_FIRST_REPORT = "Är förstagångsrapportering"
COL_SHARE_PROGRAM = "Är kopplad till aktieprogram"
COL_CHARACTER = "Karaktär"
COL_INSTRUMENT_TYPE = "Instrumenttyp"
COL_INSTRUMENT_NAME = "Instrumentnamn"
COL_ISIN = "ISIN"
COL_TRADE_DATE = "Transaktionsdatum"
COL_VOLUME = "Volym"
COL_PRICE = "Pris"
COL_CURRENCY = "Valuta"
COL_MARKETPLACE = "Handelsplats"
COL_STATUS = "Status"


@dataclass
class ParsedTransaction:
    # Bolag / instrument
    isin: str
    issuer: str
    lei: str | None
    instrument_type: str | None
    instrument_name: str | None
    # Person
    insider_name: str
    insider_name_normalized: str
    role: str | None
    is_related_party: bool
    # Transaktion
    type: str  # 'buy' | 'sell'
    character_raw: str
    volume: float
    price: float
    currency: str | None
    amount_sek: float | None
    trade_date: date
    publish_date: date
    publish_datetime: datetime | None
    # Marknadsplats / status
    marketplace: str | None       # kanonisk
    marketplace_raw: str | None   # FI:s Handelsplats-sträng
    status: str | None
    is_first_report: bool | None
    linked_to_share_program: bool | None
    # Dedupe
    dedupe_hash: str

    def as_dict(self) -> dict:
        return asdict(self)


def decode_export(raw_bytes: bytes) -> str:
    """Avkoda FI-exportens bytes (UTF-16 med BOM). Fallback till utf-8-sig."""
    for enc in ("utf-16", "utf-8-sig", "latin-1"):
        try:
            return raw_bytes.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw_bytes.decode("utf-16", errors="replace")


def read_rows(csv_text: str) -> list[dict[str, str]]:
    """Läs den avkodade CSV-texten till en lista av dictar (råa FI-kolumner)."""
    reader = csv.DictReader(io.StringIO(csv_text), delimiter=";")
    return [row for row in reader]


def normalize_name(name: str) -> str:
    """Normalisera personnamn för dedupe: trimma, kollapsa mellanslag, gemener.

    Behåller svenska tecken (å/ä/ö) men normaliserar unicode-form (NFC).
    """
    if not name:
        return ""
    name = unicodedata.normalize("NFC", name)
    name = re.sub(r"\s+", " ", name).strip().lower()
    return name


def parse_swedish_number(value: str | None) -> float | None:
    """Tolka svenskt tal: mellanslag/NBSP som tusentalsavgränsare, komma som decimal."""
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None
    s = s.replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_fi_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    s = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _parse_bool_ja(value: str | None) -> bool:
    return (value or "").strip().lower() == "ja"


def map_marketplace(handelsplats: str | None, cfg: Config) -> str | None:
    """FI:s Handelsplats-sträng -> kanonisk marknadsplats, eller None om ej tillåten."""
    if not handelsplats:
        return None
    hp = handelsplats.strip().upper()
    for canonical, raw_values in cfg["ingest"]["marketplaces"].items():
        for raw in raw_values:
            if hp == raw.strip().upper():
                return canonical
    return None


def map_type(character: str | None, cfg: Config) -> str | None:
    """FI:s Karaktär -> 'buy'/'sell', eller None om karaktären inte ska behållas."""
    if not character:
        return None
    ch = character.strip()
    chars = cfg["ingest"]["characters"]
    if ch in chars["buy"]:
        return "buy"
    if ch in chars["sell"]:
        return "sell"
    return None


def compute_dedupe_hash(
    name_normalized: str, isin: str, trade_date: date, volume: float, price: float
) -> str:
    """Dedupe-nyckel enligt kravspec: (person, ISIN, transaktionsdatum, volym, pris)."""
    key = "|".join(
        [
            name_normalized,
            (isin or "").strip().upper(),
            trade_date.isoformat() if trade_date else "",
            f"{volume:.4f}" if volume is not None else "",
            f"{price:.6f}" if price is not None else "",
        ]
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def parse_record(row: dict[str, str], cfg: Config) -> ParsedTransaction | None:
    """Normalisera + filtrera en rå FI-rad. Returnerar None om raden filtreras bort."""
    # --- Filter: status (t.ex. makulerade) ---
    status = (row.get(COL_STATUS) or "").strip()
    if status in cfg["ingest"]["exclude_status"]:
        return None

    # --- Filter: instrumenttyp (endast aktier) ---
    instrument_type = (row.get(COL_INSTRUMENT_TYPE) or "").strip()
    if instrument_type not in cfg["ingest"]["instrument_types"]:
        return None

    # --- Filter: transaktionskaraktär (endast förvärv/avyttring) ---
    character_raw = (row.get(COL_CHARACTER) or "").strip()
    txn_type = map_type(character_raw, cfg)
    if txn_type is None:
        return None

    # --- Filter: marknadsplats ---
    marketplace_raw = (row.get(COL_MARKETPLACE) or "").strip()
    marketplace = map_marketplace(marketplace_raw, cfg)
    if marketplace is None:
        return None

    # --- Obligatoriska fält ---
    isin = (row.get(COL_ISIN) or "").strip().upper()
    insider_name = (row.get(COL_PDMR) or "").strip()
    trade_dt = parse_fi_datetime(row.get(COL_TRADE_DATE))
    publish_dt = parse_fi_datetime(row.get(COL_PUBLISH))
    volume = parse_swedish_number(row.get(COL_VOLUME))
    price = parse_swedish_number(row.get(COL_PRICE))

    if not isin or not insider_name or trade_dt is None or publish_dt is None:
        return None
    if volume is None or price is None:
        return None

    trade_date = trade_dt.date()
    publish_date = publish_dt.date()
    name_norm = normalize_name(insider_name)

    currency = (row.get(COL_CURRENCY) or "").strip() or None
    amount_sek = volume * price if currency == "SEK" else None

    return ParsedTransaction(
        isin=isin,
        issuer=(row.get(COL_ISSUER) or "").strip(),
        lei=(row.get(COL_LEI) or "").strip() or None,
        instrument_type=instrument_type or None,
        instrument_name=(row.get(COL_INSTRUMENT_NAME) or "").strip() or None,
        insider_name=insider_name,
        insider_name_normalized=name_norm,
        role=(row.get(COL_ROLE) or "").strip() or None,
        is_related_party=_parse_bool_ja(row.get(COL_RELATED)),
        type=txn_type,
        character_raw=character_raw,
        volume=volume,
        price=price,
        currency=currency,
        amount_sek=amount_sek,
        trade_date=trade_date,
        publish_date=publish_date,
        publish_datetime=publish_dt,
        marketplace=marketplace,
        marketplace_raw=marketplace_raw or None,
        status=status or None,
        is_first_report=_parse_bool_ja(row.get(COL_FIRST_REPORT)),
        linked_to_share_program=_parse_bool_ja(row.get(COL_SHARE_PROGRAM)),
        dedupe_hash=compute_dedupe_hash(name_norm, isin, trade_date, volume, price),
    )


def parse_export(
    raw_bytes: bytes, cfg: Config
) -> tuple[list[ParsedTransaction], int, int]:
    """Avkoda + parsa hela exporten. Returnerar (parsade, totalt_råa, bortfiltrerade)."""
    text = decode_export(raw_bytes)
    rows = read_rows(text)
    parsed: list[ParsedTransaction] = []
    for row in rows:
        rec = parse_record(row, cfg)
        if rec is not None:
            parsed.append(rec)
    return parsed, len(rows), len(rows) - len(parsed)
