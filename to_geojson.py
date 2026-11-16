#!/usr/bin/env python3
"""Turn an osmium parking export into compact GeoJSON for the map.

Keeps destination parking locations only:
- drops street parking rows (street_side, lane, on_kerb, ...)
- keeps garages/underground/rooftop always, others only when named,
  capacity >= 10 or area >= 1500 m2
- centroids per feature; rings kept for map fill
"""
import json
import sys

STREET = {"street_side", "lane", "on_kerb", "half_on_kerb", "layby",
          "lane_parking", "carports", "sheltered"}
GARAGE = {"underground", "multi-storey", "rooftop", "mechanical",
          "structure", "covered"}


def outer_rings(geom):
    if geom["type"] == "Polygon":
        return geom["coordinates"]
    if geom["type"] == "MultiPolygon":
        rings = []
        for poly in geom["coordinates"]:
            rings.extend(poly)
        return rings
    return []


def ring_centroid(ring):
    a = cx = cy = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(a) < 1e-12:
        lons = [p[0] for p in ring]
        lats = [p[1] for p in ring]
        return sum(lons) / len(lons), sum(lats) / len(lats)
    return cx / (3 * a), cy / (3 * a)


def ring_area_m2(ring, lat):
    kx = 111320.0 * __import__("math").cos(__import__("math").radians(lat))
    ky = 110574.0
    a = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        a += x1 * kx * y2 * ky - x2 * kx * y1 * ky
    return abs(a) / 2.0


def clean(tags):
    keep = {}
    for k in ("name", "capacity", "parking", "fee", "access", "operator",
              "maxstay", "opening_hours", "covered", "park_ride",
              "access:conditional", "surface", "capacity:disabled",
              "capacity:women", "supervised", "monitoring"):
        v = tags.get(k)
        if v not in (None, "", "no"):
            keep[k] = v
    return keep


def main(src, dst):
    with open(src, encoding="utf-8") as fh:
        data = json.load(fh)

    out_features = []
    seen = set()
    kept = dropped = 0
    for f in data.get("features", []):
        geom = f.get("geometry") or {}
        tags = clean(f.get("properties") or {})
        pk = tags.get("parking")
        if pk in STREET:
            dropped += 1
            continue
        if geom["type"] == "Point":
            lon, lat = geom["coordinates"][0], geom["coordinates"][1]
            rings = None
            area = 0.0
            if not (tags.get("name") or (tags.get("capacity") and int(tags["capacity"]) >= 10)):
                dropped += 1
                continue
        elif geom["type"] in ("Polygon", "MultiPolygon"):
            rings = outer_rings(geom)
            if not rings:
                dropped += 1
                continue
            ring = max(rings, key=lambda r: ring_area_m2(r, 52.05))
            lon, lat = ring_centroid(ring)
            area = round(sum(ring_area_m2(r, lat) for r in rings))
            named = bool(tags.get("name"))
            cap = tags.get("capacity")
            cap_ok = bool(cap) and str(cap).isdigit() and int(cap) >= 10
            if not (pk in GARAGE or named or cap_ok or area >= 1500):
                dropped += 1
                continue
        else:
            dropped += 1
            continue

        key = (round(lon, 4), round(lat, 4), tags.get("name"), tags.get("capacity"))
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        if area:
            tags["area_m2"] = area
        out_features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
            "properties": tags,
            "rings": [[[[round(c, 5) for c in p] for p in r]] for r in rings] if rings else None,
        })
        kept += 1

    out = {"type": "FeatureCollection", "features": out_features}
    js = "window.PARKING_DATA = " + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";\n"
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(js)
    print(f"kept: {kept}  dropped: {dropped} -> {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
