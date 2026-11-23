import time
from typing import Dict, Any, List
from fastapi import WebSocket

ACTIVE_VEHICLES: Dict[str, Dict[str, Any]] = {}
TRAFFIC_GRID: Dict[str, Dict[str, Any]] = {}
STALE_SECONDS = 300


class LiveConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        dead = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for d in dead:
            self.disconnect(d)


ws_manager = LiveConnectionManager()


def _cell_key(lat: float, lng: float) -> str:
    return f"{round(lat / 0.005) * 0.005:.4f}:{round(lng / 0.005) * 0.005:.4f}"


def _classify_congestion(avg_speed_kmh: float) -> Dict[str, Any]:
    if avg_speed_kmh >= 28.0:
        return {"level": "free_flow", "color": "#10b981", "multiplier": 1.0, "label": "Clear Traffic"}
    elif avg_speed_kmh >= 14.0:
        return {"level": "moderate", "color": "#f59e0b", "multiplier": 1.35, "label": "Moderate Slowdown"}
    else:
        return {"level": "heavy", "color": "#ef4444", "multiplier": 1.85, "label": "Heavy Congestion"}


def ingest_telemetry(
    vehicle_id: str,
    vehicle_type: str,
    lat: float,
    lng: float,
    speed_kmh: float,
    heading: float = 0.0,
) -> Dict[str, Any]:
    now = time.time()
    ACTIVE_VEHICLES[vehicle_id] = {
        "vehicle_id": vehicle_id,
        "vehicle_type": vehicle_type,
        "lat": lat,
        "lng": lng,
        "speed_kmh": round(speed_kmh, 1),
        "heading": heading,
        "updated_at": now,
    }

    ck = _cell_key(lat, lng)
    cell = TRAFFIC_GRID.get(ck)
    if not cell or (now - cell["updated_at"] > STALE_SECONDS):
        TRAFFIC_GRID[ck] = {
            "cell_id": ck,
            "lat": round(lat / 0.005) * 0.005,
            "lng": round(lng / 0.005) * 0.005,
            "speeds": [speed_kmh],
            "updated_at": now,
        }
    else:
        cell["speeds"].append(speed_kmh)
        if len(cell["speeds"]) > 20:
            cell["speeds"] = cell["speeds"][-20:]
        cell["updated_at"] = now

    avg_speed = sum(TRAFFIC_GRID[ck]["speeds"]) / len(TRAFFIC_GRID[ck]["speeds"])
    status = _classify_congestion(avg_speed)
    return {
        "vehicle": ACTIVE_VEHICLES[vehicle_id],
        "traffic_zone": {
            "cell_id": ck,
            "avg_speed_kmh": round(avg_speed, 1),
            **status,
        },
    }


def get_live_traffic_snapshot() -> Dict[str, Any]:
    now = time.time()
    active_v = [v for v in ACTIVE_VEHICLES.values() if now - v["updated_at"] <= STALE_SECONDS]
    zones = []
    for ck, cell in list(TRAFFIC_GRID.items()):
        if now - cell["updated_at"] <= STALE_SECONDS:
            avg_spd = sum(cell["speeds"]) / len(cell["speeds"])
            info = _classify_congestion(avg_spd)
            zones.append({
                "cell_id": ck,
                "lat": cell["lat"],
                "lng": cell["lng"],
                "sample_count": len(cell["speeds"]),
                "avg_speed_kmh": round(avg_spd, 1),
                **info,
            })

    return {
        "active_vehicles_count": len(active_v),
        "vehicles": active_v,
        "traffic_zones_count": len(zones),
        "traffic_zones": zones,
    }


def get_route_traffic_multiplier(coords: List[List[float]]) -> Dict[str, Any]:
    now = time.time()
    multipliers = []
    congested_segments = 0
    for lon, lat in coords[::max(1, len(coords) // 25)]:
        ck = _cell_key(lat, lon)
        cell = TRAFFIC_GRID.get(ck)
        if cell and (now - cell["updated_at"] <= STALE_SECONDS):
            avg_spd = sum(cell["speeds"]) / len(cell["speeds"])
            info = _classify_congestion(avg_spd)
            multipliers.append(info["multiplier"])
            if info["level"] in ("moderate", "heavy"):
                congested_segments += 1

    if not multipliers:
        return {"multiplier": 1.0, "traffic_condition": "normal", "congested_zones": 0}

    avg_mult = sum(multipliers) / len(multipliers)
    cond = "heavy" if avg_mult >= 1.55 else ("moderate" if avg_mult >= 1.2 else "free_flow")
    return {
        "multiplier": round(avg_mult, 2),
        "traffic_condition": cond,
        "congested_zones": congested_segments,
    }
