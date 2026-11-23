import math
import httpx
from typing import List, Dict, Any, Tuple
from app.traffic_engine import get_route_traffic_multiplier

USER_AGENT = "ZoyMapsSaaS/2.0 (ZoyTechSolutions; contact@zoytech.in)"

NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
OSRM_BASE = "https://router.project-osrm.org"

ALPHABET = "23456789CFGHJMPQRVWX"

INDIAN_CITY_FALLBACKS = [
    {"name": "Nawalgarh", "address": "Nawalgarh, Jhunjhunu District, Rajasthan 333042, India", "lat": 27.8486, "lng": 75.2747, "category": "city"},
    {"name": "Udaipurwati", "address": "Udaipurwati, Jhunjhunu District, Rajasthan 333307, India", "lat": 27.7347, "lng": 75.4836, "category": "town"},
    {"name": "Jhunjhunu", "address": "Jhunjhunu, Rajasthan 333001, India", "lat": 28.1289, "lng": 75.3995, "category": "city"},
    {"name": "Jaipur", "address": "Jaipur, Rajasthan, India", "lat": 26.9124, "lng": 75.7873, "category": "city"},
    {"name": "Jagatpura", "address": "Jagatpura, Jaipur, Rajasthan 302017, India", "lat": 26.8358, "lng": 75.8655, "category": "suburb"},
    {"name": "New Delhi", "address": "New Delhi, Delhi, India", "lat": 28.6139, "lng": 77.2090, "category": "city"},
    {"name": "Mumbai", "address": "Mumbai, Maharashtra, India", "lat": 19.0760, "lng": 72.8777, "category": "city"},
    {"name": "Bengaluru", "address": "Bengaluru, Karnataka, India", "lat": 12.9716, "lng": 77.5946, "category": "city"},
]


def generate_zoy_plus_code(lat: float, lng: float) -> str:
    norm_lat = int((lat + 90.0) * 10000)
    norm_lng = int((lng + 180.0) * 10000)
    c1 = ALPHABET[(norm_lat // 8000) % 20] + ALPHABET[(norm_lng // 8000) % 20]
    c2 = ALPHABET[(norm_lat // 400) % 20] + ALPHABET[(norm_lng // 400) % 20]
    c3 = ALPHABET[(norm_lat // 20) % 20] + ALPHABET[(norm_lng // 20) % 20]
    c4 = ALPHABET[norm_lat % 20] + ALPHABET[norm_lng % 20]
    return f"ZOY-{c1}{c2}+{c3}{c4}"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return r * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def parse_lat_lng(coord_str: str) -> Tuple[float, float]:
    parts = [p.strip() for p in coord_str.split(",")]
    if len(parts) != 2:
        raise ValueError(f"Invalid coordinate '{coord_str}'. Expected 'lat,lng'.")
    lat, lng = float(parts[0]), float(parts[1])
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValueError(f"Coordinates out of range: {lat},{lng}")
    return lat, lng


def _local_fallback_search(query: str, limit: int) -> List[Dict[str, Any]]:
    ql = query.lower().strip()
    matches = [
        c for c in INDIAN_CITY_FALLBACKS
        if ql in c["name"].lower() or ql in c["address"].lower()
    ]
    if not matches:
        matches = [INDIAN_CITY_FALLBACKS[3]]  # Default Jaipur hub
    out = []
    for idx, m in enumerate(matches[:limit]):
        out.append({
            "place_id": f"zoy_local_{idx + 1}",
            "plus_code": generate_zoy_plus_code(m["lat"], m["lng"]),
            "formatted_address": m["address"],
            "name": m["name"],
            "category": m["category"],
            "source": "zoy-local-cache",
            "location": {"lat": m["lat"], "lng": m["lng"]},
        })
    return out


async def forward_geocode(query: str, limit: int = 5, countrycodes: str | None = None) -> List[Dict[str, Any]]:
    params = {
        "q": query,
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": limit,
    }
    if countrycodes:
        params["countrycodes"] = countrycodes

    try:
        async with httpx.AsyncClient(timeout=3.5) as client:
            resp = await client.get(
                f"{NOMINATIM_BASE}/search",
                params=params,
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data:
            lat, lng = float(item["lat"]), float(item["lon"])
            results.append({
                "place_id": f"zoy_poi_{item.get('place_id')}",
                "plus_code": generate_zoy_plus_code(lat, lng),
                "formatted_address": item.get("display_name"),
                "name": item.get("name") or item.get("display_name", "").split(",")[0],
                "category": item.get("type", "place"),
                "source": "zoy-osm-nominatim",
                "location": {"lat": lat, "lng": lng},
            })
        if results:
            return results
    except Exception:
        pass

    return _local_fallback_search(query, limit)


async def reverse_geocode(lat: float, lng: float) -> Dict[str, Any]:
    plus_code = generate_zoy_plus_code(lat, lng)
    try:
        async with httpx.AsyncClient(timeout=3.5) as client:
            resp = await client.get(
                f"{NOMINATIM_BASE}/reverse",
                params={"lat": lat, "lon": lng, "format": "jsonv2", "addressdetails": 1},
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            item = resp.json()
        if "display_name" in item:
            return {
                "place_id": f"zoy_poi_{item.get('place_id', '0')}",
                "plus_code": plus_code,
                "formatted_address": item.get("display_name"),
                "location": {"lat": float(item.get("lat", lat)), "lng": float(item.get("lon", lng))},
            }
    except Exception:
        pass

    return {
        "plus_code": plus_code,
        "formatted_address": f"Rajasthan / India Grid ({lat:.5f}, {lng:.5f})",
        "location": {"lat": lat, "lng": lng},
    }


async def compute_directions(
    origin: Tuple[float, float],
    destination: Tuple[float, float],
    mode: str = "driving",
    alternatives: bool = True,
) -> Dict[str, Any]:
    profile_map = {"driving": "car", "walking": "foot", "cycling": "bike"}
    osrm_profile = profile_map.get(mode, "car")
    coords = f"{origin[1]},{origin[0]};{destination[1]},{destination[0]}"

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(
                f"{OSRM_BASE}/route/v1/{osrm_profile}/{coords}",
                params={"overview": "full", "geometries": "geojson", "steps": "true", "alternatives": "true" if alternatives else "false"},
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            data = resp.json()

        if data.get("code") == "Ok" and data.get("routes"):
            routes_out = []
            for idx, r in enumerate(data["routes"]):
                dist_m = r["distance"]
                base_dur_s = r["duration"]
                geom_coords = r["geometry"].get("coordinates", [])

                traffic_info = (
                    get_route_traffic_multiplier(geom_coords)
                    if mode == "driving"
                    else {"multiplier": 1.0, "traffic_condition": "not_applicable", "congested_zones": 0}
                )
                live_dur_s = base_dur_s * traffic_info["multiplier"]

                steps_out = []
                for leg in r.get("legs", []):
                    for step in leg.get("steps", []):
                        maneuver = step.get("maneuver", {})
                        steps_out.append({
                            "instruction": f"{maneuver.get('type', 'continue').replace('_', ' ').title()} {maneuver.get('modifier', '')} onto {step.get('name') or 'main road'}".strip(),
                            "distance_meters": round(step.get("distance", 0), 1),
                            "duration_seconds": round(step.get("duration", 0) * traffic_info["multiplier"], 1),
                            "location": {"lng": maneuver.get("location", [0, 0])[0], "lat": maneuver.get("location", [0, 0])[1]},
                        })

                routes_out.append({
                    "route_index": idx,
                    "summary": r.get("legs", [{}])[0].get("summary", f"Route {idx + 1}"),
                    "traffic": traffic_info,
                    "distance": {"meters": round(dist_m, 1), "kilometers": round(dist_m / 1000.0, 2), "text": f"{round(dist_m / 1000.0, 2)} km"},
                    "duration": {"seconds": round(base_dur_s, 1), "minutes": round(base_dur_s / 60.0, 1), "text": f"{max(1, round(base_dur_s / 60.0))} mins"},
                    "duration_in_traffic": {"seconds": round(live_dur_s, 1), "minutes": round(live_dur_s / 60.0, 1), "text": f"{max(1, round(live_dur_s / 60.0))} mins"},
                    "geometry": r["geometry"],
                    "steps": steps_out,
                })
            return {"status": "OK", "mode": mode, "engine": "zoy-routing-v2-live-traffic", "routes": routes_out}
    except Exception:
        pass

    dist_km = round(haversine_km(origin[0], origin[1], destination[0], destination[1]) * 1.28, 2)
    speed_kmh = {"driving": 38.0, "cycling": 16.0, "walking": 5.0}.get(mode, 38.0)
    dur_mins = max(1, round((dist_km / speed_kmh) * 60.0))
    return {
        "status": "OK_LOCAL",
        "mode": mode,
        "engine": "zoy-local-router",
        "routes": [
            {
                "route_index": 0,
                "summary": "Zoy Direct Highway / Corridor Path",
                "traffic": {"multiplier": 1.0, "traffic_condition": "normal", "congested_zones": 0},
                "distance": {"meters": int(dist_km * 1000), "kilometers": dist_km, "text": f"{dist_km} km"},
                "duration": {"seconds": dur_mins * 60, "minutes": dur_mins, "text": f"{dur_mins} mins"},
                "duration_in_traffic": {"seconds": dur_mins * 60, "minutes": dur_mins, "text": f"{dur_mins} mins"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[origin[1], origin[0]], [destination[1], destination[0]]],
                },
                "steps": [
                    {
                        "instruction": f"Proceed {mode} along corridor toward destination",
                        "distance_meters": int(dist_km * 1000),
                        "duration_seconds": dur_mins * 60,
                        "location": {"lat": origin[0], "lng": origin[1]},
                    }
                ],
            }
        ],
    }
