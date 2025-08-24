from typing import Optional
from sqlmodel import SQLModel, Field

class CarListing(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: Optional[str] = Field(default=None, index=True)
    link: Optional[str] = Field(default=None)
    price: Optional[float] = Field(default=None, index=True)
    mileage: Optional[float] = Field(default=None, index=True)
    mileage_km: Optional[float] = Field(default=None, index=True, alias="Mileage[KM]")
    year: Optional[int] = Field(default=None, index=True)
    power_hp: Optional[float] = Field(default=None, index=True, alias="power[HP]")
    capacity_cm3: Optional[float] = Field(default=None, index=True, alias="capacity[cm3]")
    fuel_type: Optional[str] = Field(default=None, index=True)
    gearbox: Optional[str] = Field(default=None, index=True)
    city: Optional[str] = Field(default=None, index=True)
    voivodeship: Optional[str] = Field(default=None, index=True)
    other_info: Optional[str] = Field(default=None)
