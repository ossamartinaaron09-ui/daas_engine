#!/usr/bin/env python3
"""
Overpass API B2B Lead Extractor & Ingester for DaaS MVP.
Runs the Overpass queries and pushes validated records into the DaaS REST API.
"""

import time
import random
import requests
import argparse
from typing import Dict, List, Optional

OVERPASS_URL = "http://overpass-api.de/api/interpreter"
API_ENDPOINT = "http://127.0.0.1:8000/records"

class LeadExtractionError(RuntimeError):
    pass

def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = " ".join(str(value).split())
    return value or None

def _escape_overpass_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')

def _escape_overpass_regex(value: str) -> str:
    special = r".^$*+?{}[]\|()"
    escaped = []
    for char in value:
        if char in special:
            escaped.append("\\" + char)
        else:
            escaped.append(char)
    return "".join(escaped).replace('"', '\\"')

def _build_address(tags: Dict[str, str]) -> Optional[str]:
    street = _clean(tags.get("addr:street"))
    house_number = _clean(tags.get("addr:housenumber"))
    postcode = _clean(tags.get("addr:postcode"))
    city = _clean(tags.get("addr:city") or tags.get("addr:town") or tags.get("addr:village"))
    province = _clean(tags.get("addr:province") or tags.get("addr:state"))
    country = _clean(tags.get("addr:country"))

    line1 = " ".join(part for part in [street, house_number] if part)
    line2 = " ".join(part for part in [postcode, city] if part)

    address = ", ".join(part for part in [line1, line2, province, country] if part)
    return address or None

def _overpass_post_with_retries(session: requests.Session, query: str, timeout: float, max_attempts: int = 4) -> dict:
    for attempt in range(max_attempts):
        response = session.post(OVERPASS_URL, data={"data": query}, timeout=timeout)
        if response.status_code == 200:
            return response.json()
        if response.status_code in {408, 429, 500, 502, 503, 504}:
            delay = min(30.0, 2.0 * (2**attempt)) + random.uniform(0.5, 1.5)
            print(f"[!] Overpass server error {response.status_code}. Retrying in {delay:.1f}s...")
            time.sleep(delay)
            continue
        raise LeadExtractionError(f"Overpass API error {response.status_code}: {response.text[:500]}")
    raise LeadExtractionError("Overpass API request failed after retries")

def extract_leads(keyword: str, location: str, max_results: int = 20, timeout: float = 30.0) -> List[Dict[str, Optional[str]]]:
    if not keyword.strip() or not location.strip():
        raise ValueError("Keyword and location cannot be empty")
        
    query = f"""
    [out:json][timeout:25];
    area["name"="{_escape_overpass_string(location.strip())}"]->.searchArea;
    (
      node["amenity"="{_escape_overpass_string(keyword.strip())}"](area.searchArea);
      way["amenity"="{_escape_overpass_string(keyword.strip())}"](area.searchArea);
      node["shop"="{_escape_overpass_string(keyword.strip())}"](area.searchArea);
      way["shop"="{_escape_overpass_string(keyword.strip())}"](area.searchArea);
    );
    out tags center {min(max_results, 100)};
    """

    session = requests.Session()
    session.headers.update({"User-Agent": "daas-engine-ingester/1.0", "Accept": "application/json"})

    print(f"[*] Querying Overpass API for '{keyword}' in '{location}'...")
    data = _overpass_post_with_retries(session, query, timeout)
    
    leads = []
    seen = set()

    for element in data.get("elements", []):
        tags = element.get("tags") or {}
        name = _clean(tags.get("name"))
        if not name:
            continue

        osm_id = f"{element.get('type')}:{element.get('id')}"
        dedupe_key = (
            name.lower(),
            _clean(tags.get("phone") or tags.get("contact:phone")),
            _clean(tags.get("website") or tags.get("contact:website")),
            _build_address(tags),
        )

        if osm_id in seen or dedupe_key in seen:
            continue

        seen.add(osm_id)
        seen.add(dedupe_key)
        
        # Pydantic LocalBusinessRecord expects: vertical, name, category, phone, address, city, postal_code, website, etc.
        city = _clean(tags.get("addr:city") or tags.get("addr:town") or tags.get("addr:village"))
        postal_code = _clean(tags.get("addr:postcode"))
        phone = _clean(tags.get("phone") or tags.get("contact:phone") or tags.get("addr:phone"))
        website = _clean(tags.get("website") or tags.get("contact:website") or tags.get("url") or tags.get("contact:url"))

        leads.append({
            "vertical": "local_business",
            "name": name,
            "category": keyword.title(), # We map the search keyword to category
            "phone": phone,
            "address": _build_address(tags),
            "city": city,
            "postal_code": postal_code,
            "website": website,
            "source_url": f"https://www.openstreetmap.org/{element.get('type')}/{element.get('id')}"
        })

        if len(leads) >= max_results:
            break

    return leads

def ingest_to_api(leads: List[dict]):
    print(f"\n[*] Found {len(leads)} leads. Ingesting to local DaaS Engine (API: {API_ENDPOINT})...")
    success, failed = 0, 0
    for lead in leads:
        # Filter out None values to keep payload clean
        payload = {k: v for k, v in lead.items() if v is not None}
        try:
            resp = requests.post(API_ENDPOINT, json=payload, timeout=5)
            if resp.status_code == 201:
                success += 1
                print(f"  [+] Ingested: {payload['name']}")
            else:
                failed += 1
                print(f"  [-] Failed to ingest '{payload['name']}': {resp.text}")
        except Exception as e:
            failed += 1
            print(f"  [-] Connection error for '{payload['name']}': {e}")
            
    print(f"\n[*] Ingestion complete: {success} added, {failed} failed.")

def main():
    parser = argparse.ArgumentParser(description="Overpass API Scraper for DaaS")
    parser.add_argument("--keyword", required=True, help="Business type (e.g., restaurant, dentist, lawyers)")
    parser.add_argument("--location", required=True, help="City or Region (e.g., Madrid, Barcelona)")
    parser.add_argument("--limit", type=int, default=10, help="Max results to extract")
    args = parser.parse_args()

    leads = extract_leads(args.keyword, args.location, max_results=args.limit)
    if leads:
        ingest_to_api(leads)
    else:
        print("[-] No leads found matching the criteria.")

if __name__ == "__main__":
    main()
