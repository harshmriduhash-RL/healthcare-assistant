"""
RAG (Retrieval-Augmented Generation) pipeline for medical record PDFs:
extract text, split it into chunks, embed each chunk as a vector, store
it in Postgres via pgvector, and later search those vectors by semantic
similarity to answer questions.

Two entry points other files use:
  - process_and_store_record(...) -- called once, right after a PDF is
    uploaded (see app/api/records.py), to index it.
  - semantic_search_records(...) -- called by the Records Agent
    (app/agents/workers.py) every time a user asks a question about
    their records.
"""

from pypdf import PdfReader
from sentence_transformers import SentenceTransformer
from sqlalchemy import select

from app.db.models import RecordChunk
from app.db.session import AsyncSessionLocal

# Loaded once at import time (not per-request) since loading a transformer
# model from disk/HuggingFace cache has real startup cost -- we want that
# cost paid once when the app starts, not on every upload or search.
# "all-MiniLM-L6-v2" outputs 384-dimensional vectors, which is why
# RecordChunk.embedding in app/db/models.py is declared as Vector(384) --
# if this model is ever swapped for a different one, that column's
# dimension has to change (and everything re-embedded) to match.
_embedder = SentenceTransformer("all-MiniLM-L6-v2")

# Chunking parameters: how many characters per chunk, and how much
# consecutive chunks overlap (so a sentence that straddles a chunk
# boundary isn't completely lost from context in either chunk).
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


def extract_pdf_text(file_path: str) -> str:
    """Read every page of a PDF and concatenate its extracted text.

    pypdf's extract_text() can return None for a page with no extractable
    text (e.g. a scanned image with no text layer) -- `or ""` guards
    against that so we don't crash trying to join None into a string.
    """
    reader = PdfReader(file_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split one long string into overlapping fixed-size windows.

    A simple sliding-window chunker (not sentence- or paragraph-aware) --
    good enough for a prototype; a production system might chunk on
    semantic boundaries instead. Advancing by (chunk_size - overlap) each
    iteration is what creates the overlap between consecutive chunks.
    """
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    # Strip whitespace and drop any chunks that end up empty (e.g. from
    # trailing whitespace-only content at the end of the document).
    return [c.strip() for c in chunks if c.strip()]


async def process_and_store_record(user_id: str, record_id: str, file_path: str) -> int:
    """Full indexing pipeline for one uploaded PDF: extract -> chunk ->
    embed -> store. Called synchronously right after upload (see
    app/api/records.py) so the document is searchable immediately,
    without needing a separate background job or job queue for this
    prototype's scale.

    Returns the number of chunks created (0 if the PDF had no extractable
    text, e.g. a pure-image scan with no OCR applied).
    """
    text = extract_pdf_text(file_path)
    chunks = chunk_text(text)
    if not chunks:
        return 0

    # Embed all chunks in one batched call (much faster than one call per
    # chunk). normalize_embeddings=True scales each vector to unit length,
    # which makes cosine-distance comparisons at search time simpler/more
    # consistent.
    embeddings = _embedder.encode(chunks, normalize_embeddings=True)

    async with AsyncSessionLocal() as db:
        for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            db.add(RecordChunk(
                record_id=record_id, user_id=user_id, chunk_index=idx,
                content=chunk, embedding=embedding.tolist(),  # pgvector's SQLAlchemy type wants a plain Python list, not a numpy array
            ))
        await db.commit()

    return len(chunks)


async def semantic_search_records(user_id: str, query: str, top_k: int = 4) -> list[dict]:
    """Find the top_k chunks (across ALL of this user's records) most
    semantically similar to `query`, and return them with their source
    filename attached.

    This is what the Records Agent calls to ground its answers in the
    user's actual uploaded documents instead of the LLM's general
    training knowledge.
    """
    # Embed the query the exact same way chunks were embedded (same
    # model, same normalization) -- comparing vectors only makes sense if
    # both sides were produced consistently.
    query_embedding = _embedder.encode([query], normalize_embeddings=True)[0].tolist()

    async with AsyncSessionLocal() as db:
        # order_by(...cosine_distance(...)) is pgvector's SQLAlchemy
        # integration doing the actual similarity search IN the database
        # (using the IVFFlat index created in the migration) rather than
        # pulling every chunk into Python and comparing there -- this is
        # what makes semantic search fast even as the number of stored
        # chunks grows.
        stmt = (
            select(RecordChunk)
            .where(RecordChunk.user_id == user_id)  # never search across other users' records
            .order_by(RecordChunk.embedding.cosine_distance(query_embedding))
            .limit(top_k)
        )
        result = await db.execute(stmt)
        chunks = result.scalars().all()

    # Second query to resolve each chunk's parent record filename, so the
    # answer can cite "which file did this come from." Done in a separate
    # session/loop for simplicity in this prototype; a production version
    # would likely join this into the first query instead.
    from app.db.models import MedicalRecord
    async with AsyncSessionLocal() as db:
        output = []
        for c in chunks:
            rec = await db.get(MedicalRecord, c.record_id)
            output.append({"filename": rec.filename if rec else "unknown", "content": c.content})
        return output
