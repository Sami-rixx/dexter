#!/usr/bin/env python3
"""
Tests for Dexter Bot - BUILD STEP 5 (Knowledge Retrieval)

Covers the Step 5 requirements of ARCHITECTURE.md sections 4.1, 7 and 11:
- The retrieve() contract behind a stable interface (Snippet dataclass)
- Retrieval relevance against the REAL Grade 7 Integrated Science
  knowledge files in config/topics/ (no fabricated sample content)
- Knowledge-file parsing and metadata (grade/subject/strand/topic)
- Graceful handling of missing, empty and malformed knowledge files
- Engine integration: persona + snippets + user text prompt assembly,
  snippet_ids/match_scores reported for logging, faithful-grounding
  instructions, and unsupported questions left unanswered by knowledge
- /reload picking up new knowledge files without a restart
- Review export (Markdown + CSV) including snippet_ids/match_scores
- End-to-end: Telegram handler -> AI engine -> retriever -> logger
"""

import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, AsyncMock, Mock

from ai.retriever import (
    Snippet,
    TopicRetriever,
    retrieve,
    reload_topics,
    TOPICS_DIR,
)
from ai.ai_engine import (
    AIEngine,
    STATUS_OK,
    STATUS_QUOTA_EXHAUSTED,
    REFERENCE_INSTRUCTIONS,
    reload_config,
)
from ai.exceptions import QuotaExhaustedError

# The 26 Grade 7 Integrated Science knowledge files ingested from the CBC
# PDF (source: "[studocu.com] - Integrated Science Grade 7 CBC Notes 2024
# - Safety & Concepts.pdf").
KNOWLEDGE_FILES = [
    "grade-7-acid-base-indicators-ph-scale.md",
    "grade-7-acids-bases-alkalis.md",
    "grade-7-basic-science-skills.md",
    "grade-7-cosmetics-effects-on-health.md",
    "grade-7-electrical-appliances-uses-safety.md",
    "grade-7-electricity-sources-circuits-conductors.md",
    "grade-7-excretory-system-skin.md",
    "grade-7-excretory-system-urinary-kidneys.md",
    "grade-7-fertilization-implantation-embryo-development.md",
    "grade-7-human-reproduction-menstrual-cycle.md",
    "grade-7-integrated-science-overview.md",
    "grade-7-laboratory-apparatus-heating-holding.md",
    "grade-7-laboratory-apparatus-measuring.md",
    "grade-7-laboratory-safety-hazards-first-aid.md",
    "grade-7-laboratory-safety-importance-rules.md",
    "grade-7-magnetism-magnets-uses.md",
    "grade-7-melting-point-boiling-point.md",
    "grade-7-microscope-parts-functions.md",
    "grade-7-mixtures-types-examples.md",
    "grade-7-separating-mixtures-decantation-filtration-evaporation.md",
    "grade-7-separating-mixtures-distillation-fractional-distillation.md",
    "grade-7-separating-mixtures-extraction-crystallization-magnets.md",
    "grade-7-separating-mixtures-sublimation-chromatography.md",
    "grade-7-si-units.md",
    "grade-7-static-electricity-uses-safety.md",
    "grade-7-uses-of-acids-and-bases.md",
]


class TestRetrieverModuleContract(unittest.TestCase):
    """The retrieve() interface required by architecture section 4.1."""

    def test_snippet_dataclass_fields(self):
        snippet = Snippet(source_file="a.md", content="text", match_score=1.0)
        self.assertEqual(snippet.source_file, "a.md")
        self.assertEqual(snippet.content, "text")
        self.assertEqual(snippet.match_score, 1.0)

    def test_retrieve_signature_default(self):
        """retrieve(query, max_snippets=2) per the architecture contract."""
        import inspect
        signature = inspect.signature(retrieve)
        self.assertEqual(signature.parameters['max_snippets'].default, 2)

    def test_retriever_module_has_no_telegram_or_gemini_imports(self):
        with open('ai/retriever.py', 'r') as f:
            content = f.read()
        for line in content.split('\n'):
            stripped = line.strip()
            if stripped.startswith('import ') or stripped.startswith('from '):
                self.assertNotIn('telegram', stripped)
                self.assertNotIn('gemini', stripped)
                self.assertNotIn('sqlite', stripped)

    def test_default_topics_dir_is_config_topics(self):
        self.assertTrue(TOPICS_DIR.endswith(os.path.join('config', 'topics')))

    def test_module_retrieve_never_raises_on_bad_query(self):
        self.assertEqual(retrieve(""), [])
        self.assertEqual(retrieve("   "), [])
        self.assertEqual(retrieve("?!"), [])


class TestKnowledgeBaseFiles(unittest.TestCase):
    """Validate the real knowledge files for consistency and retrieval fit."""

    def test_all_26_knowledge_files_exist(self):
        for filename in KNOWLEDGE_FILES:
            path = os.path.join('config', 'topics', filename)
            self.assertTrue(os.path.exists(path),
                            f"missing knowledge file: {filename}")

    def test_every_knowledge_file_is_wellformed(self):
        """Each file needs an H1, the metadata block and ## sections."""
        for filename in KNOWLEDGE_FILES:
            with open(os.path.join('config', 'topics', filename),
                      encoding='utf-8') as f:
                content = f.read()
            self.assertTrue(content.lstrip().startswith('# '),
                            f"{filename}: must start with an H1 title")
            for field in ('**Grade:**', '**Learning area:**', '**Strand:**',
                          '**Keywords:**', '**Source:**'):
                self.assertIn(field, content,
                              f"{filename}: missing metadata {field}")
            self.assertIn('\n## ', content,
                          f"{filename}: needs ## sections for retrieval")

    def test_retriever_loads_all_knowledge_files(self):
        retriever = TopicRetriever()
        success, message = retriever.reload()
        self.assertTrue(success)
        self.assertNotIn('skipped', message)
        self.assertGreaterEqual(retriever.file_count, 26)
        self.assertIn('26', message)

    def test_template_file_is_ignored(self):
        """_template.md exists (architecture section 3) but is not indexed."""
        self.assertTrue(os.path.exists(os.path.join('config', 'topics',
                                                    '_template.md')))
        retriever = TopicRetriever()
        retriever.reload()
        # 26 content files, template excluded.
        self.assertEqual(retriever.file_count, 26)


class TestRetrievalRelevance(unittest.TestCase):
    """Retrieval quality against the real Grade 7 knowledge base."""

    @classmethod
    def setUpClass(cls):
        cls.retriever = TopicRetriever()
        cls.retriever.reload()

    def _assert_top(self, query, expected_file):
        snippets = self.retriever.retrieve(query)
        self.assertTrue(snippets, f"no snippet for: {query!r}")
        self.assertEqual(snippets[0].source_file, expected_file,
                         f"top result for {query!r} was "
                         f"{snippets[0].source_file}")
        return snippets

    def test_mixture_question(self):
        self._assert_top("What is a mixture?",
                         "grade-7-mixtures-types-examples.md")

    def test_acids_and_bases_question(self):
        self._assert_top(
            "What are acids and bases?",
            "grade-7-acids-bases-alkalis.md")

    def test_bunsen_burner_question(self):
        self._assert_top("How do I light a Bunsen burner?",
                         "grade-7-laboratory-apparatus-heating-holding.md")

    def test_chromatography_question_finds_right_section(self):
        snippets = self._assert_top(
            "What is chromatography used for?",
            "grade-7-separating-mixtures-sublimation-chromatography.md")
        self.assertIn("Chromatography", snippets[0].content)

    def test_ph_scale_question(self):
        snippets = self._assert_top(
            "Explain the pH scale",
            "grade-7-acid-base-indicators-ph-scale.md")
        self.assertIn("pH scale", snippets[0].content)

    def test_menstrual_cycle_question_finds_right_section(self):
        snippets = self._assert_top(
            "What is the menstrual cycle?",
            "grade-7-human-reproduction-menstrual-cycle.md")
        self.assertIn("menstrual cycle", snippets[0].content.lower())

    def test_separating_sand_from_water(self):
        self._assert_top(
            "How can I separate sand from water?",
            "grade-7-separating-mixtures-decantation-filtration-evaporation.md")

    def test_uses_of_acids(self):
        self._assert_top("Uses of acids",
                         "grade-7-uses-of-acids-and-bases.md")

    def test_magnets_question(self):
        self._assert_top("Tell me about magnets",
                         "grade-7-magnetism-magnets-uses.md")

    def test_ovulation_question(self):
        self._assert_top("What is ovulation?",
                         "grade-7-human-reproduction-menstrual-cycle.md")

    def test_si_units_question(self):
        self._assert_top("What are the SI units?", "grade-7-si-units.md")

    def test_static_electricity_question(self):
        self._assert_top("What is static electricity?",
                         "grade-7-static-electricity-uses-safety.md")

    def test_lab_safety_rules_question(self):
        self._assert_top("Laboratory safety rules",
                         "grade-7-laboratory-safety-importance-rules.md")

    def test_snippets_are_self_contained(self):
        """Snippet content carries source + grade/strand context."""
        snippets = self.retriever.retrieve("What is sublimation?")
        self.assertTrue(snippets)
        content = snippets[0].content
        self.assertIn("Source: grade-7-", content)
        self.assertIn("Grade", content)
        self.assertIn("## ", content)

    def test_match_scores_are_normalized_floats(self):
        for query in ("What is a mixture?", "Explain the pH scale",
                      "Tell me about magnets"):
            for snippet in self.retriever.retrieve(query):
                self.assertIsInstance(snippet.match_score, float)
                self.assertGreater(snippet.match_score, 0.0)
                self.assertLessEqual(snippet.match_score, 1.0)

    def test_max_snippets_is_respected(self):
        self.assertEqual(len(self.retriever.retrieve(
            "What is a mixture?", max_snippets=1)), 1)
        self.assertEqual(self.retriever.retrieve("What is a mixture?",
                                                 max_snippets=0), [])

    def test_retrieval_is_deterministic(self):
        first = self.retriever.retrieve("separate sand from water")
        second = self.retriever.retrieve("separate sand from water")
        self.assertEqual([s.source_file for s in first],
                         [s.source_file for s in second])
        self.assertEqual([s.match_score for s in first],
                         [s.match_score for s in second])

    def test_unrelated_question_returns_nothing(self):
        """Questions outside the knowledge base must not fake a match."""
        for query in ("What is the capital of France?",
                      "Who won the football match?",
                      "Write me a poem"):
            self.assertEqual(self.retriever.retrieve(query), [],
                             f"unexpected match for {query!r}")

    def test_math_question_returns_nothing(self):
        """Regression for the Step 2 contract: maths goes to the persona,
        no science snippets injected."""
        self.assertEqual(self.retriever.retrieve("What is 2+2?"), [])
        self.assertEqual(self.retriever.retrieve("Solve x + 3 = 7"), [])


class TestRetrieverRobustness(unittest.TestCase):
    """Missing/empty/malformed knowledge files handled gracefully."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, name, content):
        with open(os.path.join(self.tmpdir, name), 'w',
                  encoding='utf-8') as f:
            f.write(content)

    def test_missing_directory_yields_empty_results(self):
        retriever = TopicRetriever(os.path.join(self.tmpdir, 'nope'))
        success, message = retriever.reload()
        self.assertFalse(success)
        self.assertEqual(retriever.retrieve("mixture"), [])

    def test_empty_directory_yields_empty_results(self):
        retriever = TopicRetriever(self.tmpdir)
        success, message = retriever.reload()
        self.assertTrue(success)
        self.assertEqual(retriever.retrieve("mixture"), [])

    def test_malformed_files_are_skipped_not_fatal(self):
        self._write('good.md',
                    "# Grade 7 Science — Mixtures\n\n"
                    "- **Grade:** 7\n- **Keywords:** mixture, mixtures\n\n"
                    "## What is a mixture?\nA mixture combines substances.\n")
        with open(os.path.join(self.tmpdir, 'binary.md'), 'wb') as f:
            f.write(b'\x00\x01\x02 not utf8 \xff\xfe')
        self._write('empty.md', '')
        retriever = TopicRetriever(self.tmpdir)
        success, message = retriever.reload()
        self.assertTrue(success)
        self.assertIn('skipped', message)
        snippets = retriever.retrieve("What is a mixture?")
        self.assertEqual(len(snippets), 1)
        self.assertEqual(snippets[0].source_file, 'good.md')

    def test_file_without_sections_is_still_retrievable(self):
        self._write('flat.md',
                    "# Grade 7 Science — Photosynthesis\n\n"
                    "- **Keywords:** photosynthesis\n\n"
                    "Plants make food using sunlight.\n")
        retriever = TopicRetriever(self.tmpdir)
        retriever.reload()
        snippets = retriever.retrieve("photosynthesis")
        self.assertEqual(len(snippets), 1)
        self.assertEqual(snippets[0].source_file, 'flat.md')
        self.assertIn("sunlight", snippets[0].content)

    def test_non_markdown_and_underscore_files_ignored(self):
        self._write('real.md',
                    "# T\n\n- **Keywords:** magnet\n\n## Magnet\ncontent\n")
        self._write('notes.txt', "ignore me")
        self._write('_template.md', "# template with keyword magnet")
        retriever = TopicRetriever(self.tmpdir)
        retriever.reload()
        self.assertEqual(retriever.file_count, 1)
        snippets = retriever.retrieve("magnet")
        self.assertEqual([s.source_file for s in snippets], ['real.md'])

    def test_reload_picks_up_new_files(self):
        retriever = TopicRetriever(self.tmpdir)
        retriever.reload()
        self.assertEqual(retriever.file_count, 0)
        self._write('new.md',
                    "# Grade 7 — Magnets\n\n- **Keywords:** magnet\n\n"
                    "## Magnets\nMagnets attract iron.\n")
        success, message = retriever.reload()
        self.assertTrue(success)
        self.assertEqual(retriever.file_count, 1)
        self.assertTrue(retriever.retrieve("magnet"))

    def test_reload_with_removed_directory_keeps_previous_index(self):
        self._write('keep.md',
                    "# Grade 7 — Magnets\n\n- **Keywords:** magnet\n\n"
                    "## Magnets\nMagnets attract iron.\n")
        retriever = TopicRetriever(self.tmpdir)
        retriever.reload()
        # Simulate the directory disappearing (e.g. transiently).
        inner = os.path.join(self.tmpdir, 'inner')
        retriever = TopicRetriever(inner)
        retriever.reload()  # loads empty index from empty dir? No — dir missing
        # Now the real case: load from tmpdir, then point somewhere missing.
        retriever = TopicRetriever(self.tmpdir)
        retriever.reload()
        retriever._topics_dir = os.path.join(self.tmpdir, 'vanished')
        success, message = retriever.reload()
        self.assertFalse(success)
        self.assertIn('keeping previous', message)
        self.assertEqual(retriever.file_count, 1)
        self.assertTrue(retriever.retrieve("magnet"))

    def test_retriever_exception_returns_empty(self):
        class Boom:
            def retrieve(self, query, max_snippets=2):
                raise RuntimeError("boom")
        # Engine-level guarantee is tested below; here verify the module
        # retriever never exposes partial state after a broken reload.
        retriever = TopicRetriever(os.path.join(self.tmpdir, 'missing'))
        self.assertEqual(retriever.retrieve("anything"), [])


class TestEngineRetrievalIntegration(unittest.TestCase):
    """AI engine + retriever: prompt assembly and result metadata."""

    def test_answer_injects_snippets_and_reports_them(self):
        with patch('ai.ai_engine.call_gemini_api') as mock_call:
            mock_call.return_value = ("A mixture is two or more substances.",
                                      "gemini-2.5-flash")
            result = retrieve_and_answer("What is a mixture?")
            self.assertEqual(result.status, STATUS_OK)
            self.assertIn("grade-7-mixtures-types-examples.md",
                          result.snippet_ids)
            self.assertEqual(len(result.match_scores),
                             len(result.snippet_ids))
            self.assertTrue(all(0 < s <= 1 for s in result.match_scores))

    def test_prompt_contains_persona_snippets_and_user_text(self):
        engine = AIEngine()
        with patch('ai.ai_engine.call_gemini_api') as mock_call:
            mock_call.return_value = ("reply", "gemini-2.5-flash")
            engine.answer("What is a mixture?", "Student")
            prompt = mock_call.call_args.kwargs.get(
                'prompt', mock_call.call_args.args[0] if mock_call.call_args.args else None)
            self.assertIn(engine._persona_content, prompt)
            self.assertIn(REFERENCE_INSTRUCTIONS, prompt)
            self.assertIn("grade-7-mixtures-types-examples.md", prompt)
            self.assertIn("What is a mixture?", prompt)
            self.assertIn("Student", prompt)

    def test_prompt_without_snippets_has_no_reference_block(self):
        engine = AIEngine()
        prompt = engine._build_prompt("What is 2+2?", "Student")
        self.assertIn(engine._persona_content, prompt)
        self.assertIn("What is 2+2?", prompt)
        self.assertNotIn("Reference material", prompt)

    def test_math_question_gets_no_snippets(self):
        """Regression of the Step 2 mocked contract under Step 5."""
        with patch('ai.ai_engine.call_gemini_api') as mock_call:
            mock_call.return_value = ("4", "gemini-2.5-flash")
            result = retrieve_and_answer("What is 2+2?")
            self.assertEqual(result.snippet_ids, [])
            self.assertEqual(result.match_scores, [])

    def test_quota_error_still_reports_snippets(self):
        """Reviewers must see whether the right file was found even when
        the API call failed."""
        with patch('ai.ai_engine.call_gemini_api') as mock_call:
            mock_call.side_effect = QuotaExhaustedError("429")
            result = retrieve_and_answer("What is a mixture?")
            self.assertEqual(result.status, STATUS_QUOTA_EXHAUSTED)
            self.assertIn("grade-7-mixtures-types-examples.md",
                          result.snippet_ids)
            self.assertIn("resting", result.reply_text.lower())

    def test_broken_retriever_never_breaks_answering(self):
        class BoomRetriever:
            def retrieve(self, query, max_snippets=2):
                raise RuntimeError("retrieval exploded")
        engine = AIEngine(retriever=BoomRetriever())
        with patch('ai.ai_engine.call_gemini_api') as mock_call:
            mock_call.return_value = ("answer anyway", "gemini-2.5-flash")
            result = engine.answer("What is a mixture?", "Student")
            self.assertEqual(result.status, STATUS_OK)
            self.assertEqual(result.reply_text, "answer anyway")
            self.assertEqual(result.snippet_ids, [])

    def test_reference_instructions_demand_faithfulness(self):
        """The grounding block must forbid inventing curriculum facts."""
        self.assertIn("primary", REFERENCE_INSTRUCTIONS.lower())
        self.assertIn("not sure", REFERENCE_INSTRUCTIONS.lower())
        self.assertIn("inventing", REFERENCE_INSTRUCTIONS.lower())


def retrieve_and_answer(question):
    """Run the public answer() with a mocked Gemini call."""
    from ai.ai_engine import answer
    return answer(question, "Student")


class TestReloadConfig(unittest.TestCase):
    """Patron /reload now refreshes persona AND knowledge files."""

    def test_reload_config_reports_both_parts(self):
        success, message = reload_config()
        self.assertTrue(success)
        self.assertIn("Persona", message)
        self.assertIn("topic", message.lower())

    def test_reload_config_preserves_persona_when_malformed(self):
        persona_path = os.path.join('config', 'persona.md')
        with open(persona_path, 'r', encoding='utf-8') as f:
            original = f.read()
        try:
            with open(persona_path, 'w', encoding='utf-8') as f:
                f.write('')  # malformed: empty persona
            success, message = reload_config()
            self.assertFalse(success)
            self.assertIn("Failed to reload persona", message)
            # Topics part still succeeded.
            self.assertIn("topic", message.lower())
        finally:
            with open(persona_path, 'w', encoding='utf-8') as f:
                f.write(original)
        success, _ = reload_config()
        self.assertTrue(success)

    def test_reload_config_picks_up_new_knowledge_file(self):
        """A git pull adding knowledge files goes live without restart."""
        new_file = os.path.join('config', 'topics',
                                'zzz-test-reload-topic.md')
        self.assertFalse(os.path.exists(new_file))
        try:
            with open(new_file, 'w', encoding='utf-8') as f:
                f.write(
                    "# Grade 7 Test — Quizznastics\n\n"
                    "- **Grade:** 7 (CBC Junior Secondary)\n"
                    "- **Learning area:** Test Subject\n"
                    "- **Strand:** Test Strand\n"
                    "- **Topic:** reload test\n"
                    "- **Keywords:** quizznastics\n"
                    "- **Source:** test fixture (deleted after the test)\n\n"
                    "## What is quizznastics?\n"
                    "Quizznastics is a made-up word for this reload test.\n")
            success, message = reload_config()
            self.assertTrue(success)
            snippets = retrieve("what is quizznastics?")
            self.assertEqual([s.source_file for s in snippets],
                             ['zzz-test-reload-topic.md'])
        finally:
            if os.path.exists(new_file):
                os.remove(new_file)
            reload_config()  # restore the clean index

    def test_reload_topics_reflects_real_directory(self):
        success, message = reload_topics()
        self.assertTrue(success)
        self.assertIn('26 topic files loaded', message)


class TestEndToEndKnowledgeFlow(unittest.TestCase):
    """Telegram handler -> engine -> retriever -> logger, with mocks only
    at the Gemini boundary."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.logger_db = os.path.join(self.tmpdir, 'logger.db')
        self.ratelimit_db = os.path.join(self.tmpdir, 'ratelimit.db')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_full_flow_logs_snippets_and_consumes_quota(self):
        from bot.commands import handle_text_message

        prompt_holder = {}

        def fake_gemini(prompt, model_name="gemini-2.5-flash"):
            prompt_holder['prompt'] = prompt
            return ("A mixture is two or more pure substances.",
                    "gemini-2.5-flash")

        env = {'TELEGRAM_ID_HASH_SALT': 'test_salt_step5',
               'DAILY_API_LIMIT': '200'}
        with patch.dict('os.environ', env):
            with patch('logger.logger.get_database_path',
                       return_value=self.logger_db), \
                 patch('bot.ratelimit.get_database_path',
                       return_value=self.ratelimit_db), \
                 patch('ai.ai_engine.call_gemini_api',
                       side_effect=fake_gemini):
                mock_message = Mock()
                mock_message.text = "What is a mixture?"
                mock_message.chat = Mock()
                mock_message.chat.id = 12345678
                mock_message.reply_text = AsyncMock()
                mock_update = Mock()
                mock_update.message = mock_message
                context = Mock()
                context.bot_data = {}

                asyncio.run(handle_text_message(mock_update, context))

                # Student got the grounded answer.
                mock_message.reply_text.assert_called_once_with(
                    "A mixture is two or more pure substances.")

                # The prompt was persona + reference knowledge + question.
                prompt = prompt_holder['prompt']
                self.assertIn("Reference material", prompt)
                self.assertIn("grade-7-mixtures-types-examples.md", prompt)
                self.assertIn("What is a mixture?", prompt)
                # Privacy: no raw Telegram ID anywhere in the prompt.
                self.assertNotIn("12345678", prompt)

                # The exchange was logged with the injected snippet.
                conn = sqlite3.connect(self.logger_db)
                try:
                    row = conn.execute(
                        "SELECT chat_alias, user_text, snippet_ids, "
                        "match_scores, status FROM exchanges"
                    ).fetchone()
                finally:
                    conn.close()
                self.assertIsNotNone(row)
                self.assertTrue(row[0].startswith("Student-"))
                self.assertNotIn("12345678", row[0])
                self.assertEqual(row[1], "What is a mixture?")
                snippet_ids = json.loads(row[2])
                self.assertIn("grade-7-mixtures-types-examples.md",
                              snippet_ids)
                self.assertEqual(len(json.loads(row[3])), len(snippet_ids))
                self.assertEqual(row[4], 'ok')

                # The daily quota counter was consumed exactly once.
                from bot.ratelimit import get_today_count
                from logger.logger import nairobi_today
                self.assertEqual(
                    get_today_count(day=nairobi_today(),
                                    db_path=self.ratelimit_db), 1)


class TestReviewExport(unittest.TestCase):
    """logger/review_export.py (architecture sections 6.2 and 6.3)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = os.path.join(self.tmpdir, 'shule.db')
        self.out_dir = os.path.join(self.tmpdir, 'exports')
        self._seed()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _seed(self):
        from logger.logger import initialize_database
        with patch('logger.logger.get_database_path', return_value=self.db):
            initialize_database()
        # 2099-01-01 10:30 UTC = 13:30 EAT (same Nairobi day).
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT INTO exchanges (ts, chat_alias, user_text, snippet_ids, "
            "match_scores, model, latency_ms, status, error, reviewed, "
            "reviewer_note) VALUES ('2099-01-01T10:30:00.000000Z', "
            "'Student-07', 'What is a mixture?', "
            "'[\"grade-7-mixtures-types-examples.md\"]', '[0.9]', "
            "'gemini-2.5-flash', 812, 'ok', '', 0, NULL)")
        conn.execute(
            "INSERT INTO exchanges (ts, chat_alias, user_text, snippet_ids, "
            "match_scores, model, latency_ms, status, error, reviewed, "
            "reviewer_note) VALUES ('2099-01-01T08:45:00.000000Z', "
            "'Student-09', 'hello', '[]', '[]', "
            "'gemini-2.5-flash', 20, 'quota_exhausted', "
            "'daily API limit reached', 0, NULL)")
        # An exchange on a DIFFERENT Nairobi day must not appear in this
        # export (2099-03-01 10:00 UTC).
        conn.execute(
            "INSERT INTO exchanges (ts, chat_alias, user_text, snippet_ids, "
            "match_scores, model, latency_ms, status, error, reviewed, "
            "reviewer_note) VALUES ('2099-03-01T10:00:00.000000Z', "
            "'Student-07', 'other day', '[]', "
            "'[]', 'm', 1, 'ok', '', 0, NULL)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS daily_counters ("
            "day TEXT PRIMARY KEY, count INTEGER NOT NULL)")
        conn.execute("INSERT INTO daily_counters (day, count) "
                     "VALUES ('2099-01-01', 7)")
        conn.commit()
        conn.close()

    def test_export_day_writes_markdown_and_csv(self):
        from logger.review_export import export_day
        md_path, csv_path, count = export_day('2099-01-01', self.db,
                                              self.out_dir)
        self.assertEqual(count, 2)
        self.assertTrue(os.path.exists(md_path))
        self.assertTrue(os.path.exists(csv_path))

        with open(md_path, encoding='utf-8') as f:
            markdown = f.read()
        # Review essentials: alias, snippets with scores, counter, status.
        self.assertIn("Student-07", markdown)
        self.assertIn("What is a mixture?", markdown)
        self.assertIn("grade-7-mixtures-types-examples.md", markdown)
        self.assertIn("0.9", markdown)
        self.assertIn("Daily API counter: 7", markdown)
        self.assertIn("quota_exhausted", markdown)
        # Nairobi display time (10:30 UTC -> 13:30 EAT).
        self.assertIn("13:30 EAT", markdown)
        # The other day's exchange is excluded.
        self.assertNotIn("other day", markdown)
        # No raw Telegram IDs (aliases only).
        self.assertNotIn("12345678", markdown)

        with open(csv_path, encoding='utf-8') as f:
            csv_content = f.read()
        self.assertIn("chat_alias", csv_content)
        self.assertIn("What is a mixture?", csv_content)
        self.assertNotIn("other day", csv_content)
        self.assertEqual(len(csv_content.strip().splitlines()), 3)  # header + 2

    def test_export_day_with_no_exchanges(self):
        from logger.review_export import export_day
        md_path, csv_path, count = export_day('2099-06-01', self.db,
                                              self.out_dir)
        self.assertEqual(count, 0)
        with open(md_path, encoding='utf-8') as f:
            self.assertIn("No exchanges", f.read())

    def test_purge_old_exchanges_removes_only_old_rows(self):
        from logger.logger import purge_old_exchanges
        # Two ancient exchanges (2020) plus the three future-dated 2099
        # rows already seeded - only the ancient ones may be purged.
        conn = sqlite3.connect(self.db)
        for ts in ('2020-01-01T09:00:00.000000Z',
                   '2020-06-15T12:00:00.000000Z'):
            conn.execute(
                "INSERT INTO exchanges (ts, chat_alias, user_text, "
                "snippet_ids, match_scores, model, latency_ms, status, "
                "error, reviewed, reviewer_note) VALUES (?, 'Student-01', "
                "'ancient question', '[]', '[]', 'm', 1, 'ok', '', 0, NULL)",
                (ts,))
        conn.commit()
        conn.close()
        with patch('logger.logger.get_database_path', return_value=self.db):
            purged = purge_old_exchanges(keep_days=90)
        self.assertEqual(purged, 2)
        conn = sqlite3.connect(self.db)
        try:
            remaining = sorted(row[0] for row in conn.execute(
                "SELECT user_text FROM exchanges").fetchall())
        finally:
            conn.close()
        self.assertEqual(remaining,
                         ['What is a mixture?', 'hello', 'other day'])

    def test_cli_runs_and_exits_zero(self):
        result = subprocess.run(
            [sys.executable, 'logger/review_export.py',
             '--date', '2099-01-01', '--db', self.db,
             '--out-dir', self.out_dir],
            capture_output=True, text=True, cwd=os.getcwd())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Exported 2 exchange(s)", result.stdout)
        self.assertTrue(os.path.exists(
            os.path.join(self.out_dir, 'review_2099-01-01.md')))


class TestStep5Documentation(unittest.TestCase):
    """Step 5 layout and documentation requirements."""

    def test_template_file_exists(self):
        self.assertTrue(os.path.exists('config/topics/_template.md'))

    def test_testing_feedback_doc_exists(self):
        self.assertTrue(os.path.exists('docs/testing_feedback.md'))

    def test_readme_documents_knowledge_base(self):
        with open('README.md', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('config/topics', content)
        self.assertIn('review_export', content)


def run_tests():
    """Run all Step 5 tests and return results."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for test_class in (
        TestRetrieverModuleContract,
        TestKnowledgeBaseFiles,
        TestRetrievalRelevance,
        TestRetrieverRobustness,
        TestEngineRetrievalIntegration,
        TestReloadConfig,
        TestEndToEndKnowledgeFlow,
        TestReviewExport,
        TestStep5Documentation,
    ):
        suite.addTests(loader.loadTestsFromTestCase(test_class))
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)


if __name__ == '__main__':
    run_tests()
