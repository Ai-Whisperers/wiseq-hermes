"""Sell-price import for the WiseQ catalogue.

Why this exists
---------------
The client repository ships the *master data* for WiseQ's catalogue -- the
114 components, the 25 bundles, the shipping rules and the tariffs -- but it
does **not** ship the sell prices.  Those live in FiveX and in
``Mastersheet.xlsx``, which are not part of the repository.

That gap has a sharp consequence: after a plain ``POST /ingest`` every
product carries ``price_eur = 0``.  The school-order agent treats a
zero-priced line as a hard stop (``blocked_missing_price``), because
quoting a school EUR 0 for the goods while charging shipping money is a
business error, not a rounding issue.

So prices arrive through this module instead.  Two supported shapes:

1. A CSV export with a header row, e.g.::

       sku_text,price_eur
       231,19.95
       234,24.50

   Column names are matched case-insensitively and a few common aliases are
   accepted (``sku``/``artikelnummer``/``ean``, ``price``/``prijs``/
   ``verkoopprijs``/``sellprice``).  A file without a header row is also
   accepted when it is exactly two columns wide: ``231,19.95``.

2. A JSON object of ``{"sku": price}`` pairs, or a JSON list of
   ``{"sku_text": ..., "price_eur": ...}`` records.

The import is an **upsert** by business SKU, so it can be re-run at any time
and it replaces synthetic prices with real ones without touching anything
else.  Every row it writes also clears the ``synthetic_price`` flag, so a
human can always ask the database "which prices are still guesses?".

Nothing here invents a price.  A row without a usable price is reported as
unresolved, never written as zero.
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# Column aliases -> canonical field.
_SKU_KEYS = {"sku", "sku_text", "skutext", "artikelnummer", "artikel",
             "artikelcode", "productcode", "ean", "barcode"}
_PRICE_KEYS = {"price", "price_eur", "priceeur", "prijs", "verkoopprijs",
               "sellprice", "sell_price", "adviesprijs", "brutoprijs",
               "consumentenprijs"}


@dataclass
class PriceImportResult:
    """Outcome of one price import."""

    rows_seen: int = 0
    prices_written: int = 0
    unresolved: list[str] = field(default_factory=list)
    not_in_catalogue: list[str] = field(default_factory=list)
    source: str | None = None

    def as_dict(self) -> dict:
        return {
            "rows_seen": self.rows_seen,
            "prices_written": self.prices_written,
            "unresolved": self.unresolved,
            "not_in_catalogue": self.not_in_catalogue,
            "source": self.source,
        }


def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (key or "").strip().lower())


def _norm_sku(value: object) -> str:
    """Normalise a SKU to the business key used in ``products.sku_text``.

    Excel and CSV exports love to turn ``231`` into ``231.0`` and
    ``"0231"`` into ``231``.  Numbers are compared as strings, so both
    spellings have to collapse to the same key.

    Bundle SKUs need one more normalisation: the catalogue stores them as
    ``111+216`` (no spaces), while the live storefront and Excel exports
    write ``117 + 240``.  The whitespace around the ``+`` separator is not
    part of the identity of the bundle, so it is removed here.
    """
    text = str(value if value is not None else "").strip()
    if not text:
        return ""
    if re.fullmatch(r"\d+\.0+", text):          # 231.0 -> 231
        text = text.split(".")[0]
    text = re.sub(r"\s*\+\s*", "+", text)         # "117 + 240" -> "117+240"
    if "+" in text:                            # bundle SKU: never strip zeros
        return text
    return text.lstrip("0") or "0"


def _to_price(value: object) -> float | None:
    """Parse a price, accepting both ``19.95`` and ``"EUR 19,95"``.

    Returns ``None`` when the value cannot be read as a number, so the
    caller can report the row instead of silently writing a zero.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value), 2)
    text = str(value).strip()
    if not text:
        return None
    text = re.sub(r"(?i)\b(eur|euro|€)\b", "", text)
    text = text.replace("€", "").replace("\u20ac", "").strip()
    text = text.replace(" ", "")
    text = text.replace("\u00a0", "")
    # Strip currency codes that are glued to the number, e.g. "EUR19,95".
    text = re.sub(r"(?i)^(eur|euro)", "", text).strip()

    # Decide which separator is the decimal point.  Dutch/European exports
    # use a comma for decimals and a dot for thousands ("1.234,56"), but a
    # plain "19.95" is a decimal with a dot.  Rule:
    #   both present  -> the right-most one is the decimal separator
    #   comma only    -> decimal separator
    #   dot only      -> decimal separator, unless it looks like a
    #                    thousands group ("1.234" -> 1234)
    if "," in text and "." in text:
        dec = "," if text.rfind(",") > text.rfind(".") else "."
        thou = "." if dec == "," else ","
        text = text.replace(thou, "").replace(dec, ".")
    elif "," in text:
        text = text.replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")          # 1.234.567 -> 1234567
    elif text.count(".") == 1:
        head, _, tail = text.partition(".")
        # "1.234" is 1234 when the group looks like thousands; "19.95" is
        # a price with two decimals.
        if len(tail) == 3 and len(head) > 0 and tail.isdigit():
            text = text.replace(".", "")
        # else keep the dot as a decimal point

    text = re.sub(r"[^0-9.\-]", "", text)
    if not text or text in {"-", ".", "-."}:
        return None
    try:
        price = float(text)
    except ValueError:
        return None
    if price < 0:
        return None
    return round(price, 2)


def _rows_from_csv(text: str) -> list[dict]:
    """Parse a price CSV into ``{sku, price}`` records.

    Handles a header row, a headerless two-column file, and files whose
    separator is ``;`` (the Dutch Excel default).
    """
    if not text.strip():
        return []

    sample = text[:4096]
    delimiter = ","
    for candidate in (";", "\t", "|"):
        if sample.count(candidate) > sample.count(delimiter):
            delimiter = candidate

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    raw_rows = [r for r in reader if any((c or "").strip() for c in r)]
    if not raw_rows:
        return []

    first = raw_rows[0]
    first_keys = [_norm_key(c) for c in first]
    has_header = any(k in _SKU_KEYS for k in first_keys) and \
        any(k in _PRICE_KEYS for k in first_keys)

    if has_header:
        sku_idx = next(i for i, k in enumerate(first_keys) if k in _SKU_KEYS)
        price_idx = next(i for i, k in enumerate(first_keys) if k in _PRICE_KEYS)
        body = raw_rows[1:]
    else:
        # Headerless: expect exactly two columns (sku, price).
        if len(first) < 2:
            return []
        sku_idx, price_idx = 0, 1
        body = raw_rows

    out: list[dict] = []
    for row in body:
        if len(row) <= max(sku_idx, price_idx):
            continue
        sku = _norm_sku(row[sku_idx])
        price = _to_price(row[price_idx])
        if not sku or price is None:
            out.append({"sku": sku, "price": None})
            continue
        out.append({"sku": sku, "price": price})
    return out


def _rows_from_json(payload: object) -> list[dict]:
    """Parse JSON price payloads into ``{sku, price}`` records."""
    if isinstance(payload, dict):
        # Either {"231": 19.95} or a single record.
        if "sku" in payload or "sku_text" in payload:
            payload = [payload]
        else:
            return [{"sku": _norm_sku(k), "price": _to_price(v)}
                    for k, v in payload.items()]
    if not isinstance(payload, list):
        return []

    out: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        keys = {_norm_key(k): v for k, v in item.items()}
        sku_val = next((v for k, v in keys.items() if k in _SKU_KEYS), None)
        price_val = next((v for k, v in keys.items() if k in _PRICE_KEYS), None)
        sku = _norm_sku(sku_val)
        price = _to_price(price_val)
        if not sku:
            continue
        out.append({"sku": sku, "price": price})
    return out


def parse_price_source(text: str) -> list[dict]:
    """Parse a price export in either CSV or JSON form.

    JSON is detected by the leading ``{`` or ``[``.
    """
    stripped = (text or "").strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            return _rows_from_json(json.loads(stripped))
        except (json.JSONDecodeError, ValueError):
            return []
    return _rows_from_csv(stripped)


def load_prices(db, source: str | Path | list[dict],
                source_name: str | None = None) -> PriceImportResult:
    """Upsert sell prices into the catalogue.

    Parameters
    ----------
    db:
        An open :class:`wiseq.db.db.Database`.
    source:
        A path to a CSV/JSON export, a raw string of CSV/JSON content, or an
        already-parsed list of ``{"sku": ..., "price": ...}`` records.
    source_name:
        Label recorded in the audit trail, e.g. ``"FiveX export 2026-10-29"``.

    Returns a :class:`PriceImportResult` describing exactly what happened.
    A price is written only when the SKU exists in the catalogue *and* the
    value parses as a number; everything else is reported, never guessed.
    """
    result = PriceImportResult(source=source_name)

    rows: list[dict]
    if isinstance(source, list):
        rows = []
        for item in source:
            if not isinstance(item, dict):
                continue
            keys = {_norm_key(k): v for k, v in item.items()}
            sku_val = next((v for k, v in keys.items() if k in _SKU_KEYS), None)
            price_val = next((v for k, v in keys.items() if k in _PRICE_KEYS), None)
            sku = _norm_sku(sku_val)
            price = _to_price(price_val)
            if not sku:
                continue
            rows.append({"sku": sku, "price": price})
    else:
        if isinstance(source, (str, Path)) and not str(source).lstrip().startswith(
                ("{", "[")):
            path = Path(source)
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="replace")
                result.source = source_name or path.name
            else:
                # Not a path -> treat the string as raw CSV content.
                text = str(source)
                result.source = source_name
        else:
            text = str(source)
            result.source = source_name

        rows = parse_price_source(text)

    catalogue = {r["sku_text"]: r["title"]
                 for r in db.query("SELECT sku_text, title FROM products")}

    result.rows_seen = len(rows)
    for row in rows:
        sku = row.get("sku") or ""
        price = row.get("price")
        if not sku:
            result.unresolved.append("<blank sku>")
            continue
        if price is None:
            result.unresolved.append(f"{sku}: unreadable price")
            continue
        if sku not in catalogue:
            result.not_in_catalogue.append(sku)
            continue
        db.execute(
            "UPDATE products SET price_eur=?, synthetic_price=0 "
            "WHERE sku_text=?", (price, sku))
        result.prices_written += 1

    return result
