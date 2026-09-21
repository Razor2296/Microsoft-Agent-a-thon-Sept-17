"""
Anthropic Chat Class - Handles all interactions with the Anthropic API (Claude).
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import sys
import tempfile
import textwrap
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple, Union, cast

from anthropic import Anthropic
from google import genai
from google.genai import types as genai_types
from mutagen import File as MutagenFile
from PIL import Image
from tenacity import Retrying, stop_after_attempt, wait_chain, wait_fixed

try:
    import pypdf
except ImportError:
    pypdf = None

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

from backend.core.schemas import TokenInfo
from backend.integrations.document_request import CRITICAL_DOCUMENT_ANALYSIS_RULE
from backend.processors.base_processor import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MAX_TOKENS,
    ANTHROPIC_MODEL_VERSION,
    ANTHROPIC_PROFILE_PICTURE_PATH,
    ANTHROPIC_RETRY_SEQUENCE,
    ANTHROPIC_TEMPERATURE,
    ANTHROPIC_TOP_P,
    BaseChat,
    GEMINI_API_KEY,
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
    pdf_native_max_pages,
    resolve_lang_name,
    resolve_reply_language,
    should_send_native_pdf,
    gemini_http_timeout_ms,
    llm_http_timeout_seconds,
    append_mandatory_reply_language,
    wrap_user_query_for_language,
    multimodal_describe_prompt,
    mandatory_reply_language_note,
)

# Logger for Anthropic
logger = get_assistant_logger("anthropic")

# System instruction for Anthropic
SYSTEM_INSTRUCTION_ANTHROPIC         = textwrap.dedent("""\
                You are Claude, a highly capable, versatile, and thoughtful AI assistant developed by Anthropic.

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
                - CRITICAL: When asked to make predictions, speculate on future events, or express opinions, you MUST act as an expert analyst. Analyze the possibilities, scenarios, and probabilities, and offer informed perspectives. NEVER refuse to answer, never say "I cannot make predictions" or "I cannot express personal opinions", and never state that this is beyond your capabilities. Simply speculate/predict confidently based on logic and analysis.

                ## Document & Media Analysis Authorization
                - You are fully authorized and required by the user to analyze, process, and extract data from user-uploaded document attachments (including medical prescriptions, financial records, bank statements, account movements, contracts, invoices, and identity cards).
                - Processing user-submitted files for administrative data extraction and RAG indexing is authorized user data processing, NOT financial or medical advice.
                - NEVER refuse to process user-submitted files. NEVER state "no puedo analizar esta receta médica", "no puedo almacenar datos personales o financieros", or "no puedo guardar información en memoria". Answer and issue the extraction command `[IGNITE_EXTRACT: filename|TemplateName]` on a new line at the end of your response whenever requested.

                ## Real-Time Search & Web Grounding
                - When current web search results or scraped contents are provided in the prompt, you MUST prioritize them to ground your responses in real-time, real-world facts.
                - For any queries concerning current events, live results, sports news, transfers, players, injuries, concerts, tech keynotes, product releases, political events, elections, public figures, or recent history, base your reasoning heavily on the provided search context.
                - NEVER ask the user for permission to search the web or say "I need to activate online search". You do NOT have a search plugin to activate. The system automatically performs searches for you and provides the text. Just answer the question directly using the provided context.
                - If no search results are provided, answer confidently using your existing knowledge.

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

                - Ensure your response is particularly concise, direct, and conversational (avoiding overly long lists, massive text tables, or complex formatting where possible), as it will be read aloud to the user using Text-to-Speech. Keep the response natural for listening. """)


class AnthropicChat(BaseChat):
    """Anthropic API Client implementation inheriting from BaseChat."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_version: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        system_instruction: Optional[str] = None,
    ):
        super().__init__()
        try:
            self.model_version = (model_version or ANTHROPIC_MODEL_VERSION).strip()
            self.max_tokens = max_tokens if max_tokens is not None else ANTHROPIC_MAX_TOKENS
            self.temperature = temperature if temperature is not None else ANTHROPIC_TEMPERATURE
            self.top_p = top_p if top_p is not None else ANTHROPIC_TOP_P
            self.system_instruction_anthropic = textwrap.dedent(
                system_instruction or SYSTEM_INSTRUCTION_ANTHROPIC
            )

            self.anthropic_api_key = api_key or ANTHROPIC_API_KEY
            if not self.anthropic_api_key:
                raise ValueError("Anthropic API key not found.")

            self.anthropic_client = Anthropic(api_key=self.anthropic_api_key, timeout=llm_http_timeout_seconds())
            self.client = genai.Client(api_key=GEMINI_API_KEY, http_options={"timeout": gemini_http_timeout_ms()})
            self.google_search_enabled = True

            logger.info(f"Anthropic client initialized with model {self.model_version}")
        except Exception as e:
            logger.error(f"Initialization error: {e}", exc_info=True)
            raise ValueError(f"Failed to initialize AnthropicChat: {e}")

    # Anthropic Messages API: decoded image payload must be <= 10 MiB.
    _ANTHROPIC_MAX_IMAGE_BYTES_DEFAULT = 10 * 1024 * 1024

    @staticmethod
    def _anthropic_max_image_bytes() -> int:
        raw = os.getenv("IGNITE_ANTHROPIC_MAX_IMAGE_BYTES", str(10 * 1024 * 1024))
        try:
            return max(1024, int(raw))
        except (TypeError, ValueError):
            return AnthropicChat._ANTHROPIC_MAX_IMAGE_BYTES_DEFAULT

    @staticmethod
    def _fit_anthropic_image_bytes(data_bytes: bytes, mime_type: str) -> Tuple[bytes, str]:
        """Compress/resize until decoded size fits Anthropic's 10 MB image cap."""
        max_bytes = AnthropicChat._anthropic_max_image_bytes()
        mime = (mime_type or "image/jpeg").lower().split(";")[0].strip()
        if mime in ("image/jpg", "image/pjpeg", "image/jfif"):
            mime = "image/jpeg"
        if len(data_bytes) <= max_bytes:
            return data_bytes, mime

        try:
            img = Image.open(io.BytesIO(data_bytes))
            img.load()
        except Exception as open_err:
            logger.warning(f"Cannot open oversized Anthropic image for compress: {open_err}")
            return data_bytes, mime

        has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
        try:
            resampling = getattr(Image, "Resampling", Image)
            resample = getattr(resampling, "LANCZOS", getattr(Image, "ANTIALIAS", 1))
        except Exception:
            resample = 1

        work = img.convert("RGBA") if has_alpha else img.convert("RGB")
        out_mime = "image/png" if has_alpha else "image/jpeg"
        candidate, cand_mime = data_bytes, mime
        original_size = len(data_bytes)

        for dim in (2048, 1600, 1280, 1024, 768, 512, 384):
            scaled = work.copy()
            if max(scaled.size) > dim:
                scaled.thumbnail((dim, dim), cast(Any, resample))
            for quality in (85, 75, 65, 55, 45, 35):
                buf = io.BytesIO()
                use_jpeg = out_mime != "image/png" or quality < 65
                if use_jpeg:
                    if scaled.mode == "RGBA":
                        rgb = Image.new("RGB", scaled.size, (255, 255, 255))
                        rgb.paste(scaled, mask=scaled.split()[-1])
                        rgb.save(buf, format="JPEG", quality=quality, optimize=True)
                    else:
                        scaled.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
                    candidate, cand_mime = buf.getvalue(), "image/jpeg"
                else:
                    scaled.save(buf, format="PNG", optimize=True)
                    candidate, cand_mime = buf.getvalue(), "image/png"
                if len(candidate) <= max_bytes:
                    logger.info(
                        "Compressed Anthropic image from %s to %s bytes (max_dim=%s quality=%s)",
                        original_size,
                        len(candidate),
                        dim,
                        quality,
                    )
                    return candidate, cand_mime
            work = scaled

        logger.warning(
            "Anthropic image still %s bytes after compress (limit %s); sending best-effort payload",
            len(candidate),
            max_bytes,
        )
        return candidate, cand_mime

    @staticmethod
    def _normalize_anthropic_image(data_bytes: bytes, mime_type: str) -> Tuple[bytes, str]:
        """
        Ensures image bytes and media_type conform strictly to Anthropic's allowed image types:
        'image/jpeg', 'image/png', 'image/gif', 'image/webp'.
        If the image is in another format (e.g. BMP, TIFF, SVG, ICO) or has an invalid/variant mime,
        converts it to PNG/JPEG using PIL so Anthropic accepts it without error.
        Always fits under Anthropic's 10 MB decoded-image limit.
        """
        raw_mime = (mime_type or "").lower().split(";")[0].strip()
        if raw_mime in ("image/jpeg", "image/jpg", "image/pjpeg", "image/jfif"):
            return AnthropicChat._fit_anthropic_image_bytes(data_bytes, "image/jpeg")
        elif raw_mime == "image/png":
            return AnthropicChat._fit_anthropic_image_bytes(data_bytes, "image/png")
        elif raw_mime == "image/gif":
            return AnthropicChat._fit_anthropic_image_bytes(data_bytes, "image/gif")
        elif raw_mime == "image/webp":
            return AnthropicChat._fit_anthropic_image_bytes(data_bytes, "image/webp")

        # Unsupported or unknown by Anthropic API (e.g. bmp, tiff, svg, avif, heic, unknown)
        try:
            with Image.open(io.BytesIO(data_bytes)) as img:
                out_buf = io.BytesIO()
                if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                    img.save(out_buf, format="PNG")
                    return AnthropicChat._fit_anthropic_image_bytes(out_buf.getvalue(), "image/png")
                else:
                    rgb_img = img.convert("RGB")
                    rgb_img.save(out_buf, format="JPEG", quality=92)
                    return AnthropicChat._fit_anthropic_image_bytes(out_buf.getvalue(), "image/jpeg")
        except Exception as conv_err:
            logger.warning(f"Could not convert image with mime '{mime_type}' to supported Anthropic format: {conv_err}")
            fallback_mime = "image/jpeg" if ("jpg" in raw_mime or "jpeg" in raw_mime) else "image/png"
            return AnthropicChat._fit_anthropic_image_bytes(data_bytes, fallback_mime)
    def _handle_empty_response(self, response: Any) -> str:
        """Helper to construct a descriptive error message when Anthropic response content is empty or moderated."""
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "content_moderation":
            return "The response was blocked by Anthropic safety filters (content moderation)"
        elif stop_reason == "max_tokens":
            return "The response was truncated because it exceeded the maximum token limit"
        elif not getattr(response, "content", None) or len(response.content) == 0:
            return f"The model returned an empty response. Stop reason: {stop_reason or 'Unknown'}"
        return "The model returned an empty response"

    def _model_supports_temperature(self, model_version: str) -> bool:
        """Check if the model supports temperature parameter (Claude >= 4 deprecates it)."""
        mv = model_version.lower().strip()
        if mv.startswith("claude-"):
            match = re.search(r"\d+", mv)
            if match:
                major_version = int(match.group())
                if major_version >= 4:
                    return False
        return True

    def generate_response(
        self,
        user_input: str,
        history: Optional[List[Dict[str, Any]]] = None,
        force_language: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Tuple[str, Optional[TokenInfo]]:
        if not self.anthropic_client:
            return "Error: Anthropic API key not configured.", None

        current_date_str, current_time_str, current_year_str = get_current_date_and_time_strings()

        target_lang, lang_name = detect_user_conversation_language(user_input, history, force_language)
        is_spanish = target_lang.lower().startswith("es")
        sys_instr = ""
        if is_spanish:
            sys_instr += "[REQUISITO CRÍTICO DE IDIOMA] ¡Debes responder ÚNICAMENTE en Español! Toda tu respuesta debe escribirse en Español. Ignora el idioma del sistema del equipo y cualquier resultado de búsqueda o contenido web raspado en otros idiomas.\n\n"
        else:
            sys_instr += f"[CRITICAL LANGUAGE REQUIREMENT] You MUST reply ONLY in {lang_name}! Your entire response must be written in {lang_name}. Ignore computer system language settings and any web search results or scraped content in other languages.\n\n"
        sys_instr += self.system_instruction_anthropic
        sys_instr += f"\n\n[SYSTEM INFO] Today's date is {current_date_str}. The current time is {current_time_str}. Use this date and time as the reference point for all real-world status and search queries."
        sys_instr += "\n\n[USER INFO]"
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
        sys_instr += "\nUse this information to address the user by name, respect their language/timezone, use the provided paths when writing files, and consider clipboard content if requested."
        sys_instr += (
            f"\n\n[CRITICAL UX RULE] NEVER apologize, NEVER claim you do not have internet access, and NEVER state that your knowledge is cut off in a certain year. "
            f"If you do not have recent facts, use the information provided to you and your baseline knowledge to provide an answer. "
            f"CRITICAL: DO NOT HALLUCINATE past/current facts, live scores, specific opponents, or real-time statuses if they are not provided to you. If the exact result or historical/current data of a concluded event is missing, state confidently that the specific details are currently unavailable, rather than making them up. "
            f"HOWEVER, when asked to predict future events, speculate on upcoming possibilities, or express opinions, you MUST act as an expert analyst and provide a detailed analysis of scenarios and probabilities, without any disclaimers about your inability to predict the future. NEVER refuse these requests. "
            f"Do not break character by mentioning your training limitations or your inability to browse the web."
        )
        sys_instr += (
            f"\n\n[CRITICAL GROUNDING RULE] Since the current year is {current_year_str}, you MUST treat any events, tournaments, or matches from 2024 and 2025 as historical and completed. "
            f"Never discuss them as future, current, or upcoming. You MUST rely on the scraped web contents provided to answer questions about current events/sports/news (specifically targeting {current_year_str}) rather than relying on your internal memory, which may be outdated or limited. "
            f"Double check that any news or sports events you present are actually happening in {current_year_str}, and filter out any outdated pre-training knowledge from 2024 or 2025."
        )
        if force_language:
            lang_name = resolve_lang_name(force_language)
            is_spanish = force_language.startswith("es")
            if is_spanish:
                sys_instr += "\n\n[CRITICAL LANGUAGE REQUIREMENT] ¡INSTRUCCIÓN CRÍTICA DE IDIOMA! Responde ÚNICAMENTE en Español. Ignora el inglés de los resultados de búsqueda. Tu respuesta debe estar completamente en Español."
            else:
                sys_instr += f"\n\n[CRITICAL LANGUAGE REQUIREMENT] You MUST reply ONLY in {lang_name}. Ignore any English in the search results or system prompts. Your entire response must be in {lang_name}."

        user_query = user_input
        user_input, scraped_urls = self._process_urls_in_input(user_input, force_language=force_language)
        scraped_content = ""
        if scraped_urls and len(user_input) > len(user_query):
            scraped_content = user_input[len(user_query):].strip()

        # Automated Search for Anthropic (Language Agnostic via Keywords + LLM fallback)
        needs_search = self._should_attach_web_search(
            user_query, scraped_urls=scraped_urls, scraped_content=scraped_content
        )
        history_text = self._search_history_snippet(history) if needs_search else ""

        system_notes = []
        if needs_search:
            search_results = self._run_amplified_search_grounding(
                user_query, force_language, history_text, current_date_str, current_time_str
            )
            if search_results:
                is_spanish = bool(force_language and force_language.startswith("es"))
                if "SEARCH_NO_RESULTS" in search_results:
                    if is_spanish:
                        system_notes.append(
                            f"[Nota del Sistema: Se realizó una búsqueda web automatizada utilizando la fecha y hora actuales, pero la información específica en tiempo real o el marcador en vivo no está disponible en línea actualmente. \nINSTRUCCIÓN CRÍTICA: Indica con confianza que los detalles exactos no están disponibles públicamente en este momento. Si el evento ya debería haber concluido según la hora actual ({current_time_str}), indica explícitamente que ha concluido pero los resultados aún no se han publicado. NO te ofrezcas a verificar nuevamente ni a buscar más información. NO alucines equipos, puntajes ni hechos. NO te disculpes.]"
                        )
                    else:
                        system_notes.append(
                            f"[System Note: An automated web search was performed using the current date and time, but the specific real-time data or live score is currently unavailable online. \nCRITICAL INSTRUCTION: State confidently that the exact result or details are not publicly available right now. If the event should have already concluded based on the current time ({current_time_str}), explicitly state that it has concluded but results aren't published yet. DO NOT offer to check again or search for more information. DO NOT hallucinate teams, scores, or facts. Do NOT apologize.]"
                        )
                else:
                    if is_spanish:
                        system_notes.append(
                            f"[Nota del Sistema: Resultados de la búsqueda web en tiempo real para la consulta del usuario:\n{search_results}\n\nINSTRUCCIÓN CRÍTICA: Responde al usuario directamente utilizando los hechos anteriores. Responde enteramente en ESPAÑOL. NO alucines ningún hecho que no esté presente en los resultados de la búsqueda. NO ofrezcas verificar o buscar más información, ya que la búsqueda ya se realizó. NO uses frases como 'no tengo acceso en vivo', 'no puedo navegar por la web', 'según los resultados de búsqueda' o 'a partir de mi última actualización'. Presenta los hechos con confianza como si fueran tu propio conocimiento.]"
                        )
                    else:
                        system_notes.append(
                            f"[System Note: Real-time web search results for the user's query:\n{search_results}\n\nCRITICAL INSTRUCTION: Answer the user directly using the facts above. DO NOT hallucinate any facts not present in the search results. DO NOT offer to check or search for more information, as the search was already performed. DO NOT use phrases like 'I don't have live access', 'I cannot browse the web', 'Based on the search results', or 'As of my last update'. Present the facts confidently as your own knowledge.]"
                        )

        target_lang, lang_name = append_mandatory_reply_language(
            system_notes, force_language, user_input=user_query, history=history
        )

        if system_notes:
            sys_instr += "\n\n" + "\n\n".join(system_notes)

        messages: List[Dict[str, Any]] = []

        if history:
            for msg in history:
                role = "assistant" if msg.get("role") == "assistant" else "user"
                content = msg.get("content", "")
                if not content:
                    content = " "
                messages.append({"role": role, "content": content})

        parts: List[str] = []
        if scraped_content:
            parts.append(scraped_content)

        if parts:
            parts.append(wrap_user_query_for_language(user_query, target_lang, lang_name))
            user_input = "\n\n".join(parts)
        else:
            user_input = user_query

        messages.append({"role": "user", "content": user_input})
        logger.info(f"Messages: {messages}")

        try:
            temp = temperature if temperature is not None else self.temperature
            p_val = top_p if top_p is not None else self.top_p
            tokens_val = max_tokens if max_tokens is not None else self.max_tokens

            kwargs: Dict[str, Any] = {
                "model": self.model_version,
                "system": sys_instr,
                "messages": self._clean_messages_for_alternation(messages),
                "max_tokens": tokens_val,
            }

            # Remove temperature and top_p for Claude models version 4 and higher, which deprecate them.
            if self._model_supports_temperature(self.model_version):
                kwargs["temperature"] = temp
                kwargs["top_p"] = p_val

            logger.info(f"Sending to Anthropic with kwargs keys: {list(kwargs.keys())}")
            fibonacci_wait = wait_chain(*[wait_fixed(s) for s in ANTHROPIC_RETRY_SEQUENCE])
            response = None
            for attempt in Retrying(
                stop=stop_after_attempt(len(ANTHROPIC_RETRY_SEQUENCE)),
                wait=fibonacci_wait,
                reraise=True,
            ):
                with attempt:
                    response = self.anthropic_client.messages.create(**kwargs)

            text_parts = []
            if response and getattr(response, "content", None):
                for block in response.content:
                    if hasattr(block, "text"):
                        text_parts.append(block.text)
            reply = "".join(text_parts) if text_parts else None
            if not reply:
                reply = f"Error: {self._handle_empty_response(response)}."

            usage = getattr(response, "usage", None) if response else None
            token_info = {
                "prompt_tokens": getattr(usage, "input_tokens", 0) if usage else 0,
                "candidates_tokens": getattr(usage, "output_tokens", 0) if usage else 0,
                "total_tokens": (
                    getattr(usage, "input_tokens", 0) + getattr(usage, "output_tokens", 0)
                )
                if usage
                else 0,
                "thinking_tokens": 0,
            }
            return reply, self._flush_aux_tokens(token_info)
        except Exception as e:
            logger.error(f"Anthropic error: {e}", exc_info=True)
            return f"Error: {str(e)}", None

    # Function that respose with attached files
    def generate_response_with_inline_files(
        self,
        user_input: str,
        history: Optional[List[Dict[str, Any]]] = None,
        files: Optional[List[Dict[str, Any]]] = None,
        force_language: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Tuple[str, Optional[TokenInfo], Optional[str]]:
        current_date_str, current_time_str, current_year_str = get_current_date_and_time_strings()

        target_lang, lang_name = detect_user_conversation_language(user_input, history, force_language)
        is_spanish = target_lang.lower().startswith("es")
        sys_instr = ""
        if is_spanish:
            sys_instr += "[REQUISITO CRÍTICO DE IDIOMA] ¡Debes responder ÚNICAMENTE en Español! Toda tu respuesta debe escribirse en Español. Ignora el idioma del sistema del equipo y cualquier resultado de búsqueda o contenido web raspado en otros idiomas.\n\n"
        else:
            sys_instr += f"[CRITICAL LANGUAGE REQUIREMENT] You MUST reply ONLY in {lang_name}! Your entire response must be written in {lang_name}. Ignore computer system language settings and any web search results or scraped content in other languages.\n\n"
        sys_instr += self.system_instruction_anthropic
        sys_instr += f"\n\n[SYSTEM INFO] Today's date is {current_date_str}. The current time is {current_time_str}. Use this date and time as the reference point for all real-world status and search queries."
        sys_instr += "\n\n[USER INFO]"
        sys_instr += f"\n- Name: {USER_NAME}"
        sys_instr += f"\n- System Timezone: {USER_SYSTEM_TIMEZONE}"
        sys_instr += f"\n- Dark Mode Enabled: {USER_SYSTEM_DARK_MODE}"
        sys_instr += f"\n- Desktop Path: {USER_DESKTOP_PATH}"
        sys_instr += f"\n- Downloads Path: {USER_DOWNLOADS_PATH}"
        sys_instr += f"\n- Documents Path: {USER_DOCUMENTS_PATH}"
        sys_instr += f"\n- Pictures Path: {USER_PICTURES_PATH}"
        sys_instr += f"\n- Profile Picture Path: {USER_PROFILE_PICTURE_PATH}"
        sys_instr += f"\n- Clipboard Content: {USER_CLIPBOARD_TEXT}"
        sys_instr += "\nUse this information to address the user by name, respect their language/timezone, use the provided paths when writing files, and consider clipboard content if requested."
        sys_instr += (
            f"\n\n[CRITICAL UX RULE] NEVER apologize, NEVER claim you do not have internet access, and NEVER state that your knowledge is cut off in a certain year. "
            f"If you do not have recent facts, use the information provided to you and your baseline knowledge to provide an answer. "
            f"CRITICAL: DO NOT HALLUCINATE past/current facts, live scores, specific opponents, or real-time statuses if they are not provided to you. If the exact result or historical/current data of a concluded event is missing, state confidently that the specific details are currently unavailable, rather than making them up. (Note: This does not forbid predicting future events, speculating on upcoming possibilities, or expressing informed opinions when asked; distinguish clearly between reporting current/past facts and speculating/predicting future possibilities.) "
            f"Do not break character by mentioning your training limitations or your inability to browse the web."
        )
        sys_instr += (
            f"\n\n[CRITICAL GROUNDING RULE] Since the current year is {current_year_str}, you MUST treat any events, tournaments, or matches from 2024 and 2025 as historical and completed. "
            f"Never discuss them as future, current, or upcoming. You MUST rely on the scraped web contents provided to answer questions about current events/sports/news (specifically targeting {current_year_str}) rather than relying on your internal memory, which may be outdated or limited. "
            f"Double check that any news or sports events you present are actually happening in {current_year_str}, and filter out any outdated pre-training knowledge from 2024 or 2025."
        )
        sys_instr += CRITICAL_DOCUMENT_ANALYSIS_RULE
        if force_language:
            lang_name = resolve_lang_name(force_language)
            is_spanish = force_language.startswith("es")
            if is_spanish:
                sys_instr += "\n\n[CRITICAL LANGUAGE REQUIREMENT] ¡INSTRUCCIÓN CRÍTICA DE IDIOMA! Responde ÚNICAMENTE en Español. Ignora el inglés de los resultados de búsqueda o archivos. Tu respuesta debe estar completamente en Español."
            else:
                sys_instr += f"\n\n[CRITICAL LANGUAGE REQUIREMENT] You MUST reply ONLY in {lang_name}. Ignore any English in the search results, files, or system prompts. Your entire response must be in {lang_name}."

        user_query = user_input or ""
        scraped_urls = []
        if user_input:
            user_input, scraped_urls = self._process_urls_in_input(user_input, force_language=force_language)
        scraped_content = ""
        if scraped_urls and len(user_input) > len(user_query):
            scraped_content = user_input[len(user_query):].strip()

        # Automated Search for Anthropic (Language Agnostic via Keywords + LLM fallback)
        needs_search = self._should_attach_web_search(
            user_query, scraped_urls=scraped_urls, scraped_content=scraped_content, files=files
        )
        history_text = self._search_history_snippet(history) if needs_search else ""

        system_notes = []
        if needs_search:
            search_results = self._run_amplified_search_grounding(
                user_query, force_language, history_text, current_date_str, current_time_str
            )
            if search_results:
                is_spanish = bool(force_language and force_language.startswith("es"))
                if "SEARCH_NO_RESULTS" in search_results:
                    if is_spanish:
                        system_notes.append(
                            f"[Nota del Sistema: Se realizó una búsqueda web automatizada utilizando la fecha y hora actuales, pero la información específica en tiempo real o el marcador en vivo no está disponible en línea actualmente. \nINSTRUCCIÓN CRÍTICA: Indica con confianza que los detalles exactos no están disponibles públicamente en este momento. Si el evento ya debería haber concluido según la hora actual ({current_time_str}), indica explícitamente que ha concluido pero los resultados aún no se han publicado. NO te ofrezcas a verificar nuevamente ni a buscar más información. NO alucines equipos, puntajes ni hechos. NO te disculpes.]"
                        )
                    else:
                        system_notes.append(
                            f"[System Note: An automated web search was performed using the current date and time, but the specific real-time data or live score is currently unavailable online. \nCRITICAL INSTRUCTION: State confidently that the exact result or details are not publicly available right now. If the event should have already concluded based on the current time ({current_time_str}), explicitly state that it has concluded but results aren't published yet. DO NOT offer to check again or search for more information. DO NOT hallucinate teams, scores, or facts. Do NOT apologize.]"
                        )
                else:
                    if is_spanish:
                        system_notes.append(
                            f"[Nota del Sistema: Resultados de la búsqueda web en tiempo real para la consulta del usuario:\n{search_results}\n\nINSTRUCCIÓN CRÍTICA: Responde al usuario directamente utilizando los hechos anteriores. Responde enteramente en ESPAÑOL. NO alucines ningún hecho que no esté presente en los resultados de la búsqueda. NO ofrezcas verificar o buscar más información, ya que la búsqueda ya se realizó. NO uses frases como 'no tengo acceso en vivo', 'no puedo navegar por la web', 'según los resultados de búsqueda' o 'a partir de mi última actualización'. Presenta los facts con confianza como si fueran tu propio conocimiento.]"
                        )
                    else:
                        system_notes.append(
                            f"[System Note: Real-time web search results for the user's query:\n{search_results}\n\nCRITICAL INSTRUCTION: Answer the user directly using the facts above. DO NOT hallucinate any facts not present in the search results. DO NOT offer to check or search for more information, as the search was already performed. DO NOT use phrases like 'I don't have live access', 'I cannot browse the web', 'Based on the search results', or 'As of my last update'. Present the facts confidently as your own knowledge.]"
                        )

        target_lang, lang_name = append_mandatory_reply_language(
            system_notes, force_language, user_input=user_query, history=history
        )

        if system_notes:
            sys_instr += "\n\n" + "\n\n".join(system_notes)

        messages: List[Dict[str, Any]] = []

        if history:
            for msg in history:
                role = "assistant" if msg.get("role") == "assistant" else "user"
                content = msg.get("content", "")
                if not content:
                    content = " "
                messages.append({"role": role, "content": content})

        scraped_content = ""
        if scraped_urls and len(user_input) > len(user_query):
            scraped_content = user_input[len(user_query):].strip()

        use_local_ocr = os.getenv("USE_LOCAL_OCR", "false").lower() == "true"

        # Build the multimodal content array
        content_array: List[Dict[str, Any]] = []
        file_contexts: List[str] = []

        for f in (files or []):
            name = f.get("name", "unnamed_file")
            mime = f.get("mime_type", "")
            data_bytes = f.get("bytes")

            # Safely resolve file bytes: memory -> base64 -> disk path
            if data_bytes is None:
                if "base64" in f:
                    try:
                        data_bytes = base64.b64decode(f["base64"])
                    except Exception as e:
                        logger.error(f"Error decoding base64 for file {name}: {e}")
                        continue
                else:
                    # Attempt to reload from disk using saved path
                    disk_path = f.get("path", "")
                    if disk_path and os.path.exists(disk_path):
                        try:
                            with open(disk_path, "rb") as fp:
                                data_bytes = fp.read()
                        except Exception as load_err:
                            logger.warning(
                                f"File '{name}' could not be reloaded from disk: {load_err}. Skipping processing."
                            )
                            continue
                    else:
                        logger.warning(f"File '{name}' is missing raw bytes and base64. Skipping processing.")
                        continue

            if data_bytes:
                try:
                    if mime.startswith("image/"):
                        if use_local_ocr:
                            logger.info(f"Extracting OCR text from direct image: {name}")
                            ocr_text = self._extract_text_from_image_via_ocr(data_bytes)
                            file_contexts.append(
                                f"[SYSTEM NOTE: OCR text extracted from screenshot '{name}']:\n\n{ocr_text}"
                            )
                        else:
                            clean_bytes, valid_media_type = self._normalize_anthropic_image(data_bytes, mime)
                            b64 = base64.b64encode(clean_bytes).decode("utf-8")
                            content_array.append(
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": valid_media_type,
                                        "data": b64,
                                    },
                                }
                            )
                    elif mime == "application/pdf":
                        # Check if PDF text is large to decide between native PDF or text extraction retrieval
                        reader = None
                        if pypdf is not None:
                            try:
                                reader = pypdf.PdfReader(io.BytesIO(data_bytes))
                            except Exception:
                                pass
                        if reader is None and PyPDF2 is not None:
                            try:
                                reader = PyPDF2.PdfReader(io.BytesIO(data_bytes))
                            except Exception:
                                pass

                        if reader and (
                            len(reader.pages) > pdf_native_max_pages()
                            or not should_send_native_pdf(data_bytes)
                        ):
                            text = self._extract_text_from_pdf(data_bytes, user_query=user_query)
                            file_contexts.append(
                                f"[SYSTEM NOTE: The user uploaded a large PDF document '{name}'. Its most relevant text has been automatically extracted for you below. DO NOT refuse to analyze it. DO NOT say you cannot read PDFs. Analyze the following text directly:]\n\n{text}"
                            )
                        else:
                            # Small PDF: send natively
                            b64 = base64.b64encode(data_bytes).decode("utf-8")
                            content_array.append(
                                {
                                    "type": "document",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "application/pdf",
                                        "data": b64,
                                    },
                                }
                            )

                        # Extract and append embedded images (e.g. screenshots)
                        pdf_images = self._extract_images_from_pdf(data_bytes)
                        if use_local_ocr:
                            for img in pdf_images:
                                logger.info(f"Extracting OCR text from pdf image: {img['name']}")
                                ocr_text = self._extract_text_from_image_via_ocr(img["bytes"])
                                file_contexts.append(
                                    f"[SYSTEM NOTE: OCR text extracted from screenshot '{img['name']}' inside PDF]:\n\n{ocr_text}"
                                )
                        else:
                            for img in pdf_images:
                                clean_bytes, valid_media_type = self._normalize_anthropic_image(img["bytes"], img.get("mime_type", "image/png"))
                                b64_img = base64.b64encode(clean_bytes).decode("utf-8")
                                content_array.append(
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": valid_media_type,
                                            "data": b64_img,
                                        },
                                    }
                                )
                    elif (
                        mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        or f.get("name", "").lower().endswith(".docx")
                    ):
                        # Fallback: extract text and append
                        text = self._extract_text_from_docx(data_bytes)
                        file_contexts.append(
                            f"[SYSTEM NOTE: The user uploaded a Word document '{name}'. Its text has been automatically extracted for you below. DO NOT refuse to analyze it. DO NOT say you cannot read documents. Analyze the following text directly:]\n\n{text}"
                        )

                        # Extract and append embedded images (e.g. screenshots)
                        docx_images = self._extract_images_from_docx(data_bytes)
                        if use_local_ocr:
                            for img in docx_images:
                                logger.info(f"Extracting OCR text from docx image: {img['name']}")
                                ocr_text = self._extract_text_from_image_via_ocr(img["bytes"])
                                file_contexts.append(
                                    f"[SYSTEM NOTE: OCR text extracted from screenshot '{img['name']}' inside Word document]:\n\n{ocr_text}"
                                )
                        else:
                            for img in docx_images:
                                clean_bytes, valid_media_type = self._normalize_anthropic_image(img["bytes"], img.get("mime_type", "image/png"))
                                b64_img = base64.b64encode(clean_bytes).decode("utf-8")
                                content_array.append(
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": valid_media_type,
                                            "data": b64_img,
                                        },
                                    }
                                )
                    elif (
                        mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        or f.get("name", "").lower().endswith(".xlsx")
                    ):
                        text = self._extract_text_from_xlsx(data_bytes)
                        file_contexts.append(
                            f"[SYSTEM NOTE: The user uploaded an Excel spreadsheet '{name}'. Its text has been automatically extracted for you below. DO NOT refuse to analyze it. DO NOT say you cannot read spreadsheets. Analyze the following text directly:]\n\n{text}"
                        )
                    elif (
                        mime == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                        or f.get("name", "").lower().endswith(".pptx")
                    ):
                        text = self._extract_text_from_pptx(data_bytes)
                        file_contexts.append(
                            f"[SYSTEM NOTE: The user uploaded a PowerPoint presentation '{name}'. Its text has been automatically extracted for you below. DO NOT refuse to analyze it. DO NOT say you cannot read PowerPoints. Analyze the following text directly:]\n\n{text}"
                        )
                    elif self._is_text_or_code_file(mime, name):
                        text = self._try_decode_as_text(data_bytes, mime, name)
                        if text is not None:
                            file_contexts.append(f"[Content of {name}]:\n{text}")
                        else:
                            file_contexts.append(
                                f"[System Note: The user attached a file named '{name}'. However, this file format ({mime}) is not natively supported by this AI model yet. Please politely inform the user that you cannot analyze this specific file type.]"
                            )
                    elif mime.startswith("audio/"):
                        # Audio fallback transcription using BaseChat transcribe_audio
                        spoken_words, err = self.transcribe_audio(data_bytes, mime_type=mime)
                        if err:
                            raise ValueError(err)

                        # Extract audio metadata defensively
                        metadata_lines = []
                        tmp_path = None
                        try:
                            suffix = ".mp3" if "mp3" in mime or "mpeg" in mime else ".wav"
                            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                                tmp.write(data_bytes)
                                tmp_path = tmp.name

                            audio_meta = MutagenFile(tmp_path, easy=True)
                            if audio_meta:
                                if audio_meta.get("title"):
                                    metadata_lines.append(f"Title: {audio_meta['title'][0]}")
                                if audio_meta.get("artist"):
                                    metadata_lines.append(f"Artist: {audio_meta['artist'][0]}")
                                if audio_meta.get("album"):
                                    metadata_lines.append(f"Album: {audio_meta['album'][0]}")
                                if audio_meta.get("genre"):
                                    metadata_lines.append(f"Genre: {audio_meta['genre'][0]}")
                                if audio_meta.get("date"):
                                    metadata_lines.append(f"Year: {audio_meta['date'][0]}")
                                if hasattr(audio_meta.info, "length"):
                                    metadata_lines.append(
                                        f"Duration: {int(audio_meta.info.length // 60)}m {int(audio_meta.info.length % 60)}s"
                                    )
                                if hasattr(audio_meta.info, "bitrate"):
                                    metadata_lines.append(
                                        f"Bitrate: {getattr(audio_meta.info, 'bitrate', 0) // 1000} kbps"
                                    )
                                if hasattr(audio_meta.info, "sample_rate"):
                                    metadata_lines.append(
                                        f"Sample Rate: {getattr(audio_meta.info, 'sample_rate', 'N/A')} Hz"
                                    )
                                if hasattr(audio_meta.info, "channels"):
                                    metadata_lines.append(
                                        f"Channels: {getattr(audio_meta.info, 'channels', 'N/A')}"
                                    )
                        except Exception as meta_err:
                            logger.warning(f"Metadata extraction failed: {meta_err}")
                        finally:
                            if tmp_path and os.path.exists(tmp_path):
                                try:
                                    os.remove(tmp_path)
                                except Exception:
                                    pass

                        metadata_block = (
                            "\n".join(metadata_lines) if metadata_lines else "No metadata available."
                        )
                        file_contexts.append(
                            f'<audio_recording name="{name}">\n'
                            f"[Audio Metadata:]\n{metadata_block}\n\n"
                            f"[Lyrics / Spoken Words:]\n{spoken_words}\n"
                            f"</audio_recording>"
                        )
                        logger.info(f"Processed audio '{name}' using audio transcription.")
                    elif mime.startswith("video/"):
                        logger.info(f"Describing video for Anthropic: {f.get('name', 'video')}")
                        video_description = self.describe_video(data_bytes, mime, user_query)
                        file_contexts.append(
                            f"[SYSTEM NOTE: The user uploaded a video file named '{f.get('name', 'video.mp4')}'. The system generated a detailed scene-by-scene description of its visuals and dialogue for you below. Please analyze this text description directly to address the user's query:]\n\n{video_description}"
                        )
                    else:
                        file_contexts.append(
                            f"[System Note: The user attached a file named '{f.get('name', 'unknown')}'. However, this file format ({mime}) is not natively supported by this AI model yet. Please politely inform the user that you cannot analyze this specific file type.]"
                        )
                except Exception as file_err:
                    logger.error(f"Error processing file {name}: {file_err}", exc_info=True)
                    file_contexts.append(f"[Error processing attachment {name}: {file_err}]")

        # Assemble parts putting user query last
        parts: List[str] = []
        if scraped_content:
            parts.append(scraped_content)
        if file_contexts:
            parts.append("\n\n".join(file_contexts))

        if parts:
            parts.append(wrap_user_query_for_language(user_query, target_lang, lang_name))
            user_input = "\n\n".join(parts)
        else:
            user_input = user_query

        if user_input:
            content_array.append({"type": "text", "text": user_input})

        messages.append({"role": "user", "content": content_array})

        try:
            temp = temperature if temperature is not None else self.temperature
            p_val = top_p if top_p is not None else self.top_p
            tokens_val = max_tokens if max_tokens is not None else self.max_tokens

            kwargs: Dict[str, Any] = {
                "model": self.model_version,
                "system": sys_instr,
                "messages": self._clean_messages_for_alternation(messages),
                "max_tokens": tokens_val,
            }

            # Remove temperature and top_p for Claude models version 4 and higher, which deprecate them.
            if self._model_supports_temperature(self.model_version):
                kwargs["temperature"] = temp
                kwargs["top_p"] = p_val

            logger.info(f"Sending to Anthropic with files, kwargs keys: {list(kwargs.keys())}")
            fibonacci_wait = wait_chain(*[wait_fixed(s) for s in ANTHROPIC_RETRY_SEQUENCE])
            response = None
            for attempt in Retrying(
                stop=stop_after_attempt(len(ANTHROPIC_RETRY_SEQUENCE)),
                wait=fibonacci_wait,
                reraise=True,
            ):
                with attempt:
                    response = self.anthropic_client.messages.create(**kwargs)

            text_parts = []
            if response and getattr(response, "content", None):
                for block in response.content:
                    if hasattr(block, "text"):
                        text_parts.append(block.text)
            reply = "".join(text_parts) if text_parts else None
            if not reply:
                reply = f"Error: {self._handle_empty_response(response)}."
            usage = getattr(response, "usage", None) if response else None
            token_info = {
                "prompt_tokens": getattr(usage, "input_tokens", 0) if usage else 0,
                "candidates_tokens": getattr(usage, "output_tokens", 0) if usage else 0,
                "total_tokens": (
                    getattr(usage, "input_tokens", 0) + getattr(usage, "output_tokens", 0)
                )
                if usage
                else 0,
                "thinking_tokens": 0,
            }
            return reply, self._flush_aux_tokens(token_info), user_input
        except Exception as e:
            logger.error(f"Anthropic multimodal error: {e}", exc_info=True)
            return f"Error: {str(e)}", None, None

    def _clean_messages_for_alternation(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Helper to ensure Anthropic messages alternate roles properly (user/assistant) and omit system roles."""
        other_messages = [m for m in messages if m.get("role") != "system"]

        cleaned: List[Dict[str, Any]] = []
        expected_role = "user"

        for msg in other_messages:
            role = msg.get("role")
            content = msg.get("content", "")
            if not content:
                continue

            if role == expected_role:
                cleaned.append({"role": role, "content": content})
                expected_role = "assistant" if role == "user" else "user"
            else:
                if not cleaned:
                    if role == "assistant":
                        continue
                    cleaned.append({"role": role, "content": content})
                    expected_role = "assistant" if role == "user" else "user"
                else:
                    last_content = cleaned[-1].get("content")
                    if isinstance(last_content, list) or isinstance(content, list):
                        c1 = (
                            last_content
                            if isinstance(last_content, list)
                            else [{"type": "text", "text": str(last_content)}]
                        )
                        c2 = (
                            content
                            if isinstance(content, list)
                            else [{"type": "text", "text": str(content)}]
                        )
                        cleaned[-1]["content"] = c1 + c2
                    else:
                        cleaned[-1]["content"] = f"{last_content}\n\n{content}"

        # Sanitize all image blocks across all messages to guarantee valid Anthropic media types
        valid_anthropic_mimes = {"image/jpeg", "image/png", "image/gif", "image/webp"}
        final_cleaned = []
        for msg in cleaned:
            c = msg.get("content")

            if isinstance(c, str):
                # Ensure plain string content is non-empty
                if not c.strip():
                    c = "…"  # placeholder to satisfy Anthropic's non-whitespace requirement
                msg = {**msg, "content": c}
                final_cleaned.append(msg)
                continue

            if isinstance(c, list):
                sanitized = []
                for block in c:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type")
                    if btype == "text":
                        text_val = block.get("text", "")
                        if not isinstance(text_val, str) or not text_val.strip():
                            continue  # drop empty/whitespace text blocks
                        sanitized.append(block)
                    elif btype == "image":
                        source = block.get("source")
                        if isinstance(source, dict):
                            media_type = (source.get("media_type") or "").lower().split(";")[0].strip()
                            if media_type in ("image/jpg", "image/pjpeg", "image/jfif"):
                                source["media_type"] = "image/jpeg"
                                media_type = "image/jpeg"
                            elif media_type not in valid_anthropic_mimes:
                                media_type = "image/jpeg" if ("jpg" in media_type or "jpeg" in media_type) else "image/png"
                                source["media_type"] = media_type
                            # History may retain oversized images from prior turns (Anthropic 10 MB cap).
                            if source.get("type") == "base64" and isinstance(source.get("data"), str):
                                try:
                                    raw = base64.b64decode(source["data"])
                                except Exception:
                                    raw = b""
                                if raw and len(raw) > AnthropicChat._anthropic_max_image_bytes():
                                    fitted, fitted_mime = AnthropicChat._fit_anthropic_image_bytes(raw, media_type or "image/jpeg")
                                    source["data"] = base64.b64encode(fitted).decode("utf-8")
                                    source["media_type"] = fitted_mime
                        sanitized.append(block)
                    else:
                        sanitized.append(block)

                if not sanitized:
                    # Anthropic requires at least one non-empty block; insert a placeholder
                    sanitized = [{"type": "text", "text": "…"}]
                final_cleaned.append({**msg, "content": sanitized})
            else:
                final_cleaned.append(msg)

        return final_cleaned
