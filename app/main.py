import time
import secrets
from fastapi import FastAPI, Depends, Query, HTTPException, Path, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session
import httpx

from app.database import init_db, get_db, ApiKey, UsageLog, CustomPlace, BillingTransaction, SessionLocal
from app.schemas import (
    ApiKeyCreate,
    ApiKeyResponse,
    CustomPlaceCreate,
    DistanceMatrixRequest,
    TelemetryPingRequest,
    PlanUpgradeRequest,
)
from app.auth import verify_api_key, record_usage, generate_zoy_api_key, PLAN_LIMITS
from app.geo_engine import (
    forward_geocode,
    reverse_geocode,
    compute_directions,
    parse_lat_lng,
    haversine_km,
    generate_zoy_plus_code,
)
from app.traffic_engine import ingest_telemetry, get_live_traffic_snapshot, ws_manager

# 1x1 transparent PNG fallback so tile requests never hang or return 502 on slow networks
FALLBACK_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff"
    b"\xff\x3f\x00\x05\xfe\x02\xfe\xdc\xccY\xe7\x00\x00\x00\x00IEND\xaeB`\x82"
)

app = FastAPI(
    title="Zoy Maps v2.0 API",
    description="Google Maps-Grade Location Intelligence, Live Traffic Telemetry & SaaS Platform by Zoy Tech Solutions",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()
    db = SessionLocal()
    try:
        if db.query(ApiKey).count() == 0:
            demo_key = ApiKey(
                key="zoy_live_demo_public_sandbox_2026",
                project_name="Zoy Maps Live Playground",
                owner_email="founder@zoytech.in",
                plan="enterprise",
                rate_limit_per_min=2000,
                monthly_quota=5000000,
                wallet_balance_inr=10000.0,
            )
            db.add(demo_key)

        if db.query(CustomPlace).count() == 0:
            seed_places = [
                CustomPlace(
                    name="Jagatpura Railway Station (MILGI Hub 01)",
                    category="transit_hub",
                    address="Jagatpura, Jaipur, Rajasthan 302017",
                    city="Jaipur",
                    state="Rajasthan",
                    lat=26.8358,
                    lng=75.8655,
                    plus_code=generate_zoy_plus_code(26.8358, 75.8655),
                    verified=True,
                    contributed_by="Zoy Maps Core",
                ),
                CustomPlace(
                    name="Nawalgarh Fort & Main Market Stand",
                    category="transit_hub",
                    address="Nawalgarh, Jhunjhunu District, Rajasthan 333042",
                    city="Nawalgarh",
                    state="Rajasthan",
                    lat=27.8486,
                    lng=75.2747,
                    plus_code=generate_zoy_plus_code(27.8486, 75.2747),
                    verified=True,
                    contributed_by="Zoy Maps Rural Grid",
                ),
                CustomPlace(
                    name="Hawa Mahal - Palace of Winds",
                    category="landmark",
                    address="Hawa Mahal Rd, Badi Choupad, Pink City, Jaipur, Rajasthan 302002",
                    city="Jaipur",
                    state="Rajasthan",
                    lat=26.9239,
                    lng=75.8267,
                    plus_code=generate_zoy_plus_code(26.9239, 75.8267),
                    verified=True,
                    contributed_by="Zoy Maps Core",
                ),
                CustomPlace(
                    name="Jaipur International Airport (JAI)",
                    category="airport",
                    address="Airport Rd, Sanganer, Jaipur, Rajasthan 302029",
                    city="Jaipur",
                    state="Rajasthan",
                    lat=26.8289,
                    lng=75.8056,
                    plus_code=generate_zoy_plus_code(26.8289, 75.8056),
                    verified=True,
                    contributed_by="Zoy Maps Core",
                ),
            ]
            db.add_all(seed_places)
        db.commit()

        ingest_telemetry("MILGI-AUTO-01", "auto", 26.8550, 75.8450, 34.0, 315)
        ingest_telemetry("MILGI-AUTO-02", "auto", 26.8780, 75.8320, 11.5, 330)
        ingest_telemetry("ZOY-FLEET-09", "car", 26.9050, 75.8280, 19.0, 10)
    finally:
        db.close()


app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/sdk", StaticFiles(directory="sdk"), name="sdk")


@app.get("/", include_in_schema=False)
def serve_console():
    return FileResponse("static/index.html")


@app.post("/v1/console/keys", response_model=ApiKeyResponse, tags=["SaaS Console"])
def create_api_key(payload: ApiKeyCreate, db: Session = Depends(get_db)):
    limits = PLAN_LIMITS[payload.plan]
    new_key = ApiKey(
        key=generate_zoy_api_key(),
        project_name=payload.project_name,
        owner_email=payload.owner_email,
        plan=payload.plan,
        rate_limit_per_min=limits["rpm"],
        monthly_quota=limits["quota"],
        allowed_origins=payload.allowed_origins,
    )
    db.add(new_key)
    db.commit()
    db.refresh(new_key)
    return new_key


@app.get("/v1/console/keys", response_model=list[ApiKeyResponse], tags=["SaaS Console"])
def list_api_keys(db: Session = Depends(get_db)):
    return db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()


@app.delete("/v1/console/keys/{key_id}", tags=["SaaS Console"])
def revoke_api_key(key_id: int, db: Session = Depends(get_db)):
    obj = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="API Key not found")
    obj.is_active = False
    db.commit()
    return {"status": "revoked", "id": key_id}


@app.post("/v1/billing/upgrade", tags=["SaaS Billing"])
def upgrade_saas_plan(payload: PlanUpgradeRequest, db: Session = Depends(get_db)):
    key_obj = db.query(ApiKey).filter(ApiKey.key == payload.api_key).first()
    if not key_obj:
        raise HTTPException(status_code=404, detail="API Key not found")

    plan_cfg = PLAN_LIMITS[payload.target_plan]
    key_obj.plan = payload.target_plan
    key_obj.rate_limit_per_min = plan_cfg["rpm"]
    key_obj.monthly_quota = plan_cfg["quota"]
    key_obj.is_active = True

    tx = BillingTransaction(
        api_key_str=key_obj.key,
        plan_purchased=payload.target_plan,
        amount_inr=plan_cfg["price_inr"],
        payment_ref=f"{payload.payment_reference}_{secrets.token_hex(4)}",
        status="paid",
    )
    db.add(tx)
    db.commit()
    return {
        "status": "upgraded",
        "project_name": key_obj.project_name,
        "new_plan": key_obj.plan,
        "rate_limit_per_min": key_obj.rate_limit_per_min,
        "monthly_quota": key_obj.monthly_quota,
        "amount_inr": plan_cfg["price_inr"],
        "invoice_ref": tx.payment_ref,
    }


@app.get("/v1/console/analytics", tags=["SaaS Console"])
def get_saas_analytics(db: Session = Depends(get_db)):
    keys = db.query(ApiKey).all()
    total_requests = sum(k.requests_used for k in keys)
    revenue_inr = sum(t.amount_inr for t in db.query(BillingTransaction).all())
    custom_places_count = db.query(CustomPlace).count()
    recent_logs = db.query(UsageLog).order_by(UsageLog.timestamp.desc()).limit(20).all()
    return {
        "total_keys": len(keys),
        "active_keys": sum(1 for k in keys if k.is_active),
        "total_api_calls": total_requests,
        "total_revenue_inr": revenue_inr,
        "proprietary_places_count": custom_places_count,
        "recent_logs": [
            {
                "id": l.id,
                "endpoint": l.endpoint,
                "status_code": l.status_code,
                "latency_ms": l.latency_ms,
                "query_summary": l.query_summary,
                "timestamp": l.timestamp.isoformat(),
            }
            for l in recent_logs
        ],
    }


@app.post("/v1/places/contribute", tags=["Places & Rural Grid"])
def contribute_missing_place(
    payload: CustomPlaceCreate,
    api_key: ApiKey = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    t0 = time.perf_counter()
    plus_code = generate_zoy_plus_code(payload.lat, payload.lng)
    place = CustomPlace(
        name=payload.name,
        category=payload.category,
        address=payload.address,
        city=payload.city,
        state=payload.state,
        lat=payload.lat,
        lng=payload.lng,
        plus_code=plus_code,
        verified=True,
        contributed_by=payload.contributed_by,
    )
    db.add(place)
    db.commit()
    db.refresh(place)
    latency = (time.perf_counter() - t0) * 1000
    record_usage(db, api_key, "/v1/places/contribute", latency, query_summary=payload.name, method="POST")
    return {
        "provider": "Zoy Maps",
        "status": "PUBLISHED",
        "place": {
            "place_id": f"zoy_custom_{place.id}",
            "name": place.name,
            "category": place.category,
            "address": place.address,
            "plus_code": place.plus_code,
            "location": {"lat": place.lat, "lng": place.lng},
        },
    }


@app.get("/v1/pluscode", tags=["Places & Rural Grid"])
def get_plus_code(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    api_key: ApiKey = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    t0 = time.perf_counter()
    code = generate_zoy_plus_code(lat, lng)
    latency = (time.perf_counter() - t0) * 1000
    record_usage(db, api_key, "/v1/pluscode", latency, query_summary=f"{lat},{lng}")
    return {
        "provider": "Zoy Maps",
        "plus_code": code,
        "precision": "10m x 10m doorstep grid",
        "location": {"lat": lat, "lng": lng},
    }


@app.post("/v1/telemetry/ping", tags=["Live Traffic & Fleet"])
async def post_vehicle_telemetry(
    payload: TelemetryPingRequest,
    api_key: ApiKey = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    t0 = time.perf_counter()
    result = ingest_telemetry(
        vehicle_id=payload.vehicle_id,
        vehicle_type=payload.vehicle_type,
        lat=payload.lat,
        lng=payload.lng,
        speed_kmh=payload.speed_kmh,
        heading=payload.heading,
    )
    await ws_manager.broadcast({"event": "telemetry_update", "data": result})
    latency = (time.perf_counter() - t0) * 1000
    record_usage(db, api_key, "/v1/telemetry/ping", latency, query_summary=payload.vehicle_id, method="POST")
    return {"provider": "Zoy Maps", "status": "INGESTED", **result}


@app.get("/v1/traffic/live", tags=["Live Traffic & Fleet"])
def get_live_traffic(
    api_key: ApiKey = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    t0 = time.perf_counter()
    snapshot = get_live_traffic_snapshot()
    latency = (time.perf_counter() - t0) * 1000
    record_usage(db, api_key, "/v1/traffic/live", latency, query_summary="snapshot")
    return {"provider": "Zoy Maps", "status": "OK", **snapshot}


@app.websocket("/v1/ws/live")
async def websocket_live_stream(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        await websocket.send_json({"event": "connected", "snapshot": get_live_traffic_snapshot()})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


@app.get("/v1/geocode/search", tags=["Maps API"])
async def api_geocode_search(
    q: str = Query(..., min_length=2, description="Place name, address, or Zoy Plus Code"),
    limit: int = Query(default=5, ge=1, le=15),
    country: str | None = Query(default="in"),
    api_key: ApiKey = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    t0 = time.perf_counter()
    local_matches = (
        db.query(CustomPlace)
        .filter(
            CustomPlace.name.ilike(f"%{q}%")
            | CustomPlace.address.ilike(f"%{q}%")
            | CustomPlace.plus_code.ilike(f"%{q}%")
        )
        .limit(limit)
        .all()
    )
    results = [
        {
            "place_id": f"zoy_custom_{p.id}",
            "plus_code": p.plus_code or generate_zoy_plus_code(p.lat, p.lng),
            "formatted_address": p.address,
            "name": p.name,
            "category": p.category,
            "source": "zoy-verified-poi",
            "rating": p.rating,
            "location": {"lat": p.lat, "lng": p.lng},
        }
        for p in local_matches
    ]

    if len(results) < limit:
        global_results = await forward_geocode(q, limit=limit - len(results), countrycodes=country)
        results.extend(global_results)

    latency = (time.perf_counter() - t0) * 1000
    record_usage(db, api_key, "/v1/geocode/search", latency, query_summary=f"q={q}")

    return {
        "provider": "Zoy Maps",
        "status": "OK" if results else "ZERO_RESULTS",
        "count": len(results),
        "results": results,
    }


@app.get("/v1/geocode/reverse", tags=["Maps API"])
async def api_reverse_geocode(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    api_key: ApiKey = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    t0 = time.perf_counter()
    res = await reverse_geocode(lat, lng)
    latency = (time.perf_counter() - t0) * 1000
    record_usage(db, api_key, "/v1/geocode/reverse", latency, query_summary=f"{lat},{lng}")
    return {"provider": "Zoy Maps", "status": "OK", "result": res}


@app.get("/v1/places/autocomplete", tags=["Maps API"])
async def api_places_autocomplete(
    input: str = Query(..., min_length=2),
    country: str | None = Query(default="in"),
    api_key: ApiKey = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    t0 = time.perf_counter()
    local_matches = (
        db.query(CustomPlace)
        .filter(CustomPlace.name.ilike(f"%{input}%") | CustomPlace.plus_code.ilike(f"%{input}%"))
        .limit(3)
        .all()
    )
    predictions = [
        {
            "place_id": f"zoy_custom_{p.id}",
            "plus_code": p.plus_code,
            "description": f"{p.name} ({p.plus_code}) — {p.address}",
            "main_text": p.name,
            "secondary_text": p.address,
            "location": {"lat": p.lat, "lng": p.lng},
        }
        for p in local_matches
    ]

    remote = await forward_geocode(input, limit=5 - len(predictions), countrycodes=country)
    for r in remote:
        predictions.append({
            "place_id": r["place_id"],
            "plus_code": r["plus_code"],
            "description": r["formatted_address"],
            "main_text": r["name"],
            "secondary_text": r["formatted_address"],
            "location": r["location"],
        })

    latency = (time.perf_counter() - t0) * 1000
    record_usage(db, api_key, "/v1/places/autocomplete", latency, query_summary=f"input={input}")
    return {"provider": "Zoy Maps", "status": "OK", "predictions": predictions}


@app.get("/v1/directions", tags=["Maps API"])
async def api_directions(
    origin: str = Query(..., description="Origin coordinates as 'lat,lng'"),
    destination: str = Query(..., description="Destination coordinates as 'lat,lng'"),
    mode: str = Query(default="driving", pattern="^(driving|walking|cycling)$"),
    alternatives: bool = Query(default=True),
    api_key: ApiKey = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    t0 = time.perf_counter()
    try:
        orig_tuple = parse_lat_lng(origin)
        dest_tuple = parse_lat_lng(destination)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    route_data = await compute_directions(orig_tuple, dest_tuple, mode=mode, alternatives=alternatives)
    latency = (time.perf_counter() - t0) * 1000
    record_usage(db, api_key, "/v1/directions", latency, query_summary=f"{origin}->{destination} ({mode})")
    return {"provider": "Zoy Maps", **route_data}


@app.post("/v1/distancematrix", tags=["Maps API"])
async def api_distance_matrix(
    payload: DistanceMatrixRequest,
    api_key: ApiKey = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    t0 = time.perf_counter()
    try:
        orig_coords = [parse_lat_lng(o) for o in payload.origins]
        dest_coords = [parse_lat_lng(d) for d in payload.destinations]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    speed_kmh = {"driving": 35.0, "cycling": 15.0, "walking": 5.0}.get(payload.mode, 35.0)
    rows = []
    for o in orig_coords:
        elements = []
        for d in dest_coords:
            road_km = round(haversine_km(o[0], o[1], d[0], d[1]) * 1.28, 2)
            dur_mins = max(1, round((road_km / speed_kmh) * 60))
            elements.append({
                "distance": {"kilometers": road_km, "meters": int(road_km * 1000), "text": f"{road_km} km"},
                "duration": {"minutes": dur_mins, "seconds": dur_mins * 60, "text": f"{dur_mins} mins"},
                "status": "OK",
            })
        rows.append({"elements": elements})

    latency = (time.perf_counter() - t0) * 1000
    record_usage(
        db,
        api_key,
        "/v1/distancematrix",
        latency,
        query_summary=f"{len(orig_coords)}x{len(dest_coords)} matrix",
        method="POST",
    )
    return {
        "provider": "Zoy Maps",
        "status": "OK",
        "mode": payload.mode,
        "origin_addresses": payload.origins,
        "destination_addresses": payload.destinations,
        "rows": rows,
    }


@app.get("/v1/tiles/{style}/{z}/{x}/{y}.png", tags=["Map Tiles"])
async def api_map_tiles(
    style: str = Path(..., pattern="^(streets|dark|satellite)$"),
    z: int = Path(..., ge=0, le=20),
    x: int = Path(..., ge=0),
    y: int = Path(..., ge=0),
    key: str = Query(..., description="Zoy Maps API Key"),
    db: Session = Depends(get_db),
):
    api_key_obj = db.query(ApiKey).filter(ApiKey.key == key, ApiKey.is_active == True).first()
    if not api_key_obj:
        raise HTTPException(status_code=403, detail="Invalid or inactive Zoy Maps API Key for tile stream")

    tile_sources = {
        "streets": f"https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "dark": f"https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "satellite": f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    }
    upstream_url = tile_sources[style]

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(upstream_url, headers={"User-Agent": "ZoyMapsTileEngine/2.0"})
            if resp.status_code == 200 and resp.content:
                return Response(
                    content=resp.content,
                    media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400", "X-Powered-By": "Zoy Maps v2.0"},
                )
    except Exception:
        pass

    return Response(
        content=FALLBACK_PNG_BYTES,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300", "X-Powered-By": "Zoy Maps Fallback Tile"},
    )
