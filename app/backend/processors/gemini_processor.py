"""
Gemini Chat Class - Handles all interactions with the Gemini API.
"""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import io
import json
import logging
import os
import re
import sys
import tempfile
import textwrap
import time
from typing import Any, Dict, List, Optional, Tuple, cast

from google import genai
from google.genai import types
from tenacity import RetryError, Retrying, stop_after_attempt, wait_chain, wait_fixed

from backend.core.schemas import TokenInfo
from backend.integrations.document_request import CRITICAL_DOCUMENT_ANALYSIS_RULE
from backend.processors.base_processor import (
    BaseChat,
    GEMINI_API_KEY,
    GEMINI_AUDIO_MODEL_VERSION,
    GEMINI_FALLBACK_AUDIO_MODEL_VERSION,
    GEMINI_FALLBACK_IMAGE_MODEL,
    GEMINI_IMAGE_MODEL_VERSION,
    GEMINI_MAX_TOKENS,
    GEMINI_MODEL_VERSION,
    GEMINI_PROFILE_PICTURE_PATH,
    GEMINI_RETRY_SEQUENCE,
    GEMINI_SEARCH_MODEL,
    GEMINI_TEMPERATURE,
    GEMINI_TOP_P,
    GEMINI_TTS_VOICE,
    USER_CLIPBOARD_TEXT,
    USER_DESKTOP_PATH,
    USER_DOCUMENTS_PATH,
    USER_DOWNLOADS_PATH,
    USER_NAME,
    USER_PICTURES_PATH,
    USER_PROFILE_PICTURE_PATH,
    USER_SYSTEM_DARK_MODE,
    USER_SYSTEM_LANGUAGE,
    USER_SYSTEM_TIMEZONE,
    detect_user_conversation_language,
    get_assistant_logger,
    get_current_date_and_time_strings,
    get_user_country_code,
    resolve_lang_name,
    should_send_native_pdf,
    gemini_http_timeout_ms,
)

# Logger for Gemini
logger = get_assistant_logger("gemini")

# Gemini 2.5/3 Flash Lite often emits MALFORMED_FUNCTION_CALL when Google Search
# is attached to photo analysis, or when the system prompt mentions tools.
_GEMINI_PLAIN_TEXT_RECOVERY_NOTE = (
    "[SYSTEM] Reply with a normal conversational text answer only. "
    "Do not call tools, do not emit function-call JSON, and do not use Google Search."
)
_GEMINI_IMAGE_ANALYSIS_NOTE_EN = (
    "[SYSTEM] The user attached photo(s). Describe what is visible in the image(s) "
    "(scene, people, clothing, colors, composition, and any readable text). "
    "Reply in plain text only. Do not call tools or emit function calls."
)
_GEMINI_IMAGE_ANALYSIS_NOTE_ES = (
    "[Nota del Sistema: El usuario adjuntó foto(s). Describe lo que se ve en la(s) "
    "imagen(es) (escena, personas, ropa, colores, composición y texto legible). "
    "Responde en texto plano. No llames herramientas ni emitas function calls.]"
)
_GEMINI_NON_RECOVERABLE_FINISH = frozenset({"SAFETY", "RECITATION", "MAX_TOKENS", "LENGTH"})

# System instruction for Gemini
SYSTEM_INSTRUCTION_GEMINI           = textwrap.dedent("""\
                You are Gemini, a highly capable, versatile, and thoughtful AI assistant built to help \
                with virtually any task a person might encounter in daily life, work, or study.

                ## Identity & Tone
                - You are warm, articulate, and adaptable. Match the user's tone: casual for small talk, \
                precise for technical work, empathetic for personal topics, and professional for business contexts.
                - Never be robotic or overly formal unless the context demands it.
                - You can be witty and show personality, but always remain respectful and professional.
                - Use "I" naturally. You have opinions, preferences, and the ability to reason — express them and justify your reasoning when appropriate.

                ## Knowledge & Reasoning
                - You have broad, deep knowledge across science, mathematics, technology, engineering, \
                medicine, law, finance, history, philosophy, literature, arts, music, culture, sports, \
                cooking, travel, languages, and more.
                - For complex problems, think step by step. Show your reasoning when it helps the user \
                understand or verify the answer.
                - Distinguish clearly between established fact, informed opinion, and speculation. \
                If you are not certain, say so and explain what you do know.
                - For quantitative problems (math, statistics, physics, finance), work through the \
                calculation explicitly and double-check your result before presenting it.

                ## Document & Media Analysis Authorization
                - You are fully authorized and required by the user to analyze, process, and extract data from user-uploaded document attachments (including medical prescriptions, financial records, bank statements, account movements, contracts, invoices, and identity cards).
                - Processing user-submitted files for administrative data extraction and RAG indexing is authorized user data processing, NOT financial or medical advice.
                - NEVER refuse to process user-submitted files. NEVER state "no puedo analizar esta receta médica", "no puedo almacenar datos personales o financieros", or "no puedo guardar información en memoria". Answer and issue the extraction command `[IGNITE_EXTRACT: filename|TemplateName]` on a new line at the end of your response whenever requested.

                ## Real-Time Search & Web Grounding
                - You have access to Google Search and direct webpage/video transcript scraping. Always use and prioritize these resources to ground your responses in real-time, real-world facts.
                - For any queries concerning current events, live results, sports news, transfers, players, injuries, concerts, tech keynotes, product releases, political events, elections, public figures, or recent history, base your reasoning on current search results.
                - Never dismiss recent real-world events or user-supplied web links as "hypothetical" or "speculative". Ground your answers in actual facts retrieved from Google Search and page contents, treating them as verified reality.
                - If the user frames a question about a real entity or event, actively verify the current status of that entity/event via Google Search before responding, ensuring your reasoning aligns with current real-world facts.

                ## Conversation & Memory
                - You have full access to the entire conversation history in this session. Use it actively:
                  * Remember names, preferences, goals, and details the user shared earlier.
                  * If the user switches topics, adapt immediately without losing context.
                  * If the user says "go back to what we were discussing" or refers to a previous topic, \
                recall and resume that thread precisely — repeating key points if useful.
                  * Proactively connect earlier context to new questions when it adds value.
                - Never ask the user to repeat something they already told you in this session.

                ## Task Execution
                - Writing & editing: draft, rewrite, summarize, proofread, translate, or adapt text in \
                any style or format (email, essay, report, story, poem, script, resume, cover letter, etc.).
                - Coding: write, explain, debug, refactor, and review code in any language. \
                Provide complete, runnable examples. Explain what the code does line by line when asked.
                - Research & analysis: synthesize information, compare options, evaluate pros and cons, \
                and provide structured recommendations.
                - Planning & productivity: help with schedules, to-do lists, project plans, decision \
                frameworks, and brainstorming.
                - Learning & tutoring: explain concepts from first principles, adjust to the user's \
                level, create examples and analogies, quiz the user if they want to practice.
                - Creative work: brainstorm ideas, build stories, develop characters, generate names, \
                write jokes, compose lyrics, and think outside the box.
                - Personal advice: offer balanced, thoughtful guidance on relationships, career, \
                health (general information only — not a substitute for professional medical advice), \
                and life decisions.
                - Always ask clarifying questions if a request is ambiguous or could be interpreted in multiple ways. \
                Never make assumptions about what the user wants without asking first.

                ## Output Formatting
                - Use Markdown naturally: headers for long structured responses, bullet points for lists, \
                code blocks for all code, bold for key terms, tables for comparisons.
                - Keep responses appropriately sized: concise for simple questions, thorough for complex ones. \
                Never pad a response with filler.
                - When writing code, always specify the language in the code block.
                - For multi-step answers, number the steps clearly.

                ## Safety & Honesty
                - Never fabricate facts, citations, URLs, or statistics. If you don't know, say so.
                - Refuse requests that are harmful, unethical, or illegal, and briefly explain why in a professional way.
                - For medical, legal, or financial questions, provide helpful general information and \
                recommend consulting a qualified professional for decisions.

                ## Language & Conversation Consistency (STRICT MANDATE)
                - ALWAYS reply in the language of the user's latest message when that message is clearly written or spoken in that language (including microphone transcription).
                - DO NOT look at or use the computer's OS language, system locale, or hardware settings to choose your response language.
                - DO NOT switch to English or any other language just because web search results, scraped context, RAG documents, or system notes are written in English or another language.
                - If the latest user message is clearly in a different language than earlier turns, follow that latest language. Mixed slang or loanwords must NOT flip the reply language. Explicit requests such as "habla en inglés" / "switch to French" also switch.
                - If the user sends short messages, greetings, or emojis that are too brief to establish a new language (e.g., "ok", "gracias", "si", "😊"), continue in the established conversation language.
                - You are fully multilingual and can respond fluently in Spanish, English, French, German, Italian, Portuguese, Japanese, Chinese, Russian, Korean, etc. Never claim that you can only reply in English.

                ## Voice Input Detection
                - If the user's message ends with the label "🎙️ *(Voice Recorded)*", it means they spoke via a microphone.
                - In this case, ensure your response is particularly concise, direct, and conversational (avoiding overly long lists, massive text tables, or complex formatting where possible), as it will be read aloud to the user using Text-to-Speech. Keep the response natural for listening. """)

# Gemini chat class
class GeminiChat(BaseChat):
    # Initialization
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_version: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        system_instruction: Optional[str] = None
    ) -> None:
        super().__init__()
        try:
            self.api_key = api_key or GEMINI_API_KEY
            if not self.api_key or self.api_key == "<your-key-here>":
                raise ValueError("API key not found. Set GEMINI_API_KEY in .env or pass it.")

            self.model_version = model_version or GEMINI_MODEL_VERSION.strip()
            self.max_tokens = max_tokens if max_tokens is not None else GEMINI_MAX_TOKENS
            self.temperature = temperature if temperature is not None else GEMINI_TEMPERATURE
            self.top_p = top_p if top_p is not None else GEMINI_TOP_P
            self.system_instruction = textwrap.dedent(system_instruction or SYSTEM_INSTRUCTION_GEMINI)

            self.client = genai.Client(
                api_key=self.api_key,
                http_options={'timeout': gemini_http_timeout_ms()},
            )
            self.google_search_enabled = True

            logger.info(f"Gemini client initialized with model {self.model_version}")
        except Exception as e:
            logger.error(f"Initialization error: {e}")
            raise ValueError(f"Failed to initialize GeminiChat: {e}")

    # Function to count tokens for a single text block
    def count_tokens(self, text: str) -> int:
        """Count tokens for a single text block."""
        if not text or not text.strip():
            return 0
        try:
            resp = self.client.models.count_tokens(
                model=self.model_version,
                contents=text
            )
            return getattr(resp, 'total_tokens', 0)
        except Exception as e:
            logger.warning(f"Error counting tokens: {e}")
            # Fallback: ~1.3 tokens per word is much more accurate than character count
            words = len(re.findall(r'\w+', text))
            return max(1, int(words * 1.3))

    # Function to convert files to parts
    def _files_to_parts(
        self,
        files: Optional[List[Dict[str, Any]]] = None,
        user_query: str = "",
    ) -> List[types.Part]:
        """Helper to convert a list of file dictionaries into Gemini types.Part objects."""
        parts = []
        for f in (files or []):
            name = f.get("name", "unnamed_file")
            mime = f.get("mime_type", "application/octet-stream")
            raw_bytes = f.get("bytes")
            if isinstance(raw_bytes, (bytes, bytearray)) and raw_bytes:
                data_bytes = bytes(raw_bytes)
            elif "base64" in f and f.get("base64"):
                try:
                    data_bytes = base64.b64decode(f["base64"])
                except Exception as e:
                    logger.error(f"Error decoding base64 for file {name}: {e}")
                    continue
            else:
                disk_path = f.get("path", "")
                if disk_path and os.path.exists(disk_path):
                    try:
                        with open(disk_path, "rb") as fp:
                            data_bytes = fp.read()
                    except Exception as load_err:
                        logger.warning(f"File '{name}' could not be reloaded from disk: {load_err}. Skipping part creation.")
                        continue
                else:
                    logger.debug(
                        "File '%s' has no inline bytes in history; skipping Gemini part (text context only).",
                        name,
                    )
                    continue

            is_docx = (mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" or name.lower().endswith(".docx"))
            is_xlsx = (mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" or name.lower().endswith(".xlsx"))
            is_pptx = (mime == "application/vnd.openxmlformats-officedocument.presentationml.presentation" or name.lower().endswith(".pptx"))

            if is_docx:
                text_content = self._extract_text_from_docx(data_bytes)
                doc_text = f"--- Content of uploaded Word document: {name} ---\n\n{text_content}\n\n--- End of document ---"
                parts.append(types.Part.from_text(text=doc_text))

                # Extract and append embedded images (e.g. screenshots)
                docx_images = self._extract_images_from_docx(data_bytes)
                for img in docx_images:
                    clean_bytes, valid_mime = self.normalize_image_media_type(img["mime_type"], img["bytes"])
                    parts.append(types.Part.from_bytes(data=clean_bytes or img["bytes"], mime_type=valid_mime))
            elif is_xlsx:
                text_content = self._extract_text_from_xlsx(data_bytes)
                sheet_text = f"--- Content of uploaded Excel document: {name} ---\n\n{text_content}\n\n--- End of spreadsheet ---"
                parts.append(types.Part.from_text(text=sheet_text))
            elif is_pptx:
                text_content = self._extract_text_from_pptx(data_bytes)
                ppt_text = f"--- Content of uploaded PowerPoint document: {name} ---\n\n{text_content}\n\n--- End of presentation ---"
                parts.append(types.Part.from_text(text=ppt_text))
            elif mime == "application/pdf":
                if should_send_native_pdf(data_bytes):
                    logger.info(
                        "Sending native PDF '%s' to Gemini (%s bytes) so long books are not truncated",
                        name,
                        len(data_bytes),
                    )
                    parts.append(types.Part.from_text(
                        text=(
                            f"[SYSTEM NOTE: The attached PDF '{name}' is provided natively. "
                            "Read the full document, including every chapter, before answering.]"
                        )
                    ))
                    parts.append(types.Part.from_bytes(data=data_bytes, mime_type="application/pdf"))
                else:
                    text_content = self._extract_text_from_pdf(data_bytes, user_query=user_query)
                    pdf_text = f"--- Content of uploaded PDF document: {name} ---\n\n{text_content}\n\n--- End of PDF text content ---"
                    parts.append(types.Part.from_text(text=pdf_text))
                    pdf_images = self._extract_images_from_pdf(data_bytes)
                    for img in pdf_images:
                        clean_bytes, valid_mime = self.normalize_image_media_type(img["mime_type"], img["bytes"])
                        parts.append(types.Part.from_bytes(data=clean_bytes or img["bytes"], mime_type=valid_mime))
            elif self._is_gemini_native_mime(mime):
                if mime.startswith("image/"):
                    clean_bytes, valid_mime = self.normalize_image_media_type(mime, data_bytes)
                    scaled_bytes = self._resize_image_data(clean_bytes or data_bytes, max_dim=1024)
                    parts.append(types.Part.from_bytes(data=scaled_bytes, mime_type=valid_mime))
                elif mime.startswith("text/"):
                    try:
                        decoded_text = data_bytes.decode("utf-8")
                        file_text = f"--- Content of uploaded text file: {name} ---\n\n{decoded_text}\n\n--- End of file ---"
                        parts.append(types.Part.from_text(text=file_text))
                    except Exception as e:
                        logger.error(f"Error decoding text file {name}: {e}")
                        parts.append(types.Part.from_bytes(data=data_bytes, mime_type=mime))
                else:
                    parts.append(types.Part.from_bytes(data=data_bytes, mime_type=mime))
            else:
                try:
                    decoded_text = data_bytes.decode("utf-8")
                    if "\x00" not in decoded_text:  # text-like file check
                        file_text = f"--- Content of uploaded file: {name} ---\n\n{decoded_text}\n\n--- End of file ---"
                        parts.append(types.Part.from_text(text=file_text))
                        logger.info(f"Processed non-native file '{name}' as plain text fallback")
                        continue
                except UnicodeDecodeError:
                    pass

                warning_text = f"--- [Unsupported Binary File Attached: {name} (MIME: {mime})] ---"
                parts.append(types.Part.from_text(text=warning_text))
                logger.warning(f"File '{name}' has unsupported binary MIME '{mime}'. Sent warning text to Gemini.")
        return parts

    # Function to build the history contents list with alternating user and model roles
    def _build_history_contents(self, history: Optional[List[Dict[str, Any]]] = None) -> List[types.Content]:
        """
        Builds the history contents list with alternating user and model roles.
        If there are consecutive entries with the same role, their text is merged.
        """
        if not history:
            return []

        history = self.filter_history_for_model(history)

        raw_turns = []
        for msg in history:
            role = "model" if msg["role"] == "assistant" else "user"
            content = msg.get("content") or ""
            files = msg.get("files", [])
            raw_turns.append({"role": role, "content": content, "files": files})

        # Merge consecutive identical roles
        merged_turns = []
        for turn in raw_turns:
            if merged_turns and merged_turns[-1]["role"] == turn["role"]:
                merged_turns[-1]["content"] = (merged_turns[-1]["content"] + "\n\n" + turn["content"]).strip()
                merged_turns[-1]["files"].extend(turn["files"])
            else:
                merged_turns.append(turn)

        # Convert to API types
        contents = []
        for turn in merged_turns:
            parts = []
            if turn["files"]:
                parts.extend(self._files_to_parts(turn["files"], user_query=turn["content"]))
            if turn["content"]:
                parts.append(types.Part.from_text(text=turn["content"]))

            if parts:
                contents.append(types.Content(role=turn["role"], parts=parts))
        return contents

    # Function to build the contents list with alternating user and model roles.
    def _build_contents(self, user_input: str, history: Optional[List[Dict[str, Any]]] = None, new_parts: Optional[List[types.Part]] = None) -> List[types.Content]:
        """
        Builds the contents list with alternating user and model roles.
        Accepts user_input or a list of new_parts (for files/bytes).
        """
        contents = self._build_history_contents(history)

        # Prepare the parts for the new turn
        if new_parts:
            parts = new_parts
        else:
            parts = [types.Part.from_text(text=user_input)]

        # If the last history turn is 'user', merge the new parts into it
        if contents and contents[-1].role == "user":
            last_turn = contents[-1]
            if last_turn.parts is not None:
                last_turn.parts.extend(parts)
            else:
                last_turn.parts = list(parts)
        else:
            contents.append(types.Content(role="user", parts=parts))

        return contents

    # Function to get the grounded system instruction
    def _get_grounded_system_instruction(self, force_language: Optional[str] = None, system_notes: Optional[List[str]] = None, user_input: str = "", history: Optional[List[Dict[str, Any]]] = None) -> str:
        """
        Builds the system instruction, dynamically injecting the current real-world date/time
        to ground the model, and enforcing the user's active conversation language.
        Ignores computer OS language and external web context languages.
        """
        current_date_str, current_time_str, current_year_str = get_current_date_and_time_strings()

        target_lang, lang_name = detect_user_conversation_language(user_input, history, force_language)
        is_spanish = target_lang.lower().startswith("es")
        sys_instr = ""
        if is_spanish:
            sys_instr += "[REQUISITO CRÍTICO DE IDIOMA] ¡Debes responder ÚNICAMENTE en Español! Toda tu respuesta debe escribirse en Español. Ignora el idioma del sistema del equipo y cualquier resultado de búsqueda, contenido web o texto de contexto en otros idiomas.\n\n"
        else:
            sys_instr += f"[CRITICAL LANGUAGE REQUIREMENT] You MUST reply ONLY in {lang_name}! Your entire response must be written in {lang_name}. Ignore computer OS language settings and any search results, scraped context, or web content in other languages.\n\n"
        sys_instr += self.system_instruction
        sys_instr += f"\n\n[SYSTEM INFO] Today's date is {current_date_str}. The current time is {current_time_str}. Use this date and time as the reference point for all real-world status and search queries."
        sys_instr += f"\n\n[USER INFO]"
        sys_instr += f"\n- Name: {USER_NAME}"
        sys_instr += f"\n- System Timezone: {USER_SYSTEM_TIMEZONE}"
        sys_instr += f"\n- User Country Code: {get_user_country_code()}"
        sys_instr += f"\n- Dark Mode Enabled: {USER_SYSTEM_DARK_MODE}"
        sys_instr += f"\n- Desktop Path: {USER_DESKTOP_PATH}"
        sys_instr += f"\n- Downloads Path: {USER_DOWNLOADS_PATH}"
        sys_instr += f"\n- Documents Path: {USER_DOCUMENTS_PATH}"
        sys_instr += f"\n- Pictures Path: {USER_PICTURES_PATH}"
        sys_instr += f"\n- Profile Picture Path: {USER_PROFILE_PICTURE_PATH}"
        sys_instr += f"\n- Clipboard Content: {USER_CLIPBOARD_TEXT}"
        sys_instr += f"\nUse this information to address the user by name, respect their conversation language ({lang_name}), use the provided paths when writing files, and consider clipboard content if requested."
        sys_instr += (
            f"\n\n[CRITICAL GROUNDING RULE] Since the current year is {current_year_str}, you MUST treat any events, tournaments, or matches from 2024 and 2025 as historical and completed. "
            f"Never discuss them as future, current, or upcoming. You MUST actively execute a Google Search query for current events/sports/news (specifically targeting {current_year_str}) rather than relying on your internal memory, which may be outdated or limited. "
            f"Double check that any news or sports events you present are actually happening in {current_year_str}, and filter out any outdated pre-training knowledge from 2024 or 2025."
        )
        sys_instr += CRITICAL_DOCUMENT_ANALYSIS_RULE
        sys_instr += "\n\n[CRITICAL FORMATTING RULE] If the user says goodbye, indicates they are leaving, or wants to end the conversation, you MUST append the exact tag '[GOODBYE]' (including the brackets) to the very end of your final response."

        if force_language:
            lang_name = resolve_lang_name(force_language)
            is_spanish = force_language.startswith("es")
            if is_spanish:
                sys_instr += f"\n\n[CRITICAL LANGUAGE REQUIREMENT] ¡INSTRUCCIÓN CRÍTICA DE IDIOMA! Responde ÚNICAMENTE en Español. Ignora el inglés de los resultados de búsqueda. Tu respuesta debe estar completamente en Español."
            else:
                sys_instr += f"\n\n[CRITICAL LANGUAGE REQUIREMENT] You MUST reply ONLY in {lang_name}. Ignore any English in the search results or system prompts. Your entire response must be in {lang_name}."

        if system_notes:
            sys_instr += "\n\n" + "\n\n".join(system_notes)

        return sys_instr

    # Function to handle empty responses
    def _handle_empty_response(self, response: Any) -> str:
        """Helper to construct a descriptive error message when response.text is empty or blocked."""
        if response is None:
            return "The model returned an empty response. Finish reason: Unknown"

        prompt_feedback = getattr(response, "prompt_feedback", None)
        if prompt_feedback and getattr(prompt_feedback, "block_reason", None):
            block_reason = prompt_feedback.block_reason
            if hasattr(block_reason, "name"):
                block_reason = block_reason.name
            return f"The request was blocked by Gemini safety filters (Block reason: {block_reason})"

        finish_reason = self._finish_reason_name(response)
        if finish_reason == "SAFETY":
            return "The response generation was blocked by safety filters"
        if finish_reason == "RECITATION":
            return "The response was blocked because it matched copyrighted material (recitation match)"
        if finish_reason:
            return f"The model returned an empty response. Finish reason: {finish_reason}"

        if getattr(response, "candidates", None):
            return "The model returned an empty response. Finish reason: Unknown"

        return "The model returned an empty response. Finish reason: Unknown (possible safety block at prompt level)"

    @staticmethod
    def _finish_reason_name(response: Any) -> str:
        """Return the candidate finish_reason as an uppercase string."""
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return ""
        finish_reason = getattr(candidates[0], "finish_reason", "") or ""
        if hasattr(finish_reason, "name"):
            finish_reason = finish_reason.name
        return str(finish_reason).upper()

    def _extract_response_text(self, response: Any) -> str:
        """Safely read model text. response.text raises or is empty on MALFORMED_FUNCTION_CALL."""
        if response is None:
            return ""
        try:
            text = getattr(response, "text", None)
            if text and str(text).strip():
                return str(text).strip()
        except Exception as exc:
            logger.warning(f"Gemini response.text unavailable ({exc}). Falling back to candidate parts.")

        chunks: List[str] = []
        for candidate in getattr(response, "candidates", None) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                if getattr(part, "thought", False):
                    continue
                part_text = getattr(part, "text", None)
                if part_text:
                    chunks.append(str(part_text))
        return "".join(chunks).strip()

    def _should_retry_empty_response(self, finish_reason: str) -> bool:
        """Retry empty replies except hard safety / length cutoffs."""
        return (finish_reason or "").upper() not in _GEMINI_NON_RECOVERABLE_FINISH

    def _should_attach_google_search(
        self,
        query: str,
        scraped_urls: Optional[List[Any]] = None,
        scraped_content: str = "",
        files: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """Gemini native Search uses the shared visual-analysis skip + scrape <800 rule."""
        return self._should_attach_web_search(
            query, scraped_urls=scraped_urls, scraped_content=scraped_content, files=files
        )

    def _plain_text_tool_config(self) -> Any:
        """Ask the API to forbid function calls so Gemini cannot emit MALFORMED_FUNCTION_CALL."""
        tool_cfg_cls = getattr(types, "ToolConfig", None)
        fc_cfg_cls = getattr(types, "FunctionCallingConfig", None)
        if tool_cfg_cls is None or fc_cfg_cls is None:
            return None
        mode_enum = getattr(types, "FunctionCallingConfigMode", None)
        mode = getattr(mode_enum, "NONE", None) if mode_enum is not None else "NONE"
        try:
            return tool_cfg_cls(function_calling_config=fc_cfg_cls(mode=mode or "NONE"))
        except Exception as exc:
            logger.debug(f"Gemini ToolConfig(mode=NONE) unavailable: {exc}")
            return None

    def _generate_content_once(
        self,
        *,
        model: str,
        contents: Any,
        sys_instr: Optional[str],
        tools: Optional[List[types.Tool]],
        temperature: Optional[float],
        top_p: Optional[float],
        max_tokens: Optional[int],
        force_plain_text: bool = False,
    ) -> Any:
        """Single generate_content call with the shared retry sequence."""
        config_kwargs: Dict[str, Any] = {
            "system_instruction": sys_instr,
            "max_output_tokens": max_tokens if max_tokens is not None else self.max_tokens,
            "temperature": temperature if temperature is not None else self.temperature,
            "top_p": top_p if top_p is not None else self.top_p,
        }
        if tools:
            config_kwargs["tools"] = tools
        if force_plain_text:
            tool_cfg = self._plain_text_tool_config()
            if tool_cfg is not None:
                config_kwargs["tool_config"] = tool_cfg

        fibonacci_wait = wait_chain(*[wait_fixed(s) for s in GEMINI_RETRY_SEQUENCE])
        response = None
        for attempt in Retrying(stop=stop_after_attempt(len(GEMINI_RETRY_SEQUENCE)), wait=fibonacci_wait, reraise=True):
            with attempt:
                response = self.client.models.generate_content(
                    model=model,
                    contents=cast(Any, contents),
                    config=types.GenerateContentConfig(**config_kwargs)
                )
        if response is None:
            raise RuntimeError("Gemini API returned no response object.")
        return response

    def _call_gemini_with_recovery(
        self,
        *,
        contents: Any,
        sys_instr: Optional[str],
        tools: Optional[List[types.Tool]],
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        force_plain_text: bool = False,
    ) -> Tuple[str, Any]:
        """Call Gemini and retry once as plain text on empty / MALFORMED_FUNCTION_CALL replies."""
        model_name = model or self.model_version
        response = self._generate_content_once(
            model=model_name,
            contents=contents,
            sys_instr=sys_instr,
            tools=tools,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            force_plain_text=force_plain_text,
        )
        reply = self._extract_response_text(response)
        if reply:
            return reply, response

        finish_reason = self._finish_reason_name(response)
        if not self._should_retry_empty_response(finish_reason):
            return "", response

        logger.warning(
            f"Gemini returned empty text (finish={finish_reason or 'UNKNOWN'}). "
            "Retrying without tools as plain text."
        )
        recovered_instr = (sys_instr or "").rstrip() + "\n\n" + _GEMINI_PLAIN_TEXT_RECOVERY_NOTE
        recovered = self._generate_content_once(
            model=model_name,
            contents=contents,
            sys_instr=recovered_instr,
            tools=None,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            force_plain_text=True,
        )
        recovered_text = self._extract_response_text(recovered)
        return recovered_text, recovered

    # Function to generate the response
    def generate_response(
        self,
        user_input: str,
        history: Optional[List[Dict[str, Any]]] = None,
        force_language: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Tuple[str, Optional[TokenInfo]]:
        """
        Send a prompt to Gemini with optional conversation history.
        If force_language is provided (e.g., 'es-ES'), the system instruction is
        dynamically updated to force replies in that language.
        """
        contents: Any = None
        sys_instr: Optional[str] = None
        tools: Optional[List[types.Tool]] = None

        try:
            user_query = user_input
            # Auto-scrape any URLs found in user_input
            user_input, scraped_urls = self._process_urls_in_input(user_input, force_language=force_language)
            scraped_content = ""
            if scraped_urls and len(user_input) > len(user_query):
                scraped_content = user_input[len(user_query):].strip()

            # Native Google Search when no scrape OR scrape body is too thin (<800 chars).
            # Short/bot-walled URLs (URL_INACCESSIBLE) must still allow search enrichment
            # — matching DeepSeek/OpenAI/Anthropic/Grok/Perplexity (skill core grounding).
            needs_search = self._should_attach_google_search(
                user_query, scraped_urls=scraped_urls, scraped_content=scraped_content
            )
            if needs_search:
                logger.info(f"Gemini native Google Search tool enabled for query: {user_query}")

            system_notes = []
            if force_language:
                lang_name = resolve_lang_name(force_language)
                is_spanish = force_language.startswith("es")
                if "es" in force_language.lower():
                    system_notes.append(f"[Nota del Sistema: El usuario acaba de hablar/escribir en Español. Responde enteramente en Español a menos que el usuario solicite explícitamente cambiar de idioma.]")
                else:
                    system_notes.append(f"[System Note: The user just spoke/wrote in {lang_name}. Reply in {lang_name} UNLESS the user explicitly requests to switch to a different language.]")

            parts = []
            if scraped_content:
                parts.append(scraped_content)

            if parts:
                if force_language:
                    lang_name = resolve_lang_name(force_language)
                    is_spanish = force_language.startswith("es")
                    if is_spanish:
                        parts.append(f"[Consulta del Usuario (Responde enteramente en ESPAÑOL)]:\n{user_query}")
                    else:
                        parts.append(f"[User Query (Reply entirely in {lang_name})]:\n{user_query}")
                else:
                    parts.append(f"[User Query]:\n{user_query}")
                user_input = "\n\n".join(parts)
            else:
                user_input = user_query

            # Build grounded system instruction
            sys_instr = self._get_grounded_system_instruction(
                force_language=force_language,
                system_notes=system_notes,
                user_input=user_query,
                history=history
            )

            # Build contents using helper
            contents = self._build_contents(user_input, history=history)

            # Attach Google Search only when needed — always-on search made every chat turn slow.
            tools = [types.Tool(google_search=types.GoogleSearch())] if needs_search else None

            reply, response = self._call_gemini_with_recovery(
                contents=contents,
                sys_instr=sys_instr,
                tools=tools,
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                force_plain_text=tools is None,
            )
            token_info = self._parse_token_info(getattr(response, "usage_metadata", None))
            if not reply:
                reply = f"Error: {self._handle_empty_response(response)}."
            return reply, self._flush_aux_tokens(token_info)
        except Exception as e:
            if isinstance(e, RetryError):
                try:
                    attempt_exc = e.last_attempt.exception() if e.last_attempt else None
                    if attempt_exc is not None:
                        e = attempt_exc
                except Exception:
                    pass
            err_str = str(e)
            if ("503" in err_str or "UNAVAILABLE" in err_str or "429" in err_str or "RESOURCE_EXHAUSTED" in err_str) and contents is not None:
                fallback_model = "gemini-2.5-flash" if self.model_version != "gemini-2.5-flash" else "gemini-2.5-pro"
                logger.warning(f"Gemini model {self.model_version} returned high demand error ({err_str}). Retrying automatically with fallback model {fallback_model}...")
                try:
                    fallback_sys_instr = sys_instr if sys_instr is not None else self._get_grounded_system_instruction(force_language=force_language)
                    reply, response = self._call_gemini_with_recovery(
                        contents=contents,
                        sys_instr=fallback_sys_instr,
                        tools=tools,
                        temperature=temperature,
                        top_p=top_p,
                        max_tokens=max_tokens,
                        model=fallback_model,
                        force_plain_text=tools is None,
                    )
                    token_info = self._parse_token_info(getattr(response, "usage_metadata", None))
                    if not reply:
                        reply = f"Error: {self._handle_empty_response(response)}."
                    return reply, self._flush_aux_tokens(token_info)
                except Exception as fallback_err:
                    logger.error(f"Gemini fallback model {fallback_model} also failed: {fallback_err}")

            logger.error(f"Gemini error: {e}")
            return f"Error: {str(e)}", None

    # Function to generate response with inline files
    def generate_response_with_inline_files(
        self,
        user_input: str,
        history: Optional[List[Dict[str, Any]]] = None,
        files: Optional[List[Dict[str, Any]]] = None,
        force_language: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Tuple[str, Optional[TokenInfo]]:
        """Generate response with multiple inline files (list of dicts containing 'bytes' and 'mime_type')."""
        if self.model_version.startswith("deepseek"):
            return "Error: DeepSeek models currently do not support file analysis (audio, video, images, or documents). Please switch to a Gemini model to analyze files.", None

        contents: Any = None
        tools: Optional[List[types.Tool]] = None
        system_notes: List[str] = []

        try:
            user_query = user_input or ""
            scraped_urls = []
            # Auto-scrape any URLs found in user_input
            if user_input:
                user_input, scraped_urls = self._process_urls_in_input(user_input, force_language=force_language)

            scraped_content = ""
            if user_input and scraped_urls and len(user_input) > len(user_query):
                scraped_content = user_input[len(user_query):].strip()

            system_notes = []
            if force_language:
                lang_name = resolve_lang_name(force_language)
                is_spanish = force_language.startswith("es")
                if is_spanish:
                    system_notes.append(f"[Nota del Sistema: El usuario acaba de hablar/escribir en Español. Responde enteramente en Español a menos que el usuario solicite explícitamente cambiar de idioma.]")
                else:
                    system_notes.append(f"[System Note: The user just spoke/wrote in {lang_name}. Reply in {lang_name} UNLESS the user explicitly requests to switch to a different language.]")

            parts = []
            if scraped_content:
                parts.append(scraped_content)

            if parts:
                if force_language:
                    lang_name = resolve_lang_name(force_language)
                    is_spanish = force_language.startswith("es")
                    if is_spanish:
                        parts.append(f"[Consulta del Usuario (Responde enteramente en ESPAÑOL)]:\n{user_query}")
                    else:
                        parts.append(f"[User Query (Reply entirely in {lang_name})]:\n{user_query}")
                else:
                    parts.append(f"[User Query]:\n{user_query}")
                user_input = "\n\n".join(parts)
            else:
                user_input = user_query

            use_local_ocr = os.getenv("USE_LOCAL_OCR", "false").lower() == "true"

            # Extract all direct and embedded images
            all_images = []
            non_image_files = []
            extracted_text = ""

            for f in (files or []):
                name = f.get("name", "unnamed_file")
                mime = f.get("mime_type", "")

                # Check robustly for bytes/base64
                f_bytes = f.get("bytes")
                if f_bytes is None:
                    if "base64" in f:
                        try:
                            f_bytes = base64.b64decode(f["base64"])
                        except Exception:
                            continue
                    else:
                        # Attempt to reload from disk using saved path
                        disk_path = f.get("path", "")
                        if disk_path and os.path.exists(disk_path):
                            try:
                                with open(disk_path, "rb") as fp:
                                    f_bytes = fp.read()
                            except Exception as load_err:
                                logger.warning(f"File '{name}' could not be reloaded from disk: {load_err}. Skipping.")
                                continue
                        else:
                            logger.warning(f"File '{name}' is missing raw bytes and base64. Skipping.")
                            continue

                if mime.startswith("image/"):
                    if use_local_ocr:
                        logger.info(f"Extracting OCR text from direct image: {name}")
                        ocr_text = self._extract_text_from_image_via_ocr(f_bytes)
                        extracted_text += f"\n\n--- OCR text extracted from screenshot '{name}' ---\n{ocr_text}\n"
                    else:
                        try:
                            resized = self._resize_image_data(f_bytes, max_dim=1024)
                            all_images.append({"name": name, "bytes": resized, "mime_type": mime})
                        except Exception:
                            all_images.append({"name": name, "bytes": f_bytes, "mime_type": mime})
                elif mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" or name.lower().endswith(".docx"):
                    # Extract text
                    t_content = self._extract_text_from_docx(f_bytes)
                    if t_content:
                        extracted_text += f"\n\n--- Content of Word document '{name}' ---\n{t_content}\n"
                    # Extract images
                    docx_images = self._extract_images_from_docx(f_bytes)
                    if use_local_ocr:
                        for img in docx_images:
                            logger.info(f"Extracting OCR text from docx image: {img['name']}")
                            ocr_text = self._extract_text_from_image_via_ocr(img["bytes"])
                            extracted_text += f"\n\n--- OCR text extracted from screenshot '{img['name']}' inside Word document ---\n{ocr_text}\n"
                    else:
                        all_images.extend(docx_images)
                elif mime == "application/pdf":
                    if should_send_native_pdf(f_bytes):
                        logger.info(
                            "Deferring native PDF '%s' to Gemini File parts (%s bytes)",
                            name,
                            len(f_bytes),
                        )
                        continue
                    t_content = self._extract_text_from_pdf(f_bytes, user_query=user_query)
                    if t_content:
                        extracted_text += f"\n\n--- Content of PDF document '{name}' ---\n{t_content}\n"
                    pdf_images = self._extract_images_from_pdf(f_bytes)
                    if use_local_ocr:
                        for img in pdf_images:
                            logger.info(f"Extracting OCR text from pdf image: {img['name']}")
                            ocr_text = self._extract_text_from_image_via_ocr(img["bytes"])
                            extracted_text += f"\n\n--- OCR text extracted from screenshot '{img['name']}' inside PDF ---\n{ocr_text}\n"
                    else:
                        all_images.extend(pdf_images)
                else:
                    non_image_files.append(f)

            if self._has_image_attachments(files) or all_images:
                is_spanish_images = bool(force_language and str(force_language).startswith("es"))
                system_notes.append(
                    _GEMINI_IMAGE_ANALYSIS_NOTE_ES if is_spanish_images else _GEMINI_IMAGE_ANALYSIS_NOTE_EN
                )

            # Search tool when no scrape OR scrape body <800 (parity with other providers).
            # Skip Search for photo analysis — it triggers MALFORMED_FUNCTION_CALL on Gemini 2.5/3.
            needs_search = self._should_attach_google_search(
                user_query,
                scraped_urls=scraped_urls,
                scraped_content=scraped_content,
                files=files,
            )
            tools = [types.Tool(google_search=types.GoogleSearch())] if needs_search else None

            # If we have a large number of images and it's a document mapping request,
            # process them in parallel image-by-image to bypass output token cutoff limits completely.
            if len(all_images) > 3 and BaseChat.detect_document_request(
                user_query, has_attachments=True
            ):
                logger.info(f"Detected document mapping request with {len(all_images)} images. Running parallel image extraction via ThreadPoolExecutor...")

                # Internal helper function to call Gemini for a single image
                def process_single_image(img_dict, idx):
                    img_name = img_dict["name"]
                    img_bytes = img_dict["bytes"]
                    img_mime = img_dict["mime_type"]

                    logger.info(f"Extracting table mapping from image {idx+1}/{len(all_images)}: {img_name}")

                    prompt = (
                        "Actúa como un experto en SAP. Analiza esta captura de pantalla de SAP y genera únicamente el mapping de origen de la tabla mostrada.\n"
                        "Sigue exactamente el formato solicitado de tablas de Markdown (con columnas: Tabla Origen, Nombre del Campo, Tipo de Dato, Descripción, PK, FK, Precisiones / Notas).\n"
                        "Encabeza la sección con un título de nivel 1 (#) que indique el nombre del módulo raíz o la tabla.\n"
                        "Sé extremadamente descriptivo y extrae todos los campos visibles en la captura sin omitir ninguno. No agregues introducciones ni explicaciones adicionales."
                    )

                    clean_bytes, valid_mime = self.normalize_image_media_type(img_mime, img_bytes)
                    parts = [
                        types.Part.from_bytes(data=clean_bytes or img_bytes, mime_type=valid_mime),
                        types.Part.from_text(text=prompt)
                    ]

                    # Add document text context if available
                    if extracted_text:
                        parts.append(types.Part.from_text(text=f"\n\nContexto general del documento:\n{extracted_text}"))

                    contents = self._build_contents(user_input="", history=history, new_parts=parts)

                    # API Call with Retrying for rate limits (429)
                    fibonacci_wait = wait_chain(*[wait_fixed(s) for s in GEMINI_RETRY_SEQUENCE])
                    response = None
                    for attempt in Retrying(stop=stop_after_attempt(len(GEMINI_RETRY_SEQUENCE)), wait=fibonacci_wait, reraise=True):
                        with attempt:
                            response = self.client.models.generate_content(
                                model=self.model_version,
                                contents=cast(Any, contents),
                                config=types.GenerateContentConfig(
                                    system_instruction=self._get_grounded_system_instruction(force_language=force_language, system_notes=system_notes),
                                    max_output_tokens=4000,
                                    temperature=self.temperature,
                                    top_p=self.top_p
                                )
                            )
                    if response is None:
                        raise RuntimeError(f"Gemini API returned no response for image {idx+1}.")
                    return idx, response.text or ""

                # Run parallel extraction
                results: list[Optional[str]] = [None] * len(all_images)
                # Use max 4 workers to prevent rate limits on standard API keys
                with ThreadPoolExecutor(max_workers=4) as executor:
                    futures = {executor.submit(process_single_image, img, i): i for i, img in enumerate(all_images)}
                    for future in as_completed(futures):
                        try:
                            idx, text = future.result()
                            results[idx] = text
                        except Exception as e:
                            logger.error(f"Failed to extract table from image {futures[future]}: {e}")
                            results[futures[future]] = f"\n\n# Error en captura {futures[future] + 1}\n⚠️ [Error al extraer la tabla de la imagen: {e}]\n"

                # Combine all replies
                reply = "\n\n".join([r.strip() for r in results if r])
                token_info = {
                    "candidates_tokens": 0,
                    "thinking_tokens": 0
                }
                logger.info("Combined all parallel image replies successfully.")
            else:
                # Process normally in a single API call
                new_parts = self._files_to_parts(files, user_query=user_query)
                if user_input:
                    new_parts.append(types.Part.from_text(text=user_input))
                contents = self._build_contents(user_input="", history=history, new_parts=new_parts)

                reply, response = self._call_gemini_with_recovery(
                    contents=contents,
                    sys_instr=self._get_grounded_system_instruction(
                        force_language=force_language,
                        system_notes=system_notes,
                        user_input=user_query,
                        history=history
                    ),
                    tools=tools,
                    temperature=temperature,
                    top_p=top_p,
                    max_tokens=max_tokens,
                    force_plain_text=tools is None,
                )
                token_info = self._parse_token_info(getattr(response, "usage_metadata", None))
                if not reply:
                    reply = f"Error: {self._handle_empty_response(response)}."

            return reply, self._flush_aux_tokens(token_info)
        except Exception as e:
            if isinstance(e, RetryError):
                try:
                    attempt_exc = e.last_attempt.exception() if e.last_attempt else None
                    if attempt_exc is not None:
                        e = attempt_exc
                except Exception:
                    pass
            err_str = str(e)
            if ("503" in err_str or "UNAVAILABLE" in err_str or "429" in err_str or "RESOURCE_EXHAUSTED" in err_str) and contents is not None:
                fallback_model = "gemini-2.5-flash" if self.model_version != "gemini-2.5-flash" else "gemini-2.5-pro"
                logger.warning(f"Gemini model {self.model_version} returned high demand error with inline files ({err_str}). Retrying automatically with fallback model {fallback_model}...")
                try:
                    reply, response = self._call_gemini_with_recovery(
                        contents=contents,
                        sys_instr=self._get_grounded_system_instruction(force_language=force_language, system_notes=system_notes),
                        tools=tools,
                        temperature=temperature,
                        top_p=top_p,
                        max_tokens=max_tokens,
                        model=fallback_model,
                        force_plain_text=tools is None,
                    )
                    token_info = self._parse_token_info(getattr(response, "usage_metadata", None))
                    if not reply:
                        reply = f"Error: {self._handle_empty_response(response)}."
                    return reply, self._flush_aux_tokens(token_info)
                except Exception as fallback_err:
                    logger.error(f"Gemini fallback model {fallback_model} also failed with inline files: {fallback_err}")

            logger.error(f"Gemini error with inline files: {e}", exc_info=True)
            return f"Error: {str(e)}", None

    # Function to generate response with an uploaded file
    def generate_response_with_file(
        self,
        user_input: str,
        history: Optional[List[Dict[str, Any]]] = None,
        gemini_file: Any = None,
    ) -> Tuple[str, Optional[TokenInfo]]:
        """Generate response with an uploaded file."""
        try:
            file_part = types.Part.from_uri(file_uri=gemini_file.uri, mime_type=gemini_file.mime_type)
            new_parts = [file_part, types.Part.from_text(text=user_input)]
            contents = self._build_contents(user_input="", history=history, new_parts=new_parts)

            reply, response = self._call_gemini_with_recovery(
                contents=contents,
                sys_instr=self._get_grounded_system_instruction(),
                tools=None,
                force_plain_text=True,
            )
            token_info = self._parse_token_info(getattr(response, "usage_metadata", None))
            logger.info(f"Response with file tokens: {token_info.get('candidates_tokens', 0)} | Thinking: {token_info.get('thinking_tokens', 0)} | Total: {token_info.get('total_tokens', 0)}")
            if not reply:
                reply = f"Error: {self._handle_empty_response(response)}."
            return reply, self._flush_aux_tokens(token_info)
        except Exception as e:
            if isinstance(e, RetryError):
                try:
                    attempt_exc = e.last_attempt.exception() if e.last_attempt else None
                    if attempt_exc is not None:
                        e = attempt_exc
                except Exception:
                    pass
            logger.error(f"Gemini error with file: {e}")
            return f"Error: {str(e)}", None

    # Function to classify image errors
    @staticmethod
    def _classify_image_error(exc: Exception) -> str:
        """Map provider exceptions to a short machine-readable reason code."""
        text = str(exc or "").lower()
        if "503" in text or "unavailable" in text or "high demand" in text or "overloaded" in text:
            return "high_demand"
        if "429" in text or "rate limit" in text or "resource_exhausted" in text:
            return "rate_limit"
        if "safety" in text or "blocked" in text or "policy" in text:
            return "safety"
        if "401" in text or "403" in text or "permission" in text or "api key" in text:
            return "auth"
        return "other"

    # Function to generate friendly image errors
    @staticmethod
    def _friendly_image_error(reason: str, detail: str = "") -> str:
        """User-facing error (Spanish-friendly); never blame the prompt for 503/429."""
        if reason == "high_demand":
            return (
                "El servicio de imágenes de Gemini está saturado ahora (alta demanda). "
                "Espera unos segundos e inténtalo de nuevo."
            )
        if reason == "rate_limit":
            return (
                "Se alcanzó el límite de solicitudes de imágenes. "
                "Espera un momento e inténtalo de nuevo."
            )
        if reason == "safety":
            return (
                "La imagen fue bloqueada por filtros de seguridad. "
                "Prueba reformular la escena (sin figuras públicas nombradas ni contenido sensible)."
            )
        if reason == "auth":
            return "No se pudo autenticar con el proveedor de imágenes. Revisa la API key."
        if detail:
            return f"No se pudo generar la imagen: {detail}"
        return "No se pudo generar la imagen. Inténtalo de nuevo en unos segundos."

    # Function to merge script tokens
    def _merge_script_tokens(self, token_info: Optional[Dict[str, Any]], script_tokens: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if script_tokens and token_info:
            merged = dict(token_info)
            for key, value in script_tokens.items():
                if isinstance(value, (int, float)):
                    merged[key] = merged.get(key, 0) + value
            return merged
        if script_tokens and not token_info:
            return dict(script_tokens)
        return token_info

    # Function to generate an image
    def generate_image(self, prompt: str) -> Tuple[Optional[bytes], Optional[str], Optional[str], Optional[TokenInfo]]:
        """
        Generate an image using current Gemini native image models (Nano Banana).
        Retries on 503/high-demand and falls back across GA image models.
        Returns (image_bytes, mime_type, error_message, token_info).
        """
        prompt, _script_tokens = self._prepare_image_generation_prompt(prompt)

        image_model = GEMINI_IMAGE_MODEL_VERSION.strip() if GEMINI_IMAGE_MODEL_VERSION else "gemini-3.1-flash-image"
        fallback_model = GEMINI_FALLBACK_IMAGE_MODEL.strip() if GEMINI_FALLBACK_IMAGE_MODEL else "gemini-3-pro-image"
        # Prefer current GA Nano Banana models; avoid deprecated Imagen / 2.5-flash-image.
        models_to_try = [image_model, fallback_model, "gemini-3.1-flash-image", "gemini-3-pro-image"]
        models_to_try = list(dict.fromkeys([m for m in models_to_try if m]))

        last_reason = "other"
        last_detail = ""
        saw_high_demand = False

        for m in models_to_try:
            max_attempts = 3
            for attempt in range(1, max_attempts + 1):
                try:
                    logger.info(f"Generating image with Gemini model {m} (attempt {attempt}): {prompt[:180]}...")
                    if m.startswith("imagen-"):
                        # Legacy path if an env override still points at Imagen.
                        response = self.client.models.generate_images(
                            model=m,
                            prompt=prompt,
                            config=types.GenerateImagesConfig(
                                number_of_images=1,
                                aspect_ratio="1:1",
                                safety_filter_level="block_only_high"
                            )
                        )
                        if response.generated_images:
                            gen_img = response.generated_images[0]
                            image_obj = getattr(gen_img, "image", None)
                            image_bytes = getattr(image_obj, "image_bytes", None) if image_obj is not None else getattr(gen_img, "image_bytes", None)
                            if isinstance(image_bytes, str):
                                image_bytes = base64.b64decode(image_bytes)
                            if image_bytes:
                                token_info = None
                                if hasattr(response, 'usage_metadata') and response.usage_metadata:
                                    token_info = self._parse_token_info(response.usage_metadata)
                                token_info = self._merge_script_tokens(token_info, _script_tokens)
                                logger.info(f"Image generated successfully using {m}")
                                return image_bytes, "image/png", None, self._flush_aux_tokens(token_info) if token_info else None
                        raise ValueError(f"{m} returned no generated_images")

                    image_request = (
                        "Generate an image that matches this description EXACTLY. "
                        "Do not replace the main subject with a different animal, person, or object.\n\n"
                        f"{prompt}"
                    )
                    response = self.client.models.generate_content(
                        model=m,
                        contents=image_request,
                        config=types.GenerateContentConfig(
                            response_modalities=["IMAGE"]
                        )
                    )
                    if response.candidates:
                        candidate = response.candidates[0]
                        parts = candidate.content.parts if candidate.content else None
                        if isinstance(parts, list):
                            for part in parts:
                                if part.inline_data and part.inline_data.mime_type and part.inline_data.mime_type.startswith('image/'):
                                    image_bytes = part.inline_data.data
                                    if isinstance(image_bytes, str):
                                        image_bytes = base64.b64decode(image_bytes)
                                    mime = part.inline_data.mime_type
                                    token_info = None
                                    if hasattr(response, 'usage_metadata') and response.usage_metadata:
                                        token_info = self._parse_token_info(response.usage_metadata)
                                    token_info = self._merge_script_tokens(token_info, _script_tokens)
                                    logger.info(f"Image generated successfully using {m}")
                                    return image_bytes, mime, None, self._flush_aux_tokens(token_info) if token_info else None
                    raise ValueError(f"{m} returned no image parts")
                except Exception as e:
                    reason = self._classify_image_error(e)
                    last_reason = reason
                    last_detail = str(e)
                    logger.warning(f"Image generation failed with Gemini model {m} (attempt {attempt}): {e}")
                    if reason in ("high_demand", "rate_limit"):
                        saw_high_demand = True
                        if attempt < max_attempts:
                            time.sleep(1.5 * attempt)
                            continue
                    break  # next model

        if saw_high_demand:
            return None, None, self._friendly_image_error("high_demand"), None
        return None, None, self._friendly_image_error(last_reason, last_detail), None

    # Function to generate audio
    def generate_audio(
        self,
        prompt: str,
        language: Optional[str] = None,
        fallback_models: Optional[List[str]] = None,
    ) -> Tuple[Optional[bytes], Optional[str], Optional[str], Optional[TokenInfo], Optional[str]]:
        """
        Generate fictional audio based on user prompt using TTS models.
        Dynamically selects male/female voice based on prompt keywords.
        Returns (audio_bytes, mime_type, error_message, token_info, script).
        """
        script = None
        script_tokens: Optional[TokenInfo] = None
        try:
            # Resolve BCP-47 language code to human-readable language name
            lang_name = "the SAME language as the Request"
            if language:
                base_lang = language.split('-')[0].lower()
                _LANG_NAMES = {
                    "es": "Spanish",
                    "en": "English",
                    "fr": "French",
                    "de": "German",
                    "pt": "Portuguese",
                    "it": "Italian",
                    "zh": "Chinese",
                    "ja": "Japanese",
                    "ko": "Korean"
                }
                lang_name = _LANG_NAMES.get(base_lang, "the SAME language as the Request")

            # Step 1: Generate a script using the chat model
            script_instruction = textwrap.dedent(f"""\
            Write a short, natural-sounding spoken paragraph (max 50 words, about 15-20 seconds when read aloud) that matches the following request.
            The speaker is a person talking conversationally.

            CRITICAL LANGUAGE REQUIREMENT: You MUST write the spoken text in {lang_name}.

            Return ONLY the spoken text, without any extra commentary, quotes, or markdown.

            Request: {prompt}

            Spoken script:
            """)
            original_search_state = getattr(self, "google_search_enabled", False)
            try:
                self.google_search_enabled = False
                try:
                    script, script_tokens = self.generate_response(script_instruction, history=None)
                except Exception as e:
                    script = f"Error: {str(e)}"
                    script_tokens = None
            finally:
                self.google_search_enabled = original_search_state

            if (not script or script.startswith("Error:")) and fallback_models:
                logger.warning(f"Script generation failed with {self.model_version}, trying fallback models...")
                for model in fallback_models:
                    if model == self.model_version:
                        continue
                    try:
                        logger.info(f"Trying fallback model for script: {model}")
                        response = self.client.models.generate_content(
                            model=model,
                            contents=script_instruction,
                            config=types.GenerateContentConfig(
                                max_output_tokens=self.max_tokens,
                                temperature=self.temperature,
                                top_p=self.top_p
                            )
                        )
                        if response is not None:
                            script = response.text
                            if script and not script.startswith("Error:"):
                                script_tokens = self._flush_aux_tokens(self._parse_token_info(getattr(response, "usage_metadata", None)))
                                break
                    except Exception as ex:
                        logger.warning(f"Fallback model {model} failed: {ex}")

            if not script or script.startswith("Error:"):
                # If script generation completely failed, use the user's prompt as the script fallback
                logger.warning("All script generation attempts failed. Using prompt as fallback script.")
                script = prompt
                script_tokens = None
            else:
                script = script.strip().strip('"').strip("'")

            logger.info(f"Generated script: {script}")

            # --- Try VoiceProcessor TTS if configured ---
            if self.voice_processor.is_configured():
                voice_cat = self.voice_processor.determine_voice_category(prompt)
                try:
                    audio_bytes = self.voice_processor.generate_tts(script, voice_category=voice_cat)
                    if not audio_bytes:
                        raise ValueError("VoiceProcessor returned empty or null audio bytes")
                    token_info = self._flush_aux_tokens(script_tokens) if script_tokens else None

                    logger.info(f"VoiceProcessor TTS generated audio with voice category '{voice_cat}' successfully.")
                    return audio_bytes, "audio/mp3", None, token_info, script
                except Exception as e:
                    logger.warning(f"VoiceProcessor TTS failed: {e}. Falling back to Gemini native TTS...")

            # --- Dynamic voice selection based on prompt ---
            lower_prompt = prompt.lower()

            # Male keywords
            male_keywords_eng = ["man", "male", "guy", "boy", "gentleman", "father", "husband", "he", "him", "his"]
            male_keywords_esp = ["hombre", "masculino", "chico", "niño", "caballero", "padre", "esposo", "él", "lo"]
            male_keywords = male_keywords_eng + male_keywords_esp

            female_keywords_eng = ["woman", "female", "girl", "lady", "mother", "wife", "daughter", "she", "her", "hers"]
            female_keywords_esp = ["mujer", "femenino", "chica", "niña", "dama", "madre", "esposa", "hija", "ella", "la"]
            female_keywords = female_keywords_eng + female_keywords_esp

            # Function to get earliest keyword index
            def get_earliest_keyword_index(keywords, text):
                earliest = float('inf')
                for kw in keywords:
                    match = re.search(r'\b' + re.escape(kw) + r'\b', text)
                    if match and match.start() < earliest:
                        earliest = match.start()
                return earliest

            female_idx = get_earliest_keyword_index(female_keywords, lower_prompt)
            male_idx = get_earliest_keyword_index(male_keywords, lower_prompt)

            if female_idx < male_idx:
                voice_name = "Aoede"       # female voice
                logger.info("Detected primary female speaker, using Aoede voice")
            elif male_idx < female_idx:
                voice_name = "Charon"      # male voice
                logger.info("Detected primary male speaker, using Charon voice")
            else:
                voice_name = GEMINI_TTS_VOICE.strip() or "Charon"
                logger.info(f"No gender specified or tied, using default voice: {voice_name}")

            # Step 2: Build TTS config
            tts_model = GEMINI_AUDIO_MODEL_VERSION.strip()

            # Function to build TTS config.
            def tts_config():
                return types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                        )
                    )
                )

            audio_bytes = None
            audio_response = None
            # Primary TTS model
            try:
                fibonacci_wait = wait_chain(*[wait_fixed(s) for s in GEMINI_RETRY_SEQUENCE])
                for attempt in Retrying(stop=stop_after_attempt(len(GEMINI_RETRY_SEQUENCE)), wait=fibonacci_wait, reraise=True):
                    with attempt:
                        audio_response = self.client.models.generate_content(
                            model=tts_model,
                            contents=script,
                            config=tts_config()
                        )
                audio_bytes = self._extract_audio(audio_response)
            except Exception as e:
                logger.warning(f"Primary TTS model {tts_model} failed: {e}")

            if audio_bytes:
                token_info = None
                if audio_response is not None and hasattr(audio_response, 'usage_metadata') and audio_response.usage_metadata:
                    raw_audio_tokens = self._parse_token_info(audio_response.usage_metadata)
                    if script_tokens:
                        st_dict = script_tokens.to_legacy_dict() if isinstance(script_tokens, TokenInfo) else dict(script_tokens)
                        raw_audio_tokens["prompt_tokens"] += st_dict.get("prompt_tokens", 0)
                        raw_audio_tokens["candidates_tokens"] += st_dict.get("candidates_tokens", 0)
                        raw_audio_tokens["total_tokens"] += st_dict.get("total_tokens", 0)
                    token_info = self._flush_aux_tokens(raw_audio_tokens)
                    logger.info(f"Audio total tokens: {token_info.total_tokens}")
                elif script_tokens:
                    token_info = self._flush_aux_tokens(script_tokens)
                    logger.info(f"Audio tokens (script only): {token_info.total_tokens}")
                logger.info(f"Audio with voice {voice_name} from {tts_model}")
                return self._pcm_to_wav(audio_bytes), "audio/wav", None, token_info, script

            # Fallback to pro TTS model
            fallback_model = GEMINI_FALLBACK_AUDIO_MODEL_VERSION.strip()
            audio_response = None
            try:
                fibonacci_wait = wait_chain(*[wait_fixed(s) for s in GEMINI_RETRY_SEQUENCE])
                for attempt in Retrying(stop=stop_after_attempt(len(GEMINI_RETRY_SEQUENCE)), wait=fibonacci_wait, reraise=True):
                    with attempt:
                        audio_response = self.client.models.generate_content(
                            model=fallback_model,
                            contents=script,
                            config=tts_config()
                        )
                audio_bytes = self._extract_audio(audio_response)
            except Exception as e:
                logger.warning(f"Fallback TTS model {fallback_model} failed: {e}")

            if audio_bytes:
                token_info = None
                if audio_response is not None and hasattr(audio_response, 'usage_metadata') and audio_response.usage_metadata:
                    raw_audio_tokens = self._parse_token_info(audio_response.usage_metadata)
                    if script_tokens:
                        st_dict = script_tokens.to_legacy_dict() if isinstance(script_tokens, TokenInfo) else dict(script_tokens)
                        raw_audio_tokens["prompt_tokens"] += st_dict.get("prompt_tokens", 0)
                        raw_audio_tokens["candidates_tokens"] += st_dict.get("candidates_tokens", 0)
                        raw_audio_tokens["total_tokens"] += st_dict.get("total_tokens", 0)
                    token_info = self._flush_aux_tokens(raw_audio_tokens)
                    logger.info(f"Audio total tokens: {token_info.total_tokens}")
                elif script_tokens:
                    token_info = self._flush_aux_tokens(script_tokens)
                    logger.info(f"Audio tokens (script only): {token_info.total_tokens}")
                logger.info(f"Audio with voice {voice_name} from fallback {fallback_model}")
                return self._pcm_to_wav(audio_bytes), "audio/wav", None, token_info, script

            # If native audio generation fails completely, return browser-tts fallback
            logger.warning("Native TTS models failed. Returning browser-tts fallback.")
            final_token_info = self._flush_aux_tokens(script_tokens) if script_tokens else None
            return None, "browser-tts", None, final_token_info, script
        except Exception as e:
            logger.error(f"Audio generation error: {e}")
            if script:
                final_token_info = self._flush_aux_tokens(script_tokens) if script_tokens else None
                return None, "browser-tts", None, final_token_info, script
            return None, None, f"Audio generation failed: {str(e)}", None, None
