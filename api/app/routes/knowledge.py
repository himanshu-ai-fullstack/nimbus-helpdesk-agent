"""A tenant's knowledge base: list, upload, add by URL, re-index, delete.
Indexing (chunking + embedding) runs as a background task, so large files don't
hold the request open; the document shows 'processing' until it is ready."""

import logging
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from ..config import get_settings
from ..ingest import FetchRejected, Parsed, UnsupportedDocument, fetch_url, parse_html, parse_upload
from ..ingest.parsers import parse_pdf, parse_text
from ..rag.store import DuplicateDocument, VectorStore
from .deps import TenantAdmin

log = logging.getLogger(__name__)
router = APIRouter()


async def _index(store: VectorStore, tenant: str, document_id: int) -> None:
    try:
        await store.index_document(tenant, document_id)
    except Exception:
        # index_document has already marked the document failed with the reason.
        log.exception("indexing document %s for %s failed", document_id, tenant)


async def _store(
    request: Request, tasks: BackgroundTasks, tenant: str, parsed: Parsed, source: str
) -> dict[str, Any]:
    store: VectorStore = request.app.state.store
    try:
        doc_id = await store.create_document(
            tenant, parsed.title, parsed.pages, source=source, kind=parsed.kind
        )
    except DuplicateDocument as e:
        raise HTTPException(409, str(e)) from None
    tasks.add_task(_index, store, tenant, doc_id)
    return {"id": doc_id, "title": parsed.title, "status": "processing", "pages": len(parsed.pages)}


@router.get("/api/t/{slug}/documents")
async def list_documents(request: Request, t: TenantAdmin) -> list[dict[str, Any]]:
    return await request.app.state.store.list_documents(t.slug)


@router.post("/api/t/{slug}/documents", status_code=202)
async def upload_document(
    file: UploadFile, request: Request, tasks: BackgroundTasks, t: TenantAdmin
) -> dict[str, Any]:
    limit = get_settings().max_upload_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"files must be under {limit // 1_000_000} MB")
    name = file.filename or "upload.txt"
    try:
        parsed = parse_upload(name, data)
    except UnsupportedDocument as e:
        raise HTTPException(415, str(e)) from None
    return await _store(request, tasks, t.slug, parsed, source=name)


class UrlIn(BaseModel):
    url: str = Field(max_length=2000)


@router.post("/api/t/{slug}/documents/url", status_code=202)
async def add_url(
    body: UrlIn, request: Request, tasks: BackgroundTasks, t: TenantAdmin
) -> dict[str, Any]:
    try:
        page = await fetch_url(body.url, max_bytes=get_settings().max_upload_bytes)
        if page.content_type == "application/pdf":
            parsed = parse_pdf(page.data, page.url)
        elif page.content_type == "text/html":
            parsed = parse_html(page.data, page.url)
        else:
            parsed = parse_text(page.data, page.url)
    except (FetchRejected, UnsupportedDocument) as e:
        raise HTTPException(422, str(e)) from None
    except httpx.HTTPError as e:  # network errors, timeouts
        raise HTTPException(502, f"couldn't fetch the page: {e.__class__.__name__}") from None
    parsed.kind = "web"
    return await _store(request, tasks, t.slug, parsed, source=page.url)


@router.post("/api/t/{slug}/documents/{document_id}/reindex", status_code=202)
async def reindex(
    document_id: int, request: Request, tasks: BackgroundTasks, t: TenantAdmin
) -> dict[str, Any]:
    store: VectorStore = request.app.state.store
    if not await store.mark_processing(t.slug, document_id):
        raise HTTPException(404, "document not found")
    tasks.add_task(_index, store, t.slug, document_id)
    return {"id": document_id, "status": "processing"}


@router.delete("/api/t/{slug}/documents/{document_id}")
async def delete_document(document_id: int, request: Request, t: TenantAdmin) -> dict[str, str]:
    if not await request.app.state.store.delete_document(t.slug, document_id):
        raise HTTPException(404, "document not found")
    return {"status": "deleted"}
