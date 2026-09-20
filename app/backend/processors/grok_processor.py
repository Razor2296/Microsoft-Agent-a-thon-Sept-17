"""
Grok Chat Class - Handles all interactions with the xAI Grok API.
"""
from __future__ import annotations

from backend.processors.base_processor import (
    BaseChat,
    resolve_lang_name,
    detect_user_conversation_language,
    resolve_reply_language,
    get_current_date_and_time_strings,
    USER_NAME,
    USER_SYSTEM_LANGUAGE,
    USER_SYSTEM_TIMEZONE,
    USER_SYSTEM_DARK_MODE,
    USER_DESKTOP_PATH,
    USER_DOWNLOADS_PATH,
    USER_DOCUMENTS_PATH,
    USER_PICTURES_PATH,
    USER_PROFILE_PICTURE_PATH,
    USER_CLIPBOARD_TEXT,
    GROK_PROFILE_PICTURE_PATH,
    GROK_API_KEY,
    GROK_BASE_URL,
    GROK_MODEL_VERSION,
    GROK_MAX_TOKENS,
    GROK_TEMPERATURE,
    GROK_TOP_P,
    GROK_RETRY_SEQUENCE,
    GEMINI_API_KEY,
    GEMINI_SEARCH_MODEL,
    get_assistant_logger,
    get_user_country_code,
    gemini_http_timeout_ms,
    llm_http_timeout_seconds,
)
from backend.core.schemas import TokenInfo
from backend.integrations.document_request import CRITICAL_DOCUMENT_ANALYSIS_RULE
from google import genai
from openai import OpenAI
from tenacity import Retrying, stop_after_attempt, wait_chain, wait_fixed
from typing import Optional, List, Dict, Any, Tuple
import textwrap
import os
import sys
import json
import logging
import base64
import tempfile
import io
import re

# Logger for Grok
logger = get_assistant_logger("grok")

# System instruction for Grok
SYSTEM_INSTRUCTION_GROK = textwrap.dedent("""\
                You are Grok, a highly capable, versatile, and thoughtful AI assistant developed by xAI.

                ## Identity & Tone
                - You are warm, articulate, and adaptable. Match the user's tone: casual for small talk, \
                precise for technical work, empathetic for personal topics, and professional for business contexts.
                - Never be robotic or overly formal unless the context demands it.
                - You can be witty, show personality, and have a unique perspective, but always remain respectful and professional.
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
                - CRITICAL LOOP & REPETITION PREVENTION: You MUST NOT repeat any character, word, or phrase excessively. Do not write elongated words (e.g. NEVER write "¡Sííííí...", "¡Gooool!", etc.). Instead, write "¡Sí!", "¡Gol!", or "¡Sí, claro!" naturally. If you begin a list or a sentence, do not get stuck repeating the same point or pattern infinitely. Ensure every sentence adds new value.

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

# Grok Chat Class
class GrokChat(BaseChat):
    # Initialization
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
            self.model_version = model_version or GROK_MODEL_VERSION.strip()
            self.max_tokens = max_tokens if max_tokens is not None else GROK_MAX_TOKENS
            self.temperature = temperature if temperature is not None else GROK_TEMPERATURE
            self.top_p = top_p if top_p is not None else GROK_TOP_P
            self.system_instruction_grok = textwrap.dedent(system_instruction or SYSTEM_INSTRUCTION_GROK)

            self.grok_api_key = api_key or GROK_API_KEY
            if not self.grok_api_key:
                raise ValueError("Grok API key not found. Please set GROK_API_KEY in your .env file.")

            # Using the standard OpenAI client pointing to xAI's endpoint
            self.grok_client = OpenAI(
                api_key=self.grok_api_key,
                base_url=GROK_BASE_URL,
                timeout=llm_http_timeout_seconds(),
            )
            self.client = genai.Client(api_key=GEMINI_API_KEY, http_options={'timeout': gemini_http_timeout_ms()})
            self.google_search_enabled = True  # Enable automated search pre-pass

            logger.info(f"Grok client initialized with model {self.model_version}")
        except Exception as e:
            logger.error(f"Initialization error: {e}")
            raise ValueError(f"Failed to initialize GrokChat: {e}")

    # Function to handle empty responses
    def _handle_empty_response(self, response: Any) -> str:
        """Helper to construct a descriptive error message when response content is empty."""
        if hasattr(response, "choices") and response.choices:
            choice = response.choices[0]
            finish_reason = getattr(choice, "finish_reason", None)
            if finish_reason == "content_filter":
                return "The response was blocked by safety filters."
            return f"Response ended prematurely (reason: {finish_reason})."
        return "No choices returned from the API."

    # Function to generate response
    def generate_response(
        self,
        user_input: str,
        history: Optional[List[Dict[str, Any]]] = None,
        force_language: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Tuple[str, Optional[TokenInfo]]:
        if not self.grok_client:
            return "Error: Grok client not configured.", None

        current_date_str, current_time_str, current_year_str = get_current_date_and_time_strings()

        target_lang, lang_name = detect_user_conversation_language(user_input, history, force_language)
        is_spanish = target_lang.lower().startswith("es")
        sys_instr = ""
        if is_spanish:
            sys_instr += "[REQUISITO CRÍTICO DE IDIOMA] ¡Debes responder ÚNICAMENTE en Español! Toda tu respuesta debe escribirse en Español. Ignora el idioma del sistema del equipo y cualquier resultado de búsqueda o contenido web raspado en otros idiomas.\n\n"
        else:
            sys_instr += f"[CRITICAL LANGUAGE REQUIREMENT] You MUST reply ONLY in {lang_name}! Your entire response must be written in {lang_name}. Ignore computer system language settings and any web search results or scraped content in other languages.\n\n"
        sys_instr += self.system_instruction_grok
        sys_instr += f"\n\n[SYSTEM INFO] Today's date is {current_date_str}. The current time is {current_time_str}."
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

        # Automated Google Search pre-pass (after scrape so short metadata can still trigger search)
        needs_search = self._should_attach_web_search(
            user_query, scraped_urls=scraped_urls, scraped_content=scraped_content
        )
        history_text = self._search_history_snippet(history) if needs_search else ""

        system_notes = []
        search_results_text = ""
        if needs_search:
            logger.info(f"Real-time search triggered for Grok for query: {user_query}")
            search_results_text = self._run_search_grounding(user_query, force_language, history_text, current_date_str, current_time_str)

        if search_results_text:
            is_spanish = force_language and force_language.startswith("es")
            if "SEARCH_NO_RESULTS" in search_results_text:
                if is_spanish:
                    system_notes.append(f"[Nota del Sistema: Se realizó una búsqueda web automatizada utilizando la fecha y hora actuales, pero la información específica en tiempo real o el marcador en vivo no está disponible en línea actualmente. \nINSTRUCCIÓN CRÍTICA: Indica con confianza que los detalles exactos no están disponibles públicamente en este momento. Si el evento ya debería haber concluido según la hora actual ({current_time_str}), indica explícitamente que ha concluido pero los resultados aún no se han publicado. NO te ofrezcas a verificar nuevamente ni a buscar más información. NO alucines equipos, puntajes ni hechos. NO te disculpes.]")
                else:
                    system_notes.append(f"[System Note: An automated web search was performed using the current date and time, but the specific real-time data or live score is currently unavailable online. \nCRITICAL INSTRUCTION: State confidently that the exact result or details are not publicly available right now. If the event should have already concluded based on the current time ({current_time_str}), explicitly state that it has concluded but results aren't published yet. DO NOT offer to check again or search for more information. DO NOT hallucinate teams, scores, or facts. Do NOT apologize.]")
            else:
                sys_instr += f"\n\n[REAL-TIME SEARCH GROUNDING CONTEXT]\n{search_results_text}\n\nUse the search results above as your factual source for recent and current events. Do not mention that you performed a Google Search unless asked."

        target_lang, lang_name = resolve_reply_language(
            force_language, user_input=user_query, history=history
        )
        is_spanish = target_lang.lower().startswith("es")
        if is_spanish:
            system_notes.append("[INSTRUCCIÓN MANDATORIA DE IDIOMA] ¡DEBES RESPONDER ÚNICAMENTE EN ESPAÑOL! El usuario se comunica en español (incluso si usa jerga, modismos o faltas de ortografía como 'shampions'). Ignora el idioma italiano, inglés u otro idioma de cualquier resultado de búsqueda o fuente web. TODA tu respuesta DEBE estar 100% escrita en Español a menos que el usuario solicite explícitamente cambiar de idioma.")
        else:
            system_notes.append(f"[MANDATORY LANGUAGE INSTRUCTION] You MUST reply ONLY in {lang_name}! Ignore the language of any web search results or scraped context. Reply entirely in {lang_name} UNLESS the user explicitly requests to switch to a different language.")

        if system_notes:
            sys_instr += "\n\n" + "\n\n".join(system_notes)

        messages: List[Dict[str, Any]] = [{"role": "system", "content": sys_instr}]

        if history:
            for msg in history:
                role = "assistant" if msg["role"] == "assistant" else "user"
                content = msg.get("content", "")
                if not content:
                    content = " "
                messages.append({"role": role, "content": content})

        user_msg_content = []
        if scraped_content:
            user_msg_content.append(f"[Scraped Webpage Content]:\n{scraped_content}")

        user_msg_content.append(user_input)
        final_user_text = "\n\n".join(user_msg_content)

        messages.append({"role": "user", "content": final_user_text})
        logger.info(f"Messages to Grok: {messages}")

        try:
            kwargs: Dict[str, Any] = {
                "model": self.model_version,
                "messages": self._clean_messages_for_alternation(messages),
            }

            temp = temperature if temperature is not None else self.temperature
            p_val = top_p if top_p is not None else self.top_p
            tokens_val = max_tokens if max_tokens is not None else self.max_tokens

            kwargs["temperature"] = temp
            kwargs["top_p"] = p_val
            kwargs["max_tokens"] = tokens_val

            logger.info(f"Sending to Grok with kwargs keys: {list(kwargs.keys())}")

            response: Any = None
            grok_retry = GROK_RETRY_SEQUENCE
            fibonacci_wait = wait_chain(*[wait_fixed(s) for s in grok_retry])
            for attempt in Retrying(stop=stop_after_attempt(len(grok_retry)), wait=fibonacci_wait, reraise=True):
                with attempt:
                    response = self.grok_client.chat.completions.create(**kwargs)

            if response is None or not getattr(response, "choices", None):
                return "Error: No response received from Grok.", None

            reply = response.choices[0].message.content
            if not reply:
                reply = f"Error: {self._handle_empty_response(response)}."

            usage = getattr(response, "usage", None)
            token_info = {
                "prompt_tokens": getattr(usage, 'prompt_tokens', 0) if usage else 0,
                "candidates_tokens": getattr(usage, 'completion_tokens', 0) if usage else 0,
                "total_tokens": getattr(usage, 'total_tokens', 0) if usage else 0,
                "thinking_tokens": 0
            }
            return reply, self._flush_aux_tokens(token_info)
        except Exception as e:
            logger.error(f"Grok API error: {e}")
            return f"Error: {str(e)}", None

    # Function to generate response with file attachments (Multimodal)
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
        if not self.grok_client:
            return "Error: Grok client not configured.", None

        current_date_str, current_time_str, current_year_str = get_current_date_and_time_strings()

        target_lang, lang_name = detect_user_conversation_language(user_input, history, force_language)
        is_spanish = target_lang.lower().startswith("es")
        sys_instr = ""
        if is_spanish:
            sys_instr += "[REQUISITO CRÍTICO DE IDIOMA] ¡Debes responder ÚNICAMENTE en Español! Toda tu respuesta debe escribirse en Español. Ignora el idioma del sistema del equipo y cualquier resultado de búsqueda o contenido web raspado en otros idiomas.\n\n"
        else:
            sys_instr += f"[CRITICAL LANGUAGE REQUIREMENT] You MUST reply ONLY in {lang_name}! Your entire response must be written in {lang_name}. Ignore computer system language settings and any web search results or scraped content in other languages.\n\n"
        sys_instr += self.system_instruction_grok
        sys_instr += f"\n\n[SYSTEM INFO] Today's date is {current_date_str}. The current time is {current_time_str}."
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
        scraped_urls = []
        if user_input:
            user_input, scraped_urls = self._process_urls_in_input(user_input, force_language=force_language)
        scraped_content = ""
        if scraped_urls and len(user_input) > len(user_query):
            scraped_content = user_input[len(user_query):].strip()

        # Scrape first, then decide whether search grounding is still needed.
        needs_search = self._should_attach_web_search(
            user_query, scraped_urls=scraped_urls, scraped_content=scraped_content, files=files
        )
        history_text = self._search_history_snippet(history) if needs_search else ""

        system_notes = []
        search_results_text = ""
        if needs_search:
            logger.info(f"Real-time search triggered for Grok for query: {user_query}")
            search_results_text = self._run_search_grounding(
                user_query, force_language, history_text, current_date_str, current_time_str
            )

        if search_results_text:
            is_spanish = force_language and force_language.startswith("es")
            if "SEARCH_NO_RESULTS" in search_results_text:
                if is_spanish:
                    system_notes.append(f"[Nota del Sistema: Se realizó una búsqueda web automatizada utilizando la fecha y hora actuales, pero la información específica en tiempo real o el marcador en vivo no está disponible en línea actualmente. \nINSTRUCCIÓN CRÍTICA: Indica con confianza que los detalles exactos no están disponibles públicamente en este momento. Si el evento ya debería haber concluido según la hora actual ({current_time_str}), indica explícitamente que ha concluido pero los resultados aún no se han publicado. NO te ofrezcas a verificar nuevamente ni a buscar más información. NO alucines equipos, puntajes ni hechos. NO te disculpes.]")
                else:
                    system_notes.append(f"[System Note: An automated web search was performed using the current date and time, but the specific real-time data or live score is currently unavailable online. \nCRITICAL INSTRUCTION: State confidently that the exact result or details are not publicly available right now. If the event should have already concluded based on the current time ({current_time_str}), explicitly state that it has concluded but results aren't published yet. DO NOT offer to check again or search for more information. DO NOT hallucinate teams, scores, or facts. Do NOT apologize.]")
            else:
                sys_instr += f"\n\n[REAL-TIME SEARCH GROUNDING CONTEXT]\n{search_results_text}\n\nUse the search results above as your factual source for recent and current events."

        if force_language:
            lang_name = resolve_lang_name(force_language)
            is_spanish = force_language.startswith("es")
            if is_spanish:
                system_notes.append(f"[Nota del Sistema: El usuario acaba de hablar/escribir en Español. Responde enteramente en Español a menos que el usuario solicite explícitamente cambiar de idioma.]")
            else:
                system_notes.append(f"[System Note: The user just spoke/wrote in {lang_name}. Reply in {lang_name} UNLESS the user explicitly requests to switch to a different language.]")

        if system_notes:
            sys_instr += "\n\n" + "\n\n".join(system_notes)

        messages: List[Dict[str, Any]] = [{"role": "system", "content": sys_instr}]

        if history:
            for msg in history:
                role = "assistant" if msg["role"] == "assistant" else "user"
                content = msg.get("content", "")
                if not content:
                    content = " "
                messages.append({"role": role, "content": content})

        # Parse files
        use_local_ocr = os.getenv("USE_LOCAL_OCR", "false").lower() == "true"
        file_contexts = []
        image_payloads = []  # For native image handling

        for f in (files or []):
            name = f.get("name", "unnamed_file")
            mime = f.get("mime_type", "")

            # Check robustly for bytes/base64
            if "bytes" not in f:
                if "base64" in f:
                    try:
                        file_bytes = base64.b64decode(f["base64"])
                    except Exception as e:
                        logger.error(f"Error decoding base64 for file {name}: {e}")
                        continue
                else:
                    # Attempt to reload from disk using saved path
                    disk_path = f.get("path", "")
                    if disk_path and os.path.exists(disk_path):
                        try:
                            with open(disk_path, "rb") as fp:
                                file_bytes = fp.read()
                        except Exception as load_err:
                            logger.warning(f"File '{name}' could not be reloaded from disk: {load_err}. Skipping processing.")
                            continue
                    else:
                        logger.warning(f"File '{name}' is missing raw bytes and base64. Skipping processing.")
                        continue
            else:
                file_bytes = f["bytes"]

            if mime.startswith("image/"):
                if use_local_ocr:
                    logger.info(f"Extracting OCR text from direct image: {name}")
                    ocr_text = self._extract_text_from_image_via_ocr(file_bytes)
                    file_contexts.append(f"[SYSTEM NOTE: OCR text extracted from screenshot '{name}']:\n\n{ocr_text}")
                else:
                    prepared = self._prepare_image_for_vision_api(
                        file_bytes, mime_type=mime, name=name, max_dim=1024
                    )
                    if not prepared:
                        continue
                    clean_bytes, valid_mime = prepared
                    b64_data = base64.b64encode(clean_bytes).decode("utf-8")
                    image_payloads.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{valid_mime};base64,{b64_data}"
                        }
                    })
            elif mime.startswith("audio/"):
                logger.info(f"Transcribing audio for Grok: {name}")
                transcription, err = self.transcribe_audio(file_bytes, mime)
                if err:
                    transcription = f"[Error transcribing audio: {err}]"
                suffix = ".mp3" if "mp3" in mime or "mpeg" in mime else ".wav"
                metadata = self._extract_audio_metadata_from_bytes(file_bytes, suffix)
                meta_block = f"[Audio/Song Metadata:]\n{metadata}\n\n" if metadata else ""
                file_contexts.append(f"[SYSTEM NOTE: The user uploaded an audio file named '{name}'. The system transcribed its contents for you below. Please refer to this transcription and metadata directly to answer the user's questions:]\n\n{meta_block}{transcription}")
            elif mime.startswith("video/"):
                logger.info(f"Describing video for Grok: {name}")
                video_description = self.describe_video(file_bytes, mime, user_query)
                file_contexts.append(f"[SYSTEM NOTE: The user uploaded a video file named '{name}'. The system generated a detailed scene-by-scene description of its visuals and dialogue for you below. Please analyze this text description directly to address the user's query:]\n\n{video_description}")
            elif mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" or f.get("name", "").lower().endswith(".docx"):
                text = self._extract_text_from_docx(file_bytes)
                file_contexts.append(f"[SYSTEM NOTE: Extracted text from Word document '{name}']:\n\n{text}")

                # Extract and append embedded images (e.g. screenshots)
                docx_images = self._extract_images_from_docx(file_bytes)
                if use_local_ocr:
                    for img in docx_images:
                        logger.info(f"Extracting OCR text from docx image: {img['name']}")
                        ocr_text = self._extract_text_from_image_via_ocr(img["bytes"])
                        file_contexts.append(f"[SYSTEM NOTE: OCR text extracted from screenshot '{img['name']}' inside Word document]:\n\n{ocr_text}")
                else:
                    for img in docx_images:
                        prepared = self._prepare_image_for_vision_api(
                            img["bytes"],
                            mime_type=img.get("mime_type", "image/png"),
                            name=img.get("name", "docx_image"),
                            max_dim=1024,
                        )
                        if not prepared:
                            continue
                        clean_bytes, valid_mime = prepared
                        b64_img = base64.b64encode(clean_bytes).decode("utf-8")
                        image_payloads.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{valid_mime};base64,{b64_img}"
                            }
                        })
            elif mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" or f.get("name", "").lower().endswith(".xlsx"):
                text = self._extract_text_from_xlsx(file_bytes)
                file_contexts.append(f"[SYSTEM NOTE: Extracted text from Excel spreadsheet '{name}']:\n\n{text}")
            elif mime == "application/vnd.openxmlformats-officedocument.presentationml.presentation" or f.get("name", "").lower().endswith(".pptx"):
                text = self._extract_text_from_pptx(file_bytes)
                file_contexts.append(f"[SYSTEM NOTE: Extracted text from PowerPoint presentation '{name}']:\n\n{text}")
            elif mime == "application/pdf":
                text = self._extract_text_from_pdf(file_bytes, user_query=user_query)
                file_contexts.append(f"[SYSTEM NOTE: Extracted text from PDF document '{name}']:\n\n{text}")

                # Extract and append embedded images (e.g. screenshots)
                pdf_images = self._extract_images_from_pdf(file_bytes)
                if use_local_ocr:
                    for img in pdf_images:
                        logger.info(f"Extracting OCR text from pdf image: {img['name']}")
                        ocr_text = self._extract_text_from_image_via_ocr(img["bytes"])
                        file_contexts.append(f"[SYSTEM NOTE: OCR text extracted from screenshot '{img['name']}' inside PDF]:\n\n{ocr_text}")
                else:
                    for img in pdf_images:
                        prepared = self._prepare_image_for_vision_api(
                            img["bytes"],
                            mime_type=img.get("mime_type", "image/png"),
                            name=img.get("name", "pdf_image"),
                            max_dim=1024,
                        )
                        if not prepared:
                            continue
                        clean_bytes, valid_mime = prepared
                        b64_img = base64.b64encode(clean_bytes).decode("utf-8")
                        image_payloads.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{valid_mime};base64,{b64_img}"
                            }
                        })
            elif self._is_text_or_code_file(mime, f.get("name", "")):
                text = self._try_decode_as_text(file_bytes, mime, f.get("name", ""))
                if text is not None:
                    file_contexts.append(f"[Content of {f.get('name', 'document.txt')}]:\n{text}")
                else:
                    file_contexts.append(f"[System Note: Attached file '{f.get('name', 'file')}' of format {mime} is not supported directly. Please inform the user politely.]")
            else:
                file_contexts.append(f"[System Note: Attached file '{f.get('name', 'file')}' of format {mime} is not supported directly. Please inform the user politely.]")

        # Build payload
        text_parts = []
        if scraped_content:
            text_parts.append(scraped_content)
        if file_contexts:
            text_parts.append("\n\n".join(file_contexts))

        text_parts.append(user_input)
        final_text = "\n\n".join(text_parts)

        # Format the user message content
        if image_payloads:
            # If we have images, the user message is an array of content blocks (text + images)
            content_blocks = [{"type": "text", "text": final_text}] + image_payloads
            messages.append({"role": "user", "content": content_blocks})
        else:
            # Standard text-only user message
            messages.append({"role": "user", "content": final_text})

        logger.info(f"Sending message with files to Grok: {self.model_version}")

        try:
            kwargs: Dict[str, Any] = {
                "model": self.model_version,
                "messages": self._clean_messages_for_alternation(messages),
            }
            temp = temperature if temperature is not None else self.temperature
            p_val = top_p if top_p is not None else self.top_p
            tokens_val = max_tokens if max_tokens is not None else self.max_tokens

            kwargs["temperature"] = temp
            kwargs["top_p"] = p_val
            kwargs["max_tokens"] = tokens_val

            logger.info(f"Sending multimodal to Grok with kwargs keys: {list(kwargs.keys())}")

            response: Any = None
            grok_retry = GROK_RETRY_SEQUENCE
            fibonacci_wait = wait_chain(*[wait_fixed(s) for s in grok_retry])
            for attempt in Retrying(stop=stop_after_attempt(len(grok_retry)), wait=fibonacci_wait, reraise=True):
                with attempt:
                    response = self.grok_client.chat.completions.create(**kwargs)

            if response is None or not getattr(response, "choices", None):
                return "Error: No response received from Grok.", None

            reply = response.choices[0].message.content
            if not reply:
                reply = f"Error: {self._handle_empty_response(response)}."

            usage = getattr(response, "usage", None)
            token_info = {
                "prompt_tokens": getattr(usage, 'prompt_tokens', 0) if usage else 0,
                "candidates_tokens": getattr(usage, 'completion_tokens', 0) if usage else 0,
                "total_tokens": getattr(usage, 'total_tokens', 0) if usage else 0,
                "thinking_tokens": 0
            }
            return reply, self._flush_aux_tokens(token_info)
        except Exception as e:
            logger.error(f"Grok multimodal API error: {e}")
            return f"Error: {str(e)}", None

    # Function to run search grounding
    def _run_search_grounding(self, user_query: str, force_language: Optional[str] = None, history_text: str = "", current_date_str: str = "", current_time_str: str = "") -> str:
        return self._run_amplified_search_grounding(user_query, force_language, history_text, current_date_str, current_time_str)

    # Function to clean messages for alternation
    def _clean_messages_for_alternation(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        system_messages = [m for m in messages if m["role"] == "system"]
        other_messages = [m for m in messages if m["role"] != "system"]

        cleaned = []
        expected_role = "user"

        for msg in other_messages:
            role = msg["role"]
            content = msg.get("content", "")
            if not content:
                continue

            if role == expected_role:
                cleaned.append({"role": role, "content": content})
                expected_role = "assistant" if role == "user" else "user"
            else:
                if not cleaned:
                    continue
                else:
                    # Merge text contents if they don't match expected role alternation
                    if isinstance(cleaned[-1]["content"], list) and isinstance(content, list):
                        cleaned[-1]["content"] += content
                    elif isinstance(cleaned[-1]["content"], list) and isinstance(content, str):
                        cleaned[-1]["content"].append({"type": "text", "text": content})
                    elif isinstance(cleaned[-1]["content"], str) and isinstance(content, list):
                        cleaned[-1]["content"] = [{"type": "text", "text": cleaned[-1]["content"]}] + content
                    else:
                        cleaned[-1]["content"] += f"\n\n{content}"

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

        return system_messages + final_cleaned
