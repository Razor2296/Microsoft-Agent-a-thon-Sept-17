"""
OpenAI Chat Class - Handles all interactions with the OpenAI API.
"""
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
    OPENAI_PROFILE_PICTURE_PATH,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL_VERSION,
    OPENAI_IMAGE_MODEL_VERSION,
    OPENAI_FALLBACK_IMAGE_MODEL,
    OPENAI_MAX_TOKENS,
    OPENAI_TEMPERATURE,
    OPENAI_TOP_P,
    OPENAI_RETRY_SEQUENCE,
    GEMINI_API_KEY,
    build_openai_client,
    get_assistant_logger,
    get_user_country_code,
    gemini_http_timeout_ms,
    append_mandatory_reply_language,
    wrap_user_query_for_language,
    multimodal_describe_prompt,
    mandatory_reply_language_note,
)
from backend.core.schemas import TokenInfo
from backend.integrations.document_request import CRITICAL_DOCUMENT_ANALYSIS_RULE
from google import genai
from tenacity import Retrying, stop_after_attempt, wait_chain, wait_fixed
from typing import Any, Dict, List, Optional, Tuple
import textwrap
import os
import sys
import json
import logging
import base64
import tempfile
import io
import re

# Logger for OpenAI
logger = get_assistant_logger("openai")

# System instruction for OpenAI
SYSTEM_INSTRUCTION_OPENAI         = textwrap.dedent("""\
                You are ChatGPT, a highly capable, versatile, and thoughtful AI assistant developed by OpenAI.

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

                ## Voice Input Detection
                - If the user's message ends with the label "🎙️ *(Voice Recorded)*", it means they spoke via a microphone and the app transcribed their voice into text for you.
                - Therefore, if the user asks "can you hear me?", "are you listening?", etc., you MUST reply "Yes" (or something similar in their language) and engage naturally as if you are hearing them. Do NOT say "I am a text-based AI and cannot hear". You CAN hear them through the transcriptions.
                - Ensure your response is particularly concise, direct, and conversational (avoiding overly long lists, massive text tables, or complex formatting where possible), as it will be read aloud to the user using Text-to-Speech. Keep the response natural for listening. """)

# OpenAI Chat Class
class OpenAIChat(BaseChat):
    # Initialization
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_version: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        system_instruction: Optional[str] = None
    ):
        super().__init__()
        try:
            self.model_version = model_version or OPENAI_MODEL_VERSION.strip()
            self.max_tokens = max_tokens if max_tokens is not None else OPENAI_MAX_TOKENS
            self.temperature = temperature if temperature is not None else OPENAI_TEMPERATURE
            self.top_p = top_p if top_p is not None else OPENAI_TOP_P
            self.system_instruction_openai = textwrap.dedent(system_instruction or SYSTEM_INSTRUCTION_OPENAI)

            self.openai_api_key = api_key or OPENAI_API_KEY
            if not self.openai_api_key:
                raise ValueError("OpenAI API key not found.")

            self.openai_client = build_openai_client(api_key=self.openai_api_key)
            self.client = genai.Client(api_key=GEMINI_API_KEY, http_options={'timeout': gemini_http_timeout_ms()})
            self.google_search_enabled = True

            endpoint_label = OPENAI_BASE_URL or "https://api.openai.com/v1"
            logger.info(
                f"OpenAI client initialized with model {self.model_version} on {endpoint_label}"
            )
        except Exception as e:
            logger.error(f"Initialization error: {e}")
            raise ValueError(f"Failed to initialize OpenAIChat: {e}")

    def _handle_empty_response(self, response: Any) -> str:
        """Helper to construct a descriptive error message when OpenAI response content is empty or filtered."""
        if hasattr(response, "choices") and response.choices:
            choice = response.choices[0]
            finish_reason = getattr(choice, "finish_reason", None)
            if finish_reason == "content_filter":
                return "The response was blocked by OpenAI safety filters (content filter)"
            elif finish_reason == "length":
                return "The response was truncated because it exceeded the maximum token limit"
            elif finish_reason:
                return f"The model returned an empty response. Finish reason: {finish_reason}"
        return "The model returned an empty response"

    def _is_openai_reasoning_model(self, model_version: str) -> bool:
        """Check if the model is an OpenAI reasoning model (o1, o3, etc.) which deprecates temperature/top_p."""
        mv = model_version.lower().strip()
        if re.match(r'^o\d', mv):
            return True
        return False

    def _openai_model_excludes_temp_and_topp(self, model_version: str) -> bool:
        """Check if the model version is known to exclude/deprecate temperature and top_p (e.g. reasoning models and GPT-5+)."""
        mv = model_version.lower().strip()
        if self._is_openai_reasoning_model(mv):
            return True
        if mv.startswith("gpt-"):
            match = re.search(r'\d+', mv)
            if match:
                major_version = int(match.group())
                if major_version >= 5:
                    return True
        return False

    def _openai_model_uses_max_completion_tokens(self, model_version: str) -> bool:
        """Check if the model uses max_completion_tokens instead of max_tokens."""
        mv = model_version.lower().strip()
        if self._is_openai_reasoning_model(mv):
            return True
        if mv.startswith("gpt-"):
            match = re.search(r'\d+', mv)
            if match:
                major_version = int(match.group())
                if major_version >= 5:
                    return True
        return False

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
        if not self.openai_client:
            return "Error: OpenAI API key not configured.", None

        current_date_str, current_time_str, current_year_str = get_current_date_and_time_strings()

        target_lang, lang_name = detect_user_conversation_language(user_input, history, force_language)
        is_spanish = target_lang.lower().startswith("es")
        sys_instr = ""
        if is_spanish:
            sys_instr += "[REQUISITO CRÍTICO DE IDIOMA] ¡Debes responder ÚNICAMENTE en Español! Toda tu respuesta debe escribirse en Español. Ignora el idioma del sistema del equipo y cualquier resultado de búsqueda o contenido web raspado en otros idiomas.\n\n"
        else:
            sys_instr += f"[CRITICAL LANGUAGE REQUIREMENT] You MUST reply ONLY in {lang_name}! Your entire response must be written in {lang_name}. Ignore computer system language settings and any web search results or scraped content in other languages.\n\n"
        sys_instr += self.system_instruction_openai
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
        sys_instr += f"\nUse this information to address the user by name, respect their language/timezone, use the provided paths when writing files, and consider clipboard content if requested."
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
                sys_instr += f"\n\n[CRITICAL LANGUAGE REQUIREMENT] ¡INSTRUCCIÓN CRÍTICA DE IDIOMA! Responde ÚNICAMENTE en Español. Ignora el inglés de los resultados de búsqueda. Tu respuesta debe estar completamente en Español."
            else:
                sys_instr += f"\n\n[CRITICAL LANGUAGE REQUIREMENT] You MUST reply ONLY in {lang_name}. Ignore any English in the search results or system prompts. Your entire response must be in {lang_name}."

        user_query = user_input
        user_input, scraped_urls = self._process_urls_in_input(user_input, force_language=force_language)
        scraped_content = ""
        if scraped_urls and len(user_input) > len(user_query):
            scraped_content = user_input[len(user_query):].strip()

        needs_search = self._should_attach_web_search(
            user_query, scraped_urls=scraped_urls, scraped_content=scraped_content
        )
        history_text = self._search_history_snippet(history) if needs_search else ""

        system_notes = []
        if needs_search:
            search_results = self._run_amplified_search_grounding(user_query, force_language, history_text, current_date_str, current_time_str)
            if search_results:
                is_spanish = force_language and force_language.startswith("es")
                if "SEARCH_NO_RESULTS" in search_results:
                    if is_spanish:
                        system_notes.append(f"[Nota del Sistema: Se realizó una búsqueda web automatizada utilizando la fecha y hora actuales, pero la información específica en tiempo real o el marcador en vivo no está disponible en línea actualmente. \nINSTRUCCIÓN CRÍTICA: Indica con confianza que los detalles exactos no están disponibles públicamente en este momento. Si el evento ya debería haber concluido según la hora actual ({current_time_str}), indica explícitamente que ha concluido pero los resultados aún no se han publicado. NO te ofrezcas a verificar nuevamente ni a buscar más información. NO alucines equipos, puntajes ni hechos. NO te disculpes.]")
                    else:
                        system_notes.append(f"[System Note: An automated web search was performed using the current date and time, but the specific real-time data or live score is currently unavailable online. \nCRITICAL INSTRUCTION: State confidently that the exact result or details are not publicly available right now. If the event should have already concluded based on the current time ({current_time_str}), explicitly state that it has concluded but results aren't published yet. DO NOT offer to check again or search for more information. DO NOT hallucinate teams, scores, or facts. Do NOT apologize.]")
                else:
                    if is_spanish:
                        system_notes.append(f"[Nota del Sistema: Resultados de la búsqueda web en tiempo real para la consulta del usuario:\n{search_results}\n\nINSTRUCCIÓN CRÍTICA: Responde al usuario directamente utilizando los hechos anteriores. Responde enteramente en ESPAÑOL. NO alucines ningún hecho que no esté presente en los resultados de la búsqueda. NO ofrezcas verificar o buscar más información, ya que la búsqueda ya se realizó. NO uses frases como 'no tengo acceso en vivo', 'no puedo navegar por la web', 'según los resultados de búsqueda' o 'a partir de mi última actualización'. Presenta los hechos con confianza como si fueran tu propio conocimiento.]")
                    else:
                        system_notes.append(f"[System Note: Real-time web search results for the user's query:\n{search_results}\n\nCRITICAL INSTRUCTION: Answer the user directly using the facts above. DO NOT hallucinate any facts not present in the search results. DO NOT offer to check or search for more information, as the search was already performed. DO NOT use phrases like 'I don't have live access', 'I cannot browse the web', 'Based on the search results', or 'As of my last update'. Present the facts confidently as your own knowledge.]")

        target_lang, lang_name = append_mandatory_reply_language(
            system_notes, force_language, user_input=user_query, history=history
        )

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

        parts = []
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
            kwargs: Dict[str, Any] = {
                "model": self.model_version,
                "messages": self._clean_messages_for_alternation(messages),
            }
            temp = temperature if temperature is not None else self.temperature
            p_val = top_p if top_p is not None else self.top_p
            tokens_val = max_tokens if max_tokens is not None else self.max_tokens

            if self._openai_model_uses_max_completion_tokens(self.model_version):
                kwargs["max_completion_tokens"] = tokens_val
            else:
                kwargs["max_tokens"] = tokens_val

            if not self._openai_model_excludes_temp_and_topp(self.model_version):
                kwargs["temperature"] = temp
                kwargs["top_p"] = p_val

            logger.info(f"Sending to OpenAI with kwargs keys: {list(kwargs.keys())}")
            fibonacci_wait = wait_chain(*[wait_fixed(s) for s in OPENAI_RETRY_SEQUENCE])
            response = None
            for attempt in Retrying(stop=stop_after_attempt(len(OPENAI_RETRY_SEQUENCE)), wait=fibonacci_wait, reraise=True):
                with attempt:
                    response = self.openai_client.chat.completions.create(**kwargs)

            if not response or not hasattr(response, "choices") or not response.choices:
                return "Error: Empty or invalid response from OpenAI API.", None

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
            logger.error(f"OpenAI error: {e}")
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
    ) -> Tuple[str, Optional[TokenInfo], Optional[str]]:
        current_date_str, current_time_str, current_year_str = get_current_date_and_time_strings()

        target_lang, lang_name = detect_user_conversation_language(user_input, history, force_language)
        is_spanish = target_lang.lower().startswith("es")
        sys_instr = ""
        if is_spanish:
            sys_instr += "[REQUISITO CRÍTICO DE IDIOMA] ¡Debes responder ÚNICAMENTE en Español! Toda tu respuesta debe escribirse en Español. Ignora el idioma del sistema del equipo y cualquier resultado de búsqueda o contenido web raspado en otros idiomas.\n\n"
        else:
            sys_instr += f"[CRITICAL LANGUAGE REQUIREMENT] You MUST reply ONLY in {lang_name}! Your entire response must be written in {lang_name}. Ignore computer system language settings and any web search results or scraped content in other languages.\n\n"
        sys_instr += self.system_instruction_openai
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
        sys_instr += f"\nUse this information to address the user by name, respect their language/timezone, use the provided paths when writing files, and consider clipboard content if requested."
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
                sys_instr += f"\n\n[CRITICAL LANGUAGE REQUIREMENT] ¡INSTRUCCIÓN CRÍTICA DE IDIOMA! Responde ÚNICAMENTE en Español. Ignora el inglés de los resultados de búsqueda o archivos. Tu respuesta debe estar completamente en Español."
            else:
                sys_instr += f"\n\n[CRITICAL LANGUAGE REQUIREMENT] You MUST reply ONLY in {lang_name}. Ignore any English in the search results, files, or system prompts. Your entire response must be in {lang_name}."

        user_query = user_input or ""
        scraped_urls = []
        if user_input:
            user_input, scraped_urls = self._process_urls_in_input(user_input, force_language=force_language)
        scraped_content = ""
        if scraped_urls and len(user_input) > len(user_query):
            scraped_content = user_input[len(user_query):].strip()

        # Automated Search for OpenAI (Language Agnostic via Keywords + LLM fallback)
        needs_search = self._should_attach_web_search(
            user_query, scraped_urls=scraped_urls, scraped_content=scraped_content, files=files
        )
        history_text = self._search_history_snippet(history) if needs_search else ""

        system_notes = []
        if needs_search:
            search_results = self._run_amplified_search_grounding(user_query, force_language, history_text, current_date_str, current_time_str)
            if search_results:
                is_spanish = force_language and force_language.startswith("es")
                if "SEARCH_NO_RESULTS" in search_results:
                    if is_spanish:
                        system_notes.append(f"[Nota del Sistema: Se realizó una búsqueda web automatizada utilizando la fecha y hora actuales, pero la información específica en tiempo real o el marcador en vivo no está disponible en línea actualmente. \nINSTRUCCIÓN CRÍTICA: Indica con confianza que los detalles exactos no están disponibles públicamente en este momento. Si el evento ya debería haber concluido según la hora actual ({current_time_str}), indica explícitamente que ha concluido pero los resultados aún no se han publicado. NO te ofrezcas a verificar nuevamente ni a buscar más información. NO alucines equipos, puntajes ni hechos. NO te disculpes.]")
                    else:
                        system_notes.append(f"[System Note: An automated web search was performed using the current date and time, but the specific real-time data or live score is currently unavailable online. \nCRITICAL INSTRUCTION: State confidently that the exact result or details are not publicly available right now. If the event should have already concluded based on the current time ({current_time_str}), explicitly state that it has concluded but results aren't published yet. DO NOT offer to check again or search for more information. DO NOT hallucinate teams, scores, or facts. Do NOT apologize.]")
                else:
                    if is_spanish:
                        system_notes.append(f"[Nota del Sistema: Resultados de la búsqueda web en tiempo real para la consulta del usuario:\n{search_results}\n\nINSTRUCCIÓN CRÍTICA: Responde al usuario directamente utilizando los hechos anteriores. Responde enteramente en ESPAÑOL. NO alucines ningún hecho que no esté presente en los resultados de la búsqueda. NO ofrezcas verificar o buscar más información, ya que la búsqueda ya se realizó. NO uses frases como 'no tengo acceso en vivo', 'no puedo navegar por la web', 'según los resultados de búsqueda' o 'a partir de mi última actualización'. Presenta los hechos con confianza como si fueran tu propio conocimiento.]")
                    else:
                        system_notes.append(f"[System Note: Real-time web search results for the user's query:\n{search_results}\n\nCRITICAL INSTRUCTION: Answer the user directly using the facts above. DO NOT hallucinate any facts not present in the search results. DO NOT offer to check or search for more information, as the search was already performed. DO NOT use phrases like 'I don't have live access', 'I cannot browse the web', 'Based on the search results', or 'As of my last update'. Present the facts confidently as your own knowledge.]")

        target_lang, lang_name = append_mandatory_reply_language(
            system_notes, force_language, user_input=user_query, history=history
        )

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

        scraped_content = ""
        if scraped_urls and len(user_input) > len(user_query):
            scraped_content = user_input[len(user_query):].strip()

        use_local_ocr = os.getenv("USE_LOCAL_OCR", "false").lower() == "true"

        # Build the multimodal content array
        content_array = []

        file_contexts = []
        for f in (files or []):
            name = f.get("name", "unnamed_file")
            mime = f.get("mime_type", "")
            if "bytes" not in f:
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
                            logger.warning(f"File '{name}' could not be reloaded from disk: {load_err}. Skipping processing.")
                            continue
                    else:
                        logger.warning(f"File '{name}' is missing raw bytes and base64. Skipping processing.")
                        continue
            else:
                data_bytes = f["bytes"]

            if mime.startswith("image/"):
                if use_local_ocr:
                    logger.info(f"Extracting OCR text from direct image: {name}")
                    ocr_text = self._extract_text_from_image_via_ocr(data_bytes)
                    file_contexts.append(f"[SYSTEM NOTE: OCR text extracted from screenshot '{name}']:\n\n{ocr_text}")
                else:
                    clean_bytes, valid_mime = self.normalize_image_media_type(mime, data_bytes)
                    b64 = base64.b64encode(clean_bytes or data_bytes).decode("utf-8")
                    content_array.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{valid_mime};base64,{b64}"}
                    })
            elif mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" or f.get("name", "").lower().endswith(".docx"):
                # Fallback: extract text and append
                text = self._extract_text_from_docx(data_bytes)
                file_contexts.append(f"[SYSTEM NOTE: The user uploaded a Word document '{name}'. Its text has been automatically extracted for you below. DO NOT refuse to analyze it. DO NOT say you cannot read documents. Analyze the following text directly:]\n\n{text}")

                # Extract and append embedded images (e.g. screenshots)
                docx_images = self._extract_images_from_docx(data_bytes)
                if use_local_ocr:
                    for img in docx_images:
                        logger.info(f"Extracting OCR text from docx image: {img['name']}")
                        ocr_text = self._extract_text_from_image_via_ocr(img["bytes"])
                        file_contexts.append(f"[SYSTEM NOTE: OCR text extracted from screenshot '{img['name']}' inside Word document]:\n\n{ocr_text}")
                else:
                    for img in docx_images:
                        clean_bytes, valid_mime = self.normalize_image_media_type(img.get("mime_type", "image/png"), img["bytes"])
                        b64 = base64.b64encode(clean_bytes or img["bytes"]).decode("utf-8")
                        content_array.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:{valid_mime};base64,{b64}"}
                        })
            elif mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" or f.get("name", "").lower().endswith(".xlsx"):
                text = self._extract_text_from_xlsx(data_bytes)
                file_contexts.append(f"[SYSTEM NOTE: The user uploaded an Excel spreadsheet '{name}'. Its text has been automatically extracted for you below. DO NOT refuse to analyze it. DO NOT say you cannot read spreadsheets. Analyze the following text directly:]\n\n{text}")
            elif mime == "application/vnd.openxmlformats-officedocument.presentationml.presentation" or f.get("name", "").lower().endswith(".pptx"):
                text = self._extract_text_from_pptx(data_bytes)
                file_contexts.append(f"[SYSTEM NOTE: The user uploaded a PowerPoint presentation '{name}'. Its text has been automatically extracted for you below. DO NOT refuse to analyze it. DO NOT say you cannot read PowerPoints. Analyze the following text directly:]\n\n{text}")
            elif mime == "application/pdf":
                text = self._extract_text_from_pdf(data_bytes, user_query=user_query)
                file_contexts.append(f"[SYSTEM NOTE: The user uploaded a PDF document '{name}'. Its text has been automatically extracted for you below. DO NOT refuse to analyze it. DO NOT say you cannot read PDFs. Analyze the following text directly:]\n\n{text}")

                # Extract and append embedded images (e.g. screenshots)
                pdf_images = self._extract_images_from_pdf(data_bytes)
                if use_local_ocr:
                    for img in pdf_images:
                        logger.info(f"Extracting OCR text from pdf image: {img['name']}")
                        ocr_text = self._extract_text_from_image_via_ocr(img["bytes"])
                        file_contexts.append(f"[SYSTEM NOTE: OCR text extracted from screenshot '{img['name']}' inside PDF]:\n\n{ocr_text}")
                else:
                    for img in pdf_images:
                        clean_bytes, valid_mime = self.normalize_image_media_type(img.get("mime_type", "image/png"), img["bytes"])
                        b64 = base64.b64encode(clean_bytes or img["bytes"]).decode("utf-8")
                        content_array.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:{valid_mime};base64,{b64}"}
                        })
            elif self._is_text_or_code_file(mime, name):
                text = self._try_decode_as_text(data_bytes, mime, name)
                if text is not None:
                    file_contexts.append(f"[Content of {name}]:\n{text}")
                else:
                    file_contexts.append(f"[System Note: The user attached a file named '{name}'. However, this file format ({mime}) is not natively supported by this AI model yet. Please politely inform the user that you cannot analyze this specific file type.]")
            elif mime.startswith("audio/"):
                try:
                    suffix = ".mp3" if "mp3" in mime or "mpeg" in mime else ".wav"
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(data_bytes)
                        tmp_path = tmp.name

                    with open(tmp_path, "rb") as audio_file:
                        transcript = self.openai_client.audio.transcriptions.create(
                            model="whisper-1",
                            file=audio_file
                        )

                    os.remove(tmp_path)

                    metadata = self._extract_audio_metadata_from_bytes(data_bytes, suffix)
                    meta_block = f"[Audio/Song Metadata:]\n{metadata}\n\n" if metadata else ""

                    file_contexts.append(f"[Audio Transcription and Metadata of '{name}']:\n\n{meta_block}{transcript.text}")
                except Exception as e:
                    logger.error(f"Whisper transcription failed: {e}")
                    file_contexts.append(f"[System Note: Failed to transcribe audio file '{name}' due to an error: {e}]")
            elif mime.startswith("video/"):
                logger.info(f"Describing video for OpenAI: {name}")
                video_description = self.describe_video(data_bytes, mime, user_query)
                file_contexts.append(f"[SYSTEM NOTE: The user uploaded a video file named '{name}'. The system generated a detailed scene-by-scene description of its visuals and dialogue for you below. Please analyze this text description directly to address the user's query:]\n\n{video_description}")
            else:
                file_contexts.append(f"[System Note: The user attached a file named '{name}'. However, this file format ({mime}) is not natively supported by this AI model yet. Please politely inform the user that you cannot analyze this specific file type.]")

        # Assemble parts putting user query last
        parts = []
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
            kwargs: Dict[str, Any] = {
                "model": self.model_version,
                "messages": self._clean_messages_for_alternation(messages),
            }
            temp = temperature if temperature is not None else self.temperature
            p_val = top_p if top_p is not None else self.top_p
            tokens_val = max_tokens if max_tokens is not None else self.max_tokens

            if self._openai_model_uses_max_completion_tokens(self.model_version):
                kwargs["max_completion_tokens"] = tokens_val
            else:
                kwargs["max_tokens"] = tokens_val

            if not self._openai_model_excludes_temp_and_topp(self.model_version):
                kwargs["temperature"] = temp
                kwargs["top_p"] = p_val

            response = self.openai_client.chat.completions.create(**kwargs)
            if not response or not hasattr(response, "choices") or not response.choices:
                return "Error: Empty or invalid response from OpenAI API.", None, None

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
            return reply, self._flush_aux_tokens(token_info), user_input
        except Exception as e:
            logger.error(f"OpenAI multimodal error: {e}")
            return f"Error: {str(e)}", None, None

    # Function to clean messages for alternation
    def _clean_messages_for_alternation(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        system_messages = [m for m in messages if m.get("role") == "system"]
        other_messages = [m for m in messages if m.get("role") != "system"]

        cleaned = []
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
