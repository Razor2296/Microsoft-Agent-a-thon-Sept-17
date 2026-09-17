// app/frontend/models.js
// Logic for model friendly names mapping and dropdown updates

let isPopulatingModels = false; // Guard against cascade when repopulating model list

// Function to format model IDs to friendly names (Streamlit style but cleaner)
function formatModelName(id) {
    if (!id) return "";

    // Custom mappings for common models
    const customMappings = {
        "gpt-4o": "GPT-4o",
        "gpt-4o-mini": "GPT-4o Mini",
        "gpt-4-turbo": "GPT-4 Turbo",
        "gpt-4": "GPT-4",
        "gpt-4.1": "GPT-4.1",
        "gpt-4.1-mini": "GPT-4.1 Mini",
        "gpt-4.1-nano": "GPT-4.1 Nano",
        "o1": "GPT-o1",
        "o3": "GPT-o3",
        "o3-mini": "GPT-o3 Mini"
    };

    const lowerId = id.toLowerCase();
    if (customMappings[lowerId]) {
        return customMappings[lowerId];
    }

    // Handle standard patterns:
    let name = id;

    // Replace claude version hyphens like "4-6", "4-7", "4-8" with dots "4.6", "4.7", "4.8"
    name = name.replace(/(\d+)-(\d+)/g, "$1.$2");

    // Replace other hyphens with spaces
    name = name.replace(/-/g, " ");

    // Capitalize words correctly
    let formatted = name.split(' ').map(word => {
        if (!word) return "";

        const lowerWord = word.toLowerCase();

        // Specific word corrections
        if (lowerWord === "gpt") return "GPT";
        if (lowerWord === "deepseek") return "Deepseek";
        if (lowerWord === "gemini") return "Gemini";
        if (lowerWord === "claude") return "Claude";
        if (lowerWord === "pro") return "Pro";
        if (lowerWord === "flash") return "Flash";
        if (lowerWord === "lite") return "Lite";
        if (lowerWord === "preview") return "Preview";
        if (lowerWord === "opus") return "Opus";
        if (lowerWord === "sonnet") return "Sonnet";
        if (lowerWord === "qwen") return "Qwen";
        if (lowerWord === "grok") return "Grok";

        // Handle roman numerals or versions like "v4" -> "V4"
        if (/^v\d+$/.test(lowerWord)) {
            return "V" + lowerWord.substring(1).toUpperCase();
        }

        // Default capitalize
        return word.charAt(0).toUpperCase() + word.slice(1);
    }).join(' ');

    // Fallback prefix for unknown OpenAI models
    if ((formatted.startsWith("GPT") || formatted.toLowerCase().startsWith("o1") || formatted.toLowerCase().startsWith("o3")) && !formatted.startsWith("OpenAI")) {
        formatted = "OpenAI " + formatted;
    }
    return formatted;
}

// Functions to update models
function populateModels(options, selected) {
    isPopulatingModels = true;
    const sel = document.getElementById('model-select');
    sel.innerHTML = '';
    options.forEach(opt => {
        const option = document.createElement('option');
        option.value = opt;
        option.textContent = formatModelName(opt);
        if (opt === selected) option.selected = true;
        sel.appendChild(option);
    });
    sel.dataset.prevValue = sel.value;
    isPopulatingModels = false;
}

// Functions to update header info
function updateHeaderInfo(provider) {
    let name = `${provider} Assistant`;
    let label = provider.toUpperCase();
    let color = '#3186FF';

    if (provider && provider.startsWith("group_")) {
        name = window.customGroups && window.customGroups[provider] ? window.customGroups[provider].name : "AI Group";
        label = "GROUP";
        color = '#00a884'; // WhatsApp green
    } else {
        if (provider === 'DeepSeek') color = '#4C6BFE';
        else if (provider === 'OpenAI') color = '#10a37f';
        else if (provider === 'Anthropic') color = '#cc785c';
        else if (provider === 'Perplexity') color = '#19a3b8';
        else if (provider === 'Grok') color = '#09090B';
    }

    document.getElementById('header-title').textContent = name;
    document.getElementById('header-avatar-container').innerHTML = getAvatarHtml(provider, true);

    // Set CSS variables for dynamic provider styling
    document.documentElement.style.setProperty('--provider-color', color);
    document.documentElement.style.setProperty('--provider-label', `"${label}"`);
}

