from sqlalchemy import Column, Integer, String, Float, Date, ForeignKey
from sqlalchemy.orm import relationship
from ..db.base_class import Base 

class InventoryLot(Base):
    __tablename__ = "inventory_lots"

    id = Column(String, primary_key=True, index=True) # lot_id from CSV
    lot_qty = Column(Integer, nullable=False)
    batch_received_date = Column(Date)
    expiry_date = Column(Date, index=True)

    # Foreign Key to establish the link to the products table
    product_id = Column(String, ForeignKey("products.id"), nullable=False)

    product = relationship("Product", back_populates="inventory_lots")