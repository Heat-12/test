#!/usr/bin/env python3

import argparse
import csv
import os
import sys
import time
from typing import Dict, Iterable, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

GOOGLE_MAPS_PLACES_TEXTSEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
GOOGLE_MAPS_PLACE_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
GOOGLE_MAPS_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


def create_requests_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def geocode_location(session: requests.Session, api_key: str, address: str) -> Optional[Tuple[float, float]]:
    params = {"address": address, "key": api_key}
    response = session.get(GOOGLE_MAPS_GEOCODE_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    if data.get("status") != "OK" or not data.get("results"):
        return None
    location = data["results"][0]["geometry"]["location"]
    return location["lat"], location["lng"]


def text_search_places(
    session: requests.Session,
    api_key: str,
    query: str,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    radius_meters: Optional[int] = None,
    max_results: int = 120,
) -> Iterable[Dict]:
    params: Dict[str, object] = {
        "query": query,
        "key": api_key,
    }
    if lat is not None and lng is not None:
        params["location"] = f"{lat},{lng}"
    if radius_meters is not None:
        params["radius"] = str(radius_meters)

    next_page_token: Optional[str] = None
    fetched = 0

    while True:
        if next_page_token:
            params["pagetoken"] = next_page_token
            # Per Google docs, need a short delay before using next_page_token
            time.sleep(2)
        else:
            params.pop("pagetoken", None)

        response = session.get(GOOGLE_MAPS_PLACES_TEXTSEARCH_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        status = data.get("status")
        if status not in ("OK", "ZERO_RESULTS"):
            # If INVALID_REQUEST due to early page token usage, brief wait and retry once
            if status == "INVALID_REQUEST" and "next_page_token" in data:
                time.sleep(2)
                continue
            break

        results = data.get("results", [])
        for result in results:
            yield result
            fetched += 1
            if fetched >= max_results:
                return

        next_page_token = data.get("next_page_token")
        if not next_page_token:
            return


def fetch_place_details(
    session: requests.Session,
    api_key: str,
    place_id: str,
) -> Dict:
    fields = [
        "name",
        "url",
        "formatted_phone_number",
        "international_phone_number",
        "website",
        "address_components",
        "formatted_address",
        "rating",
        "user_ratings_total",
    ]
    params = {
        "place_id": place_id,
        "fields": ",".join(fields),
        "key": api_key,
    }
    response = session.get(GOOGLE_MAPS_PLACE_DETAILS_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    if data.get("status") != "OK":
        return {}
    return data.get("result", {})


def extract_city_from_address_components(address_components: List[Dict]) -> str:
    # Try locality, then postal_town, then administrative levels
    wanted_hierarchy = [
        "locality",
        "postal_town",
        "administrative_area_level_2",
        "administrative_area_level_1",
    ]
    type_to_name: Dict[str, str] = {}
    for comp in address_components:
        types = comp.get("types", [])
        long_name = comp.get("long_name", "")
        for t in types:
            if t not in type_to_name:
                type_to_name[t] = long_name
    for t in wanted_hierarchy:
        if t in type_to_name and type_to_name[t]:
            return type_to_name[t]
    return ""


def normalize_phone(result: Dict) -> str:
    return result.get("international_phone_number") or result.get("formatted_phone_number") or ""


def build_output_row(result: Dict) -> Dict[str, str]:
    name = result.get("name", "")
    website = result.get("website", "")
    phone = normalize_phone(result)
    city = ""
    if "address_components" in result and result["address_components"]:
        city = extract_city_from_address_components(result["address_components"]) or city
    if not city and result.get("formatted_address"):
        # Fallback: best-effort parse city from formatted_address (comma-separated)
        try:
            parts = [p.strip() for p in result["formatted_address"].split(",")]
            if len(parts) >= 2:
                city = parts[-3] if len(parts) >= 3 else parts[-2]
        except Exception:
            pass

    return {
        "name": name,
        "phone": phone,
        "website": website,
        "city": city,
        "place_id": result.get("place_id", ""),
        "rating": str(result.get("rating", "")),
        "user_ratings_total": str(result.get("user_ratings_total", "")),
        "maps_url": result.get("url", ""),
    }


def write_csv(rows: Iterable[Dict[str, str]], output_path: str) -> None:
    fieldnames = [
        "name",
        "phone",
        "website",
        "city",
        "place_id",
        "rating",
        "user_ratings_total",
        "maps_url",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main(argv: Optional[List[str]] = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Google Maps business scraper using the official Places API."
    )
    parser.add_argument(
        "--api-key",
        dest="api_key",
        default=os.getenv("GOOGLE_MAPS_API_KEY", ""),
        help="Google Maps API key (or set env GOOGLE_MAPS_API_KEY)",
    )
    parser.add_argument(
        "--query",
        required=True,
        help="Text search query, e.g. 'plumbers' or 'coffee shop'",
    )
    parser.add_argument(
        "--location",
        help="Freeform location to bias results, e.g. 'Austin, TX' (uses Geocoding API)",
    )
    parser.add_argument(
        "--lat",
        type=float,
        help="Latitude for location bias (alternative to --location)",
    )
    parser.add_argument(
        "--lng",
        type=float,
        help="Longitude for location bias (alternative to --location)",
    )
    parser.add_argument(
        "--radius",
        type=int,
        default=10000,
        help="Search radius in meters (used when lat/lng provided)",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=120,
        help="Maximum number of places to fetch (cap depends on pagination)",
    )
    parser.add_argument(
        "--output",
        default="output.csv",
        help="Output CSV file path",
    )
    parser.add_argument(
        "--details-delay-ms",
        type=int,
        default=150,
        help="Delay in milliseconds between Place Details calls to respect QPS limits",
    )

    args = parser.parse_args(argv)

    if not args.api_key:
        print("Error: API key is required. Provide --api-key or set GOOGLE_MAPS_API_KEY.", file=sys.stderr)
        return 2

    session = create_requests_session()

    lat = args.lat
    lng = args.lng

    if args.location and (lat is None or lng is None):
        geocoded = geocode_location(session, args.api_key, args.location)
        if not geocoded:
            print(f"Failed to geocode location: {args.location}", file=sys.stderr)
            return 1
        lat, lng = geocoded

    results: List[Dict[str, str]] = []

    # Gather list of place_ids from Text Search
    places_iter = text_search_places(
        session=session,
        api_key=args.api_key,
        query=args.query,
        lat=lat,
        lng=lng,
        radius_meters=args.radius if (lat is not None and lng is not None) else None,
        max_results=args.max_results,
    )

    delay_seconds = max(args.details_delay_ms, 0) / 1000.0

    for place in places_iter:
        place_id = place.get("place_id")
        if not place_id:
            continue
        details = fetch_place_details(session, args.api_key, place_id)
        if not details:
            continue
        # Ensure we keep place_id even if not in details (some fields excluded)
        if "place_id" not in details:
            details["place_id"] = place_id
        row = build_output_row(details)
        results.append(row)
        if delay_seconds > 0:
            time.sleep(delay_seconds)

    write_csv(results, args.output)
    print(f"Wrote {len(results)} rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())