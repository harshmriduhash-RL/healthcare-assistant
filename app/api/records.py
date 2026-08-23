"""
Medical record upload + listing routes.

Uploading is a two-part job: (1) save the raw PDF file to disk and record
its metadata in the medical_records table, and (2) hand it off to the RAG
pipeline (app/agents/rag.py) to extract, chunk, and embed its text for
later semantic search. Both happen synchronously in the same request here
-- for a prototype's file sizes, this keeps things simple (no background
job queue needed) at the cost of the upload request taking a bit longer
to return while indexing runs.
"""

import os
import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.rag import process_and_store_record
from app.core.config import settings
from app.core.deps import get_current_user
from app.db.models import MedicalRecord, User, Notification
from app.db.session import get_db

router = APIRouter(prefix="/api/records", tags=["records"])


@router.post("/upload")
async def upload_record(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Accept a PDF upload, save it, record its metadata, and index it
    for semantic search.
    """
    os.makedirs(settings.upload_dir, exist_ok=True)
    # Prefix the stored filename with a random UUID so two users
    # uploading files with the same original name (e.g. "report.pdf")
    # never collide on disk -- the ORIGINAL filename is preserved
    # separately in the `filename` DB column for display purposes.
    safe_name = f"{uuid.uuid4()}_{file.filename}"
    file_path = os.path.join(settings.upload_dir, safe_name)

    contents = await file.read()
    if len(contents) > settings.max_upload_mb * 1024 * 1024:
        return {"error": f"File exceeds {settings.max_upload_mb}MB limit"}

    with open(file_path, "wb") as f:
        f.write(contents)

    record = MedicalRecord(user_id=user.id, filename=file.filename, file_path=file_path)
    db.add(record)
    await db.commit()
    await db.refresh(record)  # need record.id before passing it to the RAG pipeline below

    # Extract text, chunk it, embed each chunk, and store it -- see
    # app/agents/rag.py. Runs synchronously so the record is searchable
    # the moment this request returns.
    chunk_count = await process_and_store_record(user.id, record.id, file_path)

    # Generate mock AI insights for the uploaded record
    db.add(Notification(
        user_id=user.id,
        notification_type="record_insight",
        title=f"Insights from {record.filename}",
        body="Key values extracted: Cholesterol 210 mg/dL (up from 195). Blood pressure 120/80 (stable).",
        related_id=record.id
    ))
    await db.commit()

    return {"id": record.id, "filename": record.filename, "chunks_indexed": chunk_count}


@router.get("/")
async def list_records(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """List this user's uploaded records, most recent first."""
    result = await db.execute(select(MedicalRecord).where(MedicalRecord.user_id == user.id).order_by(MedicalRecord.uploaded_at.desc()))
    records = result.scalars().all()
    return [{"id": r.id, "filename": r.filename, "record_type": r.record_type, "uploaded_at": r.uploaded_at.isoformat()} for r in records]
