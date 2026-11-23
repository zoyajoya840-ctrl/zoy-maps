/**
 * Zoy Maps React Native / Expo SDK v2.0.0
 * Plug-and-play module for MILGI Passenger & Partner Mobile Apps
 */

export class ZoyMapsMobile {
  constructor({ apiKey, baseUrl = "http://localhost:8000" }) {
    if (!apiKey) throw new Error("[ZoyMapsMobile] apiKey is required");
    this.apiKey = apiKey;
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  async _call(endpoint, { method = "GET", params = {}, body = null } = {}) {
    const query = Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== null)
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
      .join("&");

    const url = `${this.baseUrl}${endpoint}${query ? `?${query}` : ""}`;
    const response = await fetch(url, {
      method,
      headers: {
        "X-API-Key": this.apiKey,
        "Content-Type": "application/json",
      },
      body: body ? JSON.stringify(body) : null,
    });

    const json = await response.json();
    if (!response.ok) {
      throw new Error(json?.detail?.message || "Zoy Maps Mobile API request failed");
    }
    return json;
  }

  searchPlaces(q, limit = 5) {
    return this._call("/v1/geocode/search", { params: { q, limit } });
  }

  autocomplete(input) {
    return this._call("/v1/places/autocomplete", { params: { input } });
  }

  reverseGeocode(lat, lng) {
    return this._call("/v1/geocode/reverse", { params: { lat, lng } });
  }

  getRoute(originLatLng, destLatLng, mode = "driving") {
    return this._call("/v1/directions", {
      params: { origin: originLatLng, destination: destLatLng, mode },
    });
  }

  streamDriverLocation({ vehicleId, vehicleType = "auto", lat, lng, speedKmh, heading = 0 }) {
    return this._call("/v1/telemetry/ping", {
      method: "POST",
      body: {
        vehicle_id: vehicleId,
        vehicle_type: vehicleType,
        lat,
        lng,
        speed_kmh: speedKmh,
        heading,
      },
    });
  }

  addMissingPlace({ name, category = "transit_hub", address, city = "Jaipur", state = "Rajasthan", lat, lng }) {
    return this._call("/v1/places/contribute", {
      method: "POST",
      body: { name, category, address, city, state, lat, lng },
    });
  }
}
