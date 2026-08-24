"""
Medical Record Upload, OCR Extraction, Auto-Reconciliation, and Doctor Visit Summary Export.
"""

import os
import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.rag import process_and_store_record
from app.core.config import settings
from app.core.deps import get_current_patient_context, get_current_user
from app.db.models import MedicalRecord, Notification, Patient, User
from app.db.session import get_db
from app.services.ocr_service import (
    analyze_prescription_discrepancies,
    extract_and_store_lab_vitals,
    extract_text_from_file,
    generate_doctor_visit_summary,
)

router = APIRouter(prefix="/api/records", tags=["records"])


@router.post("/upload")
async def upload_record(
    file: UploadFile = File(...),
    patient: Patient = Depends(get_current_patient_context),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Accept a PDF or image upload, run OCR & lab value extraction, index RAG chunks, and run prescription auto-reconciliation."""
    os.makedirs(settings.upload_dir, exist_ok=True)
    safe_name = f"{uuid.uuid4()}_{file.filename}"
    file_path = os.path.join(settings.upload_dir, safe_name)

    contents = await file.read()
    if len(contents) > settings.max_upload_mb * 1024 * 1024:
        return {"error": f"File exceeds {settings.max_upload_mb}MB limit"}

    with open(file_path, "wb") as f:
        f.write(contents)

    # Perform text extraction
    extracted_text = await extract_text_from_file(file_path, file.filename)

    record = MedicalRecord(
        patient_id=patient.id,
        user_id=user.id,
        filename=file.filename,
        file_path=file_path,
        extracted_summary=extracted_text[:1000] if extracted_text else "Medical document uploaded.",
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    # Process chunks for RAG vector search
    chunk_count = await process_and_store_record(patient.id, record.id, file_path)

    # Extract & store lab vitals (HbA1c, BP, Glucose, Creatinine, Cholesterol)
    vitals_found = await extract_and_store_lab_vitals(db, patient.id, extracted_text, source=file.filename)

    # Run prescription auto-reconciliation check against current medicines
    reconcile_results = await analyze_prescription_discrepancies(db, patient.id, extracted_text)

    # Create notification insight
    insight_text = f"Analyzed {file.filename}. "
    if vitals_found:
        insight_text += f"Extracted vitals: {', '.join([f'{v[\"type\"]}: {v[\"value\"]}' for v in vitals_found])}. "
    if reconcile_results["has_discrepancies"]:
        insight_text += "Proposed prescription updates found for human review."
        record.reconciliation_proposed = True
        await db.commit()

    db.add(Notification(
        user_id=user.id,
        patient_id=patient.id,
        notification_type="record_insight",
        title=f"Document Insights: {record.filename}",
        body=insight_text,
        related_id=record.id,
        action_payload={"reconciliation": reconcile_results},
    ))
    await db.commit()

    return {
        "id": record.id,
        "filename": record.filename,
        "chunks_indexed": chunk_count,
        "vitals_extracted": vitals_found,
        "reconciliation": reconcile_results,
    }


@router.get("/")
async def list_records(
    patient: Patient = Depends(get_current_patient_context),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List uploaded medical records for the current patient context."""
    stmt = (
        select(MedicalRecord)
        .where(MedicalRecord.patient_id == patient.id)
        .order_by(MedicalRecord.uploaded_at.desc())
    )
    result = await db.execute(stmt)
    records = result.scalars().all()
    return [{
        "id": r.id,
        "filename": r.filename,
        "record_type": r.record_type,
        "summary": r.extracted_summary,
        "reconciliation_proposed": r.reconciliation_proposed,
        "uploaded_at": r.uploaded_at.isoformat(),
    } for r in records]


@router.get("/export-summary/{patient_id}")
async def export_doctor_visit_summary(
    patient_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """1-Click doctor visit preparation summary export."""
    summary = await generate_doctor_visit_summary(db, patient_id)
    return summary
