# app/models/commission_plan.py
"""
Commission plan model for defining merchant commission structures.
"""


from app.db.base import BaseModel
from sqlalchemy import CHAR, Boolean, Column, Integer, String


class CommissionPlan(BaseModel):
    __tablename__ = "commission_plans"
    
    name = Column(String(255), nullable=False)
    percentage_bps = Column(Integer, nullable=False)  # basis points, e.g. 1000 = 10.00%
    flat_fee_minor = Column(Integer, nullable=False, default=0)
    currency = Column(CHAR(3), nullable=False, default='NGN')
    is_default = Column(Boolean, nullable=False, default=False)
    
    def __repr__(self):
        return f"<CommissionPlan(id={self.id}, name={self.name}, rate={self.percentage_bps}bps)>"