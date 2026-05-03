from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from pickup_eds.instruments.base import BenchServiceProtocol

router = APIRouter(prefix="/api/data", tags=["data"])


def _service(request: Request) -> BenchServiceProtocol:
    return request.app.state.service


@router.get("/list")
async def list_datasets(request: Request) -> dict[str, object]:
    datasets = await _service(request).datasets()
    return {"items": [item.model_dump(mode="json") for item in datasets]}


@router.get("/{dataset_id}/preview")
async def preview_dataset(dataset_id: str, request: Request) -> dict[str, object]:
    preview = await _service(request).preview_dataset(dataset_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    return preview


@router.get("/{dataset_id}/download")
async def download_dataset(dataset_id: str, request: Request) -> FileResponse:
    dataset = await _service(request).get_dataset(dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    return FileResponse(
        path=dataset.file_path,
        media_type="application/octet-stream",
        filename=Path(dataset.file_path).name,
    )


@router.delete("/{dataset_id}")
async def delete_dataset(dataset_id: str, request: Request) -> dict[str, object]:
    ok = await _service(request).delete_dataset(dataset_id)
    if not ok:
        raise HTTPException(status_code=404, detail="dataset not found")
    return {"ok": True, "id": dataset_id}
