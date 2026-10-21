// Global State
let currentGameData = null;
let currentFacts = null;
let currentCodexPromptPackage = null;

// DOM Elements
const generatorForm = document.getElementById("generator-form");
const isPreorderCheckbox = document.getElementById("is_preorder");
const releaseDateGroup = document.getElementById("release-date-group");
const releaseDateInput = document.getElementById("release_date_note");

const resultsCard = document.getElementById("results-card");
const initialView = document.getElementById("initial-state-view");
const loadingView = document.getElementById("loading-state-view");
const contentView = document.getElementById("content-state-view");
const codexPromptView = document.getElementById("codex-prompt-state-view");
const loadingPhaseText = document.getElementById("loading-phase-text");

// Fields
const outProductName = document.getElementById("out_product_name");
const outSeoTitle = document.getElementById("out_seo_title");
const outMetaDescription = document.getElementById("out_meta_description");
const outShortDescription = document.getElementById("out_short_description");
const outTags = document.getElementById("out_tags");
const outExtendedDescriptionHtml = document.getElementById("out_extended_description_html");
const outBoxContents = document.getElementById("out_box_contents");
const htmlPreviewContainer = document.getElementById("html-preview-container");
const tagsPillsContainer = document.getElementById("tags-pills-container");
const codexPromptOutput = document.getElementById("codex_prompt_output");
const codexResponseInput = document.getElementById("codex_response_input");
const codexSourcesList = document.getElementById("codex-sources-list-container");

// Spec Fields
const specPublisher = document.getElementById("spec_publisher");
const specDesigner = document.getElementById("spec_designer");
const specIllustrator = document.getElementById("spec_illustrator");
const specEditionLanguage = document.getElementById("spec_edition_language");
const specManualLanguage = document.getElementById("spec_manual_language");
const specPlayers = document.getElementById("spec_players");
const specAge = document.getElementById("spec_age");
const specPlayTime = document.getElementById("spec_play_time");
const specInstructionPdf = document.getElementById("spec_instruction_pdf");
const specPreorderField = document.getElementById("spec_preorder_field");
const specReleaseDate = document.getElementById("spec_release_date");

// Logs / Meta
const warningsBox = document.getElementById("warnings-box");
const warningsList = document.getElementById("warnings-list-container");
const sourcesList = document.getElementById("sources-list-container");
const productModeBadge = document.getElementById("product-mode-badge");

// Buttons
const generateBtn = document.getElementById("generate-btn");
const saveEditBtn = document.getElementById("save-edit-btn");
const reRunBtn = document.getElementById("re-run-btn");
const importCodexResultBtn = document.getElementById("import-codex-result-btn");
const apiConfigToggle = document.getElementById("api-config-toggle");
const apiConfigFields = document.getElementById("api-config-fields");
const apiToggleIcon = document.getElementById("api-toggle-icon");
const apiProvider = document.getElementById("api_provider");
const apiKey = document.getElementById("api_key");
const apiBaseUrl = document.getElementById("api_base_url");
const apiModel = document.getElementById("api_model");
const apiBaseUrlGroup = document.getElementById("api-base-url-group");
const apiModelGroup = document.getElementById("api-model-group");

// Phase Messages for Loading
const loadingPhases = [
    "Inicjalizacja wyszukiwania...",
    "Wyszukiwanie gry na BoardGameGeek...",
    "Wyszukiwanie polskich źródeł w wyszukiwarce...",
    "Pobieranie stron i usuwanie boilerplate...",
    "Ekstrakcja faktów za pomocą sztucznej inteligencji...",
    "Reconcylacja danych i walidacja...",
    "Generowanie unikalnego opisu i metadanych..."
];

// Initialize Preorder Event
isPreorderCheckbox.addEventListener("change", (e) => {
    if (e.target.checked) {
        releaseDateGroup.style.display = "block";
    } else {
        releaseDateGroup.style.display = "none";
        releaseDateInput.value = "";
    }
});

function getApiPayload() {
    return {
        api_provider: apiProvider.value,
        api_key: apiKey.value.trim(),
        api_base_url: apiBaseUrl.value.trim(),
        api_model: apiModel.value.trim()
    };
}

function getSelectedTone() {
    const checkedTone = document.querySelector('input[name="tone_preference"]:checked');
    return checkedTone ? checkedTone.value : "sales";
}

function getToneLabel(tone) {
    const labels = {
        standard: "Standardowy",
        sales: "Sprzedażowy",
        family: "Rodzinny",
        neutral: "Neutralny",
        short: "Krótszy"
    };
    return labels[tone] || labels.sales;
}

function updateApiFields() {
    const provider = apiProvider.value;
    const isCodexPrompt = provider === "codex_prompt";
    const showOpenAiCompatibleFields = provider === "z_ai" || provider === "deepseek" || provider === "custom" || provider === "openai";
    apiKey.closest(".form-group").style.display = isCodexPrompt ? "none" : "block";
    apiBaseUrlGroup.style.display = showOpenAiCompatibleFields ? "block" : "none";
    apiModelGroup.style.display = showOpenAiCompatibleFields ? "block" : "none";
    generateBtn.querySelector("span").textContent = isCodexPrompt ? "Przygotuj prompt" : "Generuj opis";

    if (isCodexPrompt) {
        apiKey.value = "";
        apiBaseUrl.value = "";
        apiModel.value = "";
    } else if (provider === "z_ai") {
        if (!apiBaseUrl.value) {
            apiBaseUrl.value = "https://api.z.ai/api/paas/v4/";
        }
        if (!apiModel.value) {
            apiModel.value = "glm-5.2";
        }
    } else if (provider === "deepseek") {
        if (!apiBaseUrl.value || apiBaseUrl.value === "https://api.z.ai/api/paas/v4/") {
            apiBaseUrl.value = "https://api.deepseek.com";
        }
        if (!apiModel.value || apiModel.value === "glm-5.2") {
            apiModel.value = "deepseek-v4-flash";
        }
    } else if (provider === "openai" && (apiBaseUrl.value === "https://api.z.ai/api/paas/v4/" || apiBaseUrl.value === "https://api.deepseek.com")) {
        apiBaseUrl.value = "";
    }
}

apiConfigToggle.addEventListener("click", () => {
    const isVisible = apiConfigFields.style.display !== "none";
    apiConfigFields.style.display = isVisible ? "none" : "block";
    apiToggleIcon.className = isVisible
        ? "fa-solid fa-chevron-down toggle-icon"
        : "fa-solid fa-chevron-up toggle-icon";
});

apiProvider.addEventListener("change", updateApiFields);
updateApiFields();

// Tab Navigation
const tabButtons = document.querySelectorAll(".tab-btn");
tabButtons.forEach(btn => {
    btn.addEventListener("click", () => {
        const targetTab = btn.getAttribute("data-tab");
        
        tabButtons.forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
        
        btn.classList.add("active");
        document.getElementById(targetTab).classList.add("active");
    });
});

// Setup input listeners for live updates and character counters
setupCounter(outSeoTitle, "seo_title_count");
setupCounter(outMetaDescription, "meta_desc_count");
setupCounter(outShortDescription, "short_desc_count");

outExtendedDescriptionHtml.addEventListener("input", (e) => {
    htmlPreviewContainer.innerHTML = e.target.value;
});

function collapseWhitespace(value) {
    return (value || "").replace(/\s+/g, " ").trim();
}

function normalizeHeadingText(value) {
    return collapseWhitespace(value).replace(/:$/, "").toLowerCase();
}

function isUnknownPlaceholder(value) {
    const normalized = collapseWhitespace(value)
        .toLowerCase()
        .replace(/[.:;,\-]+$/g, "")
        .replace("potweirdzonych", "potwierdzonych");
    return [
        "brak danych",
        "brak informacji",
        "brak potwierdzenia",
        "brak potwierdzonych danych",
        "brak potwierdzonej informacji",
        "brak potwierdzonych informacji",
        "nieznane",
        "nieznany",
        "nieznana",
        "nie ustalono",
        "nie potwierdzono"
    ].includes(normalized);
}

function slugifyStorePath(value) {
    const withoutCompanySuffix = collapseWhitespace(value)
        .replace(/\b(?:sp\.?\s*z\s*o\.?o\.?|s\.?a\.?|ltd\.?|inc\.?|games?)\b/gi, " ");
    return withoutCompanySuffix
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/-+/g, "-")
        .replace(/^-|-$/g, "");
}

function producerStoreUrl(publisher) {
    const slug = slugifyStorePath(publisher);
    const knownProducerUrls = {
        "2-pionki": "https://graszki.pl/2-Pionki/pr/599",
        "awaken-realms": "https://graszki.pl/Awaken-Realms/pr/608",
        "board-dice": "https://graszki.pl/BoardDice/pr/73",
        "fishbone": "https://graszki.pl/Fishbone-Game/pr/444",
        "fishbone-game": "https://graszki.pl/Fishbone-Game/pr/444",
        "gamegenic": "https://graszki.pl/Gamegenic/pr/603",
        "goliath": "https://graszki.pl/Goliath-Games/pr/453",
        "goliath-games": "https://graszki.pl/Goliath-Games/pr/453",
        "lacerta": "https://graszki.pl/Lacerta/pr/12",
        "lucky-duck": "https://graszki.pl/luckyduck",
        "nasza-ksiegarnia": "https://graszki.pl/naszaksiegarnia",
        "phalanx": "https://graszki.pl/Phalanx-Games/pr/62",
        "phalanx-games": "https://graszki.pl/Phalanx-Games/pr/62",
        "portal": "https://graszki.pl/portal",
        "portal-games": "https://graszki.pl/portal",
        "smart-flamingo": "https://graszki.pl/Smart-Flamingo/pr/455",
        "ultra-pro": "https://graszki.pl/Ultra-Pro/pr/586",
    };
    return slug ? (knownProducerUrls[slug] || "") : "";
}

function createTextLi(doc, label, value) {
    const cleanValue = collapseWhitespace(value);
    if (!cleanValue || isUnknownPlaceholder(cleanValue)) return null;

    const li = doc.createElement("li");
    const strong = doc.createElement("strong");
    strong.textContent = `${label}:`;
    li.appendChild(strong);
    li.appendChild(doc.createTextNode(` ${cleanValue}`));
    return li;
}

function createPublisherLi(doc, publisher) {
    const cleanValue = collapseWhitespace(publisher);
    if (!cleanValue || isUnknownPlaceholder(cleanValue)) return null;

    const producerUrl = producerStoreUrl(cleanValue);
    if (!producerUrl) return createTextLi(doc, "Wydawca", cleanValue);

    const li = doc.createElement("li");
    const strong = doc.createElement("strong");
    const link = doc.createElement("a");
    strong.textContent = "Wydawca:";
    link.href = producerUrl;
    link.textContent = cleanValue;
    li.appendChild(strong);
    li.appendChild(doc.createTextNode(" "));
    li.appendChild(link);
    return li;
}

function manualPdfLinkLabel(gameName, manualUrl) {
    try {
        const url = new URL(manualUrl, window.location.href);
        const pathName = decodeURIComponent(url.pathname.split("/").filter(Boolean).pop() || "");
        if (pathName.toLowerCase().endsWith(".pdf")) return pathName;
    } catch (_err) {
        // Fall through to the generated display name for non-standard pasted values.
    }
    const gameSlug = slugifyStorePath(gameName);
    return gameSlug ? `${gameSlug}-instrukcja.pdf` : "instrukcja.pdf";
}

function findSectionHeading(root, sectionName) {
    const target = normalizeHeadingText(sectionName);
    const headings = root.querySelectorAll("h1, h2, h3, h4");
    return Array.from(headings).find(h => normalizeHeadingText(h.textContent) === target) || null;
}

function getSectionNodes(heading) {
    const nodes = [];
    let node = heading ? heading.nextSibling : null;
    while (node) {
        if (node.nodeType === Node.ELEMENT_NODE && /^H[1-4]$/i.test(node.tagName)) break;
        nodes.push(node);
        node = node.nextSibling;
    }
    return nodes;
}

function removeSection(root, sectionName) {
    const heading = findSectionHeading(root, sectionName);
    if (!heading) return;
    getSectionNodes(heading).forEach(node => node.remove());
    heading.remove();
}

function getContentRoot(container) {
    return container.querySelector("div.def[itemprop='description']") || container;
}

function createSectionHeading(doc, text, referenceHeading = null) {
    const heading = doc.createElement(referenceHeading ? referenceHeading.tagName.toLowerCase() : "h2");
    heading.textContent = text;
    if (referenceHeading) {
        heading.className = referenceHeading.className;
        heading.setAttribute("style", referenceHeading.getAttribute("style") || "");
    }
    return heading;
}

function replaceListSection(root, sectionName, listItems, insertBeforeHeadingName = null) {
    const doc = root.ownerDocument;
    let heading = findSectionHeading(root, sectionName);
    const referenceHeading = findSectionHeading(root, "Dodatkowe informacje") || root.querySelector("h1, h2, h3, h4");

    if (!listItems.length) {
        removeSection(root, sectionName);
        return;
    }

    if (!heading) {
        heading = createSectionHeading(doc, `${sectionName}:`, referenceHeading);
        const insertBefore = insertBeforeHeadingName ? findSectionHeading(root, insertBeforeHeadingName) : null;
        if (insertBefore) {
            root.insertBefore(heading, insertBefore);
        } else {
            root.appendChild(heading);
        }
    } else {
        getSectionNodes(heading).forEach(node => node.remove());
    }

    const ul = doc.createElement("ul");
    listItems.forEach(item => ul.appendChild(item));
    heading.insertAdjacentElement("afterend", ul);
}

function buildBoxContentItems(doc) {
    return outBoxContents.value
        .split("\n")
        .map(line => collapseWhitespace(line))
        .filter(Boolean)
        .map(line => {
            const li = doc.createElement("li");
            li.textContent = line;
            return li;
        });
}

function buildAdditionalInfoItems(doc) {
    const items = [];
    const push = (label, value) => {
        const li = createTextLi(doc, label, value);
        if (li) items.push(li);
    };

    push("Autor", specDesigner.value);
    const publisherLi = createPublisherLi(doc, specPublisher.value);
    if (publisherLi) items.push(publisherLi);
    push("Ilustrator", specIllustrator.value);
    push("Wydanie", specEditionLanguage.value);
    push("Instrukcja", specManualLanguage.value);
    push("Liczba graczy", specPlayers.value);
    push("Zalecany wiek", specAge.value);
    push("Czas gry", specPlayTime.value);
    if (currentGameData && currentGameData.is_preorder) {
        push("Orientacyjna premiera", specReleaseDate.value);
    }
    if (specInstructionPdf.value.trim()) {
        const li = doc.createElement("li");
        const strong = doc.createElement("strong");
        const link = doc.createElement("a");
        strong.textContent = "Instrukcja PDF:";
        link.href = specInstructionPdf.value.trim();
        link.textContent = manualPdfLinkLabel(outProductName.value, specInstructionPdf.value.trim());
        link.target = "_blank";
        link.rel = "noopener";
        li.appendChild(strong);
        li.appendChild(doc.createTextNode(" "));
        li.appendChild(link);
        items.push(li);
    }
    return items;
}

const controlledAdditionalInfoLabels = new Set([
    "autor",
    "projektant",
    "wydawca",
    "ilustrator",
    "ilustracje",
    "wydanie",
    "instrukcja",
    "instrukcja pdf",
    "liczba graczy",
    "zalecany wiek",
    "wiek",
    "czas gry",
    "czas rozgrywki",
    "orientacyjna premiera"
]);

function getPreservedAdditionalInfoItems(root, doc) {
    const heading = findSectionHeading(root, "Dodatkowe informacje");
    if (!heading) return [];

    const ul = getSectionNodes(heading).find(node => node.nodeType === Node.ELEMENT_NODE && node.tagName === "UL");
    if (!ul) return [];

    return Array.from(ul.querySelectorAll(":scope > li"))
        .filter(li => {
            const text = collapseWhitespace(li.textContent);
            const label = normalizeHeadingText(text.split(":")[0] || "");
            return label && !controlledAdditionalInfoLabels.has(label);
        })
        .map(li => doc.importNode(li, true));
}

function syncSpecsToHtml() {
    if (!currentGameData || !outExtendedDescriptionHtml.value.trim()) return;

    const container = document.createElement("div");
    container.innerHTML = outExtendedDescriptionHtml.value;
    const root = getContentRoot(container);
    const preservedAdditionalItems = getPreservedAdditionalInfoItems(root, document);

    replaceListSection(root, "Zawartość pudełka", buildBoxContentItems(document), "Dodatkowe informacje");
    replaceListSection(root, "Dodatkowe informacje", [
        ...buildAdditionalInfoItems(document),
        ...preservedAdditionalItems
    ]);

    outExtendedDescriptionHtml.value = container.innerHTML;
    htmlPreviewContainer.innerHTML = outExtendedDescriptionHtml.value;
}

[
    outBoxContents,
    specPublisher,
    specDesigner,
    specIllustrator,
    specEditionLanguage,
    specManualLanguage,
    specPlayers,
    specAge,
    specPlayTime,
    specInstructionPdf,
    specReleaseDate
].forEach(element => {
    if (element) element.addEventListener("input", syncSpecsToHtml);
});

function setupCounter(inputElement, counterId) {
    const counter = document.getElementById(counterId);
    const update = () => {
        counter.textContent = `${inputElement.value.length} znaków`;
    };
    inputElement.addEventListener("input", update);
    // Initial call
    update();
}

// Intercept form submission
generatorForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    
    // Read Form Fields
    const payload = {
        product_name: document.getElementById("product_name").value,
        original_title: document.getElementById("original_title").value,
        publisher: document.getElementById("publisher").value,
        is_preorder: isPreorderCheckbox.checked,
        release_date_note: releaseDateInput.value,
        category: document.getElementById("category").value,
        target_audience: document.getElementById("target_audience").value,
        official_link: document.getElementById("official_link").value,
        manual_link: document.getElementById("manual_link").value,
        tone_preference: getSelectedTone(),
        ...getApiPayload()
    };
    
    const endpoint = payload.api_provider === "codex_prompt" ? "/api/codex-prompt" : "/api/generate";
    await runPipeline(payload, endpoint);
});

// Run generation backend call
async function runPipeline(payload, endpoint) {
    // Show Loading
    initialView.style.display = "none";
    contentView.style.display = "none";
    codexPromptView.style.display = "none";
    loadingView.style.display = "flex";
    
    // Rotate through loading phases to entertain user
    let phaseIdx = 0;
    loadingPhaseText.textContent = loadingPhases[0];
    const phaseInterval = setInterval(() => {
        phaseIdx = (phaseIdx + 1) % loadingPhases.length;
        loadingPhaseText.textContent = loadingPhases[phaseIdx];
    }, 4500);
    
    try {
        const response = await fetch(endpoint, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload)
        });
        
        clearInterval(phaseInterval);
        
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.detail || "Błąd podczas generowania opisu.");
        }
        
        const data = await response.json();
        if (data.mode === "codex_prompt") {
            populateCodexPrompt(data);
            showToast("Prompt do Codexa jest gotowy.", "success");
        } else {
            data.tone_preference = data.tone_preference || payload.tone_preference || "sales";
            populateResults(data);
            showToast("Opis wygenerowany pomyślnie!", "success");
        }
        
    } catch (err) {
        clearInterval(phaseInterval);
        showToast(err.message, "error");
        loadingView.style.display = "none";
        initialView.style.display = "flex";
    }
}

// Make it globally accessible for other functions
window.runPipeline = runPipeline;

// Populate values from response JSON
function populateResults(data) {
    currentGameData = data;
    currentCodexPromptPackage = null;
    
    // Store facts for regeneration
    currentFacts = {
        publisher: data.additional_info.publisher,
        designer: data.additional_info.designer,
        illustrator: data.additional_info.illustrator,
        edition_language: data.additional_info.edition_language,
        manual_language: data.additional_info.manual_language,
        players: data.additional_info.players,
        age: data.additional_info.age,
        play_time: data.additional_info.play_time,
        instruction_pdf: data.additional_info.instruction_pdf,
        release_date: data.release_date_note,
        box_contents: data.box_contents,
        original_sources: data.sources
    };
    
    // Hide loading, show content
    loadingView.style.display = "none";
    codexPromptView.style.display = "none";
    contentView.style.display = "flex";
    
    // Preorder status
    const toneLabel = getToneLabel(data.tone_preference || getSelectedTone());
    if (data.is_preorder) {
        productModeBadge.textContent = `Przedsprzedaż / ${toneLabel}`;
        productModeBadge.style.backgroundColor = "var(--accent-pink)";
        specPreorderField.style.display = "flex";
        specReleaseDate.value = data.release_date_note || "";
    } else {
        productModeBadge.textContent = toneLabel;
        productModeBadge.style.backgroundColor = "var(--accent-indigo)";
        specPreorderField.style.display = "none";
    }
    
    // Set Fields
    outProductName.value = data.product_name || "";
    outSeoTitle.value = data.seo_title || "";
    outMetaDescription.value = data.meta_description || "";
    outShortDescription.value = data.short_description || "";
    outTags.value = (data.tags || []).join(", ");
    
    outExtendedDescriptionHtml.value = data.extended_description_html || "";
    htmlPreviewContainer.innerHTML = data.extended_description_html || "";
    
    // Box contents
    outBoxContents.value = (data.box_contents || []).join("\n");
    
    // Spec Fields
    specPublisher.value = data.additional_info.publisher || "";
    specDesigner.value = data.additional_info.designer || "";
    specIllustrator.value = data.additional_info.illustrator || "";
    specEditionLanguage.value = data.additional_info.edition_language || "polski";
    specManualLanguage.value = data.additional_info.manual_language || "polski";
    specPlayers.value = data.additional_info.players || "";
    specAge.value = data.additional_info.age || "";
    specPlayTime.value = data.additional_info.play_time || "";
    specInstructionPdf.value = data.additional_info.instruction_pdf || "";
    
    // Update counters
    triggerEvent(outSeoTitle, "input");
    triggerEvent(outMetaDescription, "input");
    triggerEvent(outShortDescription, "input");
    
    // Tags Pills
    renderTagPills();
    
    // Warnings
    if (data.warnings && data.warnings.length > 0) {
        warningsBox.style.display = "block";
        warningsList.innerHTML = "";
        data.warnings.forEach(warn => {
            const li = document.createElement("li");
            li.textContent = warn;
            warningsList.appendChild(li);
        });
    } else {
        warningsBox.style.display = "none";
    }
    
    renderSources(sourcesList, data.sources || []);
}

function renderSources(container, sources) {
    container.innerHTML = "";
    if (sources && sources.length > 0) {
        sources.forEach(src => {
            const item = document.createElement("div");
            item.className = "source-item";
            
            const meta = document.createElement("div");
            meta.className = "source-item-meta";
            
            const link = document.createElement("a");
            link.className = "source-url";
            link.href = src.url;
            link.target = "_blank";
            link.textContent = src.title || src.url;
            
            const badge = document.createElement("span");
            badge.className = "source-type-badge";
            badge.textContent = src.source_type || "other";
            
            meta.appendChild(link);
            meta.appendChild(badge);
            item.appendChild(meta);
            
            if (src.facts_found && src.facts_found.length > 0) {
                const facts = document.createElement("div");
                facts.className = "source-facts";
                facts.textContent = `Fakty: ${src.facts_found.join(", ")}`;
                item.appendChild(facts);
            }
            
            container.appendChild(item);
        });
    } else {
        container.innerHTML = "<p style='font-size: 12px; color: var(--text-muted);'>Brak zewnętrznych źródeł.</p>";
    }
}

function populateCodexPrompt(data) {
    currentCodexPromptPackage = data;
    currentGameData = null;
    currentFacts = null;

    loadingView.style.display = "none";
    contentView.style.display = "none";
    codexPromptView.style.display = "flex";

    codexPromptOutput.value = data.prompt || "";
    codexResponseInput.value = "";
    renderSources(codexSourcesList, data.sources || []);
}

// Fire input event programmatically to update counters
function triggerEvent(element, eventName) {
    const event = new Event(eventName, { bubbles: true });
    element.dispatchEvent(event);
}

// Render pills for tags
function renderTagPills() {
    tagsPillsContainer.innerHTML = "";
    const tagsStr = outTags.value;
    if (!tagsStr) return;
    
    const tags = tagsStr.split(",").map(t => t.trim()).filter(t => t);
    tags.forEach((tag, idx) => {
        const pill = document.createElement("span");
        pill.className = "tag-pill";
        pill.textContent = tag;
        
        const remove = document.createElement("i");
        remove.className = "fa-solid fa-xmark remove-tag";
        remove.addEventListener("click", () => {
            tags.splice(idx, 1);
            outTags.value = tags.join(", ");
            renderTagPills();
        });
        
        pill.appendChild(remove);
        tagsPillsContainer.appendChild(pill);
    });
}

// Update pills when tags text field changes
outTags.addEventListener("change", renderTagPills);

// Copy value helper
window.copyValue = function(elementId) {
    const element = document.getElementById(elementId);
    if (!element) return;
    
    element.select();
    element.setSelectionRange(0, 99999); // For mobile devices
    
    navigator.clipboard.writeText(element.value)
        .then(() => {
            // Find triggering button
            const labelContainer = element.previousElementSibling;
            if (labelContainer) {
                const btn = labelContainer.querySelector(".btn-copy");
                if (btn) {
                    const origHtml = btn.innerHTML;
                    btn.innerHTML = "<i class='fa-solid fa-check'></i> Skopiowano!";
                    btn.classList.add("copied");
                    setTimeout(() => {
                        btn.innerHTML = origHtml;
                        btn.classList.remove("copied");
                    }, 2000);
                }
            }
            showToast("Skopiowano do schowka!", "success");
        })
        .catch(err => {
            showToast("Nie udało się skopiować: " + err, "error");
        });
};

window.copyTags = function() {
    copyValue("out_tags");
};

window.pasteFromClipboard = function(elementId) {
    const element = document.getElementById(elementId);
    if (!element || !navigator.clipboard) return;

    navigator.clipboard.readText()
        .then(text => {
            element.value = text;
            showToast("Wklejono ze schowka.", "success");
        })
        .catch(err => {
            showToast("Nie udało się wkleić: " + err, "error");
        });
};

// Toast message handler
function showToast(message, type = "success") {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    
    const icon = document.createElement("i");
    if (type === "success") {
        icon.className = "fa-solid fa-circle-check";
        icon.style.color = "var(--accent-teal)";
    } else {
        icon.className = "fa-solid fa-circle-exclamation";
        icon.style.color = "var(--accent-red)";
    }
    
    const text = document.createElement("span");
    text.textContent = message;
    
    const close = document.createElement("i");
    close.className = "fa-solid fa-xmark toast-close";
    close.addEventListener("click", () => {
        toast.remove();
    });
    
    toast.appendChild(icon);
    toast.appendChild(text);
    toast.appendChild(close);
    container.appendChild(toast);
    
    // Auto remove after 4 seconds
    setTimeout(() => {
        toast.style.animation = "slideIn 0.3s reverse forwards";
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// Save manual edits button
saveEditBtn.addEventListener("click", async () => {
    if (!currentGameData) return;
    
    // Prepare payload by collecting all current values from inputs
    const payload = {
        product_name: outProductName.value,
        original_title: currentGameData.original_title,
        is_preorder: currentGameData.is_preorder,
        release_date_note: specPreorderField.style.display !== "none" ? specReleaseDate.value : "",
        short_description: outShortDescription.value,
        seo_title: outSeoTitle.value,
        meta_description: outMetaDescription.value,
        tags: outTags.value.split(",").map(t => t.trim()).filter(t => t),
        extended_description_html: outExtendedDescriptionHtml.value,
        box_contents: outBoxContents.value.split("\n").map(t => t.trim()).filter(t => t),
        additional_info: {
            publisher: specPublisher.value,
            designer: specDesigner.value,
            illustrator: specIllustrator.value,
            edition_language: specEditionLanguage.value,
            manual_language: specManualLanguage.value,
            players: specPlayers.value,
            age: specAge.value,
            play_time: specPlayTime.value,
            instruction_pdf: specInstructionPdf.value
        },
        sources: currentGameData.sources,
        warnings: currentGameData.warnings
    };
    
    try {
        saveEditBtn.disabled = true;
        saveEditBtn.innerHTML = "<i class='fa-solid fa-spinner fa-spin'></i> Zapisywanie...";
        
        const response = await fetch("/api/save-manual-edit", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload)
        });
        
        const data = await response.json();
        saveEditBtn.disabled = false;
        saveEditBtn.innerHTML = "<i class='fa-solid fa-floppy-disk'></i> Zapisz poprawioną wersję";
        
        if (!response.ok) {
            throw new Error(data.detail || "Błąd podczas zapisu.");
        }
        
        showToast(data.message, "success");
        
    } catch (err) {
        saveEditBtn.disabled = false;
        saveEditBtn.innerHTML = "<i class='fa-solid fa-floppy-disk'></i> Zapisz poprawioną wersję";
        showToast(err.message, "error");
    }
});

importCodexResultBtn.addEventListener("click", async () => {
    const responseText = codexResponseInput.value.trim();
    if (!responseText) {
        showToast("Wklej wynik JSON od Codexa.", "error");
        return;
    }

    try {
        importCodexResultBtn.disabled = true;
        importCodexResultBtn.innerHTML = "<i class='fa-solid fa-spinner fa-spin'></i> Wczytywanie...";
        
        const response = await fetch("/api/import-codex-result", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ response_text: responseText })
        });
        
        const data = await response.json();
        importCodexResultBtn.disabled = false;
        importCodexResultBtn.innerHTML = "<i class='fa-solid fa-file-import'></i> Wczytaj wynik i zapisz";
        
        if (!response.ok) {
            throw new Error(data.detail || "Nie udało się wczytać wyniku Codexa.");
        }
        
        data.tone_preference = data.tone_preference || "sales";
        populateResults(data);
        showToast("Wynik Codexa zapisany.", "success");
    } catch (err) {
        importCodexResultBtn.disabled = false;
        importCodexResultBtn.innerHTML = "<i class='fa-solid fa-file-import'></i> Wczytaj wynik i zapisz";
        showToast(err.message, "error");
    }
});

// Re-run pipeline completely (re-scraping BGG and websites)
reRunBtn.addEventListener("click", () => {
    if (!currentGameData) return;
    // Just trigger submit event of generatorForm
    generatorForm.dispatchEvent(new Event("submit"));
});

// Quick Tone Regeneration Buttons
const regenBtns = document.querySelectorAll(".regen-tone-btn");
regenBtns.forEach(btn => {
    btn.addEventListener("click", async () => {
        if (!currentGameData || !currentFacts) {
            showToast("Najpierw wygeneruj opis!", "error");
            return;
        }
        
        const tone = btn.getAttribute("data-tone");
        
        // Prepare payload containing resolved facts so we don't have to scrape websites again
        const payload = {
            product_name: document.getElementById("product_name").value,
            original_title: document.getElementById("original_title").value,
            is_preorder: isPreorderCheckbox.checked,
            release_date_note: releaseDateInput.value,
            category: document.getElementById("category").value,
            target_audience: document.getElementById("target_audience").value,
            official_link: document.getElementById("official_link").value,
            manual_link: document.getElementById("manual_link").value,
            tone_preference: tone,
            resolved_facts: currentFacts,
            ...getApiPayload()
        };
        
        // Set loading message
        loadingPhaseText.textContent = "Regenerowanie opisu (zastosowanie stylu: " + tone + ")...";
        
        await runPipeline(payload, "/api/regenerate");
    });
});

// Batch Rebel workflow
const singleModeBtn = document.getElementById("single-mode-btn");
const batchModeBtn = document.getElementById("batch-mode-btn");
const singleView = document.getElementById("single-view");
const batchView = document.getElementById("batch-view");
const batchWorkspace = document.getElementById("batch-workspace");
let currentBatchId = null;
let currentBatchProduct = null;
let currentBatchOffset = 0;
const batchPageSize = 100;

function setAppMode(mode) {
    const batch = mode === "batch";
    singleView.hidden = batch;
    batchView.hidden = !batch;
    singleModeBtn.classList.toggle("active", !batch);
    batchModeBtn.classList.toggle("active", batch);
    history.replaceState(null, "", batch ? "#batch" : location.pathname);
    if (batch) loadBatches();
}

singleModeBtn.addEventListener("click", () => setAppMode("single"));
batchModeBtn.addEventListener("click", () => setAppMode("batch"));

async function batchApi(url, options = {}) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Operacja nie powiodła się.");
    return data;
}

async function fileToBase64(file) {
    const bytes = new Uint8Array(await file.arrayBuffer());
    const chunkSize = 0x8000;
    let binary = "";
    for (let index = 0; index < bytes.length; index += chunkSize) {
        binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
    }
    return btoa(binary);
}

document.getElementById("batch-import-btn").addEventListener("click", async () => {
    const button = document.getElementById("batch-import-btn");
    const skyFile = document.getElementById("batch-sky-file").files[0];
    const rebelFile = document.getElementById("batch-rebel-file").files[0];
    if (!skyFile) return showToast("Wybierz eksport produktów Sky-Shop.", "error");
    try {
        button.disabled = true;
        button.innerHTML = "<i class='fa-solid fa-spinner fa-spin'></i> Importowanie...";
        const payload = {
            name: document.getElementById("batch-name").value.trim(),
            sky_csv_base64: await fileToBase64(skyFile),
            rebel_csv_base64: rebelFile ? await fileToBase64(rebelFile) : null
        };
        const batch = await batchApi("/api/batches/import", {
            method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)
        });
        currentBatchId = batch.id;
        await loadBatches();
        showToast(`Utworzono partię ${batch.id} (${batch.total} produktów).`, "success");
    } catch (error) {
        showToast(error.message, "error");
    } finally {
        button.disabled = false;
        button.innerHTML = "<i class='fa-solid fa-file-import'></i> Utwórz partię";
    }
});

async function loadBatches() {
    try {
        const data = await batchApi("/api/batches");
        const picker = document.getElementById("batch-picker");
        picker.replaceChildren();
        for (const batch of data.items) {
            const option = document.createElement("option");
            option.value = batch.id;
            option.textContent = `${batch.name} · ${batch.id}`;
            picker.appendChild(option);
        }
        if (!currentBatchId && data.items.length) currentBatchId = data.items[0].id;
        if (currentBatchId) {
            picker.value = currentBatchId;
            batchWorkspace.hidden = false;
            await refreshBatch();
        }
    } catch (error) {
        showToast(error.message, "error");
    }
}

document.getElementById("batch-picker").addEventListener("change", event => {
    currentBatchId = event.target.value;
    currentBatchProduct = null;
    currentBatchOffset = 0;
    refreshBatch();
});
document.getElementById("batch-refresh-btn").addEventListener("click", () => currentBatchId ? refreshBatch() : loadBatches());
document.getElementById("batch-status-filter").addEventListener("change", () => {
    currentBatchOffset = 0;
    loadBatchProducts();
});

async function refreshBatch() {
    if (!currentBatchId) return;
    try {
        const batch = await batchApi(`/api/batches/${currentBatchId}`);
        document.getElementById("batch-title").textContent = batch.name;
        document.getElementById("batch-id").textContent = batch.id;
        document.getElementById("batch-report-btn").href = `/api/batches/${batch.id}/report.csv`;
        const batchLabels = {ready: "Gotowa", generating: "Generowanie", review: "Do kontroli", failed: "Błąd", interrupted: "Przerwana", completed: "Zakończona", completed_with_errors: "Zakończona z błędami", publishing: "Wysyłanie", rolling_back: "Przywracanie", rolled_back: "Przywrócona"};
        document.getElementById("batch-status").textContent = batchLabels[batch.status] || batch.status;
        const message = document.getElementById("batch-message");
        message.hidden = !batch.message;
        message.textContent = batch.message || "";
        message.classList.toggle("is-error", ["failed", "interrupted"].includes(batch.status) || /błąd|odrzucił|przerwan/i.test(batch.message || ""));
        renderBatchProgress(batch);
        const busy = ["generating", "publishing", "rolling_back"].includes(batch.status);
        document.getElementById("batch-pilot-btn").disabled = busy;
        document.getElementById("batch-full-btn").disabled = busy;
        document.getElementById("batch-publish-btn").disabled = busy;
        renderBatchStats(batch);
        await loadBatchProducts();
    } catch (error) {
        showToast(error.message, "error");
    }
}

function formatBatchDuration(seconds) {
    if (!seconds) return "0 s";
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    return hours ? `${hours} godz. ${minutes} min` : minutes ? `${minutes} min ${secs} s` : `${secs} s`;
}

function renderBatchProgress(batch) {
    const progress = batch.progress || {};
    const active = ["generating", "publishing", "rolling_back"].includes(batch.status);
    const container = document.getElementById("batch-progress");
    container.hidden = !active;
    if (!active) return;
    const done = progress.done || 0;
    const total = progress.total || 0;
    document.getElementById("batch-progress-title").textContent = `${done} z ${total} (${progress.percent || 0}%)`;
    const elapsed = formatBatchDuration(progress.elapsed_seconds || 0);
    const eta = progress.eta_seconds ? formatBatchDuration(progress.eta_seconds) : "";
    document.getElementById("batch-progress-time").textContent = eta ? `Czas: ${elapsed} · pozostało ok. ${eta}` : `Czas: ${elapsed}`;
    document.getElementById("batch-progress-bar").style.width = `${progress.percent || 0}%`;
    document.getElementById("batch-progress-current").textContent = progress.current_product ? `Aktualnie: ${progress.current_product} · zadania równoległe: ${progress.workers}` : "Przygotowywanie kolejki…";
}

function renderBatchHtmlPreview() {
    const source = document.getElementById("batch-extended-description");
    document.getElementById("batch-html-preview").innerHTML = source.value || "";
}

function renderBatchStats(batch) {
    const container = document.getElementById("batch-stats");
    const labels = {
        matched: "Dopasowane", generating: "Generowane", needs_review: "Do kontroli",
        approved: "Zatwierdzone", verified: "Zweryfikowane", failed: "Błędy",
        unchanged: "Bez zmian", rolled_back: "Przywrócone"
    };
    container.replaceChildren();
    const total = document.createElement("div");
    total.className = "batch-stat";
    total.innerHTML = `<strong>${batch.total}</strong><span>Razem</span>`;
    container.appendChild(total);
    for (const [status, count] of Object.entries(batch.counts || {})) {
        const stat = document.createElement("div");
        stat.className = `batch-stat status-${status}`;
        stat.innerHTML = `<strong>${count}</strong><span>${labels[status] || status}</span>`;
        container.appendChild(stat);
    }
}

const batchStatusLabels = {
    matched: "Dopasowany", generating: "Generowanie", needs_review: "Do kontroli",
    approved: "Zatwierdzony", verified: "Zweryfikowany", failed: "Błąd",
    unchanged: "Bez zmian", rolled_back: "Przywrócony"
};

async function loadBatchProducts() {
    if (!currentBatchId) return;
    const status = document.getElementById("batch-status-filter").value;
    const query = new URLSearchParams({limit: String(batchPageSize), offset: String(currentBatchOffset), status});
    const data = await batchApi(`/api/batches/${currentBatchId}/products?${query}`);
    const body = document.getElementById("batch-product-rows");
    body.replaceChildren();
    for (const product of data.items) {
        const row = document.createElement("tr");
        row.dataset.productId = product.product_id;
        if (currentBatchProduct?.product_id === product.product_id) row.classList.add("active");
        const checkboxCell = document.createElement("td");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.className = "batch-select-product";
        checkbox.checked = product.status === "needs_review";
        checkbox.disabled = product.status !== "needs_review";
        checkboxCell.appendChild(checkbox);
        const values = [product.product_id, product.name, product.product_type === "accessory" ? "Akcesorium" : "Gra", batchStatusLabels[product.status] || product.status];
        row.appendChild(checkboxCell);
        for (const value of values) {
            const cell = document.createElement("td");
            cell.textContent = value;
            row.appendChild(cell);
        }
        row.addEventListener("click", event => {
            if (event.target !== checkbox) openBatchProduct(product.product_id);
        });
        body.appendChild(row);
    }
    const page = Math.floor(currentBatchOffset / batchPageSize) + 1;
    const pages = Math.max(1, Math.ceil(data.total / batchPageSize));
    document.getElementById("batch-page-label").textContent = `Strona ${page} z ${pages}`;
    document.getElementById("batch-prev-btn").disabled = currentBatchOffset === 0;
    document.getElementById("batch-next-btn").disabled = currentBatchOffset + batchPageSize >= data.total;
}

document.getElementById("batch-prev-btn").addEventListener("click", () => {
    currentBatchOffset = Math.max(0, currentBatchOffset - batchPageSize);
    loadBatchProducts();
});
document.getElementById("batch-next-btn").addEventListener("click", () => {
    currentBatchOffset += batchPageSize;
    loadBatchProducts();
});

async function openBatchProduct(productId) {
    try {
        currentBatchProduct = await batchApi(`/api/batches/${currentBatchId}/products/${productId}`);
        const product = currentBatchProduct;
        document.getElementById("batch-editor").hidden = false;
        document.getElementById("batch-product-name").textContent = product.name;
        document.getElementById("batch-product-meta").textContent = `ID ${product.product_id} · ${product.match_method.toUpperCase()} · ${product.product_type}`;
        document.getElementById("batch-product-status").textContent = batchStatusLabels[product.status] || product.status;
        document.getElementById("batch-status-reason").textContent = product.status_reason || "";
        const content = product.content || {};
        document.getElementById("batch-short-description").value = content.short_description || "";
        document.getElementById("batch-seo-title").value = content.seo_title || "";
        document.getElementById("batch-meta-description").value = content.meta_description || "";
        document.getElementById("batch-tags").value = (content.tags || []).join(", ");
        document.getElementById("batch-extended-description").value = content.extended_description_html || "";
        renderBatchHtmlPreview();
        const source = product.source || {};
        const sourceLink = document.getElementById("batch-source-link");
        sourceLink.hidden = !source.rebel_page_url;
        sourceLink.href = source.rebel_page_url || "#";
        const facts = [];
        if (source.players) facts.push(`Liczba graczy: ${source.players}`);
        if (source.age) facts.push(`Wiek: ${source.age}`);
        if (source.play_time) facts.push(`Czas gry: ${source.play_time}`);
        if (source.box_contents?.length) facts.push(`Zawartość pudełka:\n${source.box_contents.map(item => `• ${item}`).join("\n")}`);
        document.getElementById("batch-source-facts").textContent = facts.join("\n\n") || "Brak dodatkowych parametrów na karcie produktu.";
        const alerts = document.getElementById("batch-product-alerts");
        alerts.replaceChildren();
        for (const text of [product.error, ...(product.warnings || [])].filter(Boolean)) {
            const alert = document.createElement("div");
            alert.className = "batch-alert";
            alert.textContent = text;
            alerts.appendChild(alert);
        }
        loadBatchProducts();
    } catch (error) {
        showToast(error.message, "error");
    }
}

async function saveBatchProduct(approved) {
    if (!currentBatchProduct) return;
    const content = {
        short_description: document.getElementById("batch-short-description").value,
        seo_title: document.getElementById("batch-seo-title").value,
        meta_description: document.getElementById("batch-meta-description").value,
        tags: document.getElementById("batch-tags").value.split(",").map(value => value.trim()).filter(Boolean),
        extended_description_html: document.getElementById("batch-extended-description").value
    };
    try {
        currentBatchProduct = await batchApi(`/api/batches/${currentBatchId}/products/${currentBatchProduct.product_id}`, {
            method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify({content, approved})
        });
        showToast(approved ? "Treść zapisana i zatwierdzona." : "Treść zapisana.", "success");
        await refreshBatch();
        await openBatchProduct(currentBatchProduct.product_id);
    } catch (error) {
        showToast(error.message, "error");
    }
}

document.getElementById("batch-save-btn").addEventListener("click", () => saveBatchProduct(false));
document.getElementById("batch-save-approve-btn").addEventListener("click", () => saveBatchProduct(true));
document.getElementById("batch-extended-description").addEventListener("input", renderBatchHtmlPreview);

async function startBatchGeneration(mode) {
    if (!currentBatchId) return;
    const limit = Math.max(1, Math.min(200, Number(document.getElementById("batch-generation-limit").value) || 50));
    try {
        await batchApi(`/api/batches/${currentBatchId}/generate`, {
            method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({mode, limit})
        });
        showToast(mode === "pilot" ? "Uruchomiono generowanie pilota." : `Uruchomiono generowanie kolejnych ${limit} produktów.`, "success");
        await refreshBatch();
    } catch (error) {
        showToast(error.message, "error");
    }
}
document.getElementById("batch-pilot-btn").addEventListener("click", () => startBatchGeneration("pilot"));
document.getElementById("batch-full-btn").addEventListener("click", () => startBatchGeneration("batch"));

document.getElementById("batch-approve-visible-btn").addEventListener("click", async () => {
    const selected = [...document.querySelectorAll("#batch-product-rows tr")]
        .filter(row => row.querySelector("input").checked)
        .map(row => row.dataset.productId);
    if (!selected.length) return showToast("Zaznacz produkty w statusie Do kontroli.", "error");
    try {
        const result = await batchApi(`/api/batches/${currentBatchId}/approve`, {
            method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({product_ids: selected})
        });
        showToast(`Zatwierdzono: ${result.updated}.`, "success");
        await refreshBatch();
    } catch (error) {
        showToast(error.message, "error");
    }
});

async function runDangerousBatchAction(action) {
    if (!currentBatchId) return;
    const confirmation = document.getElementById("batch-confirmation").value.trim();
    if (confirmation !== currentBatchId) return showToast("Wpisz poprawne ID partii.", "error");
    try {
        await batchApi(`/api/batches/${currentBatchId}/${action}`, {
            method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({confirmation})
        });
        document.getElementById("batch-confirmation").value = "";
        showToast(action === "publish" ? "Rozpoczęto zapis do Sky-Shop." : "Rozpoczęto przywracanie kopii.", "success");
        await refreshBatch();
    } catch (error) {
        showToast(error.message, "error");
    }
}
document.getElementById("batch-publish-btn").addEventListener("click", () => runDangerousBatchAction("publish"));
document.getElementById("batch-rollback-btn").addEventListener("click", () => runDangerousBatchAction("rollback"));

setInterval(() => {
    if (!batchView.hidden && currentBatchId) refreshBatch();
}, 5000);

if (location.hash === "#batch") setAppMode("batch");
