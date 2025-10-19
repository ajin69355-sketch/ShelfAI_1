#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Seed DB from CSV (ShelfAI) — aligned to your models and header row.

Expected CSV headers (exact):
product_id, lot_id, sku, product_name, category, barcode_ean13,
location_id, location_name, supplier_id, use_by_or_best_before,
batch_received_date, expiry_date, opening_stock_qty, lot_qty,
reorder_level_qty, unit_cost, unit_price, avg_daily_sales,
safety_stock, case_size, max_stock
"""

import argparse, csv, os, sys
from pathlib import Path
from datetime import datetime

# ---------- DB session / Base (supports common layouts + DATABASE_URL fallback)
SessionLocal = engine = Base = None
try:
    from backend.app.db.session import SessionLocal, engine  # type: ignore
    from backend.app.db.base_class import Base               # type: ignore
except Exception:
    pass
if SessionLocal is None or engine is None or Base is None:
    try:
        from backend.app.database import SessionLocal, engine, Base  # type: ignore
    except Exception:
        pass
if SessionLocal is None or engine is None or Base is None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker, declarative_base
    DB_URL = os.getenv("DATABASE_URL")
    if not DB_URL:
        print("ERROR: DATABASE_URL not set and app DB session not importable.")
        sys.exit(1)
    engine = create_engine(DB_URL, future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base = declarative_base()

# ---------- Models
try:
    from backend.app.models.product import Product  # type: ignore
except Exception as e:
    print("Import error: models.product.Product ->", e); sys.exit(1)
try:
    from backend.app.models.inventory_lot import InventoryLot  # type: ignore
except Exception:
    InventoryLot = None  # allow product-only loads

# ---------- Cleaners
def _s(x):   return None if x is None else (str(x).strip() or None)
def _upper(x):
    s = _s(x); return s.upper() if s else None
def _int(x):
    try: return int(str(x).replace(",", "").strip()) if x not in (None,"") else None
    except: return None
def _float(x):
    if x in (None,""): return None
    try: return float(str(x).replace(",", "").strip())
    except: return None
def _ean13(x):
    if x in (None,""): return None
    digits = "".join(ch for ch in str(x) if ch.isdigit())
    return digits[:13] if digits else None
def _date(x):
    x = _s(x)
    if not x: return None
    for f in ("%Y-%m-%d","%d/%m/%Y","%d-%m-%Y","%m/%d/%Y"):
        try: return datetime.strptime(x, f).date()
        except ValueError: pass
    return None
def _date_iso(x):
    d = _date(x); return d.isoformat() if d else ""

# ---------- Product upsert
def find_or_create_product(db, product_id, sku):
    """
    Prefer explicit product_id; else unique sku. Create if missing with id=(product_id or sku).
    NOTE: Your Product.id is String PK, so passing id is correct.
    """
    if product_id:
        p = db.get(Product, product_id)
        if p: return p, False
    if sku:
        p = db.query(Product).filter(Product.sku == sku).one_or_none()
        if p: return p, False
    if not (product_id or sku):
        return None, "SKIP(no id/sku)"
    p = Product(id=(product_id or sku), sku=(sku or product_id))
    db.add(p); db.flush()
    return p, True

def update_product_fields(prod, row):
    # Required & core identifiers
    name = _s(row.get("product_name")) or prod.sku  # product_name is NOT NULL -> fallback to SKU
    prod.product_name = name
    sku  = _upper(row.get("sku"))
    if sku: prod.sku = sku

    # Descriptive
    cat  = _s(row.get("category"));           prod.category = cat if cat is not None else prod.category
    ean  = _ean13(row.get("barcode_ean13"));  prod.barcode_ean13 = ean if ean is not None else prod.barcode_ean13

    # Financials (Float columns in your model)
    uc = _float(row.get("unit_cost"));   prod.unit_cost  = uc if uc is not None else prod.unit_cost
    up = _float(row.get("unit_price"));  prod.unit_price = up if up is not None else prod.unit_price

    # Inventory strategy (Ints/Floats as per model)
    rl = _int(row.get("reorder_level_qty"));    prod.reorder_level_qty = rl if rl is not None else prod.reorder_level_qty
    ss = _int(row.get("safety_stock"));         prod.safety_stock      = ss if ss is not None else prod.safety_stock
    ads = _float(row.get("avg_daily_sales"));   prod.avg_daily_sales   = ads if ads is not None else prod.avg_daily_sales

# ---------- Lot upsert
def make_lot_id(row, sku):
    """Prefer explicit lot_id; else generate stable id for idempotency."""
    explicit = _s(row.get("lot_id"))
    if explicit: return explicit
    b = _date_iso(row.get("batch_received_date"))
    e = _date_iso(row.get("expiry_date") or row.get("use_by_or_best_before"))
    return f"{_upper(sku) or 'SKU'}|{b}|{e}"

def upsert_lot(db, row, product):
    if not InventoryLot or not product:
        return None, "SKIP(no lot model or no product)"
    lot_id = make_lot_id(row, product.sku)
    lot = db.get(InventoryLot, lot_id)
    created = False
    if lot is None:
        lot = InventoryLot(id=lot_id, product_id=product.id)
        db.add(lot); db.flush()
        created = True

    # mandatory lot_qty (nullable=False in your model) -> use lot_qty or fallback to opening_stock_qty
    qty_raw = row.get("lot_qty")
    if qty_raw in (None, ""):
        qty_raw = row.get("opening_stock_qty")
    q = _int(qty_raw)
    if q is None:
        # Can't satisfy NOT NULL -> skip this lot row safely
        return lot if not created else None, "SKIP(missing lot_qty/opening_stock_qty)"

    lot.lot_qty = q
    # dates
    br = _date(row.get("batch_received_date"))
    if br: lot.batch_received_date = br
    ex = _date(row.get("expiry_date") or row.get("use_by_or_best_before"))
    if ex: lot.expiry_date = ex

    # link FK
    lot.product_id = product.id
    return lot, created

# ---------- Main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="Path to CSV (e.g. data/shelfai_stock_lots_UPDATED.csv)")
    ap.add_argument("--dry-run", action="store_true", help="Parse & upsert without commit")
    ap.add_argument("--limit", type=int, default=None, help="Stop after N rows (debug)")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        print("CSV not found:", path); sys.exit(1)

    # Create tables if missing (dev/CI). Prod should use migrations.
    try:
        Base.metadata.create_all(bind=engine)
    except Exception:
        pass

    db = SessionLocal()
    created_p = updated_p = created_l = updated_l = skipped = 0

    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            rdr = csv.DictReader(f)
            if not rdr.fieldnames:
                print("Empty CSV or missing header"); sys.exit(1)

            for i, row in enumerate(rdr, start=1):
                if args.limit and i > args.limit: break

                sku = _upper(row.get("sku"))
                product_id = _s(row.get("product_id"))

                prod, created = find_or_create_product(db, product_id, sku)
                if prod is None:
                    skipped += 1
                    print(f"[{i}] SKIP: no product_id/sku")
                    continue

                # update product (track minimal fields to infer "updated")
                before = (prod.product_name, prod.category, prod.barcode_ean13,
                          prod.unit_cost, prod.unit_price, prod.reorder_level_qty,
                          prod.safety_stock, prod.avg_daily_sales)
                update_product_fields(prod, row)
                after  = (prod.product_name, prod.category, prod.barcode_ean13,
                          prod.unit_cost, prod.unit_price, prod.reorder_level_qty,
                          prod.safety_stock, prod.avg_daily_sales)
                if created: created_p += 1
                elif before != after: updated_p += 1

                # lots (if the table is present)
                if InventoryLot:
                    lot, lot_created = upsert_lot(db, row, prod)
                    if lot_created is True: created_l += 1
                    elif lot_created is False: updated_l += 1
                    else:
                        # lot_created holds a string when skipped; count skip
                        if isinstance(lot_created, str): skipped += 1

        print(f"\nRESULT: products_created={created_p} products_updated={updated_p} "
              f"lots_created={created_l} lots_updated={updated_l} skipped_rows={skipped}")

        if args.dry_run:
            db.rollback(); print("Dry-run: rolled back.")
        else:
            db.commit(); print("Committed.")
    except Exception as e:
        db.rollback(); print("ERROR during import:", e); sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()
