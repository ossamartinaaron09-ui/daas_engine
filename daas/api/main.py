"""FastAPI delivery application for DaaS MVP.

Exposes RESTful endpoints for health probes, record querying with vertical and keyword
filtering, pagination, single record retrieval, vertical summary, and record ingestion.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import ValidationError

from fastapi import Depends, FastAPI, HTTPException, Path, Query, status
from fastapi.responses import JSONResponse

from daas import __version__
from daas.db.manager import DatabaseManager
from daas.models import VerticalEnum, create_record

# Global default database manager instance
_default_db_manager: Optional[DatabaseManager] = None


def get_db() -> DatabaseManager:
    """Dependency provider returning the active DatabaseManager instance."""
    global _default_db_manager
    if _default_db_manager is None:
        _default_db_manager = DatabaseManager(db_path="daas.db", auto_init=True)
    return _default_db_manager


def set_default_db(db: DatabaseManager) -> None:
    """Set global default database manager (useful for test fixtures)."""
    global _default_db_manager
    _default_db_manager = db


def create_app(db_path: Optional[str] = None) -> FastAPI:
    """Application factory creating and configuring the FastAPI delivery application.

    Args:
        db_path: Optional SQLite database path. If provided, configures a dedicated
                 DatabaseManager instance for this application.

    Returns:
        Configured FastAPI application instance.
    """
    app = FastAPI(
        title="DaaS Engine MVP Delivery API",
        version=__version__,
        description="RESTful delivery API for multi-vertical B2B structured records.",
    )

    if db_path is not None:
        app_db = DatabaseManager(db_path=db_path, auto_init=True)
        app.dependency_overrides[get_db] = lambda: app_db

    # Route 1: Health Probe
    @app.get(
        "/health",
        status_code=status.HTTP_200_OK,
        summary="Service health and database connectivity probe",
    )
    def health_check(db: DatabaseManager = Depends(get_db)) -> Dict[str, Any]:
        """Verify API service liveness and database connectivity."""
        try:
            # Execute probe query against SQLite
            db.count_by_vertical()
            return {
                "status": "healthy",
                "version": __version__,
                "database": "connected",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "status": "degraded",
                    "database": "disconnected",
                    "error": str(exc),
                },
            )

    # Route 2: Query Records
    @app.get(
        "/records",
        status_code=status.HTTP_200_OK,
        summary="Query, filter, and paginate stored records",
    )
    def query_records(
        vertical: Optional[str] = Query(None, description="Vertical category filter"),
        keyword: Optional[str] = Query(None, description="Search term matching title, category, location, or payload"),
        limit: int = Query(50, ge=1, le=100, description="Maximum records to return (1-100)"),
        offset: int = Query(0, ge=0, description="Pagination offset (>= 0)"),
        db: DatabaseManager = Depends(get_db),
    ) -> Dict[str, Any]:
        """Retrieve paginated list of validated records with optional filtering."""
        normalized_vertical: Optional[str] = None
        if vertical is not None:
            clean_vert = vertical.strip().lower()
            valid_verticals = [v.value for v in VerticalEnum]
            if clean_vert not in valid_verticals:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid vertical '{vertical}'. Must be one of: {valid_verticals}",
                )
            normalized_vertical = clean_vert

        items, total = db.query_records(
            vertical=normalized_vertical,
            keyword=keyword,
            limit=limit,
            offset=offset,
        )

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": items,
        }

    # Route 3: Single Record by ID
    @app.get(
        "/records/{record_id}",
        status_code=status.HTTP_200_OK,
        summary="Retrieve single record by primary key ID",
    )
    def get_record_by_id(
        record_id: int = Path(..., ge=1, description="Primary key record ID"),
        db: DatabaseManager = Depends(get_db),
    ) -> Dict[str, Any]:
        """Fetch a single record by its integer primary key."""
        record = db.get_by_id(record_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Record with ID {record_id} not found",
            )
        return record

    # Route 4: Supported Verticals & Volume Summary
    @app.get(
        "/verticals",
        status_code=status.HTTP_200_OK,
        summary="List supported verticals and active record counts",
    )
    def list_verticals(db: DatabaseManager = Depends(get_db)) -> Dict[str, Any]:
        """Retrieve list of supported verticals and active record counts."""
        counts = db.count_by_vertical()
        display_names = {
            "local_business": "Local Business Directory",
            "real_estate": "Real Estate Listings",
            "ecommerce": "E-Commerce Products",
        }

        supported_list = [
            {
                "name": v.value,
                "display_name": display_names.get(v.value, v.value.replace("_", " ").title()),
                "count": counts.get(v.value, 0),
            }
            for v in VerticalEnum
        ]

        return {
            "supported_verticals": supported_list,
            "total_records": sum(counts.values()),
        }

    # Route 5: Ingest / Store Record
    @app.post(
        "/records",
        status_code=status.HTTP_201_CREATED,
        summary="Ingest and validate a new polymorphic record",
    )
    def create_record_endpoint(
        body: Dict[str, Any],
        db: DatabaseManager = Depends(get_db),
    ) -> Dict[str, Any]:
        """Accept polymorphic record payload, validate against Pydantic schema, and persist in SQLite."""
        if not isinstance(body, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Request body must be a JSON object",
            )

        try:
            record = create_record(body)
        except (ValueError, ValidationError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            )

        new_id = db.insert_record(record)
        vert_str = record.vertical.value if isinstance(record.vertical, VerticalEnum) else str(record.vertical)

        return {
            "id": new_id,
            "vertical": vert_str,
            "status": "created",
            "message": "Record successfully validated and persisted",
        }

    return app


# Default singleton app instance
app = create_app()
