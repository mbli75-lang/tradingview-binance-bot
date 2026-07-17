"""Tester för FI-parsern. Speglar det verifierade formatet (UTF-16, ';', komma-decimal)."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from insider_tracker.config import load_config
from insider_tracker.ingest import parser as P

HEADER = (
    "Publiceringsdatum;Emittent;LEI-kod;Anmälningsskyldig;Person i ledande ställning;"
    "Befattning;Närstående;Korrigering;Beskrivning av korrigering;"
    "Är förstagångsrapportering;Är kopplad till aktieprogram;Karaktär;Instrumenttyp;"
    "Instrumentnamn;ISIN;Transaktionsdatum;Volym;Volymsenhet;Pris;Valuta;Handelsplats;Status;"
)


def _row(**over) -> str:
    """Bygg en rå FI-rad (fältordning enligt HEADER). Defaults = giltig aktie-köp."""
    f = {
        "publish": "2026-07-13 09:15:00",
        "issuer": "Testbolag AB",
        "lei": "549300TESTLEI0000000",
        "obligated": "Anna Andersson",
        "pdmr": "Anna Andersson",
        "role": "Verkställande direktör",
        "related": "",
        "correction": "",
        "corr_desc": "",
        "first_report": "Ja",
        "share_program": "",
        "character": "Förvärv",
        "instrument_type": "Aktie",
        "instrument_name": "Testbolag AB",
        "isin": "SE0000000001",
        "trade_date": "2026-07-10 00:00:00",
        "volume": "12 500,0",
        "unit": "Antal",
        "price": "45,50",
        "currency": "SEK",
        "marketplace": "SPOTLIGHT STOCK MARKET",
        "status": "Aktuell",
    }
    f.update(over)
    return ";".join([
        f["publish"], f["issuer"], f["lei"], f["obligated"], f["pdmr"], f["role"],
        f["related"], f["correction"], f["corr_desc"], f["first_report"],
        f["share_program"], f["character"], f["instrument_type"], f["instrument_name"],
        f["isin"], f["trade_date"], f["volume"], f["unit"], f["price"], f["currency"],
        f["marketplace"], f["status"], "",
    ])


def _csv_bytes(*rows: str) -> bytes:
    return ("\r\n".join([HEADER, *rows]) + "\r\n").encode("utf-16")


@pytest.fixture(scope="module")
def cfg():
    return load_config()


# ---------------- enhetstester på hjälpfunktioner ----------------

def test_parse_swedish_number_decimal_comma():
    assert P.parse_swedish_number("0,07") == pytest.approx(0.07)
    assert P.parse_swedish_number("45,50") == pytest.approx(45.5)


def test_parse_swedish_number_thousands_separator():
    assert P.parse_swedish_number("12 500,0") == pytest.approx(12500.0)
    assert P.parse_swedish_number("1\xa0234\xa0567,5") == pytest.approx(1234567.5)


def test_parse_swedish_number_empty():
    assert P.parse_swedish_number("") is None
    assert P.parse_swedish_number(None) is None


def test_normalize_name():
    assert P.normalize_name("  Anna   Andersson ") == "anna andersson"
    assert P.normalize_name("Åke Öberg") == "åke öberg"


def test_parse_fi_datetime():
    assert P.parse_fi_datetime("2026-07-13 09:15:00") == datetime(2026, 7, 13, 9, 15, 0)
    assert P.parse_fi_datetime("2026-07-13 00:00:00") == datetime(2026, 7, 13)
    assert P.parse_fi_datetime("") is None


def test_dedupe_hash_stable_and_distinct():
    d = date(2026, 7, 10)
    h1 = P.compute_dedupe_hash("anna andersson", "SE0000000001", d, 12500.0, 45.5)
    h2 = P.compute_dedupe_hash("anna andersson", "SE0000000001", d, 12500.0, 45.5)
    h3 = P.compute_dedupe_hash("anna andersson", "SE0000000001", d, 12500.0, 45.6)
    assert h1 == h2
    assert h1 != h3


def test_decode_export_utf16(cfg):
    raw = _csv_bytes(_row())
    text = P.decode_export(raw)
    assert "Publiceringsdatum" in text
    rows = P.read_rows(text)
    assert len(rows) == 1
    assert rows[0]["ISIN"] == "SE0000000001"


# ---------------- parse_record: happy path ----------------

def test_parse_record_valid_buy(cfg):
    rows = P.read_rows(P.decode_export(_csv_bytes(_row())))
    rec = P.parse_record(rows[0], cfg)
    assert rec is not None
    assert rec.type == "buy"
    assert rec.isin == "SE0000000001"
    assert rec.insider_name == "Anna Andersson"
    assert rec.insider_name_normalized == "anna andersson"
    assert rec.volume == pytest.approx(12500.0)
    assert rec.price == pytest.approx(45.5)
    assert rec.amount_sek == pytest.approx(12500.0 * 45.5)
    assert rec.marketplace == "Spotlight"
    assert rec.trade_date == date(2026, 7, 10)
    assert rec.publish_date == date(2026, 7, 13)
    assert rec.is_related_party is False


def test_parse_record_sell_maps_type(cfg):
    rows = P.read_rows(P.decode_export(_csv_bytes(_row(character="Avyttring"))))
    rec = P.parse_record(rows[0], cfg)
    assert rec is not None and rec.type == "sell"


def test_parse_record_related_party(cfg):
    rows = P.read_rows(P.decode_export(_csv_bytes(_row(related="Ja"))))
    rec = P.parse_record(rows[0], cfg)
    assert rec is not None and rec.is_related_party is True


def test_amount_sek_none_for_foreign_currency(cfg):
    rows = P.read_rows(P.decode_export(_csv_bytes(_row(currency="EUR"))))
    rec = P.parse_record(rows[0], cfg)
    assert rec is not None and rec.amount_sek is None


# ---------------- parse_record: filter ----------------

@pytest.mark.parametrize("over", [
    {"instrument_type": "Teckningsoption"},   # ej aktie
    {"instrument_type": "Teckningsrätt/Uniträtt"},
    {"character": "Tilldelning"},             # ej förvärv/avyttring
    {"character": "Teckning"},
    {"marketplace": "XETRA - REGULIERTER MARKT"},  # ej tillåten marknadsplats
    {"marketplace": "Utanför handelsplats"},
    {"status": "Makulerad"},                  # exkluderad status
])
def test_parse_record_filtered_out(cfg, over):
    rows = P.read_rows(P.decode_export(_csv_bytes(_row(**over))))
    assert P.parse_record(rows[0], cfg) is None


def test_marketplace_first_north_variants(cfg):
    for mp in ("FIRST NORTH SWEDEN", "FIRST NORTH SWEDEN - SME GROWTH MARKET"):
        rows = P.read_rows(P.decode_export(_csv_bytes(_row(marketplace=mp))))
        rec = P.parse_record(rows[0], cfg)
        assert rec is not None and rec.marketplace == "First North"


def test_nasdaq_stockholm_kept(cfg):
    rows = P.read_rows(P.decode_export(_csv_bytes(_row(marketplace="NASDAQ STOCKHOLM AB"))))
    rec = P.parse_record(rows[0], cfg)
    assert rec is not None and rec.marketplace == "Nasdaq Stockholm"


# ---------------- parse_export (helhet) ----------------

def test_parse_export_counts(cfg):
    raw = _csv_bytes(
        _row(),                                   # behålls
        _row(character="Tilldelning"),            # bort
        _row(instrument_type="Option"),           # bort
        _row(pdmr="Bertil Bengtsson", isin="SE0000000002", price="10,0"),  # behålls
    )
    parsed, total, filtered = P.parse_export(raw, cfg)
    assert total == 4
    assert len(parsed) == 2
    assert filtered == 2
