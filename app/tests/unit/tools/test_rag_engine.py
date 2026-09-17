"""
app/tests/unit/tools/test_rag_engine.py
Comprehensive unit tests for Skill 2.1 — Persistent Memory (Local RAG Engine)

Covers complex scenarios, vector similarity calculations, SQLite schema persistence,
edge cases (unicode, accents, empty inputs), multithreaded concurrency, and prompt snippet generation.

LLM Reference: app/skills/02_core_features/SKILLS_CORE.md § 2.1
"""
import os
import shutil
import tempfile
import threading
import pytest
from pydantic import ValidationError

from backend.tools.rag_engine import LocalRAGEngine
from backend.core.schemas import RAGDocument, RAGQueryPayload, RAGSearchResult


# ---------------------------------------------------------------------------
# Schemas & DTO Validation
# ---------------------------------------------------------------------------

class TestRAGSchemas:
    """Test Pydantic V2 schemas for Skill 2.1."""

    def test_valid_rag_document(self):
        doc = RAGDocument(doc_id="doc_1", text="Sample content", metadata={"category": "test"})
        assert doc.doc_id == "doc_1"
        assert doc.text == "Sample content"
        assert doc.metadata == {"category": "test"}
        assert doc.created_at

    def test_empty_doc_id_rejected(self):
        with pytest.raises(ValidationError):
            RAGDocument(doc_id="", text="Content")

    def test_empty_text_rejected(self):
        with pytest.raises(ValidationError):
            RAGDocument(doc_id="doc_1", text="")

    def test_valid_rag_search_result(self):
        res = RAGSearchResult(doc_id="doc_1", text="Memory text", score=0.95, metadata={})
        assert res.score == 0.95
        assert res.text == "Memory text"

    def test_rag_query_payload_constraints(self):
        req = RAGQueryPayload(query="Where is Peru?", top_k=5)
        assert req.top_k == 5

        with pytest.raises(ValidationError):
            RAGQueryPayload(query="test", top_k=0)  # top_k >= 1 constraint


# ---------------------------------------------------------------------------
# Vector Math & Cosine Similarity
# ---------------------------------------------------------------------------

class TestCosineSimilarityMath:
    """Test vector math and similarity bounds."""

    def test_identical_vectors_similarity_one(self):
        vec_a = [1.0, 2.0, 3.0, 4.0]
        vec_b = [1.0, 2.0, 3.0, 4.0]
        score = LocalRAGEngine._cosine_similarity(vec_a, vec_b)
        assert pytest.approx(score, 0.001) == 1.0

    def test_orthogonal_vectors_similarity_zero(self):
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [0.0, 1.0, 0.0]
        score = LocalRAGEngine._cosine_similarity(vec_a, vec_b)
        assert score == 0.0

    def test_zero_vector_returns_zero(self):
        vec_a = [0.0, 0.0, 0.0]
        vec_b = [1.0, 2.0, 3.0]
        score = LocalRAGEngine._cosine_similarity(vec_a, vec_b)
        assert score == 0.0

    def test_mismatched_vector_lengths_return_zero(self):
        vec_a = [1.0, 2.0]
        vec_b = [1.0, 2.0, 3.0]
        score = LocalRAGEngine._cosine_similarity(vec_a, vec_b)
        assert score == 0.0


# ---------------------------------------------------------------------------
# LocalRAGEngine Lifecycle & Database Tests
# ---------------------------------------------------------------------------

class TestLocalRAGEngineLifecycle:

    @pytest.fixture
    def temp_rag_engine(self):
        tmp_dir = tempfile.mkdtemp(prefix="ignite_rag_test_")
        db_file = os.path.join(tmp_dir, "test_rag.db")
        engine = LocalRAGEngine(db_path=db_file)
        yield engine
        shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_database_auto_creation(self, temp_rag_engine):
        assert os.path.exists(temp_rag_engine.db_path)

    def test_index_and_retrieve_single_document(self, temp_rag_engine):
        success = temp_rag_engine.index_document(
            doc_id="note_1",
            text="Python is an interpreted high-level general-purpose programming language.",
            metadata={"type": "note"},
        )
        assert success is True

        results = temp_rag_engine.search_relevant_context("What is Python programming?", top_k=1)
        assert len(results) == 1
        assert results[0].doc_id == "note_1"
        assert "interpreted high-level" in results[0].text
        assert results[0].score > 0.0

    def test_update_existing_document(self, temp_rag_engine):
        temp_rag_engine.index_document("doc_A", "Initial version of note")
        temp_rag_engine.index_document("doc_A", "Updated version of note with more details")

        results = temp_rag_engine.search_relevant_context("Updated version", top_k=1)
        assert len(results) == 1
        assert "Updated version" in results[0].text

    def test_delete_document(self, temp_rag_engine):
        temp_rag_engine.index_document("doc_to_delete", "Temporary information")
        assert len(temp_rag_engine.search_relevant_context("Temporary", top_k=1)) == 1

        del_success = temp_rag_engine.delete_document("doc_to_delete")
        assert del_success is True
        assert len(temp_rag_engine.search_relevant_context("Temporary", top_k=1)) == 0

    def test_clear_memory(self, temp_rag_engine):
        temp_rag_engine.index_document("d1", "Alpha content")
        temp_rag_engine.index_document("d2", "Beta content")

        clear_success = temp_rag_engine.clear_memory()
        assert clear_success is True
        assert len(temp_rag_engine.search_relevant_context("Alpha", top_k=5)) == 0


# ---------------------------------------------------------------------------
# Complex Scenarios & Edge Cases
# ---------------------------------------------------------------------------

class TestComplexRAGScenarios:

    @pytest.fixture
    def rag_engine(self):
        tmp_dir = tempfile.mkdtemp(prefix="ignite_complex_rag_")
        db_file = os.path.join(tmp_dir, "complex_rag.db")
        engine = LocalRAGEngine(db_path=db_file)
        yield engine
        shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_empty_and_blank_query_handling(self, rag_engine):
        rag_engine.index_document("d1", "Valid content")
        assert rag_engine.search_relevant_context("") == []
        assert rag_engine.search_relevant_context("   ") == []
        assert rag_engine.index_document("", "Content") is False
        assert rag_engine.index_document("id", "") is False

    def test_spanish_accents_and_unicode_characters(self, rag_engine):
        # Index document in Spanish with accents and special characters
        rag_engine.index_document(
            doc_id="peru_info",
            text="La capital del Perú es Lima. El país cuenta con 24 departamentos y una provincia constitucional.",
            metadata={"lang": "es"},
        )
        rag_engine.index_document(
            doc_id="recipes",
            text="Receta de Ceviche peruano: pescado fresco, limón, cebolla morada y ají mochero.",
            metadata={"lang": "es"},
        )

        # Search query with inverted question mark and accents
        results = rag_engine.search_relevant_context("¿Cuál es la capital del Perú?", top_k=1)
        assert len(results) == 1
        assert results[0].doc_id == "peru_info"
        assert "Lima" in results[0].text

    def test_semantic_ranking_relevance_sorting(self, rag_engine):
        # Index 3 distinctly themed documents
        rag_engine.index_document("astronomy", "Black holes are regions of spacetime where gravity is so strong that nothing can escape.")
        rag_engine.index_document("cooking", "Italian pasta requires semolina flour, fresh eggs, and boiling salted water.")
        rag_engine.index_document("software", "SQL Server is a relational database management system developed by Microsoft.")

        # Query astronomy
        astro_res = rag_engine.search_relevant_context("Tell me about spacetime and black holes", top_k=3)
        assert len(astro_res) > 0
        assert astro_res[0].doc_id == "astronomy"

        # Query software
        sw_res = rag_engine.search_relevant_context("Microsoft SQL Server database management", top_k=3)
        assert len(sw_res) > 0
        assert sw_res[0].doc_id == "software"

    def test_index_conversation_turn_and_prompt_snippet(self, rag_engine):
        # Simulate conversation turn auto-indexing
        rag_engine.index_conversation_turn(
            user_msg="¿Cuál es la clave del servidor de desarrollo?",
            assistant_reply="La clave del servidor dev es Ignite2026SecurePass!",
            session_id="session_dev_1",
        )

        # Retrieve system prompt snippet
        snippet = rag_engine.get_rag_system_prompt_snippet("clave del servidor dev", top_k=1)
        assert "[LOCAL PERSISTENT MEMORY RECALLED]" in snippet
        assert "Ignite2026SecurePass" in snippet

    def test_index_session_messages_skips_welcome_and_keeps_group_replies(self, rag_engine):
        counted = rag_engine.index_session_messages(
            [
                {"role": "assistant", "content": "Welcome", "is_welcome": True},
                {"role": "user", "content": "What is the office WiFi password?"},
                {"role": "assistant", "content": "Error: boom"},
                {"role": "assistant", "content": "The WiFi password is Harbor-42."},
                {"role": "assistant", "content": "Grok agrees: Harbor-42."},
            ],
            "Gemini_gemini-3.1-flash-lite_20260101_000000",
        )
        assert counted >= 2
        snippet = rag_engine.get_rag_system_prompt_snippet("office WiFi password", top_k=2)
        assert "Harbor-42" in snippet
        assert rag_engine.document_exists(
            "turn_Gemini_gemini-3.1-flash-lite_20260101_000000_0"
        )
        # Second backfill must be idempotent (stable doc ids, no duplicate embeddings).
        again = rag_engine.index_session_messages(
            [
                {"role": "user", "content": "What is the office WiFi password?"},
                {"role": "assistant", "content": "The WiFi password is Harbor-42."},
            ],
            "Gemini_gemini-3.1-flash-lite_20260101_000000",
        )
        assert again >= 1

    def test_multithreaded_concurrent_indexing_and_searching(self, rag_engine):
        # Test 10 concurrent threads inserting and querying simultaneously
        errors = []

        def worker_task(worker_id):
            try:
                doc_id = f"thread_doc_{worker_id}"
                text = f"Thread worker {worker_id} content processing high-concurrency tasks."
                rag_engine.index_document(doc_id, text)
                res = rag_engine.search_relevant_context(f"worker {worker_id}", top_k=2)
                assert len(res) > 0
            except Exception as err:
                errors.append(err)

        threads = [threading.Thread(target=worker_task, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent execution errors encountered: {errors}"
