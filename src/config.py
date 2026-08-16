"""
config.py
---------
Single source of truth for paths and tunable settings.

Every script in src/ imports from here. Before this file was wired up,
PROJECT_ROOT was redefined in 6 scripts, the embedding model name and
collection name in 3 each, and TOP_K disagreed with itself (config said
5, query.py said 3) — so changing the embedding model meant editing
three files and silently getting it wrong in a fourth.

Paths are absolute, derived from this file's location, so scripts behave
the same whatever directory they are run from.

Imported as `from config import ...`, which works because the scripts are
run directly (`python src/chunk.py`), putting src/ on the import path.
"""

from pathlib import Path


# ============================================================
# Project layout
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = PROJECT_ROOT / "data"
EVALUATION_DIR = PROJECT_ROOT / "evaluation"

# Pipeline stages, in order. Each stage reads the previous one's output.
SOURCE_DIR = DATA_DIR / "source"                 # input PDFs
EXTRACTED_DIR = DATA_DIR / "extracted"           # ingest.py
PREPROCESSED_DIR = DATA_DIR / "preprocessed"     # preprocessing.py
CHUNKS_DIR = DATA_DIR / "chunks"                 # chunk.py
CHUNKS_PATH = CHUNKS_DIR / "chunks.json"
CHROMA_DIR = DATA_DIR / "chroma_db"              # embed.py
QUERY_RESULTS_PATH = DATA_DIR / "query_results.json"   # query.py

# Labelled evaluation set and the report evaluate_retrieval.py writes.
QUERIES_PATH = EVALUATION_DIR / "clinical_queries.json"
RETRIEVAL_REPORT_PATH = EVALUATION_DIR / "retrieval_report.json"


# ============================================================
# Preprocessing
#
# Page furniture is detected by frequency rather than hardcoded regex,
# so these thresholds control how aggressive that detection is.
# ============================================================

# Lines this far from the top/bottom of a page may be furniture. Beyond
# that, a bare number is more likely a table cell — a dose or an eGFR
# threshold — than a page number.
EDGE_LINES = 8

# A line must appear near the edge of this fraction of pages to count as
# a running header/footer.
FURNITURE_PAGE_RATIO = 0.5

# Frequency detection is meaningless on a very short document.
MIN_PAGES_FOR_DETECTION = 4

# Real clinical prose is never byte-identical across half a document, but
# a copyright footer can be long.
MAX_FURNITURE_LINE_LENGTH = 250

# A page is treated as a table of contents when this fraction of its
# lines look like contents entries. Measured on these documents: real
# contents pages score 0.34-1.00, the highest page of real clinical
# content scores 0.08, so 0.30 sits in a wide gap.
TOC_LINE_RATIO = 0.30
MIN_TOC_LINES = 8


# ============================================================
# Chunking
# ============================================================

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150

# Page types preprocessing.py flags as non-content. Chunking these would
# put copyright notices and contents listings into the index as if they
# were clinical guidance.
SKIPPED_PAGE_TYPES = {"copyright", "table_of_contents"}

# Drop chunks too short to support an answer — e.g. a cover-page title,
# which is topically dense and so scores highly against almost any
# diabetes question while carrying no clinical information.
#
# Kept deliberately low: some genuinely short chunks ARE clinical
# content. "IF SYMPTOMATIC and FPG >=15 mmol/L ... gliclazide 80 mg
# 1 x daily" is 85 characters of dosing guidance that a higher threshold
# would silently delete.
MIN_CHUNK_CHARS = 60


# ============================================================
# Embedding and vector store
# ============================================================

# General-purpose model, 384 dimensions, 256-token window. Note the
# window: chunks near CHUNK_SIZE characters are already at its limit, so
# raising CHUNK_SIZE without changing model would silently truncate.
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

COLLECTION_NAME = "clinical_rag_t2dm"


# ============================================================
# Retrieval
# ============================================================

# Chunks retrieved per query. Raised from 3 after measuring recall on the
# labelled set: answers were being retrieved and then truncated away.
TOP_K = 10

# Similarity distance above which a match is considered too weak.
#
# NOT currently safe to use as an abstention threshold on its own. On the
# labelled set the in-scope and out-of-scope score ranges OVERLAP:
# worst in-scope is 0.833, worst out-of-scope is 0.755. Any single
# cut-off either admits unanswerable questions or refuses real ones.
# Kept here as a measured reference point, not as a safety mechanism.
WEAK_MATCH_DISTANCE = 0.75
