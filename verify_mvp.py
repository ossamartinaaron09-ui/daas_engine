#!/usr/bin/env python3
"""DaaS MVP Standalone Acceptance Verification Runner.

Verifies all 5 Acceptance Criteria specified in ORIGINAL_REQUEST.md & spec_report.md:
  AC1: Extractor Functionality (3 verticals parsed from HTML fixtures without errors)
  AC2: Data Validation (missing mandatory fields rejected by Pydantic)
  AC3: Persistence (5 mock records inserted and retrieved from SQLite)
  AC4: API Server Startup (FastAPI starts and /health returns 200 OK)
  AC5: API Delivery (GET /records returns stored mock records with 200 OK)
Plus an integrated end-to-end pipeline run from scraping to API delivery.

Usage:
  .venv/bin/python3 verify_mvp.py [--verbose]
"""

import os
import sys
import time
import pathlib
import traceback
from datetime import datetime, timezone

# Ensure project root is on sys.path
PROJECT_ROOT = pathlib.Path(__file__).parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pydantic import ValidationError
from fastapi.testclient import TestClient

from daas import __version__
from daas.models import (
    BaseRecord,
    EcommerceRecord,
    LocalBusinessRecord,
    RealEstateRecord,
    VerticalEnum,
    create_record,
)
from daas.db.manager import DatabaseManager
from daas.scrapers import (
    EcommerceScraper,
    LocalBusinessScraper,
    RealEstateScraper,
    default_registry,
)
from daas.api.main import create_app, get_db


# ANSI Color formatting
class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def colorize(text: str, color_code: str) -> str:
    """Return colored text if stdout is a tty or forcibly formatted."""
    return f"{color_code}{text}{Colors.RESET}"


def print_banner():
    """Print verification banner."""
    print("=" * 78)
    print(colorize(f" DaaS Engine MVP — Verification Runner (v{__version__})", Colors.BOLD + Colors.CYAN))
    print(colorize(f" Timestamp: {datetime.now(timezone.utc).isoformat()} | Workspace: {PROJECT_ROOT}", Colors.DIM))
    print("=" * 78)
    print()


def verify_ac1(fixtures_dir: pathlib.Path, verbose: bool = False) -> None:
    """AC1: Extractor Functionality.
    
    A programmatic test successfully extracts data from sample HTML fixtures
    for each of the 3 verticals without throwing parsing errors.
    """
    verticals_info = [
        (VerticalEnum.LOCAL_BUSINESS, "sample_local_business.html", LocalBusinessScraper),
        (VerticalEnum.REAL_ESTATE, "sample_real_estate.html", RealEstateScraper),
        (VerticalEnum.ECOMMERCE, "sample_ecommerce.html", EcommerceScraper),
    ]

    total_parsed = 0

    for vertical, filename, scraper_cls in verticals_info:
        fixture_path = fixtures_dir / filename
        assert fixture_path.exists(), f"Fixture file not found: {fixture_path}"

        html_content = fixture_path.read_text(encoding="utf-8")
        scraper = scraper_cls()

        # Parse raw records
        raw_items = scraper.parse(html_content)
        assert isinstance(raw_items, list), f"Expected list from {scraper_cls.__name__}.parse()"
        assert len(raw_items) > 0, f"No records extracted from {filename}"

        # Extract strict Pydantic models
        models = scraper.extract_all(html_content, strict=True)
        assert len(models) == len(raw_items), "Mismatch between raw and validated records count"

        total_parsed += len(models)
        if verbose:
            print(f"    - {vertical.value}: parsed {len(models)} items using {scraper_cls.__name__}")

    assert total_parsed == 9, f"Expected 9 total parsed items across 3 verticals, got {total_parsed}"
    print(f"  {colorize('[PASS]', Colors.BOLD + Colors.GREEN)} AC1: Extractor Functionality (3 verticals parsed without errors)")


def verify_ac2(verbose: bool = False) -> None:
    """AC2: Data Validation.
    
    Demonstrates that records with missing mandatory fields are rejected by Pydantic.
    """
    rejection_tests = [
        # Local Business: mandatory name and category
        (
            "LocalBusiness missing name",
            lambda: LocalBusinessRecord(category="Restaurant"),
            "name",
        ),
        (
            "LocalBusiness empty name",
            lambda: LocalBusinessRecord(name="   ", category="Restaurant"),
            "name",
        ),
        (
            "LocalBusiness missing category",
            lambda: LocalBusinessRecord(name="Joe's Cafe"),
            "category",
        ),
        # Real Estate: mandatory title, price (> 0), location
        (
            "RealEstate missing price",
            lambda: RealEstateRecord(title="Beach Villa", location="Miami"),
            "price",
        ),
        (
            "RealEstate non-positive price",
            lambda: RealEstateRecord(title="Beach Villa", location="Miami", price=0.0),
            "price",
        ),
        (
            "RealEstate missing location",
            lambda: RealEstateRecord(title="Beach Villa", price=500000.0),
            "location",
        ),
        # E-Commerce: mandatory title, price (>= 0), sku
        (
            "Ecommerce missing sku",
            lambda: EcommerceRecord(title="Wireless Mouse", price=29.99),
            "sku",
        ),
        (
            "Ecommerce negative price",
            lambda: EcommerceRecord(title="Wireless Mouse", sku="MS-01", price=-10.0),
            "price",
        ),
        (
            "Ecommerce missing title",
            lambda: EcommerceRecord(sku="MS-01", price=29.99),
            "title",
        ),
    ]

    for label, constructor, expected_field in rejection_tests:
        try:
            constructor()
            raise AssertionError(f"Expected ValidationError for {label}, but instantiation succeeded!")
        except ValidationError as e:
            assert expected_field in str(e), f"Expected '{expected_field}' in error, got: {e}"
            if verbose:
                print(f"    - Rejected {label} as expected (field: {expected_field})")

    # Polymorphic factory rejection
    try:
        create_record({"vertical": "local_business", "category": "Dentist"})
        raise AssertionError("Expected ValidationError from create_record with missing name")
    except ValidationError:
        pass

    try:
        create_record({"vertical": "invalid_vertical", "name": "Test"})
        raise AssertionError("Expected ValueError from create_record with unknown vertical")
    except ValueError:
        pass

    print(f"  {colorize('[PASS]', Colors.BOLD + Colors.GREEN)} AC2: Data Validation (missing mandatory fields rejected by Pydantic)")


def verify_ac3(verbose: bool = False) -> tuple[DatabaseManager, list[int]]:
    """AC3: Persistence.
    
    Inserts 5 valid mock records into SQLite database and reads them back with field matching.
    """
    db = DatabaseManager(":memory:")

    mock_records = [
        LocalBusinessRecord(
            name="Joe's Artisanal Bakery",
            category="Bakery & Cafe",
            phone="+1-555-0101",
            address="101 Main St",
            rating=4.8,
            review_count=142,
        ),
        LocalBusinessRecord(
            name="TechNova Solutions",
            category="IT Services",
            phone="+1-555-0102",
            address="202 Tech Blvd",
            rating=4.5,
            review_count=89,
        ),
        RealEstateRecord(
            title="Luxury 3-Bed Oceanview Villa",
            price=850000.0,
            location="Miami, FL",
            bedrooms=3,
            bathrooms=3.5,
            area_sqm=220.0,
        ),
        RealEstateRecord(
            title="Cozy Studio in Historic Center",
            price=175000.0,
            location="Valencia, Spain",
            bedrooms=1,
            bathrooms=1.0,
            area_sqm=45.0,
        ),
        EcommerceRecord(
            title="Ergonomic Wireless Mechanical Keyboard",
            price=129.99,
            sku="KB-MECH-RGB-01",
            brand="TypeMaster",
            availability=True,
            rating=4.7,
            review_count=320,
        ),
    ]

    inserted_ids = []
    for record in mock_records:
        rec_id = db.insert_record(record)
        assert isinstance(rec_id, int) and rec_id > 0
        inserted_ids.append(rec_id)

    assert len(set(inserted_ids)) == 5, "Database did not generate 5 distinct primary keys"

    # Read back each record and verify exact equality
    for original, rec_id in zip(mock_records, inserted_ids):
        retrieved = db.get_by_id(rec_id)
        assert retrieved is not None, f"Record ID {rec_id} not found"
        assert retrieved["id"] == rec_id
        assert retrieved["vertical"] == original.vertical.value

        if isinstance(original, LocalBusinessRecord):
            assert retrieved["title_or_name"] == original.name
            assert retrieved["category"] == original.category
            assert retrieved["data"]["phone"] == original.phone
        elif isinstance(original, RealEstateRecord):
            assert retrieved["title_or_name"] == original.title
            assert retrieved["price"] == original.price
            assert retrieved["location"] == original.location
        elif isinstance(original, EcommerceRecord):
            assert retrieved["title_or_name"] == original.title
            assert retrieved["price"] == original.price
            assert retrieved["data"]["sku"] == original.sku

        if verbose:
            print(f"    - Persisted & verified ID={rec_id}: {retrieved['title_or_name']} ({retrieved['vertical']})")

    # Verify query and counts
    items, total = db.query_records(limit=10)
    assert total == 5 and len(items) == 5
    counts = db.count_by_vertical()
    assert counts.get("local_business") == 2
    assert counts.get("real_estate") == 2
    assert counts.get("ecommerce") == 1

    print(f"  {colorize('[PASS]', Colors.BOLD + Colors.GREEN)} AC3: Persistence (5 mock records inserted and retrieved from SQLite)")
    return db, inserted_ids


def verify_ac4(db: DatabaseManager, verbose: bool = False) -> TestClient:
    """AC4: API Server Startup.
    
    FastAPI server starts locally without errors; GET /health returns 200 OK.
    """
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 200, f"Expected 200 OK from /health, got {response.status_code}"

    data = response.json()
    assert data.get("status") == "healthy", f"Expected healthy status, got: {data.get('status')}"
    assert data.get("database") == "connected", f"Expected connected database, got: {data.get('database')}"
    assert data.get("version") == __version__
    assert "timestamp" in data

    if verbose:
        print(f"    - GET /health responded: {data}")

    print(f"  {colorize('[PASS]', Colors.BOLD + Colors.GREEN)} AC4: API Server Startup (FastAPI starts and /health returns 200 OK)")
    return client


def verify_ac5(client: TestClient, verbose: bool = False) -> None:
    """AC5: API Delivery.
    
    GET /records returns stored mock records in valid JSON with HTTP 200 OK,
    and supports filtering by vertical and keyword.
    """
    # 1. Fetch all records
    resp_all = client.get("/records")
    assert resp_all.status_code == 200
    all_data = resp_all.json()
    assert all_data.get("total") == 5
    assert len(all_data.get("items", [])) == 5

    # 2. Filter by vertical: real_estate
    resp_re = client.get("/records?vertical=real_estate")
    assert resp_re.status_code == 200
    re_data = resp_re.json()
    assert re_data["total"] == 2
    assert all(item["vertical"] == "real_estate" for item in re_data["items"])

    # 3. Filter by vertical: local_business
    resp_lb = client.get("/records?vertical=local_business")
    assert resp_lb.status_code == 200
    lb_data = resp_lb.json()
    assert lb_data["total"] == 2
    assert all(item["vertical"] == "local_business" for item in lb_data["items"])

    # 4. Filter by vertical: ecommerce
    resp_ec = client.get("/records?vertical=ecommerce")
    assert resp_ec.status_code == 200
    ec_data = resp_ec.json()
    assert ec_data["total"] == 1
    assert ec_data["items"][0]["title_or_name"] == "Ergonomic Wireless Mechanical Keyboard"

    # 5. Search by keyword
    resp_bakery = client.get("/records?keyword=bakery")
    assert resp_bakery.status_code == 200
    assert any("Bakery" in item["title_or_name"] for item in resp_bakery.json()["items"])

    resp_ocean = client.get("/records?keyword=oceanview")
    assert resp_ocean.status_code == 200
    assert "Oceanview" in resp_ocean.json()["items"][0]["title_or_name"]

    # 6. Invalid vertical parameter returns 400 Bad Request
    resp_invalid = client.get("/records?vertical=crypto_tokens")
    assert resp_invalid.status_code == 400

    if verbose:
        print("    - Query filters tested: /records, ?vertical=..., ?keyword=..., bad vertical 400")

    print(f"  {colorize('[PASS]', Colors.BOLD + Colors.GREEN)} AC5: API Delivery (GET /records returns stored mock records with 200 OK)")


def verify_e2e_pipeline(fixtures_dir: pathlib.Path, verbose: bool = False) -> None:
    """Full End-to-End Pipeline Integration.
    
    Connects HTML scraping -> Pydantic validation -> SQLite persistence -> API delivery.
    """
    e2e_db = DatabaseManager(":memory:")
    app = create_app()
    app.dependency_overrides[get_db] = lambda: e2e_db

    # Step 1: Scrape and validate all 3 fixtures
    verticals = [
        (VerticalEnum.LOCAL_BUSINESS, "sample_local_business.html"),
        (VerticalEnum.REAL_ESTATE, "sample_real_estate.html"),
        (VerticalEnum.ECOMMERCE, "sample_ecommerce.html"),
    ]

    total_ingested = 0
    for vertical, filename in verticals:
        html = (fixtures_dir / filename).read_text(encoding="utf-8")
        scraper = default_registry.get(vertical)
        records = scraper.extract_all(html, strict=True)
        assert len(records) == 3

        for rec in records:
            pk = e2e_db.insert_record(rec)
            assert pk > 0
            total_ingested += 1

    assert total_ingested == 9

    # Step 2: Query via FastAPI API Client
    with TestClient(app) as client:
        # Check totals
        res = client.get("/records?limit=20")
        assert res.status_code == 200
        assert res.json()["total"] == 9

        # Check verticals counts
        res_v = client.get("/verticals")
        assert res_v.status_code == 200
        assert res_v.json()["total_records"] == 9

        # Check specific item retrieval
        res_kw = client.get("/records?keyword=headphones")
        assert res_kw.status_code == 200
        assert res_kw.json()["total"] == 1
        assert "Noise-Cancelling" in res_kw.json()["items"][0]["title_or_name"]

        # Dynamic POST ingestion
        res_post = client.post("/records", json={
            "vertical": "ecommerce",
            "title": "USB-C Fast Charger 65W",
            "price": 34.99,
            "sku": "CHG-65W-01",
            "brand": "PowerVolt",
        })
        assert res_post.status_code == 201
        assert res_post.json()["id"] == 10

        # Check updated count
        res_updated = client.get("/records")
        assert res_updated.json()["total"] == 10

    if verbose:
        print("    - End-to-end pipeline: scraped 9 items from 3 HTML files, persisted to SQLite, verified through REST API")

    print(f"  {colorize('[PASS]', Colors.BOLD + Colors.GREEN)} Integrated Pipeline: Scraped 9 records across 3 verticals and queried via REST API")


def main() -> int:
    """Run all verification criteria sequentially."""
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    fixtures_dir = PROJECT_ROOT / "tests" / "fixtures"

    start_time = time.time()
    print_banner()

    print(colorize("Executing Acceptance Criteria Checks:", Colors.BOLD))
    print()

    try:
        # AC1: Extractor Functionality
        verify_ac1(fixtures_dir, verbose=verbose)

        # AC2: Data Validation
        verify_ac2(verbose=verbose)

        # AC3: Persistence
        db, inserted_ids = verify_ac3(verbose=verbose)

        # AC4: API Server Startup
        client = verify_ac4(db, verbose=verbose)

        # AC5: API Delivery
        verify_ac5(client, verbose=verbose)

        # Integrated E2E Pipeline
        verify_e2e_pipeline(fixtures_dir, verbose=verbose)

        elapsed = time.time() - start_time
        print()
        print("=" * 78)
        print(colorize(f" ALL 5 ACCEPTANCE CRITERIA VERIFIED SUCCESSFULLY! ({elapsed:.3f}s)", Colors.BOLD + Colors.GREEN))
        print("=" * 78)
        return 0

    except Exception as exc:
        elapsed = time.time() - start_time
        print()
        print("=" * 78)
        print(colorize(f" VERIFICATION FAILED after {elapsed:.3f}s", Colors.BOLD + Colors.RED))
        print("=" * 78)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
