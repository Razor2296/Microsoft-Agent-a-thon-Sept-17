"""
app/backend/tools/rag_engine.py
Skill 2.1 — Persistent Memory (Local RAG Engine with SQLite Vector Store)

Stores documents, user notes, and conversation turns in a local SQLite database
(<IGNITE_DATA_DIR or get_writable_data_dir()>/Databases/vector_store/local_rag[__tenant].db)
with dense vector embeddings and cosine similarity search.

LLM Reference: See app/skills/02_core_features/SKILLS_CORE.md § 2.1
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
import hashlib
from typing import Any, Dict, List, Optional, Tuple

from backend.core.libraries import get_assistant_logger
from backend.core.runtime_paths import get_writable_data_dir
from backend.core.schemas import RAGDocument, RAGQueryPayload, RAGSearchResult

logger = get_assistant_logger("rag_engine")

# Optional SBERT model loading with defensive fallback
_SENTENCE_TRANSFORMER_MODEL = None
_SBERT_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer  # type: ignore
    _SBERT_AVAILABLE = True
except ImportError:
    _SBERT_AVAILABLE = False

# Class That Manages Persistent Memory of the Assistant, Uses SBERT to Embedd Text and Cosine Similarity to Search for Similar Documents
class LocalRAGEngine:
    """
    Production-grade Local RAG Engine backed by an autonomous SQLite Vector Store.
    Provides document indexing, conversation turn logging, cosine similarity vector search,
    and system prompt snippet formatting.
    """

    @staticmethod
    def default_db_path(tenant_key: Optional[str] = None) -> str:
        """
        Per-tenant SQLite path for ACA isolation. Desktop (no tenant) keeps local_rag.db.
        Never share one DB file across X-Ignite-Session-Id tenants.

        Base dir follows IGNITE_DATA_DIR (ACA Azure Files) or get_writable_data_dir()
        so frozen desktop writes under %LOCALAPPDATA%\\Ignite Chat instead of Program Files.
        Without IGNITE_DATA_DIR on ACA the DB would sit on the container's ephemeral layer
        and every deploy or scale-to-zero would wipe it.
        """
        tools_dir = os.path.dirname(os.path.abspath(__file__))
        app_root = os.path.dirname(os.path.dirname(tools_dir))
        env_dir = (os.getenv("IGNITE_DATA_DIR") or "").strip()
        base_dir = env_dir or get_writable_data_dir()
        db_dir = os.path.join(base_dir, "Databases", "vector_store")
        try:
            os.makedirs(db_dir, exist_ok=True)
        except OSError as exc:
            if base_dir == app_root:
                raise
            logger.warning(
                "IGNITE_DATA_DIR=%s is not writable (%s); RAG DB falls back to %s and will "
                "not survive container restarts.", base_dir, exc, app_root
            )
            db_dir = os.path.join(app_root, "Databases", "vector_store")
            os.makedirs(db_dir, exist_ok=True)
        if tenant_key and str(tenant_key).strip():
            cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(tenant_key).strip())[:64]
            if cleaned:
                return os.path.join(db_dir, f"local_rag__{cleaned}.db")
        return os.path.join(db_dir, "local_rag.db")

    def __init__(self, db_path: Optional[str] = None, tenant_key: Optional[str] = None):
        if db_path is None:
            db_path = self.default_db_path(tenant_key)

        self.db_path = db_path
        self._tenant_key = (tenant_key or "").strip() or None
        self._init_database()
        self._init_embedding_model()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a thread-safe connection to local_rag.db with WAL mode."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
        except Exception:
            pass
        return conn

    def _init_database(self) -> None:
        """Initialize SQLite database schema for document and vector storage."""
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS rag_documents (
                        doc_id TEXT PRIMARY KEY,
                        content TEXT NOT NULL,
                        metadata TEXT,
                        created_at TEXT NOT NULL
                    );
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS rag_vectors (
                        doc_id TEXT PRIMARY KEY,
                        embedding_json TEXT NOT NULL,
                        FOREIGN KEY (doc_id) REFERENCES rag_documents(doc_id) ON DELETE CASCADE
                    );
                    """
                )
                conn.commit()
                logger.info(f"Local RAG SQLite database initialized at: {self.db_path}")
        except Exception as err:
            logger.error(f"Failed to initialize Local RAG database: {err}", exc_info=True)

    def _init_embedding_model(self) -> None:
        """Attempt to load SentenceTransformer model or mark fallback mode."""
        global _SENTENCE_TRANSFORMER_MODEL, _SBERT_AVAILABLE
        if _SBERT_AVAILABLE and _SENTENCE_TRANSFORMER_MODEL is None:
            try:
                logger.info("Loading SBERT model (all-MiniLM-L6-v2) for Local RAG...")
                _SENTENCE_TRANSFORMER_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
                logger.info("SBERT model loaded successfully.")
            except Exception as err:
                logger.warning(f"Could not load SentenceTransformer model: {err}. Using TF-IDF/N-Gram vectorizer fallback.")
                _SBERT_AVAILABLE = False

    # ---------------------------------------------------------------------------
    # Embeddings & Cosine Similarity
    # ---------------------------------------------------------------------------

    def _compute_embedding(self, text: str) -> List[float]:
        """
        Compute dense float vector embedding for given text.
        Uses SBERT if available; otherwise uses deterministic N-Gram TF-IDF subword vectorizer.
        """
        if not text or not text.strip():
            return [0.0] * 64

        clean_text = text.strip().lower()

        if _SBERT_AVAILABLE and _SENTENCE_TRANSFORMER_MODEL is not None:
            try:
                vector = _SENTENCE_TRANSFORMER_MODEL.encode(clean_text)
                return vector.tolist()
            except Exception as err:
                logger.warning(f"SBERT encoding failed: {err}. Falling back to N-Gram vectorizer.")

        # Fallback vectorizer: Character & Word 3-gram hash frequency vector (64 dimensions)
        dims = 64
        vec = [0.0] * dims
        tokens = re.findall(r"\w+", clean_text)

        # Word tokens
        for token in tokens:
            idx = int(hashlib.md5(token.encode('utf-8')).hexdigest(), 16) % dims
            vec[idx] += 1.0

        # Subword n-grams (3-grams) for robust subword matching
        for i in range(len(clean_text) - 2):
            ngram = clean_text[i : i + 3]
            idx = int(hashlib.md5(ngram.encode('utf-8')).hexdigest(), 16) % dims
            vec[idx] += 0.5

        # L2 Normalize
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [round(x / norm, 5) for x in vec]

        return vec

    @staticmethod
    def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """Calculate cosine similarity score between two dense float vectors."""
        if not vec_a or not vec_b or len(vec_a) != len(vec_b):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))

        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0

        similarity = dot_product / (norm_a * norm_b)
        return max(0.0, min(1.0, similarity))

    # ---------------------------------------------------------------------------
    # Public Indexing API
    # ---------------------------------------------------------------------------

    def index_document(
        self,
        doc_id: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Index or update a document text in local vector store.

        Args:
            doc_id: Unique string identifier for the document.
            text: Main body text content.
            metadata: Optional dictionary of tags.

        Returns:
            True if document was successfully indexed.
        """
        if not doc_id or not text or not text.strip():
            logger.warning("RAGEngine: Skipped indexing empty document or doc_id")
            return False

        meta_dict = metadata or {}
        meta_json = json.dumps(meta_dict, ensure_ascii=False)
        created_at = meta_dict.get("created_at") or time.strftime("%Y-%m-%d %H:%M:%S")

        embedding = self._compute_embedding(text)
        embedding_json = json.dumps(embedding)

        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO rag_documents (doc_id, content, metadata, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(doc_id) DO UPDATE SET
                        content = excluded.content,
                        metadata = excluded.metadata,
                        created_at = excluded.created_at;
                    """,
                    (doc_id, text.strip(), meta_json, created_at),
                )
                conn.execute(
                    """
                    INSERT INTO rag_vectors (doc_id, embedding_json)
                    VALUES (?, ?)
                    ON CONFLICT(doc_id) DO UPDATE SET
                        embedding_json = excluded.embedding_json;
                    """,
                    (doc_id, embedding_json),
                )
                conn.commit()
                logger.info(f"Indexed document '{doc_id}' into RAG local vector store.")
                return True
        except Exception as err:
            logger.error(f"Error indexing document '{doc_id}': {err}", exc_info=True)
            return False

    def document_exists(self, doc_id: str) -> bool:
        """Return True when doc_id is already stored (used to skip re-embedding backfills)."""
        if not doc_id:
            return False
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT 1 FROM rag_documents WHERE doc_id = ? LIMIT 1;",
                    (doc_id,),
                ).fetchone()
                return row is not None
        except Exception as err:
            logger.warning(f"Error checking RAG document '{doc_id}': {err}")
            return False

    def index_conversation_turn(
        self,
        user_msg: str,
        assistant_reply: str,
        session_id: str = "default",
        turn_index: Optional[int] = None,
    ) -> bool:
        """
        Index a conversation turn (User prompt + Assistant reply) into RAG memory.
        When turn_index is set, doc_id is stable so archived sessions can be backfilled
        without duplicating vectors on every launch.
        """
        if not user_msg or not user_msg.strip():
            return False

        if turn_index is not None:
            doc_id = f"turn_{session_id}_{int(turn_index)}"
            if self.document_exists(doc_id):
                return True
        else:
            doc_id = f"turn_{session_id}_{int(time.time() * 1000)}"
        content = f"User Question: {user_msg.strip()}\nAssistant Answer: {assistant_reply.strip()}"
        metadata = {
            "source": "conversation_history",
            "session_id": session_id,
            "user_prompt": user_msg.strip(),
        }
        return self.index_document(doc_id, content, metadata)

    def index_session_messages(self, messages: List[Dict[str, Any]], session_id: str) -> int:
        """Index user/assistant pairs from a saved session. Skips welcome and error turns."""
        if not messages or not session_id:
            return 0
        indexed = 0
        pending_user = None
        turn_idx = 0
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            if msg.get("is_welcome"):
                continue
            role = str(msg.get("role") or "").strip().lower()
            content = msg.get("content")
            text = content.strip() if isinstance(content, str) else ""
            if role == "user" and text:
                pending_user = text
            elif role == "assistant" and pending_user and text:
                if text.startswith("Error:") or text.startswith("⚠️"):
                    continue
                if self.index_conversation_turn(
                    pending_user, text, session_id=session_id, turn_index=turn_idx
                ):
                    indexed += 1
                turn_idx += 1
        return indexed

    def delete_document(self, doc_id: str) -> bool:
        """Delete a document and its vector embedding by doc_id."""
        try:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM rag_vectors WHERE doc_id = ?;", (doc_id,))
                conn.execute("DELETE FROM rag_documents WHERE doc_id = ?;", (doc_id,))
                conn.commit()
                return True
        except Exception as err:
            logger.error(f"Error deleting document '{doc_id}': {err}")
            return False

    def clear_memory(self) -> bool:
        """Wipe all documents and vectors from the local RAG store."""
        try:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM rag_vectors;")
                conn.execute("DELETE FROM rag_documents;")
                conn.commit()
                logger.info("Cleared all records from local RAG store.")
                return True
        except Exception as err:
            logger.error(f"Error clearing RAG memory: {err}")
            return False

    # ---------------------------------------------------------------------------
    # Public Retrieval API
    # ---------------------------------------------------------------------------

    def search_relevant_context(
        self,
        query: str,
        top_k: int = 3,
        min_score: float = 0.1,
    ) -> List[RAGSearchResult]:
        """
        Query the local vector store for the top_k most relevant documents.

        Args:
            query: The search query or current user message.
            top_k: Number of top relevant results to return.
            min_score: Minimum cosine similarity threshold.

        Returns:
            List of RAGSearchResult DTOs ordered by similarity score descending.
        """
        if not query or not query.strip():
            return []

        query_vec = self._compute_embedding(query)
        req = RAGQueryPayload(query=query, top_k=top_k)

        results: List[RAGSearchResult] = []
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT d.doc_id, d.content, d.metadata, v.embedding_json
                    FROM rag_documents d
                    JOIN rag_vectors v ON d.doc_id = v.doc_id
                    """
                )
                rows = cursor.fetchall()

                scored_items: List[Tuple[float, str, str, Dict[str, Any]]] = []
                for row in rows:
                    doc_id = row["doc_id"]
                    content = row["content"]
                    meta_raw = row["metadata"]
                    meta_dict = json.loads(meta_raw) if meta_raw else {}
                    doc_vec = json.loads(row["embedding_json"])

                    score = self._cosine_similarity(query_vec, doc_vec)
                    if score >= min_score:
                        scored_items.append((score, doc_id, content, meta_dict))

                # Sort by similarity score descending
                scored_items.sort(key=lambda x: x[0], reverse=True)
                top_items = scored_items[: req.top_k]

                for score, doc_id, content, meta_dict in top_items:
                    results.append(
                        RAGSearchResult(
                            doc_id=doc_id,
                            text=content,
                            score=round(score, 4),
                            metadata=meta_dict,
                        )
                    )

            logger.info(f"Local RAG search for '{query[:30]}...' found {len(results)} relevant memories")
            return results
        except Exception as err:
            logger.error(f"Error executing RAG search for '{query}': {err}", exc_info=True)
            return []

    def get_rag_system_prompt_snippet(self, query: str, top_k: int = 3) -> str:
        """
        Build a formatted system prompt instruction string containing retrieved local memories.
        """
        results = self.search_relevant_context(query, top_k=top_k)
        if not results:
            return ""

        lines = ["[LOCAL PERSISTENT MEMORY RECALLED] Relevant past memories/notes:"]
        for idx, item in enumerate(results, 1):
            lines.append(f"- Memory {idx} (Score {item.score}): {item.text}")
        lines.append("Use these recalled factual memories to provide consistent, personalized answers.")
        return "\n".join(lines)
