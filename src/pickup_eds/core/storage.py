from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sqlite3
import uuid

import numpy as np

from pickup_eds.core.ring_buffer import decimate_pair
from pickup_eds.schemas import DatasetSummary


class StorageManager:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._recordings_dir = self._data_dir / "recordings"
        self._db_path = self._data_dir / "catalog.sqlite3"

    def initialize(self) -> None:
        self._recordings_dir.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    duration_s REAL NOT NULL,
                    sample_rate_hz INTEGER NOT NULL,
                    sample_count INTEGER NOT NULL,
                    file_path TEXT NOT NULL,
                    file_size_bytes INTEGER NOT NULL,
                    min_value REAL NOT NULL,
                    max_value REAL NOT NULL
                )
                """
            )
            conn.commit()

    def list_datasets(self) -> list[DatasetSummary]:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, label, created_at, duration_s, sample_rate_hz, sample_count,
                       file_path, file_size_bytes, min_value, max_value
                FROM datasets
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [self._row_to_summary(row) for row in rows]

    def save_recording(
        self,
        *,
        label: str,
        times: np.ndarray,
        values: np.ndarray,
        sample_rate_hz: int,
        format: str = "npz",
    ) -> DatasetSummary:
        if format not in {"npz", "csv"}:
            raise ValueError(f"unsupported recording format: {format!r}")
        created_at = datetime.now(UTC)
        dataset_id = f"{created_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        safe_label = label.replace(" ", "_")
        ext = "npz" if format == "npz" else "csv"
        file_path = self._recordings_dir / f"{created_at.strftime('%Y%m%d_%H%M%S')}_{safe_label}.{ext}"
        if format == "npz":
            np.savez_compressed(file_path, time_s=times, value=values.astype(np.float32))
        else:
            # Two-column CSV with header. float32 keeps disk size sane while
            # remaining lossless for typical voltage ranges (±10 V).
            stacked = np.column_stack([times.astype(np.float64), values.astype(np.float32)])
            np.savetxt(
                file_path,
                stacked,
                delimiter=",",
                header="time_s,value",
                comments="",
                fmt=("%.7f", "%.6e"),
            )
        summary = DatasetSummary(
            id=dataset_id,
            label=label,
            created_at=created_at,
            duration_s=float(times[-1] - times[0]) if len(times) > 1 else 0.0,
            sample_rate_hz=sample_rate_hz,
            sample_count=int(len(times)),
            file_path=str(file_path),
            file_size_bytes=file_path.stat().st_size,
            min_value=float(values.min()) if len(values) else 0.0,
            max_value=float(values.max()) if len(values) else 0.0,
        )
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO datasets (
                    id, label, created_at, duration_s, sample_rate_hz, sample_count,
                    file_path, file_size_bytes, min_value, max_value
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary.id,
                    summary.label,
                    summary.created_at.isoformat(),
                    summary.duration_s,
                    summary.sample_rate_hz,
                    summary.sample_count,
                    summary.file_path,
                    summary.file_size_bytes,
                    summary.min_value,
                    summary.max_value,
                ),
            )
            conn.commit()
        return summary

    def get_dataset(self, dataset_id: str) -> DatasetSummary | None:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT id, label, created_at, duration_s, sample_rate_hz, sample_count,
                       file_path, file_size_bytes, min_value, max_value
                FROM datasets
                WHERE id = ?
                """,
                (dataset_id,),
            ).fetchone()
        return self._row_to_summary(row) if row else None

    def load_preview(
        self,
        dataset_id: str,
        *,
        max_points: int = 900,
    ) -> dict[str, object] | None:
        summary = self.get_dataset(dataset_id)
        if summary is None:
            return None
        if summary.file_path.endswith(".csv"):
            arr = np.loadtxt(summary.file_path, delimiter=",", skiprows=1)
            times = arr[:, 0]
            values = arr[:, 1]
        else:
            payload = np.load(summary.file_path)
            times = payload["time_s"]
            values = payload["value"]
        times, values = decimate_pair(times, values, max_points=max_points)
        return {
            "id": summary.id,
            "label": summary.label,
            "sample_rate_hz": summary.sample_rate_hz,
            "time_s": times.tolist(),
            "value": values.tolist(),
        }

    def _row_to_summary(self, row: sqlite3.Row) -> DatasetSummary:
        return DatasetSummary(
            id=row["id"],
            label=row["label"],
            created_at=datetime.fromisoformat(row["created_at"]),
            duration_s=float(row["duration_s"]),
            sample_rate_hz=int(row["sample_rate_hz"]),
            sample_count=int(row["sample_count"]),
            file_path=row["file_path"],
            file_size_bytes=int(row["file_size_bytes"]),
            min_value=float(row["min_value"]),
            max_value=float(row["max_value"]),
        )
