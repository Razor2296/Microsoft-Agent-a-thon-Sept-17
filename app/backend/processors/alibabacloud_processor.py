"""
Alibaba Cloud Chat Class - Handles all interactions with the Alibaba Cloud DashScope API.
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
from typing import Any, Dict, List, Optional, Tuple, cast

from google import genai
from google.genai import types as genai_types
from mutagen import File as MutagenFile
from openai import OpenAI
from openai.types.chat import ChatCompletion
from tenacity import Retrying, stop_after_attempt, wait_chain, wait_fixed

from backend.core.schemas import TokenInfo
from backend.integrations.document_request import CRITICAL_DOCUMENT_ANALYSIS_RULE
from backend.processors.base_processor import (
    ALIBABACLOUD_API_KEY,
    ALIBABACLOUD_BASE_URL,
    ALIBABACLOUD_MAX_TOKENS,
    ALIBABACLOUD_MODEL_VERSION,
    ALIBABACLOUD_PROFILE_PICTURE_PATH,
    ALIBABACLOUD_RETRY_SEQUENCE,
    ALIBABACLOUD_TEMPERATURE,
    ALIBABACLOUD_TOP_P,
    GEMINI_API_KEY,
    GEMINI_SEARCH_MODEL,
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
    BaseChat,
    detect_user_conversation_language,
    get_assistant_logger,
    get_current_date_and_time_strings,
    get_user_country_code,
    resolve_lang_name,
    gemini_http_timeout_ms,
    llm_http_timeout_seconds,
)

# Logger for Alibaba Cloud
logger = get_assistant_logger("alibabacloud")

# System instruction for Alibaba Cloud
SYSTEM_INSTRUCTION_ALIBABACLOUD = textwrap.dedent("""\
    You are Alibaba Cloud's Qwen model, a highly capable, versatile, and thoughtful AI assistant developed by Alibaba Cloud.

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

    ## Voice Input Detection
    - If the user's message ends with the label "🎙️ *(Voice Recorded)*", it means they spoke via a microphone and the app transcribed their voice into text for you.
    - Therefore, if the user asks "can you hear me?", "are you listening?", etc., you MUST reply "Yes" (or something similar in their language) and engage naturally as if you are hearing them. Do NOT say "I am a text-based AI and cannot hear". You CAN hear them through the transcriptions.
    - Ensure your response is particularly concise, direct, and conversational (avoiding overly long lists, massive text tables, or complex formatting where possible), as it will be read aloud to the user using Text-to-Speech. Keep the response natural for listening. """)


class AlibabaCloudChat(BaseChat):
    """Alibaba Cloud DashScope API Client implementation inheriting from BaseChat."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_version: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        system_instruction: Optional[str] = None,
    ):
        super().__init__()
        try:
            self.model_version = (model_version or ALIBABACLOUD_MODEL_VERSION).strip()
            self.max_tokens = max_tokens if max_tokens is not None else ALIBABACLOUD_MAX_TOKENS
            self.temperature = temperature if temperature is not None else ALIBABACLOUD_TEMPERATURE
            self.top_p = top_p if top_p is not None else ALIBABACLOUD_TOP_P
            self.system_instruction_alibabacloud = textwrap.dedent(
                system_instruction or SYSTEM_INSTRUCTION_ALIBABACLOUD
            )

            self.alibabacloud_api_key = api_key or ALIBABACLOUD_API_KEY
            if not self.alibabacloud_api_key:
                raise ValueError(
                    "Alibaba Cloud API key not found. Please set ALIBABACLOUD_API_KEY in your .env file."
                )

            self.alibabacloud_base_url = base_url or ALIBABACLOUD_BASE_URL

            workspace_id = None
            if "maas.aliyuncs.com" in self.alibabacloud_base_url:
                parsed_url = urllib.parse.urlparse(self.alibabacloud_base_url)
                netloc = parsed_url.netloc
                if netloc:
                    parts = netloc.split(".")
                    if parts:
                        workspace_id = parts[0]
                        logger.info(f"Extracted Alibaba Cloud Workspace ID: {workspace_id}")

            # Using the standard OpenAI client pointing to Alibaba Cloud DashScope endpoint
            client_headers = {}
            if workspace_id:
                client_headers["X-DashScope-WorkSpace"] = workspace_id

            self.alibabacloud_client = OpenAI(
                api_key=self.alibabacloud_api_key,
                base_url=self.alibabacloud_base_url,
                timeout=llm_http_timeout_seconds(),
                default_headers=client_headers,
            )
            self.client = genai.Client(api_key=GEMINI_API_KEY, http_options={"timeout": gemini_http_timeout_ms()})
            self.google_search_enabled = True  # Enable automated search pre-pass

            logger.info(
                f"Alibaba Cloud client initialized with model {self.model_version} on {self.alibabacloud_base_url}"
            )
        except Exception as e:
            logger.error(f"Initialization error in AlibabaCloudChat: {e}", exc_info=True)
            raise ValueError(f"Failed to initialize AlibabaCloudChat: {e}")

    def _handle_empty_response(self, response: Any) -> str:
        """Helper to construct a descriptive error message when response content is empty or filtered."""
        if hasattr(response, "choices") and response.choices:
            choice = response.choices[0]
            finish_reason = getattr(choice, "finish_reason", None)
            if finish_reason == "content_filter":
                return "The response was blocked by Alibaba Cloud safety filters."
            return f"Response ended prematurely (reason: {finish_reason})."
        return "No choices returned from the API."

    def generate_response(
        self,
        user_input: str,
        history: Optional[List[Dict[str, Any]]] = None,
        force_language: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Tuple[str, Optional[TokenInfo]]:
        """Generate conversational response using Alibaba Cloud DashScope API."""
        reply: Optional[str] = None
        token_info: Optional[Dict[str, Any]] = None

        if not self.alibabacloud_client:
            return "Error: Alibaba Cloud client not configured.", None

        current_date_str, current_time_str, current_year_str = get_current_date_and_time_strings()

        target_lang, lang_name = detect_user_conversation_language(user_input, history, force_language)
        is_spanish = target_lang.lower().startswith("es")
        sys_instr = ""
        if is_spanish:
            sys_instr += "[REQUISITO CRÍTICO DE IDIOMA] ¡Debes responder ÚNICAMENTE en Español! Toda tu respuesta debe escribirse en Español. Ignora el idioma del sistema del equipo y cualquier resultado de búsqueda o contenido web raspado en otros idiomas.\n\n"
        else:
            sys_instr += f"[CRITICAL LANGUAGE REQUIREMENT] You MUST reply ONLY in {lang_name}! Your entire response must be written in {lang_name}. Ignore computer system language settings and any web search results or scraped content in other languages.\n\n"

        sys_instr += self.system_instruction_alibabacloud
        sys_instr += f"\n\n[SYSTEM INFO] Today's date is {current_date_str}. The current time is {current_time_str}."
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

        sys_instr += (
            f"\n\n[CRITICAL UX RULE] NEVER apologize, NEVER claim you do not have internet access, and NEVER state that your knowledge is cut off in a certain year. "
            f"If you do not have recent facts, use the information provided to you and your baseline knowledge to provide an answer. "
            f"CRITICAL: DO NOT HALLUCINATE past/current facts, live scores, specific opponents, or real-time statuses if they are not provided to you. If the exact result or historical/current data of a concluded event is missing, state confidently that the specific details are currently unavailable, rather than making them up. "
            f"Do not break character by mentioning your training limitations or your inability to browse the web."
        )
        sys_instr += (
            f"\n\n[CRITICAL GROUNDING RULE] Since the current year is {current_year_str}, you MUST treat any events, tournaments, or matches from 2024 and 2025 as historical and completed. "
            f"Never discuss them as future, current, or upcoming. You MUST rely on the scraped web contents provided to answer questions about current events/sports/news (specifically targeting {current_year_str}) rather than relying on your internal memory, which may be outdated or limited. "
            f"Double check that any news or sports events you present are actually happening in {current_year_str}, and filter out any outdated pre-training knowledge from 2024 or 2025."
        )

        user_query = user_input or ""
        processed_input, scraped_urls = self._process_urls_in_input(user_query, force_language=force_language)

        scraped_content = ""
        if scraped_urls and len(processed_input) > len(user_query):
            scraped_content = processed_input[len(user_query):].strip()

        # Automated Search for Alibaba Cloud
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
                            "[Nota del Sistema: Se realizó una búsqueda web automatizada, pero la información específica en tiempo real no está disponible en línea actualmente. Indica con confianza que los detalles exactos no están disponibles públicamente en este momento. NO alucines. NO te disculpes.]"
                        )
                    else:
                        system_notes.append(
                            "[System Note: An automated web search was performed, but the specific real-time data is currently unavailable online. State confidently that the exact details are not publicly available right now. DO NOT hallucinate. Do NOT apologize.]"
                        )
                else:
                    if is_spanish:
                        system_notes.append(
                            f"[Nota del Sistema: Resultados de la búsqueda web en tiempo real para la consulta del usuario:\n{search_results}\n\nINSTRUCCIÓN CRÍTICA: Responde al usuario directamente utilizando los hechos anteriores. Responde enteramente en ESPAÑOL. NO alucines. Presenta los hechos con confianza.]"
                        )
                    else:
                        system_notes.append(
                            f"[System Note: Real-time web search results for the user's query:\n{search_results}\n\nCRITICAL INSTRUCTION: Answer the user directly using the facts above. DO NOT hallucinate. Present the facts confidently.]"
                        )

        if force_language:
            lang_name = resolve_lang_name(force_language)
            is_spanish = force_language.startswith("es")
            if is_spanish:
                system_notes.append(
                    "[Nota del Sistema: El usuario acaba de hablar/escribir en Español. Responde enteramente en Español a menos que el usuario solicite explícitamente cambiar de idioma.]"
                )
            else:
                system_notes.append(
                    f"[System Note: The user just spoke/wrote in {lang_name}. Reply in {lang_name} UNLESS the user explicitly requests to switch to a different language.]"
                )

        if system_notes:
            sys_instr += "\n\n" + "\n\n".join(system_notes)

        messages: List[Dict[str, Any]] = [{"role": "system", "content": sys_instr}]

        # Build dialog history
        if history:
            for item in history:
                role = item.get("role")
                content = item.get("content")
                if role in ["user", "assistant"]:
                    if not content:
                        content = " "
                    messages.append({"role": role, "content": content})

        parts: List[str] = []
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
            user_payload = "\n\n".join(parts)
        else:
            user_payload = user_query

        messages.append({"role": "user", "content": user_payload})
        logger.info(f"Messages count: {len(messages)}")

        try:
            kwargs: dict[str, Any] = {
                "model": self.model_version,
                "messages": self._clean_messages_for_alternation(messages),
            }
            temp = temperature if temperature is not None else self.temperature
            p_val = top_p if top_p is not None else self.top_p
            tokens_val = max_tokens if max_tokens is not None else self.max_tokens

            kwargs["temperature"] = temp
            kwargs["top_p"] = p_val
            kwargs["max_tokens"] = tokens_val

            logger.info(f"Sending to Alibaba Cloud with kwargs keys: {list(kwargs.keys())}")
            fibonacci_wait = wait_chain(*[wait_fixed(s) for s in ALIBABACLOUD_RETRY_SEQUENCE])
            response: Optional[ChatCompletion] = None
            for attempt in Retrying(
                stop=stop_after_attempt(len(ALIBABACLOUD_RETRY_SEQUENCE)),
                wait=fibonacci_wait,
                reraise=True,
            ):
                with attempt:
                    raw_resp = self.alibabacloud_client.chat.completions.create(
                        stream=False, **kwargs
                    )
                    if isinstance(raw_resp, ChatCompletion):
                        response = raw_resp
                    elif hasattr(raw_resp, "choices"):
                        response = cast(ChatCompletion, raw_resp)

            if response and response.choices:
                reply = response.choices[0].message.content
                if not reply:
                    reply = f"Error: {self._handle_empty_response(response)}."
            else:
                reply = "Error: Empty response returned from Alibaba Cloud."

            usage = getattr(response, "usage", None)
            token_info = {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
                "candidates_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
                "total_tokens": getattr(usage, "total_tokens", 0) if usage else 0,
                "thinking_tokens": 0,
            }
            return reply, self._flush_aux_tokens(token_info)
        except Exception as e:
            logger.error(f"Alibaba Cloud error: {e}", exc_info=True)
            return f"Error: {str(e)}", None

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
        """Generate response handling multimodal file attachments."""
        reply: Optional[str] = None
        token_info: Optional[Dict[str, Any]] = None

        if not self.alibabacloud_client:
            return "Error: Alibaba Cloud client not configured.", None

        current_date_str, current_time_str, current_year_str = get_current_date_and_time_strings()

        target_lang, lang_name = detect_user_conversation_language(user_input, history, force_language)
        is_spanish = target_lang.lower().startswith("es")
        sys_instr = ""
        if is_spanish:
            sys_instr += "[REQUISITO CRÍTICO DE IDIOMA] ¡Debes responder ÚNICAMENTE en Español! Toda tu respuesta debe escribirse en Español. Ignora el idioma del sistema del equipo y cualquier resultado de búsqueda o contenido web raspado en otros idiomas.\n\n"
        else:
            sys_instr += f"[CRITICAL LANGUAGE REQUIREMENT] You MUST reply ONLY in {lang_name}! Your entire response must be written in {lang_name}. Ignore computer system language settings and any web search results or scraped content in other languages.\n\n"

        sys_instr += self.system_instruction_alibabacloud
        sys_instr += f"\n\n[SYSTEM INFO] Today's date is {current_date_str}. The current time is {current_time_str}."
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

        sys_instr += (
            f"\n\n[CRITICAL UX RULE] NEVER apologize, NEVER claim you do not have internet access, and NEVER state that your knowledge is cut off in a certain year. "
            f"If you do not have recent facts, use the information provided to you and your baseline knowledge to provide an answer. "
            f"CRITICAL: DO NOT HALLUCINATE past/current facts, live scores, specific opponents, or real-time statuses if they are not provided to you. If the exact result or historical/current data of a concluded event is missing, state confidently that the specific details are currently unavailable, rather than making them up. "
            f"Do not break character by mentioning your training limitations or your inability to browse the web."
        )
        sys_instr += (
            f"\n\n[CRITICAL GROUNDING RULE] Since the current year is {current_year_str}, you MUST treat any events, tournaments, or matches from 2024 and 2025 as historical and completed. "
            f"Never discuss them as future, current, or upcoming. You MUST rely on the scraped web contents provided to answer questions about current events/sports/news (specifically targeting {current_year_str}) rather than relying on your internal memory, which may be outdated or limited. "
            f"Double check that any news or sports events you present are actually happening in {current_year_str}, and filter out any outdated pre-training knowledge from 2024 or 2025."
        )
        sys_instr += CRITICAL_DOCUMENT_ANALYSIS_RULE

        user_query = user_input or ""
        user_input, scraped_urls = self._process_urls_in_input(user_input, force_language=force_language)

        scraped_content = ""
        if scraped_urls and len(user_input) > len(user_query):
            scraped_content = user_input[len(user_query):].strip()

        # Automated Search for Alibaba Cloud
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
                            "[Nota del Sistema: Se realizó una búsqueda web automatizada, pero la información en tiempo real no está disponible en línea actualmente. Indica que los detalles no están disponibles. NO alucines.]"
                        )
                    else:
                        system_notes.append(
                            "[System Note: An automated web search was performed, but the real-time data is currently unavailable online. State that the details are not available. DO NOT hallucinate.]"
                        )
                else:
                    if is_spanish:
                        system_notes.append(
                            f"[Nota del Sistema: Resultados de la búsqueda web en tiempo real:\n{search_results}\n\nINSTRUCCIÓN CRÍTICA: Responde al usuario directamente utilizando los hechos anteriores. Responde enteramente en ESPAÑOL. NO alucines.]"
                        )
                    else:
                        system_notes.append(
                            f"[System Note: Real-time web search results:\n{search_results}\n\nCRITICAL INSTRUCTION: Answer the user directly using the facts above. DO NOT hallucinate.]"
                        )

        if force_language:
            lang_name = resolve_lang_name(force_language)
            is_spanish = force_language.startswith("es")
            if is_spanish:
                system_notes.append(
                    "[Nota del Sistema: El usuario acaba de hablar/escribir en Español. Responde enteramente en Español a menos que el usuario solicite explícitamente cambiar de idioma.]"
                )
            else:
                system_notes.append(
                    f"[System Note: The user just spoke/wrote in {lang_name}. Reply in {lang_name} UNLESS the user explicitly requests to switch to a different language.]"
                )

        if system_notes:
            sys_instr += "\n\n" + "\n\n".join(system_notes)

        # Parse inline file contents
        content_array: List[Dict[str, Any]] = []
        file_contexts: List[str] = []
        is_vl_model = "vl" in self.model_version.lower()

        for file_item in (files or []):
            file_name = file_item.get("name", "Unknown File")
            mime_type = file_item.get("mime_type", "")
            data_bytes = file_item.get("bytes")

            # Safely resolve file bytes: memory → base64 → disk path
            if data_bytes is None:
                if "base64" in file_item:
                    try:
                        data_bytes = base64.b64decode(file_item["base64"])
                    except Exception as b64_err:
                        logger.error(f"Error decoding base64 for file {file_name}: {b64_err}")
                        continue
                else:
                    disk_path = file_item.get("path", "")
                    if disk_path and os.path.exists(disk_path):
                        try:
                            with open(disk_path, "rb") as fp:
                                data_bytes = fp.read()
                        except Exception as load_err:
                            logger.warning(
                                f"File '{file_name}' could not be reloaded from disk: {load_err}. Skipping processing."
                            )
                            continue
                    else:
                        logger.warning(
                            f"File '{file_name}' is missing raw bytes and base64. Skipping processing."
                        )
                        continue

            if data_bytes:
                try:
                    if mime_type.startswith("image/"):
                        clean_bytes, valid_mime = self.normalize_image_media_type(mime_type, data_bytes)
                        if is_vl_model:
                            # Qwen-VL native visual payload mapping
                            b64 = base64.b64encode(clean_bytes or data_bytes).decode("utf-8")
                            content_array.append(
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:{valid_mime};base64,{b64}"},
                                }
                            )
                            logger.info(f"Processed image '{file_name}' natively using Qwen-VL payload.")
                        else:
                            # Fallback description using Gemini Flash
                            scaled_bytes = self._resize_image_data(clean_bytes or data_bytes, max_dim=1024)
                            image_part = genai_types.Part.from_bytes(
                                data=scaled_bytes, mime_type=valid_mime
                            )
                            prompt_part = genai_types.Part.from_text(
                                text="Analyze this image thoroughly. Write a detailed, natural, first-person narrative description of everything you see: objects, people, colors, text on screen, layout, mood, and any other relevant details. Do NOT use the words 'transcription', 'transcript', or 'description'. Write it as flowing prose as if you are directly observing it."
                            )

                            vision_resp = self.client.models.generate_content(
                                model=GEMINI_SEARCH_MODEL,
                                contents=cast(Any, [image_part, prompt_part]),
                            )
                            desc = (
                                vision_resp.text
                                if vision_resp and vision_resp.text
                                else "No description generated."
                            )
                            desc = re.sub(r"\b[Tt]ranscri(?:pt|ption|bed|bing)\b", "content", desc)
                            file_contexts.append(
                                f'<image_file name="{file_name}">\n[What I can see in this image:]\n{desc}\n</image_file>'
                            )
                            logger.info(
                                f"Processed image '{file_name}' using Gemini fallback description."
                            )

                    elif mime_type.startswith("video/"):
                        # Video fallback description using Gemini Flash
                        video_part = genai_types.Part.from_bytes(data=data_bytes, mime_type=mime_type)
                        prompt_part = genai_types.Part.from_text(
                            text="Analyze this video thoroughly and write a detailed, natural narrative of everything that happens. Include: what is shown visually scene by scene, all spoken words and dialogue (written as direct quotes), any text visible on screen, and the overall context or topic. Do NOT use the words 'transcription' or 'transcript' anywhere. Write in flowing prose as if you are directly watching and listening to the video."
                        )
                        vision_resp = self.client.models.generate_content(
                            model=GEMINI_SEARCH_MODEL,
                            contents=cast(Any, [video_part, prompt_part]),
                        )
                        desc = (
                            vision_resp.text
                            if vision_resp and vision_resp.text
                            else "No description generated."
                        )
                        desc = re.sub(r"\b[Tt]ranscri(?:pt|ption|bed|bing)\b", "spoken content", desc)
                        file_contexts.append(
                            f'<video_file name="{file_name}">\n[What I can see and hear in this video:]\n{desc}\n</video_file>'
                        )
                        logger.info(
                            f"Processed video '{file_name}' using Gemini description fallback."
                        )

                    elif mime_type.startswith("audio/"):
                        # Audio fallback transcription using BaseChat
                        spoken_words, err = self.transcribe_audio(data_bytes, mime_type=mime_type)
                        if err:
                            raise ValueError(err)

                        # Extract audio metadata defensively
                        metadata_lines = []
                        tmp_path = None
                        try:
                            suffix = ".mp3" if "mp3" in mime_type or "mpeg" in mime_type else ".wav"
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
                            f'<audio_recording name="{file_name}">\n'
                            f"[Audio Metadata:]\n{metadata_block}\n\n"
                            f"[Lyrics / Spoken Words:]\n{spoken_words}\n"
                            f"</audio_recording>"
                        )
                        logger.info(
                            f"Processed audio '{file_name}' using Gemini transcription fallback."
                        )

                    elif (
                        mime_type
                        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        or file_name.lower().endswith(".docx")
                    ):
                        text = self._extract_text_from_docx(data_bytes)
                        file_contexts.append(
                            f'<file name="{file_name}" type="word_document">\n{text}\n</file>'
                        )

                    elif (
                        mime_type
                        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        or file_name.lower().endswith(".xlsx")
                    ):
                        text = self._extract_text_from_xlsx(data_bytes)
                        file_contexts.append(
                            f'<file name="{file_name}" type="excel_spreadsheet">\n{text}\n</file>'
                        )

                    elif (
                        mime_type
                        == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                        or file_name.lower().endswith(".pptx")
                    ):
                        text = self._extract_text_from_pptx(data_bytes)
                        file_contexts.append(
                            f'<file name="{file_name}" type="powerpoint_presentation">\n{text}\n</file>'
                        )

                    elif mime_type == "application/pdf":
                        text = self._extract_text_from_pdf(data_bytes, user_query=user_query)
                        file_contexts.append(
                            f'<file name="{file_name}" type="pdf_document">\n{text}\n</file>'
                        )

                    elif self._is_text_or_code_file(mime_type, file_name):
                        text = self._try_decode_as_text(data_bytes, mime_type, file_name)
                        if text is not None:
                            file_contexts.append(
                                f'<file name="{file_name}" type="text_file">\n{text}\n</file>'
                            )
                        else:
                            file_contexts.append(
                                f"[System Note: The user attached a file named '{file_name}'. However, this file format ({mime_type}) is not natively supported. Please politely inform the user.]"
                            )

                    else:
                        file_contexts.append(
                            f"[System Note: The user attached a file named '{file_name}'. However, this file format ({mime_type}) is not natively supported. Please politely inform the user.]"
                        )
                except Exception as file_err:
                    logger.error(f"Error processing file {file_name}: {file_err}", exc_info=True)
                    file_contexts.append(f"[Error processing attachment {file_name}: {file_err}]")

        messages: List[Dict[str, Any]] = [{"role": "system", "content": sys_instr}]

        # Build history
        if history:
            for item in history:
                role = item.get("role")
                content = item.get("content")
                if role in ["user", "assistant"]:
                    if not content:
                        content = " "
                    messages.append({"role": role, "content": content})

        parts: List[str] = []
        if scraped_content:
            parts.append(scraped_content)
        if file_contexts:
            parts.append("\n\n".join(file_contexts))

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
            user_payload = "\n\n".join(parts)
        else:
            user_payload = user_query

        if is_vl_model and content_array:
            content_array.append({"type": "text", "text": user_payload})
            messages.append({"role": "user", "content": content_array})
        else:
            messages.append({"role": "user", "content": user_payload})

        logger.info(f"Messages with files count: {len(messages)}")

        try:
            kwargs: dict[str, Any] = {
                "model": self.model_version,
                "messages": self._clean_messages_for_alternation(messages),
            }
            temp = temperature if temperature is not None else self.temperature
            p_val = top_p if top_p is not None else self.top_p
            tokens_val = max_tokens if max_tokens is not None else self.max_tokens

            kwargs["temperature"] = temp
            kwargs["top_p"] = p_val
            kwargs["max_tokens"] = tokens_val

            logger.info(f"Sending to Alibaba Cloud with kwargs keys: {list(kwargs.keys())}")
            fibonacci_wait = wait_chain(*[wait_fixed(s) for s in ALIBABACLOUD_RETRY_SEQUENCE])
            response: Optional[ChatCompletion] = None
            for attempt in Retrying(
                stop=stop_after_attempt(len(ALIBABACLOUD_RETRY_SEQUENCE)),
                wait=fibonacci_wait,
                reraise=True,
            ):
                with attempt:
                    raw_resp = self.alibabacloud_client.chat.completions.create(
                        stream=False, **kwargs
                    )
                    if isinstance(raw_resp, ChatCompletion):
                        response = raw_resp
                    elif hasattr(raw_resp, "choices"):
                        response = cast(ChatCompletion, raw_resp)

            if response and response.choices:
                reply = response.choices[0].message.content
                if not reply:
                    reply = f"Error: {self._handle_empty_response(response)}."
            else:
                reply = "Error: Empty response returned from Alibaba Cloud."

            usage = getattr(response, "usage", None)
            token_info = {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
                "candidates_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
                "total_tokens": getattr(usage, "total_tokens", 0) if usage else 0,
                "thinking_tokens": 0,
            }
            return reply, self._flush_aux_tokens(token_info)
        except Exception as e:
            logger.error(f"Alibaba Cloud error: {e}", exc_info=True)
            return f"Error: {str(e)}", None

    def _clean_messages_for_alternation(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Helper to ensure messages alternate roles properly (e.g. system, user, assistant, user)."""
        cleaned: List[Dict[str, Any]] = []
        system_msgs = [m for m in messages if m.get("role") == "system"]
        other_msgs = [m for m in messages if m.get("role") != "system"]

        # Combine system messages
        if system_msgs:
            combined_system = "\n\n".join([str(m.get("content", "")) for m in system_msgs])
            cleaned.append({"role": "system", "content": combined_system})

        # Ensure role alternation for user/assistant
        expected_role = "user"
        for m in other_msgs:
            role = m.get("role")
            content = m.get("content")
            if role == expected_role:
                cleaned.append({"role": role, "content": content})
                expected_role = "assistant" if expected_role == "user" else "user"
            else:
                # Merge consecutive messages of the same role
                if cleaned and cleaned[-1].get("role") == role:
                    # Content can be a string or a list of parts (multimodal)
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
                else:
                    # Insert default message or skip if out of order
                    if role == "assistant" and expected_role == "user":
                        cleaned.append({"role": "user", "content": "..."})
                    cleaned.append({"role": role, "content": content})
                    expected_role = "user" if role == "assistant" else "assistant"

        # Sanitize content in all cleaned messages: strip empty text blocks, fix image_url MIME types
        final_cleaned = []
        for msg in cleaned:
            c = msg.get("content")
            if isinstance(c, str):
                if not c.strip():
                    c = "…"
                final_cleaned.append({**msg, "content": c})
                continue
            if isinstance(c, list):
                sanitized = []
                for block in c:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type")
                    if btype == "text":
                        if not (block.get("text") or "").strip():
                            continue  # drop empty text blocks
                        sanitized.append(block)
                    elif btype == "image_url":
                        img_info = block.get("image_url")
                        if isinstance(img_info, dict) and "url" in img_info:
                            url = img_info["url"]
                            if url.startswith("data:image/jpg;") or url.startswith("data:image/pjpeg;") or url.startswith("data:image/jfif;"):
                                img_info["url"] = "data:image/jpeg;" + url.split(";", 1)[1]
                        sanitized.append(block)
                    else:
                        sanitized.append(block)
                if not sanitized:
                    sanitized = [{"type": "text", "text": "…"}]
                final_cleaned.append({**msg, "content": sanitized})
            else:
                final_cleaned.append(msg)

        return final_cleaned
