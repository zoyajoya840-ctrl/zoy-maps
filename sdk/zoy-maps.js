/**
 * Zoy Maps Web JavaScript SDK v2.0.0
 * Enterprise Location, Live Traffic & Routing SDK by Zoy Tech Solutions
 */
(function (global) {
  class ZoyMapsClient {
    constructor(options = {}) {
      if (!options.apiKey) {
        throw new Error("[ZoyMaps] apiKey is required to initialize ZoyMapsClient.");
      }
      this.apiKey = options.apiKey;
      this.baseUrl = (options.baseUrl || window.location.origin).replace(/\/$/, "");
    }

    async _request(path, params = {}, method = "GET", body = null) {
      const url = new URL(`${this.baseUrl}${path}`);
      if (method === "GET") {
        Object.entries(params).forEach(([k, v]) => {
          if (v !== undefined && v !== null) url.searchParams.append(k, v);
        });
      }

      const res = await fetch(url.toString(), {
        method,
        headers: {
          "X-API-Key": this.apiKey,
          "Content-Type": "application/json",
        },
        body: body ? JSON.stringify(body) : null,
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail?.message || JSON.stringify(data.detail) || "Zoy Maps API Error");
      }
      return data;
    }

    geocode(query, options = {}) {
      return this._request("/v1/geocode/search", {
        q: query,
        limit: options.limit || 5,
        country: options.country || "in",
      });
    }

    reverseGeocode(lat, lng) {
      return this._request("/v1/geocode/reverse", { lat, lng });
    }

    autocomplete(input, country = "in") {
      return this._request("/v1/places/autocomplete", { input, country });
    }

    getDirections(origin, destination, mode = "driving") {
      const origStr = Array.isArray(origin) ? origin.join(",") : origin;
      const destStr = Array.isArray(destination) ? destination.join(",") : destination;
      return this._request("/v1/directions", { origin: origStr, destination: destStr, mode });
    }

    getDistanceMatrix(origins, destinations, mode = "driving") {
      return this._request("/v1/distancematrix", {}, "POST", { origins, destinations, mode });
    }

    contributePlace(placePayload) {
      return this._request("/v1/places/contribute", {}, "POST", placePayload);
    }

    getPlusCode(lat, lng) {
      return this._request("/v1/pluscode", { lat, lng });
    }

    pingTelemetry(telemetryPayload) {
      return this._request("/v1/telemetry/ping", {}, "POST", telemetryPayload);
    }

    getLiveTraffic() {
      return this._request("/v1/traffic/live");
    }

    connectLiveStream(onMessage) {
      const wsProto = this.baseUrl.startsWith("https") ? "wss" : "ws";
      const host = this.baseUrl.replace(/^https?:\/\//, "");
      const ws = new WebSocket(`${wsProto}://${host}/v1/ws/live`);
      ws.onmessage = (evt) => onMessage(JSON.parse(evt.data));
      return ws;
    }

    getTileUrlTemplate(style = "streets") {
      return `${this.baseUrl}/v1/tiles/${style}/{z}/{x}/{y}.png?key=${encodeURIComponent(this.apiKey)}`;
    }
  }

  global.ZoyMaps = {
    Client: ZoyMapsClient,
    version: "2.0.0",
  };
})(window);
