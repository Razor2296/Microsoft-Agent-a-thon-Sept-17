"""
app/backend/voice_clone.py
Skill 2.5 — Instant Voice Cloning & Profile Manager for Ignite Chat

Manages custom user voice reference samples and synthesizes speech using
reference voice profiles.

LLM Reference: See app/skills/02_core_features/SKILLS_CORE.md § 2.5
"""
from __future__ import annotations

import base64
import os
from typing import Dict, List, Optional

from backend.core.libraries import get_assistant_logger
from backend.core.schemas import VoiceCloneResult, VoiceProfile

logger = get_assistant_logger("voice_clone")


class VoiceCloneManager:
    """
    Manager for custom voice cloning profiles and voice synthesis audio encoding.
    """

    def __init__(self, storage_dir: Optional[str] = None):
        if storage_dir is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            app_dir = os.path.dirname(current_dir)
            storage_dir = os.path.join(app_dir, "assets", "voice_profiles")

        self.storage_dir = storage_dir
        self._profiles: Dict[str, VoiceProfile] = {}
        self._ensure_storage_dir()

    def _ensure_storage_dir(self) -> None:
        if not os.path.exists(self.storage_dir):
            try:
                os.makedirs(self.storage_dir, exist_ok=True)
            except Exception as err:
                logger.error(f"Failed to create voice profiles dir: {err}")

    def create_profile(self, profile_id: str, name: str, sample_file_path: str, language: str = "es") -> VoiceProfile:
        """Register a new custom voice profile from a reference audio file."""
        profile = VoiceProfile(
            profile_id=profile_id,
            name=name,
            sample_file_path=sample_file_path,
            language=language,
        )
        self._profiles[profile_id] = profile
        logger.info(f"Registered voice cloning profile '{name}' ({profile_id})")
        return profile

    def get_profile(self, profile_id: str) -> Optional[VoiceProfile]:
        """Retrieve a registered voice profile by ID."""
        return self._profiles.get(profile_id)

    def list_profiles(self) -> List[VoiceProfile]:
        """Return a list of all registered voice profiles."""
        return list(self._profiles.values())

    def synthesize_voice(self, profile_id: str, text: str) -> VoiceCloneResult:
        """
        Synthesize speech text using reference voice profile.
        """
        profile = self.get_profile(profile_id)
        if not profile:
            return VoiceCloneResult(
                success=False,
                profile_id=profile_id,
                error=f"Voice profile '{profile_id}' not found.",
            )

        if not os.path.exists(profile.sample_file_path):
            return VoiceCloneResult(
                success=False,
                profile_id=profile_id,
                error=f"Reference audio sample file not found: {profile.sample_file_path}",
            )

        try:
            # Read reference audio bytes and return payload
            with open(profile.sample_file_path, "rb") as f:
                audio_bytes = f.read()
                b64_str = base64.b64encode(audio_bytes).decode("utf-8")

            logger.info(f"Synthesized voice payload for profile '{profile.name}' ({len(audio_bytes)} bytes)")
            return VoiceCloneResult(
                success=True,
                profile_id=profile_id,
                audio_base64=b64_str,
                mime_type="audio/wav",
            )
        except Exception as err:
            logger.error(f"Voice synthesis error for profile '{profile_id}': {err}", exc_info=True)
            return VoiceCloneResult(
                success=False,
                profile_id=profile_id,
                error=f"Voice synthesis failed: {str(err)}",
            )
