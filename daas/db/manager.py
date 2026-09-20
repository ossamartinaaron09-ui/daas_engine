"""Database manager encapsulating SQLite schema, indexing, and CRUD methods."""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from daas.db.connection import configure_connection, get_connection
from daas.models import (
    BaseRecord,
    EcommerceRecord,
    LocalBusinessRecord,
    RealEstateRecord,
    VerticalEnum,
    create_record,
)


class DatabaseManager:
    """Encapsulates SQLite connection management, DDL, and CRUD operations."""

    DDL_STATEMENTS = """
    CREATE TABLE IF NOT EXISTS records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vertical TEXT NOT NULL,
        title_or_name TEXT NOT NULL,
        price REAL,
        category TEXT,
        location TEXT,
        source_url TEXT,
        payload TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_records_vertical ON records(vertical);
    CREATE INDEX IF NOT EXISTS idx_records_title_or_name ON records(title_or_name COLLATE NOCASE);
    CREATE INDEX IF NOT EXISTS idx_records_category ON records(category COLLATE NOCASE);
    CREATE INDEX IF NOT EXISTS idx_records_location ON records(location COLLATE NOCASE);
    CREATE INDEX IF NOT EXISTS idx_records_created_at ON records(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_records_vert_title ON records(vertical, title_or_name COLLATE NOCASE);
    """

    def __init__(self, db_path: str = "daas.db", auto_init: bool = True):
        self.db_path = db_path
        self._is_memory = db_path == ":memory:"
        # Keep persistent connection for in-memory database
        self._shared_conn = get_connection(":memory:") if self._is_memory else None
        if auto_init:
            self.init_db()

    def get_conn(self):
        """Retrieve a connection for executing queries."""
        if self._is_memory:
            return self._shared_conn
        return get_connection(self.db_path)

    def init_db(self) -> None:
        """Execute DDL statements to set up schema and indexes idempotently."""
        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            cursor.executescript(self.DDL_STATEMENTS)
            conn.commit()
            cursor.close()
        finally:
            if not self._is_memory:
                conn.close()

    def _extract_columns(self, record: BaseRecord) -> Tuple[str, str, Optional[float], Optional[str], Optional[str]]:
        """Extract searchable indexed columns according to record vertical."""
        vertical_str = record.vertical.value if isinstance(record.vertical, VerticalEnum) else str(record.vertical)

        if isinstance(record, LocalBusinessRecord):
            title_or_name = record.name
            price = None
            category = record.category
            location = record.city or record.address
        elif isinstance(record, RealEstateRecord):
            title_or_name = record.title
            price = record.price
            category = record.property_type
            location = record.location
        elif isinstance(record, EcommerceRecord):
            title_or_name = record.title
            price = record.price
            category = record.category
            location = None
        else:
            title_or_name = getattr(record, "title", getattr(record, "name", "Untitled"))
            price = getattr(record, "price", None)
            category = getattr(record, "category", None)
            location = getattr(record, "location", getattr(record, "address", None))

        return vertical_str, title_or_name, price, category, location

    def insert_record(self, record: Union[BaseRecord, Dict[str, Any]]) -> int:
        """Insert a single validated record into the database.
        
        Args:
            record: Validated BaseRecord instance or raw dictionary conforming to a vertical schema.
            
        Returns:
            The auto-generated primary key ID.
            
        Raises:
            ValueError or ValidationError: If record is malformed.
        """
        if isinstance(record, dict):
            record = create_record(record)
        elif not isinstance(record, BaseRecord):
            raise ValueError(f"Expected BaseRecord instance or dict, got {type(record).__name__}")

        vertical_str, title_or_name, price, category, location = self._extract_columns(record)
        source_url = record.source_url
        payload = json.dumps(record.model_dump(mode="json"))
        created_at = record.created_at.isoformat() if record.created_at else datetime.now(timezone.utc).isoformat()

        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO records (vertical, title_or_name, price, category, location, source_url, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (vertical_str, title_or_name, price, category, location, source_url, payload, created_at),
            )
            record_id = cursor.lastrowid
            conn.commit()
            cursor.close()
            record.id = record_id
            return record_id
        finally:
            if not self._is_memory:
                conn.close()

    def insert_batch(self, records: Sequence[Union[BaseRecord, Dict[str, Any]]]) -> Tuple[int, int]:
        """Insert a batch of records transactionally.
        
        Malformed records that fail validation or insertion are counted as rejected.
        
        Returns:
            Tuple of (success_count, rejected_count).
        """
        success_count = 0
        rejected_count = 0

        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            for item in records:
                try:
                    if isinstance(item, dict):
                        record = create_record(item)
                    elif isinstance(item, BaseRecord):
                        record = item
                    else:
                        raise ValueError(f"Invalid record type: {type(item).__name__}")

                    vertical_str, title_or_name, price, category, location = self._extract_columns(record)
                    source_url = record.source_url
                    payload = json.dumps(record.model_dump(mode="json"))
                    created_at = record.created_at.isoformat() if record.created_at else datetime.now(timezone.utc).isoformat()

                    cursor.execute(
                        """
                        INSERT INTO records (vertical, title_or_name, price, category, location, source_url, payload, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (vertical_str, title_or_name, price, category, location, source_url, payload, created_at),
                    )
                    record.id = cursor.lastrowid
                    success_count += 1
                except Exception:
                    rejected_count += 1

            conn.commit()
            cursor.close()
            return success_count, rejected_count
        finally:
            if not self._is_memory:
                conn.close()

    def get_by_id(self, record_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a single stored record by primary key ID.
        
        Returns:
            Deserialized dictionary envelope or None if not found.
        """
        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, vertical, title_or_name, price, category, location, source_url, payload, created_at
                FROM records
                WHERE id = ?
                """,
                (record_id,),
            )
            row = cursor.fetchone()
            cursor.close()
            if not row:
                return None

            return {
                "id": row["id"],
                "vertical": row["vertical"],
                "title_or_name": row["title_or_name"],
                "price": row["price"],
                "category": row["category"],
                "location": row["location"],
                "source_url": row["source_url"],
                "created_at": row["created_at"],
                "data": json.loads(row["payload"]),
            }
        finally:
            if not self._is_memory:
                conn.close()

    def query_records(
        self,
        vertical: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Query stored records with optional vertical and keyword filters and pagination.
        
        Returns:
            Tuple of (list_of_record_dicts, total_matching_count).
        """
        limit = max(1, min(limit, 100))
        offset = max(0, offset)

        clauses = []
        params: List[Any] = []

        if vertical:
            clauses.append("vertical = ?")
            params.append(vertical.strip().lower())

        if keyword:
            kw = f"%{keyword.strip()}%"
            clauses.append("(title_or_name LIKE ? OR category LIKE ? OR location LIKE ?)")
            params.extend([kw, kw, kw])

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        conn = self.get_conn()
        try:
            cursor = conn.cursor()

            # Count query
            count_sql = f"SELECT COUNT(*) as total FROM records {where_sql}"
            cursor.execute(count_sql, params)
            total_count = cursor.fetchone()["total"]

            # Data query
            data_sql = f"""
            SELECT id, vertical, title_or_name, price, category, location, source_url, payload, created_at
            FROM records
            {where_sql}
            ORDER BY id ASC
            LIMIT ? OFFSET ?
            """
            cursor.execute(data_sql, params + [limit, offset])
            rows = cursor.fetchall()
            cursor.close()

            items = [
                {
                    "id": r["id"],
                    "vertical": r["vertical"],
                    "title_or_name": r["title_or_name"],
                    "price": r["price"],
                    "category": r["category"],
                    "location": r["location"],
                    "source_url": r["source_url"],
                    "created_at": r["created_at"],
                    "data": json.loads(r["payload"]),
                }
                for r in rows
            ]
            return items, total_count
        finally:
            if not self._is_memory:
                conn.close()

    def count_by_vertical(self) -> Dict[str, int]:
        """Aggregate stored record volume grouped by vertical."""
        counts = {v.value: 0 for v in VerticalEnum}

        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT vertical, COUNT(*) as cnt FROM records GROUP BY vertical")
            rows = cursor.fetchall()
            cursor.close()
            for r in rows:
                counts[r["vertical"]] = r["cnt"]
            return counts
        finally:
            if not self._is_memory:
                conn.close()

    def delete_record(self, record_id: int) -> bool:
        """Delete a record by primary key ID.
        
        Returns:
            True if deleted, False if record did not exist.
        """
        conn = self.get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM records WHERE id = ?", (record_id,))
            deleted = cursor.rowcount > 0
            conn.commit()
            cursor.close()
            return deleted
        finally:
            if not self._is_memory:
                conn.close()

    def close(self) -> None:
        """Close shared connection if using in-memory database."""
        if self._is_memory and self._shared_conn:
            self._shared_conn.close()
            self._shared_conn = None
