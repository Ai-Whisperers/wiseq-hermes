"""Seed realistic operational history so the agents have something to chew on.

The seed deliberately reproduces the *shape* of WiseQ's real business:

  * school/B2B orders with mixed categories (some framable, some not)
  * a bol.com marketplace order
  * six months of purchase history for the purchase-intelligence agent
  * a bol.com listing set with the content problems Rob saw in the
    platform report (small images, off-length titles, weak keyword scores)

All names, e-mails and figures are synthetic.  Real customer data never
enters this file.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from .db.db import Database, new_id

SCHOOLS = [
    ("Basisschool De Zon", "info@basisschool-dezon.test", "Amsterdam", True),
    ("Obs De Doorbraak", "admin@obs-doorbraak.test", "Utrecht", False),
    ("BS De Rietplas", "bureau@rietplas.test", "Grootebroek", False),
    ("Stichting Talentenpunt", "info@talentenpunt.test", "Alkmaar", True),
    ("Middelbare School Zandvliet", "administratie@zandvliet.test", "Haarlem", False),
    ("Internaat School De Brug", "info@debrug.test", "Amsterdam", False),
]

INBOUND_EMAILS = [
    """Beste WiseQ,

Graag ontvangen wij een offerte voor de volgende artikelen voor onze
leerlingen:
- 117 x 2
- 234 x 10

Aantal is 12 stuks in totaal. Graag levering voor 15 november.

Met vriendelijke groet,
Basisschool De Zon
info@basisschool-dezon.test
Inkooporder: PO-2026-4412
""",
    """Goedendag,

Wij bestellen graag voor onze leerlingen:
- 101 x 25
- 207 x 50

Kunt u een offerte sturen inclusief verzendkosten naar Nederland?

Met vriendelijke groet,
Obs De Doorbraak
admin@obs-doorbraak.test
""",
    """Hallo WiseQ team,

Voor ons schoolfeest willen wij 30 oortjes en 5 opladers bestellen.
Kunnen jullie een pakketprijs geven voor:
- 103 x 30
- 106 x 5

Groet,
BS De Rietplas
bureau@rietplas.test
""",
    """Beste,

Wij willen graag uitbreiden met de volgende combinaties:
- 113+216 x 3
- 111 + 216 x 6

Kunt u bevestigen of deze op voorraad zijn? Wij ontvangen graag een factuur.

Met vriendelijke groet,
Stichting Talentenpunt
info@talentenpunt.test
""",
]


def _rand_price(seed_sku: str) -> float:
    rng = random.Random(seed_sku)
    return round(rng.uniform(6.5, 34.9), 2)


def seed_stock(db: Database, random_seed: int = 20261029) -> dict:
    """Populate the stock table ONLY -- no prices, no orders.

    ``seed_all`` also rewrites ``products.price_eur`` with random values,
    which would destroy the live Shopify prices the client demo imports.
    The low-stock price guard, however, needs stock rows to have anything
    to say.  This function fills stock and nothing else, so the demo can
    show the guard working against real catalogue prices.

    The distribution is deterministic: the same seed always produces the
    same stock levels, so the demo output is reproducible.
    """
    db.init_schema()
    rng = random.Random(random_seed)
    products = db.query(
        "SELECT sku_text, product_type FROM products ORDER BY sku_text")
    counts = {"skus": len(products), "low_stock": 0}
    for p in products:
        # Bundles are made of components; stock them at the component level.
        if p["product_type"] == "bundle":
            on_hand = rng.choice([40, 120, 300])
        else:
            on_hand = rng.choice([0, 5, 12, 40, 120, 300])
        # Reserved units are already spoken for, so they cannot exceed
        # what is on hand -- a negative "available" would be nonsense and
        # would also make the low-stock list look worse than reality.
        reserved = 0 if on_hand == 0 else min(on_hand,
                                            rng.choice([0, 0, 0, 2, 8]))
        db.execute(
            """INSERT INTO stock (sku, on_hand, reserved) VALUES (?,?,?)
               ON CONFLICT(sku) DO UPDATE SET on_hand=excluded.on_hand,
                                           reserved=excluded.reserved""",
            (p["sku_text"], on_hand, reserved))
        if on_hand - reserved <= 10:
            counts["low_stock"] += 1
    return counts


def seed_all(db: Database, months_of_history: int = 6,
             random_seed: int = 20261029) -> dict:
    rng = random.Random(random_seed)
    db.init_schema()

    # -- prices on the catalogue -------------------------------------
    products = db.query("SELECT sku_text, product_type FROM products")
    for p in products:
        price = 0.0 if p["product_type"] == "bundle" else _rand_price(p["sku_text"])
        weight = 0 if p["product_type"] == "bundle" else rng.choice(
            [60, 90, 120, 180, 250, 320, 450, 700])
        db.execute(
            "UPDATE products SET price_eur=?, weight_gram=? WHERE sku_text=?",
            (price, weight, p["sku_text"]))
        db.execute(
            "INSERT INTO stock (sku, on_hand, reserved) VALUES (?,?,0) "
            "ON CONFLICT(sku) DO UPDATE SET on_hand=excluded.on_hand",
            (p["sku_text"], rng.choice([0, 5, 12, 40, 120, 300])))

    # -- schools -------------------------------------------------------
    school_ids = []
    for name, email, city, stichting in SCHOOLS:
        sid = new_id()
        db.execute(
            """INSERT INTO schools (school_id, name, email, contact_person, city,
                                   country, is_stichting, segment)
               VALUES (?,?,?,?,?,?,?,?)""",
            (sid, name, email, None, city, "NL", 1 if stichting else 0, "school"))
        school_ids.append(sid)

    # -- six months of purchase history -------------------------------
    # Real orders, so the FK on order_lines holds and the rolling-average
    # maths sees genuine order_lines rows.
    components = [r["sku_text"] for r in
                  db.query("SELECT sku_text FROM products WHERE product_type='component'")]
    now = datetime.utcnow()
    made = 0
    for month in range(months_of_history):
        n_orders = rng.randint(3, 6)
        for o in range(n_orders):
            order_id = new_id()
            order_number = f"HIST-{now:%Y%m}-{month:02d}-{o:02d}"
            created = now - timedelta(days=rng.randint(month * 30, month * 30 + 29),
                                      hours=rng.randint(0, 23))
            rows = []
            for _ in range(rng.randint(1, 4)):
                sku = rng.choice(components)
                price_row = db.query_one("SELECT price_eur FROM products WHERE sku_text=?",
                                         (sku,))
                price = float(price_row["price_eur"] or 0) if price_row else 10.0
                qty = rng.randint(1, 40)
                rows.append((new_id(), order_id, sku, f"seed-{sku}", qty,
                             price, round(price * qty, 2), None, None, None, 0,
                             "framed", 0, created.isoformat()))
            subtotal = round(sum(r[6] for r in rows), 2)
            db.execute(
                """INSERT INTO orders (order_id, order_number, customer_id, channel, status,
                                       total_eur, shipping_eur, discount_pct, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (order_id, order_number, school_ids[rng.randrange(len(school_ids))],
                 "b2b_school", "delivered", subtotal, 0, 0, created.isoformat()))
            db.executemany(
                """INSERT INTO order_lines (line_id, order_id, sku, title, quantity,
                        unit_price_eur, line_total_eur, rule_key, carrier, tariff_key,
                        shipping_eur, framing_status, is_bundle, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
            made += 1

    # -- bol.com listing set with the content problems Rob described --
    listings = []
    for i in range(40):
        title_len = rng.choice([22, 35, 55, 78, 140])
        desc_len = rng.choice([60, 110, 300, 950, 1200])
        image = rng.choice([800, 1000, 1200, 1500, 2000])
        kw = round(rng.uniform(1.0, 5.0), 2)
        content = round(rng.uniform(1.0, 5.0), 2)
        listings.append((
            f"listing-{i:03d}", rng.choice(["WiseQ NL", "WiseQ Electronics"]),
            None, f"Seed listing {i}", title_len, desc_len, image, kw, content, 1,
            None))
    db.executemany(
        """INSERT INTO assortment (listing_id, account, sku, title, title_len,
                description_len, image_px, keyword_score, content_score, online, issues)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""", listings)

    return {"schools": len(school_ids), "history_orders": made,
            "listings": len(listings)}