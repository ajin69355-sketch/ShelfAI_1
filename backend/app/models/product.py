from sqlalchemy import Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import relationship
from ..db.base_class import Base 

class Product(Base):
    __tablename__ = "products"

    id = Column(String, primary_key=True, index=True) # product_id from CSV
    sku = Column(String, unique=True, index=True, nullable=False)
    product_name = Column(String, index=True, nullable=False)
    category = Column(String)
    barcode_ean13 = Column(String, unique=True)
    
    # Financials
    unit_cost = Column(Float)
    unit_price = Column(Float)
    
    # Inventory Strategy
    reorder_level_qty = Column(Integer)
    safety_stock = Column(Integer)
    avg_daily_sales = Column(Float)

    inventory_lots = relationship("InventoryLot", back_populates="product")