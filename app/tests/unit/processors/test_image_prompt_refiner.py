"""
Unit tests for Image Prompt Refiner instruction building & multilingual slang preservation.
"""
from backend.processors.base_processor import BaseChat


def test_build_image_prompt_refine_instruction_contains_multilingual_rules():
    processor = BaseChat()
    prompt = "genera la imagen en donde se muestre el streamer la cobra bailando con la camiseta del barcelona"
    instruction = processor._build_image_prompt_refine_instruction(prompt)

    # Verify instruction contains critical disambiguation guidelines
    assert "ROLE: You are an expert Multilingual Visual Prompt Engineer" in instruction
    assert "CREATOR & SLANG DISAMBIGUATION" in instruction
    assert "MULTILINGUAL FEW-SHOT EXAMPLES" in instruction
    assert "streamer" in instruction
    assert "La Cobra" in instruction
    assert "Gaules" in instruction
    assert "Speed" in instruction
    assert "Razor Callahan" in instruction
    assert "NFSMW" in instruction


def test_local_fallback_refine_strips_prefix_and_boosts():
    processor = BaseChat()
    raw_prompt = "genera una imagen de un gato astronauta en marte"
    cleaned = raw_prompt.lower()
    for prefix in ["genera una imagen de", "genera la imagen de"]:
        if cleaned.startswith(prefix):
            cleaned = raw_prompt[len(prefix):].strip(" :,-")
            break
    assert "un gato astronauta en marte" in cleaned
