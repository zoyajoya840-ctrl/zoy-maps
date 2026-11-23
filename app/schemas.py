from pydantic import BaseModel, Field
from typing import List
from datetime import datetime


class ApiKeyCreate(BaseModel):
    project_name: str = Field(..., min_length=2, max_length=100, examples=["MILGI Mobility App"])
    owner_email: str = Field(..., examples=["founder@zoytech.in"])
    plan: str = Field(default="pro", pattern="^(free|pro|enterprise)$")
    allowed_origins: str = Field(default="*")


class ApiKeyResponse(BaseModel):
    id: int
    key: str
    project_name: str
    owner_email: str
    plan: str
    rate_limit_per_min: int
    monthly_quota: int
    requests_used: int
    wallet_balance_inr: float
    is_active: bool
    allowed_origins: str
    created_at: datetime

    class Config:
        from_attributes = True


class CustomPlaceCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    category: str = Field(default="local_business")
    address: str = Field(..., min_length=4)
    city: str = Field(default="Jaipur")
    state: str = Field(default="Rajasthan")
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    contributed_by: str = Field(default="Community Mapper")


class DistanceMatrixRequest(BaseModel):
    origins: List[str] = Field(..., description="List of 'lat,lng' strings")
    destinations: List[str] = Field(..., description="List of 'lat,lng' strings")
    mode: str = Field(default="driving", pattern="^(driving|walking|cycling)$")


class TelemetryPingRequest(BaseModel):
    vehicle_id: str = Field(..., examples=["MILGI-RJ14-AUTO-101"])
    vehicle_type: str = Field(default="auto", pattern="^(auto|car|bike|bus|truck)$")
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    speed_kmh: float = Field(..., ge=0, le=180)
    heading: float = Field(default=0.0, ge=0, le=360)


class PlanUpgradeRequest(BaseModel):
    api_key: str
    target_plan: str = Field(..., pattern="^(free|pro|enterprise)$")
    payment_reference: str = Field(default="rzp_live_instant_demo")
