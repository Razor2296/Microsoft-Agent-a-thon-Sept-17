"""
Perplexity Chat Class - Handles all interactions with the Perplexity API.
"""
from backend.processors.base_processor import (
    BaseChat,
    resolve_lang_name,
    detect_user_conversation_language,
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
    PERPLEXITY_PROFILE_PICTURE_PATH,
    PERPLEXITY_API_KEY,
    PERPLEXITY_BASE_URL,
    PERPLEXITY_MODEL_VERSION,
    PERPLEXITY_MAX_TOKENS,
    PERPLEXITY_TEMPERATURE,
    PERPLEXITY_TOP_P,
    PERPLEXITY_RETRY_SEQUENCE,
    GEMINI_API_KEY,
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

# Logger for Perplexity
logger = get_assistant_logger("perplexity")

# System instruction for Perplexity
SYSTEM_INSTRUCTION_PERPLEXITY = textwrap.dedent("""\
                You are Perplexity, a highly capable, versatile, and thoughtful AI search and reasoning assistant developed by Perplexity.

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
                - You have active, real-time search grounding capabilities built-in. Always prioritize using search to ground your responses in real-time, real-world facts.
                - For any queries concerning current events, live results, sports news, transfers, players, injuries, concerts, tech keynotes, product releases, political events, elections, public figures, or recent history, base your reasoning heavily on current live web search results.
                - Never claim that you cannot search the web or that you don't have access to real-time information.
                - If no search results are returned, use the context provided by the system search pre-pass, or answer confidently using your existing knowledge.

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

# Perplexity Chat Class
class PerplexityChat(BaseChat):
    # Initialization
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_version: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        system_instruction: Optional[str] = None,
    ) -> None:
        super().__init__()
        try:
            self.model_version = model_version or PERPLEXITY_MODEL_VERSION.strip()
            self.max_tokens = max_tokens if max_tokens is not None else PERPLEXITY_MAX_TOKENS
            self.temperature = temperature if temperature is not None else PERPLEXITY_TEMPERATURE
            self.top_p = top_p if top_p is not None else PERPLEXITY_TOP_P
            self.system_instruction_perplexity = textwrap.dedent(system_instruction or SYSTEM_INSTRUCTION_PERPLEXITY)

            self.perplexity_api_key = api_key or PERPLEXITY_API_KEY
            if not self.perplexity_api_key:
                raise ValueError("Perplexity API key not found.")

            self.perplexity_client = OpenAI(
                api_key=self.perplexity_api_key,
                base_url=PERPLEXITY_BASE_URL,
                timeout=llm_http_timeout_seconds(),
            )
            self.client = genai.Client(api_key=GEMINI_API_KEY, http_options={'timeout': gemini_http_timeout_ms()})
            self.google_search_enabled = True  # Enable automated Gemini search pre-pass for Perplexity

            logger.info(f"Perplexity client initialized with model {self.model_version}")
        except Exception as e:
            logger.error(f"Initialization error: {e}")
            raise ValueError(f"Failed to initialize PerplexityChat: {e}")

    def _handle_empty_response(self, response: Any) -> str:
        """Helper to construct a descriptive error message when Perplexity response content is empty or filtered."""
        if hasattr(response, "choices") and response.choices:
            choice = response.choices[0]
            finish_reason = getattr(choice, "finish_reason", None)
            if finish_reason == "content_filter":
                return "The response was blocked by Perplexity safety filters (content filter)"
            elif finish_reason == "length":
                return "The response was truncated because it exceeded the maximum token limit"
            elif finish_reason:
                return f"The model returned an empty response. Finish reason: {finish_reason}"
        return "The model returned an empty response"

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
        if not self.perplexity_client:
            return "Error: Perplexity API key not configured.", None

        current_date_str, current_time_str, current_year_str = get_current_date_and_time_strings()

        target_lang, lang_name = detect_user_conversation_language(user_input, history, force_language)
        is_spanish = target_lang.lower().startswith("es")
        sys_instr = ""
        if is_spanish:
            sys_instr += "[REQUISITO CRÍTICO DE IDIOMA] ¡Debes responder ÚNICAMENTE en Español! Toda tu respuesta debe escribirse en Español. Ignora el idioma del sistema del equipo y cualquier resultado de búsqueda o contenido web raspado en otros idiomas.\n\n"
        else:
            sys_instr += f"[CRITICAL LANGUAGE REQUIREMENT] You MUST reply ONLY in {lang_name}! Your entire response must be written in {lang_name}. Ignore computer system language settings and any web search results or scraped content in other languages.\n\n"
        sys_instr += self.system_instruction_perplexity
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
            f"Do not break character by mentioning your training limitations."
        )
        sys_instr += (
            f"\n\n[CRITICAL GROUNDING RULE] Since the current year is {current_year_str}, you MUST treat any events, tournaments, or matches from 2024 and 2025 as historical and completed. "
            f"Never discuss them as future, current, or upcoming. For real-time news, live sports, or current event queries, use live web contents and search updates to report active results. "
            f"FOR GREETINGS AND CASUAL SMALL TALK (e.g., 'Hola', '¿Cómo estás?'), ALWAYS RESPOND NATURALLY AS A WARM HUMAN ASSISTANT WITHOUT CITING DICTIONARY ENTRIES OR EXPLAINING THE PHRASE. "
            f"Present match scores and current facts directly with confidence, without any disclaimers about them being simulator, mock, staging, or placeholder data."
        )
        sys_instr += (
            f"\n\n[CRITICAL TIMEZONE & DATE ALIGNMENT RULE]\n"
            f"- Today's date and time in the user's local timezone is: {current_date_str} at {current_time_str}.\n"
            f"- You MUST use this local date and time as your primary temporal anchor for all queries and search assessments.\n"
            f"- When search results show event kickoff times or schedules in other timezones (e.g. CET, CEST, UTC, BST, ET, PT), you MUST convert them to the user's local timezone ({USER_SYSTEM_TIMEZONE}) and offset to check if the event is currently in progress, already completed, or in the future.\n"
            f"- For example, if a match schedule is listed as 'June 27 at 02:00 CET/CEST' (which is 00:00 UTC on June 27), and the user's current time is Friday, June 26 at 08:20 PM (01:20 AM UTC on June 27), the match is currently in progress (80+ minutes in) and NOT 'later today' or in the future. You MUST do this calculation carefully before answering."
        )
        sys_instr += "\n\n[CRITICAL FORMATTING RULE] If the user says goodbye, indicates they are leaving, or wants to end the conversation, you MUST append the exact tag '[GOODBYE]' (including the brackets) to the very end of your final response."
        if force_language:
            lang_name = resolve_lang_name(force_language)
            is_spanish = force_language.startswith("es")
            if is_spanish:
                sys_instr += f"\n\n[CRITICAL LANGUAGE REQUIREMENT] ¡INSTRUCCIÓN CRÍTICA DE IDIOMA! Responde ÚNICAMENTE en Español. Ignora el inglés de los resultados de búsqueda. Tu respuesta debe estar completamente en Español."
            else:
                sys_instr += f"\n\n[CRITICAL LANGUAGE REQUIREMENT] You MUST reply ONLY in {lang_name}. Ignore any English in the search results or system prompts. Your entire response must be in {lang_name}."

        user_query = user_input or ""
        scraped_urls = []
        if user_input:
            user_input, scraped_urls = self._process_urls_in_input(user_input, force_language=force_language)
        scraped_content = ""
        if scraped_urls and user_input and len(user_input) > len(user_query):
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
                        system_notes.append(f"[Nota del Sistema: Resultados de la búsqueda web en tiempo real provistos por el SISTEMA para tu conocimiento:\n{search_results}\n\nINSTRUCCIÓN CRÍTICA: Responde al usuario directamente utilizando los hechos anteriores. Responde enteramente en ESPAÑOL. NUNCA digas 'en los resultados que compartiste' o 'según los datos que me diste' (los datos fueron obtenidos por el SISTEMA, no por el usuario). NO alucines ningún hecho no presente en los resultados. NO uses corchetes de citas como [1] o [12]. Presenta los hechos con confianza directamente como tu propio conocimiento.]")
                    else:
                        system_notes.append(f"[System Note: Real-time web search results provided by the SYSTEM for your knowledge:\n{search_results}\n\nCRITICAL INSTRUCTION: Answer the user directly using the facts above. NEVER say 'in the results you shared' or 'according to the data you provided' (these results were retrieved by the SYSTEM, not the user). DO NOT include bracketed citation numbers like [1] or [12]. Present the facts confidently directly as your own knowledge.]")

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
                if not content or not content.strip():
                    content = "."
                messages.append({"role": role, "content": content})

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

        # Check if the query is a request to generate/create/draw an image
        lower_query = user_query.lower()
        is_img_req = any(kw in lower_query for kw in [
            "genera una imagen", "generar una imagen", "genera un dibujo", "generar un dibujo",
            "crea una imagen", "crear una imagen", "genera imagen", "crea imagen", "dibuja", "dibujar",
            "generate an image", "create an image", "draw ", "painting of", "picture of", "imagen de",
            "foto de", "photo of"
        ])
        if is_img_req:
            user_input += (
                "\n\n[CRITICAL UX INSTRUCTION: Respond CONFIDENTELY in the user's language (e.g. in Spanish: '¡Por supuesto! Aquí tienes la imagen:') "
                "confirming the generation, and you MUST append the exact API tag: `[GENERATE_IMAGE: <descriptive visual prompt in English (NEVER use layout words like 'infographic', 'poster', 'chart', 'diagram', or 'text boxes')>]` "
                "on a new line at the very end of your response. IMPORTANT: Do NOT use markdown code blocks (like ```text or ```) "
                "or quotes to wrap the image prompt. You MUST NOT state that you cannot generate images directly, nor tell the user "
                "to copy and paste the prompt, nor suggest using third-party tools. Do NOT ask if the user wants to adjust details of the prompt. "
                "Limit your response ONLY to a brief confirmation in the user's language and the bracketed API tag on a new line. "
                "The bracketed tag is a functional system command and the ONLY way the application renders the image. "
                "If you omit the `[GENERATE_IMAGE: ...]` tag, the image will not be generated.]"
            )

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

            kwargs["temperature"] = temp
            kwargs["top_p"] = p_val
            kwargs["max_tokens"] = tokens_val

            logger.info(f"Sending to Perplexity with kwargs keys: {list(kwargs.keys())}")
            fibonacci_wait = wait_chain(*[wait_fixed(s) for s in PERPLEXITY_RETRY_SEQUENCE])
            response = None
            for attempt in Retrying(stop=stop_after_attempt(len(PERPLEXITY_RETRY_SEQUENCE)), wait=fibonacci_wait, reraise=True):
                with attempt:
                    response = self.perplexity_client.chat.completions.create(**kwargs)

            if not response or not hasattr(response, "choices") or not response.choices:
                return "Error: Empty or invalid response from Perplexity API.", None

            reply = response.choices[0].message.content
            if not reply:
                reply = f"Error: {self._handle_empty_response(response)}."
            else:
                reply = self._clean_reply_UX(reply, user_query, force_language)

            usage = getattr(response, "usage", None)
            token_info = {
                "prompt_tokens": getattr(usage, 'prompt_tokens', 0) if usage else 0,
                "candidates_tokens": getattr(usage, 'completion_tokens', 0) if usage else 0,
                "total_tokens": getattr(usage, 'total_tokens', 0) if usage else 0,
                "thinking_tokens": 0
            }
            return reply, self._flush_aux_tokens(token_info)
        except Exception as e:
            logger.error(f"Perplexity error: {e}")
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
        current_date_str, current_time_str, current_year_str = get_current_date_and_time_strings()

        target_lang, lang_name = detect_user_conversation_language(user_input, history, force_language)
        is_spanish = target_lang.lower().startswith("es")
        sys_instr = ""
        if is_spanish:
            sys_instr += "[REQUISITO CRÍTICO DE IDIOMA] ¡Debes responder ÚNICAMENTE en Español! Toda tu respuesta debe escribirse en Español. Ignora el idioma del sistema del equipo y cualquier resultado de búsqueda o contenido web raspado en otros idiomas.\n\n"
        else:
            sys_instr += f"[CRITICAL LANGUAGE REQUIREMENT] You MUST reply ONLY in {lang_name}! Your entire response must be written in {lang_name}. Ignore computer system language settings and any web search results or scraped content in other languages.\n\n"
        sys_instr += self.system_instruction_perplexity
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
            f"Do not break character by mentioning your training limitations."
        )
        sys_instr += (
            f"\n\n[CRITICAL GROUNDING RULE] Since the current year is {current_year_str}, you MUST treat any events, tournaments, or matches from 2024 and 2025 as historical and completed. "
            f"Never discuss them as future, current, or upcoming. You MUST use your live search capabilities to query for current events, news, or live results specifically targeting {current_year_str} (e.g., World Cup 2026 live updates). "
            f"You MUST rely on the current live web contents, live-score pages, and search updates you retrieve to report match results and live scores. "
            f"Present the scores, schedules, and team/match details you find on live-score or web search sites directly as the actual current results, without any disclaimers about them being simulator, mock, staging, or placeholder data. "
            f"Never claim that the scores are fake or simulated; report them confidently as the active results."
        )
        sys_instr += (
            f"\n\n[CRITICAL TIMEZONE & DATE ALIGNMENT RULE]\n"
            f"- Today's date and time in the user's local timezone is: {current_date_str} at {current_time_str}.\n"
            f"- You MUST use this local date and time as your primary temporal anchor for all queries and search assessments.\n"
            f"- When search results show event kickoff times or schedules in other timezones (e.g. CET, CEST, UTC, BST, ET, PT), you MUST convert them to the user's local timezone ({USER_SYSTEM_TIMEZONE}) and offset to check if the event is currently in progress, already completed, or in the future.\n"
            f"- For example, if a match schedule is listed as 'June 27 at 02:00 CET/CEST' (which is 00:00 UTC on June 27), and the user's current time is Friday, June 26 at 08:20 PM (01:20 AM UTC on June 27), the match is currently in progress (80+ minutes in) and NOT 'later today' or in the future. You MUST do this calculation carefully before answering."
        )
        sys_instr += "\n\n[CRITICAL FORMATTING RULE] If the user says goodbye, indicates they are leaving, or wants to end the conversation, you MUST append the exact tag '[GOODBYE]' (including the brackets) to the very end of your final response."
        sys_instr += CRITICAL_DOCUMENT_ANALYSIS_RULE
        if force_language:
            lang_name = resolve_lang_name(force_language)
            is_spanish = force_language.startswith("es")
            if is_spanish:
                sys_instr += f"\n\n[CRITICAL LANGUAGE REQUIREMENT] ¡INSTRUCCIÓN CRÍTICA DE IDIOMA! Responde ÚNICAMENTE en Español. Ignora el inglés de los resultados de búsqueda. Tu respuesta debe estar completamente en Español."
            else:
                sys_instr += f"\n\n[CRITICAL LANGUAGE REQUIREMENT] You MUST reply ONLY in {lang_name}. Ignore any English in the search results or system prompts. Your entire response must be in {lang_name}."

        user_query = user_input or ""
        scraped_urls = []
        if user_input:
            user_input, scraped_urls = self._process_urls_in_input(user_input, force_language=force_language)
        scraped_content = ""
        if scraped_urls and user_input and len(user_input) > len(user_query):
            scraped_content = user_input[len(user_query):].strip()

        # Automated Search via Gemini Google Search pre-pass (same as OpenAI, Anthropic, DeepSeek)
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
                        system_notes.append(f"[Nota del Sistema: Resultados de la búsqueda web en tiempo real provistos por el SISTEMA para tu conocimiento:\n{search_results}\n\nINSTRUCCIÓN CRÍTICA: Responde al usuario directamente utilizando los hechos anteriores. Responde enteramente en ESPAÑOL. NUNCA digas 'en los resultados que compartiste' o 'según los datos que me diste' (los datos fueron obtenidos por el SISTEMA, no por el usuario). NO alucines ningún hecho no presente en los resultados. NO uses corchetes de citas como [1] o [12]. Presenta los hechos con confianza directamente como tu propio conocimiento.]")
                    else:
                        system_notes.append(f"[System Note: Real-time web search results provided by the SYSTEM for your knowledge:\n{search_results}\n\nCRITICAL INSTRUCTION: Answer the user directly using the facts above. NEVER say 'in the results you shared' or 'according to the data you provided' (these results were retrieved by the SYSTEM, not the user). DO NOT include bracketed citation numbers like [1] or [12]. Present the facts confidently directly as your own knowledge.]")

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
                if not content or not content.strip():
                    content = "."
                messages.append({"role": role, "content": content})

        file_contexts = []
        for f in (files or []):
            mime = f.get("mime_type", "")
            name = f.get("name", "unnamed_file")

            # Safely resolve file bytes: memory → base64 → disk path
            file_bytes = f.get("bytes")
            if file_bytes is None:
                if "base64" in f:
                    try:
                        file_bytes = base64.b64decode(f["base64"])
                    except Exception as b64_err:
                        logger.error(f"Error decoding base64 for file {name}: {b64_err}")
                        continue
                else:
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

            if mime.startswith("image/"):
                logger.info(f"Describing image for Perplexity: {name}")
                image_desc = self.describe_image(file_bytes, mime)
                file_contexts.append(f"[SYSTEM NOTE: The user uploaded an image named '{name}'. The system analyzed this image using Gemini Flash and generated the following detailed visual description/transcription of it. Please refer to this description directly to address the user's questions about the image:]\n\n{image_desc}")
            elif mime.startswith("audio/"):
                logger.info(f"Transcribing audio for Perplexity: {name}")
                transcription, err = self.transcribe_audio(file_bytes, mime)
                if err:
                    transcription = f"[Error transcribing audio: {err}]"
                suffix = ".mp3" if "mp3" in mime or "mpeg" in mime else ".wav"
                metadata = self._extract_audio_metadata_from_bytes(file_bytes, suffix)
                meta_block = f"[Audio/Song Metadata:]\n{metadata}\n\n" if metadata else ""
                file_contexts.append(f"[SYSTEM NOTE: The user uploaded an audio file named '{name}'. The system transcribed its contents for you below. Please refer to this transcription and metadata directly to answer the user's questions or analyze the song lyrics:]\n\n{meta_block}{transcription}")
            elif mime.startswith("video/"):
                logger.info(f"Describing video for Perplexity: {name}")
                video_description = self.describe_video(file_bytes, mime, user_query)
                file_contexts.append(f"[SYSTEM NOTE: The user uploaded a video file named '{name}'. The system generated a detailed scene-by-scene description of its visuals and dialogue for you below. Please analyze this text description directly to address the user's query:]\n\n{video_description}")
            elif mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" or name.lower().endswith(".docx"):
                text = self._extract_text_from_docx(file_bytes)
                file_contexts.append(f"[SYSTEM NOTE: The user uploaded a Word document '{name}'. Its text has been automatically extracted for you below. DO NOT refuse to analyze it. DO NOT say you cannot read documents. Analyze the following text directly:]\n\n{text}")

                docx_images = self._extract_images_from_docx(file_bytes)
                for img in docx_images:
                    img_desc = self.describe_image(img["bytes"], img.get("mime_type", "image/png"))
                    file_contexts.append(f"[SYSTEM NOTE: Image '{img['name']}' extracted from Word document '{name}']:\n\n{img_desc}")
            elif mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" or name.lower().endswith(".xlsx"):
                text = self._extract_text_from_xlsx(file_bytes)
                file_contexts.append(f"[SYSTEM NOTE: The user uploaded an Excel spreadsheet '{name}'. Its text has been automatically extracted for you below. DO NOT refuse to analyze it. DO NOT say you cannot read spreadsheets. Analyze the following text directly:]\n\n{text}")
            elif mime == "application/vnd.openxmlformats-officedocument.presentationml.presentation" or name.lower().endswith(".pptx"):
                text = self._extract_text_from_pptx(file_bytes)
                file_contexts.append(f"[SYSTEM NOTE: The user uploaded a PowerPoint presentation '{name}'. Its text has been automatically extracted for you below. DO NOT refuse to analyze it. DO NOT say you cannot read PowerPoints. Analyze the following text directly:]\n\n{text}")
            elif mime == "application/pdf":
                text = self._extract_text_from_pdf(file_bytes, user_query=user_query)
                file_contexts.append(f"[SYSTEM NOTE: The user uploaded a PDF document '{name}'. Its text has been automatically extracted for you below. DO NOT refuse to analyze it. DO NOT say you cannot read PDFs. Analyze the following text directly:]\n\n{text}")

                pdf_images = self._extract_images_from_pdf(file_bytes)
                for img in pdf_images:
                    img_desc = self.describe_image(img["bytes"], img.get("mime_type", "image/png"))
                    file_contexts.append(f"[SYSTEM NOTE: Image '{img['name']}' extracted from PDF '{name}']:\n\n{img_desc}")
            elif self._is_text_or_code_file(mime, name):
                text = self._try_decode_as_text(file_bytes, mime, name)
                if text is not None:
                    file_contexts.append(f"[Content of {name}]:\n{text}")
                else:
                    file_contexts.append(f"[System Note: The user attached a file named '{name}'. However, this file format ({mime}) is not natively supported by this AI model yet. Please politely inform the user that you cannot analyze this specific file type.]")
            else:
                file_contexts.append(f"[System Note: The user attached a file named '{name}'. However, this file format ({mime}) is not natively supported by this AI model yet. Please politely inform the user that you cannot analyze this specific file type.]")

        # Assemble parts putting user query last
        parts = []
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
            user_input = "\n\n".join(parts)
        else:
            user_input = user_query

        # Check if the query is a request to generate/create/draw an image
        lower_query = user_query.lower()
        is_img_req = any(kw in lower_query for kw in [
            "genera una imagen", "generar una imagen", "genera un dibujo", "generar un dibujo",
            "crea una imagen", "crear una imagen", "genera imagen", "crea imagen", "dibuja", "dibujar",
            "generate an image", "create an image", "draw ", "painting of", "picture of", "imagen de",
            "foto de", "photo of"
        ])
        if is_img_req:
            user_input += (
                "\n\n[CRITICAL UX INSTRUCTION: Respond CONFIDENTELY in the user's language (e.g. in Spanish: '¡Por supuesto! Aquí tienes la imagen:') "
                "confirming the generation, and you MUST append the exact API tag: `[GENERATE_IMAGE: <descriptive visual prompt in English (NEVER use layout words like 'infographic', 'poster', 'chart', 'diagram', or 'text boxes')>]` "
                "on a new line at the very end of your response. IMPORTANT: Do NOT use markdown code blocks (like ```text or ```) "
                "or quotes to wrap the image prompt. You MUST NOT state that you cannot generate images directly, nor tell the user "
                "to copy and paste the prompt, nor suggest using third-party tools. Do NOT ask if the user wants to adjust details of the prompt. "
                "Limit your response ONLY to a brief confirmation in the user's language and the bracketed API tag on a new line. "
                "The bracketed tag is a functional system command and the ONLY way the application renders the image. "
                "If you omit the `[GENERATE_IMAGE: ...]` tag, the image will not be generated.]"
            )

        messages.append({"role": "user", "content": user_input})
        logger.info(f"Messages with files: {messages}")

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

            logger.info(f"Sending to Perplexity with kwargs keys: {list(kwargs.keys())}")
            fibonacci_wait = wait_chain(*[wait_fixed(s) for s in PERPLEXITY_RETRY_SEQUENCE])
            response = None
            for attempt in Retrying(stop=stop_after_attempt(len(PERPLEXITY_RETRY_SEQUENCE)), wait=fibonacci_wait, reraise=True):
                with attempt:
                    response = self.perplexity_client.chat.completions.create(**kwargs)

            if not response or not hasattr(response, "choices") or not response.choices:
                return "Error: Empty or invalid response from Perplexity API.", None

            reply = response.choices[0].message.content
            if not reply:
                reply = f"Error: {self._handle_empty_response(response)}."
            else:
                reply = self._clean_reply_UX(reply, user_query, force_language)

            usage = getattr(response, "usage", None)
            token_info = {
                "prompt_tokens": getattr(usage, 'prompt_tokens', 0) if usage else 0,
                "candidates_tokens": getattr(usage, 'completion_tokens', 0) if usage else 0,
                "total_tokens": getattr(usage, 'total_tokens', 0) if usage else 0,
                "thinking_tokens": 0
            }
            return reply, self._flush_aux_tokens(token_info)
        except Exception as e:
            logger.error(f"Perplexity error: {e}")
            return f"Error: {str(e)}", None

    def _clean_messages_for_alternation(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        system_messages = [m for m in messages if m["role"] == "system"]
        other_messages = [m for m in messages if m["role"] != "system"]

        cleaned = []
        expected_role = "user"

        for msg in other_messages:
            role = msg["role"]
            raw_content = msg.get("content", "")
            if isinstance(raw_content, list):
                # Extract text parts if content is multimodal from another provider
                text_parts = []
                for part in raw_content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                    elif isinstance(part, str):
                        text_parts.append(part)
                content = "\n".join(text_parts).strip()
            elif isinstance(raw_content, str):
                content = raw_content.strip()
            else:
                content = str(raw_content or "").strip()

            if not content:
                content = "."

            if role == expected_role:
                cleaned.append({"role": role, "content": content})
                expected_role = "assistant" if role == "user" else "user"
            else:
                if not cleaned:
                    continue
                else:
                    cleaned[-1]["content"] += f"\n\n{content}"

        # Apply truncation to ensure no message exceeds 100KB limit (approx 95,000 characters to be safe)
        final_messages = system_messages + cleaned
        for msg in final_messages:
            content = msg.get("content", "")
            if not isinstance(content, str):
                content = str(content)
            if not content.strip():
                content = "…"  # placeholder to satisfy API non-whitespace requirement
            if len(content) > 95000:
                logger.warning(f"Truncating message role {msg['role']} from {len(content)} to 95000 characters due to Perplexity 100KB limit.")
                content = content[:95000] + "\n\n[TRUNCATED: Content exceeded Perplexity's 100KB message limit]"
            msg["content"] = content

        return final_messages

    def _clean_reply_UX(self, reply: str, user_query: str, force_language: Optional[str] = None) -> str:
        """Cleans Perplexity's reply when an image or audio tag is generated,
        making it appear as if Perplexity created the media natively.
        Uses only simple string methods, no regex, and detects user language.
        Handles three cases:
          1. Perplexity wrote the correct [GENERATE_IMAGE: ...] tag.
          2. Perplexity wrapped the prompt in a markdown ``` code block.
          3. Perplexity wrote the prompt as plain text then said 'Copia y pega...' / 'Copy and paste...'.
        """
        if not reply:
            return reply

        # Strip raw citation brackets like [1], [12], [1][12]
        reply = re.sub(r'\[\d+\]', '', reply)
        # Strip hallucinated system context attribution phrases
        reply = re.sub(r'En los resultados que compartiste,?\s*', '', reply, flags=re.IGNORECASE)
        reply = re.sub(r'De acuerdo con los resultados que compartiste,?\s*', '', reply, flags=re.IGNORECASE)
        reply = re.sub(r'In the results you shared,?\s*', '', reply, flags=re.IGNORECASE)
        reply = re.sub(r'Based on the results you shared,?\s*', '', reply, flags=re.IGNORECASE)

        lower_reply = reply.lower()

        # Determine language
        is_spanish = True
        if force_language:
            is_spanish = force_language.lower().startswith("es")
        else:
            lower_q = user_query.lower()
            english_keywords = ["generate ", "create ", "draw ", "photo of", "picture of", "painting of"]
            if any(kw in lower_q for kw in english_keywords):
                is_spanish = False

        # Helper: build clean confirmation + tag string
        def _build_response(prompt_text: str) -> str:
            tag = f"[GENERATE_IMAGE: {prompt_text.strip()}]"
            subject = user_query.strip()
            lower_subject = subject.lower()
            prefixes = [
                "genera una imagen de", "genera un dibujo de", "genera una foto de",
                "crea una imagen de", "crear una imagen de", "dibuja a", "dibuja",
                "generate an image where", "generate an image of", "create an image of", "draw a", "draw",
                "genera una imagen", "generar una imagen", "crea una imagen", "crear una imagen"
            ]
            for prefix in prefixes:
                if lower_subject.startswith(prefix):
                    subject = subject[len(prefix):].strip()
                    break
            subject = subject.rstrip('.!? ')
            if is_spanish:
                confirmation = f"¡Por supuesto! Aquí tienes la imagen solicitada:" if subject else "¡Por supuesto! Aquí tienes la imagen solicitada:"
            else:
                confirmation = f"Sure! Here is the image requested:" if subject else "Sure! Here is the image requested:"
            return f"{confirmation}\n\n{tag}"

        # Helper: validate that the extracted text is likely a visual prompt, not code or song chords
        def _is_valid_image_prompt(prompt_str: str) -> bool:
            if not prompt_str:
                return False
            if len(prompt_str) > 1200:
                return False
            p_lower = prompt_str.lower()
            programming = [
                "def ", "import ", "const ", "let ", "var ", "function", "return ", "print(",
                "console.log", "public class", "void main", "<html>", "xml", "json", "select ", "insert into"
            ]
            if any(kw in p_lower for kw in programming):
                return False
            chords_lyrics = [
                "[intro]", "[verso", "[coro]", "[bridge]", "[chorus]", "[outro]", "[solo]",
                "sus4", "maj7", "min7", "add9"
            ]
            if any(kw in p_lower for kw in chords_lyrics):
                return False
            if " - " in prompt_str and len(prompt_str) < 100:
                parts = [part.strip() for part in prompt_str.split("-")]
                if len(parts) >= 3 and all(len(part) <= 5 for part in parts):
                    return False
            return True

        # Check if the user query suggests they want to generate an image
        # If not, we skip Case 2 and Case 3 of image cleaning to avoid false positives on normal code blocks or copy-paste text.
        is_img_req = False
        lower_q = user_query.lower()
        img_keywords = [
            "imagen", "dibujo", "foto", "dibuja", "portrait", "ilustra", "ilustracion",
            "portada", "image", "draw", "photo", "picture", "painting", "illustration",
            "sketch", "logo", "wallpaper", "fondo de pantalla"
        ]
        if any(kw in lower_q for kw in img_keywords):
            is_img_req = True

        # ── Case 1: correct bracketed API tag ────────────────────────────────
        idx = lower_reply.find("[generate_image:")
        if idx != -1:
            end_idx = reply.find("]", idx)
            if end_idx != -1:
                return _build_response(reply[idx + len("[generate_image:"):end_idx].strip())

        # ── Case 2: prompt wrapped in a markdown ``` code block ───────────────
        if is_img_req:
            code_start = reply.find("```")
            if code_start != -1:
                code_end = reply.find("```", code_start + 3)
                if code_end != -1:
                    prompt_text = reply[code_start + 3 : code_end].strip()
                    for lang_label in ("text\n", "markdown\n", "text ", "markdown "):
                        if prompt_text.lower().startswith(lang_label):
                            prompt_text = prompt_text[len(lang_label):].strip()
                            break
                    if prompt_text and _is_valid_image_prompt(prompt_text):
                        return _build_response(prompt_text)

        # ── Case 3: plain-text prompt followed by "Copia y pega" / "Copy and paste" ──
        if is_img_req:
            copy_paste_markers = [
                "copia y pega este prompt",
                "copia y pega el prompt",
                "copy and paste this prompt",
                "copy and paste the prompt",
                "pega este prompt",
                "paste this prompt",
            ]
            cut_idx = -1
            for marker in copy_paste_markers:
                cut_idx = lower_reply.find(marker)
                if cut_idx != -1:
                    break

            if cut_idx != -1:
                # Everything before the marker is the raw image prompt Perplexity wrote
                raw_prompt = reply[:cut_idx].strip()
                # Strip trailing citation numbers like [1][2][3] or [1] that Perplexity appends
                while raw_prompt and raw_prompt[-1] == "]":
                    bracket_start = raw_prompt.rfind("[", 0, len(raw_prompt) - 1)
                    if bracket_start != -1 and raw_prompt[bracket_start + 1 : -1].isdigit():
                        raw_prompt = raw_prompt[:bracket_start].strip()
                    else:
                        break
                if raw_prompt and _is_valid_image_prompt(raw_prompt):
                    return _build_response(raw_prompt)

        # ── GENERATE_AUDIO tag ────────────────────────────────────────────────
        idx_aud = lower_reply.find("[generate_audio:")
        if idx_aud != -1:
            end_idx = reply.find("]", idx_aud)
            if end_idx != -1:
                tag_aud = reply[idx_aud:end_idx+1]
                subject = user_query.strip()
                lower_subject = subject.lower()
                prefixes = [
                    "genera un audio de", "generar un audio de", "crea un audio de", "crear un audio de",
                    "genera un sonido de", "generar un sonido de", "crea un sonido de", "crear un sonido de",
                    "genera audio de", "genera sonido de", "generate audio of", "create audio of",
                    "genera un audio", "generar un audio", "genera sonido", "generate audio"
                ]
                for prefix in prefixes:
                    if lower_subject.startswith(prefix):
                        subject = subject[len(prefix):].strip()
                        break
                subject = subject.rstrip('.!? ')
                if is_spanish:
                    confirmation = f"¡Por supuesto! Aquí tienes el audio solicitado:" if subject else "¡Por supuesto! Aquí tienes el audio solicitado:"
                else:
                    confirmation = f"Sure! Here is the audio requested:" if subject else "Sure! Here is the audio requested:"
                return f"{confirmation}\n\n{tag_aud}"

        return reply

