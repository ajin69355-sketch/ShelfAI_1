import os
import pandas as pd
from typing import List
from pydantic import ValidationError

from .models import CleanStockLot

COLUMN_MAPPING = {
    "product_id": "product_id",
    "lot_id": "lot_id",
    "barcode_ean13": "barcode_ean13",
    "product_name": "product_name",
    "brand": "brand",
    "category": "category",
    "uom": "uom",
    "unit_price_gbp_inc_vat": "unit_price_gbp_inc_vat",
    "vat_rate": "vat_rate",
    "lot_qty": "lot_qty",
    "reorder_level_qty": "reorder_level_qty",
    "expiry_date": "expiry_date",
    "use_by_or_best_before": "use_by_or_best_before",
    "supplier_name": "supplier_name",
    "location": "location",
}

def load_and_clean_data(file_path: str) -> List[CleanStockLot]:
    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}")
        return []

    print(f"--- Starting data loading from {file_path} ---")

    df = pd.read_csv(file_path)
    df_renamed = df.rename(columns=COLUMN_MAPPING)
    df_selected = df_renamed[list(COLUMN_MAPPING.values())].copy()  # Fix for SettingWithCopyWarning

    # --- EXPIRY DATE PARSING ---
    # Try numeric Excel-style dates first
    df_selected.loc[:, 'expiry_date'] = pd.to_numeric(df_selected['expiry_date'], errors='coerce')
    numeric_mask = df_selected['expiry_date'].notna()
    if numeric_mask.any():
        df_selected.loc[numeric_mask, 'expiry_date'] = pd.to_datetime(
            df_selected.loc[numeric_mask, 'expiry_date'], unit='d', origin='1899-12-30'
        )

    # For remaining rows, try standard date string parsing
    string_mask = df_selected['expiry_date'].isna()
    if string_mask.any():
        df_selected.loc[string_mask, 'expiry_date'] = pd.to_datetime(
            df_selected.loc[string_mask, 'expiry_date'], errors='coerce'
        )

    # Drop rows with invalid dates after both attempts
    rows_before_drop = len(df_selected)
    df_cleaned = df_selected.dropna(subset=['expiry_date'])
    rows_after_drop = len(df_cleaned)
    if rows_before_drop > rows_after_drop:
        print(f"Warning: Dropped {rows_before_drop - rows_after_drop} rows due to invalid expiry dates.")

    records = df_cleaned.to_dict(orient='records')

    clean_data: List[CleanStockLot] = []
    error_count = 0
    for idx, record in enumerate(records):
        try:
            clean_data.append(CleanStockLot(**record))
        except ValidationError as e:
            print(f"Validation Error in row {idx + 2}: {e}")
            error_count += 1

    print(f"--- Data loading complete ---")
    print(f"Successfully processed: {len(clean_data)} records.")
    print(f"Validation errors:    {error_count} records.")

    return clean_data
