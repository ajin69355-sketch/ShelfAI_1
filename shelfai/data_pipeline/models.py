# shelfai/data_pipeline/models.py

import pydantic
from datetime import datetime
from typing import Literal

# Pydantic's BaseModel provides data validation and type hints.
# This class defines the exact structure and data types for a single,
# clean stock lot record. The loader's job is to produce objects of this type.

class CleanStockLot(pydantic.BaseModel):
    """
    Represents a single, validated, and cleaned stock lot record.
    This is the "source of truth" for data within the application.
    """
    product_id: str
    lot_id: str
    barcode_ean13: int
    product_name: str
    brand: str
    category: str
    uom: str
    unit_price_gbp_inc_vat: float
    vat_rate: float
    lot_qty: int
    reorder_level_qty: int
    
    # Critical Transformation: Ensure expiry_date is a proper datetime object.
    # This is essential for all time-based logic (e.g., expiry alerts).
    expiry_date: datetime

    use_by_or_best_before: Literal['Use By', 'Best Before']
    supplier_name: str
    location: str

    # Model config allows us to control Pydantic's behavior.
    # 'extra = 'forbid'' ensures that no unexpected columns from the CSV
    # accidentally make it into our clean data model. This prevents silent errors.
    class Config:
        extra = 'forbid'