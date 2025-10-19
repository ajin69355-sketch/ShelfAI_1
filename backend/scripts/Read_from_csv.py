#!/usr/bin/env python3
"""
CSV -> DB seeder for ShelfAI (mobile-friendly workflow)

- Reads ONE CSV from /data
- Cleans strings, numbers, dates
- Upserts Product by SKU (idempotent)
- Upserts InventoryLot by a stable generated ID (or lot_id if present)
- Safe dry-run mode
"""
import argparse, csv, sys
from pathlib import Path
from datetime import datetime
from decimal import Decimal, InvalidOperation

# --- project imports (adjust if your project names differ) ---
# database session + engine
try:
    from backend.app.database import SessionLocal, engine
except Exception as e:
    print("Import error: backend.app.database (SessionLocal, engine).", e); sys.exit(1)

# models
try:
    from backend.app.models.product import Product
except Exception as e:
    print("Import error: backend.app.models.product.Product", e); sys.exit(1)

try:
    from backend.app.models.inventory_lot import InventoryLot
except Exception as e:
    InventoryLot = None  # lot table optional

# ---------- cleaners ----------
def _s(x): return None if x is None else (str(x).strip() or None)
def _upper(x): 
    s=_s(x); return s.upper() if s else None
def _int(x):
    try: return int(str(x).replace(",", "").strip()) if x not in (None,"") else None
    except: return None
def _dec(x):
    if x in (None,""): return None
    try: return Decimal(str(x).replace(",", "").strip())
    except (InvalidOperation, ValueError): return None
def _date(x):
    x=_s(x)
    if not x: return None
    for f in ("%Y-%m-%d","%d/%m/%Y","%d-%m-%Y","%m/%d/%Y"):
        try: return datetime.strptime(x,f).date()
        except ValueError: pass
    return None

# ---------- helpers ----------
def get_or_create_product_by_sku(db, sku):
    sku = _upper(sku)
    if not sku: return None, "SKIP(no SKU)"
    obj = db.query(Product).filter(Product.sku == sku).one_or_none()
    created = False
    if obj is None:
        obj = Product(sku=sku)
        db.add(obj); db.flush()  # get obj.id
        created = True
    return obj, created

def upsert_product_fields(prod, row):
    # Map common CSV column names (edit left side to match your CSV headers exactly if needed)
    name   = row.get("product_name") or row.get("name")
    cat    = row.get("category")
    ean    = row.get("barcode_ean13") or row.get("barcode")
    ucost  = row.get("unit_cost") or row.get("cost")
    uprice = row.get("unit_price") or row.get("price") or row.get("retail_price")
    rlevel = row.get("reorder_level_qty") or row.get("reorder_point")
    safety = row.get("safety_stock")
    ads    = row.get("avg_daily_sales") or row.get("avg_sales_per_day")

    if hasattr(prod, "product_name") and name is not None: prod.product_name = _s(name)
    if hasattr(prod, "category")     and cat  is not None: prod.category = _s(cat)
    if hasattr(prod, "barcode_ean13")and ean  is not None: prod.barcode_ean13 = _s(ean)
    if hasattr(prod, "unit_cost")    and ucost is not None: prod.unit_cost = _dec(ucost)
    if hasattr(prod, "unit_price")   and uprice is not None: prod.unit_price = _dec(uprice)
    if hasattr(prod, "reorder_level_qty") and rlevel is not None:
        v=_int(rlevel); prod.reorder_level_qty = v if v is not None else prod.reorder_level_qty
    if hasattr(prod, "safety_stock") and safety is not None:
        v=_int(safety); prod.safety_stock = v if v is not None else prod.safety_stock
    if hasattr(prod, "avg_daily_sales") and ads is not None:
        v=_dec(ads); prod.avg_daily_sales = float(v) if v is not None else prod.avg_daily_sales

def stable_lot_id(sku, batch_received_date, expiry_date, explicit_lot_id=None):
    """
    Generate a stable InventoryLot.id if CSV has no lot_id.
    Using SKU + dates makes re-runs idempotent.
    """
    if explicit_lot_id: return _s(explicit_lot_id)
    a = _upper(sku) or "SKU"
    b = _s(batch_received_date) or ""
    c = _s(expiry_date) or ""
    return f"{a}|{b}|{c}"

def upsert_inventory_lot(db, row, product):
    if not InventoryLot or not product:
        return None, "SKIP(no InventoryLot model or product)"
    lot_id = stable_lot_id(
        row.get("sku"), row.get("batch_received_date"), row.get("expiry_date"),
        explicit_lot_id=row.get("lot_id") or row.get("id")
    )
    lot = db.query(InventoryLot).get(lot_id)
    created = False
    if lot is None:
        lot = InventoryLot(id=lot_id, product_id=product.id)
        db.add(lot); db.flush()
        created = True
    # set fields if present
    if hasattr(lot, "product_id"): lot.product_id = product.id
    if hasattr(lot, "lot_qty") and row.get("lot_qty") is not None:
        v=_int(row.get("lot_qty")); lot.lot_qty = v if v is not None else lot.lot_qty
    if hasattr(lot, "batch_received_date") and row.get("batch_received_date") is not None:
        lot.batch_received_date = _date(row.get("batch_received_date")) or lot.batch_received_date
    if hasattr(lot, "expiry_date") and row.get("expiry_date") is not None:
        lot.expiry_date = _date(row.get("expiry_date")) or lot.expiry_date
    return lot, created

def normalize_headers(headers):
    """Build a map of lower_snake header -> original header"""
    mapping = {}
    for h in headers:
        key = h.strip().lower().replace(" ", "_")
        mapping[key] = h
    return mapping

def normalize_row(row, header_map):
    """Return a dict with normalized keys -> values from the original row"""
    out = {}
    for norm, orig in header_map.items():
        out[norm] = row.get(orig)
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="CSV path under /data")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    csv_path = Path(args.file)
    if not csv_path.exists():
        print("CSV not found:", csv_path); sys.exit(1)

    # Optional: create tables in dev; prod uses migrations
    try:
        from backend.app.models import Base
        Base.metadata.create_all(bind=engine)
    except Exception:
        pass

    db = SessionLocal()
    created_p = updated_p = created_l = updated_l = skipped = 0

    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            header_map = normalize_headers(headers)

            for i, raw in enumerate(reader, start=1):
                if args.limit and i > args.limit: break
                row = normalize_row(raw, header_map)

                # 1) Product upsert by SKU
                sku = row.get("sku") or row.get("item_code") or row.get("product_code")
                prod, was_created = get_or_create_product_by_sku(db, sku)
                if not prod:
                    skipped += 1
                    print(f"[{i}] SKIP: no SKU")
                    continue

                before = prod.__dict__.copy()
                upsert_product_fields(prod, row)
                after = prod.__dict__

                if was_created: created_p += 1
                else:
                    # naive update detection
                    updated = any(before.get(k) != after.get(k) for k in after.keys())
                    if updated: updated_p += 1

                # 2) InventoryLot (optional)
                if InventoryLot:
                    lot, lot_created = upsert_inventory_lot(db, row, prod)
                    if lot:
                        if lot_created: created_l += 1
                        else: updated_l += 1

        print(f"\nRESULT: products_created={created_p} products_updated={updated_p} "
              f"lots_created={created_l} lots_updated={updated_l} skipped_rows={skipped}")

        if args.dry_run:
            db.rollback(); print("Dry-run: rolled back.")
        else:
            db.commit(); print("Committed.")
    except Exception as e:
        db.rollback(); print("ERROR while importing:", e); sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()
