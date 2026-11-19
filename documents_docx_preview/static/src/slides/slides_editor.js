/* Éditeur PowerPoint : textes, mise en forme (gras, italique, souligné,
 * taille, couleur) et animations d'entrée des diapositives. */
import * as pdfjsLib from "/web/static/lib/pdfjs/build/pdf.js";

pdfjsLib.GlobalWorkerOptions.workerSrc = "/web/static/lib/pdfjs/build/pdf.worker.js";

const root = document.getElementById("se-root");
const config = JSON.parse(root.dataset.config);
const statusEl = document.getElementById("se-status");
const messageEl = document.getElementById("se-message");
const slidesEl = document.getElementById("se-slides");
const saveBtn = document.getElementById("se-save");
const closeBtn = document.getElementById("se-close");

let checksum = null;
let saving = false;
/** Paragraphes : { slide, index, original, textarea, fmt0, fmt, controls } */
let fields = [];
/** Animations : { slide, spid, original, select } */
let animFields = [];

const FORMAT_KEYS = ["bold", "italic", "underline", "size", "color"];
const ANIMATIONS = [
    ["", "Aucune"],
    ["appear", "Apparition"],
    ["fade", "Fondu"],
    ["fly", "Entrée par le bas"],
];

function setStatus(text, kind) {
    statusEl.textContent = text || "";
    statusEl.className = "sv-status" + (kind ? " se-" + kind : "");
}

function showError(text) {
    messageEl.className = "sv-message sv-error";
    messageEl.textContent = text;
    messageEl.hidden = false;
}

function formatChanges(field) {
    const diff = {};
    for (const key of FORMAT_KEYS) {
        if (field.fmt[key] !== field.fmt0[key] && field.fmt[key] !== null && field.fmt[key] !== undefined) {
            diff[key] = field.fmt[key];
        }
    }
    return diff;
}

function fieldChanged(field) {
    return field.textarea.value !== field.original || Object.keys(formatChanges(field)).length > 0;
}

function changedFields() {
    return fields.filter(fieldChanged);
}

function changedAnimations() {
    return animFields.filter((a) => a.select.value !== a.original);
}

function refreshDirty() {
    const count = changedFields().length + changedAnimations().length;
    saveBtn.disabled = count === 0 || saving;
    if (count) {
        setStatus(`${count} modification${count > 1 ? "s" : ""} non enregistrée${count > 1 ? "s" : ""}`, "warn");
    } else if (!saving) {
        setStatus("");
    }
}

function autoSize(textarea) {
    textarea.style.height = "auto";
    textarea.style.height = textarea.scrollHeight + 2 + "px";
}

function shapeLabel(shape) {
    if (shape.kind === "table") {
        return "Tableau";
    }
    const name = (shape.name || "").toLowerCase();
    if (name.startsWith("title") || name.startsWith("titre")) {
        return "Titre";
    }
    if (name.startsWith("subtitle") || name.startsWith("sous-titre")) {
        return "Sous-titre";
    }
    return "Zone de texte";
}

function applyPreviewStyle(field) {
    const t = field.textarea;
    t.style.fontWeight = field.fmt.bold ? "700" : "";
    t.style.fontStyle = field.fmt.italic ? "italic" : "";
    t.style.textDecoration = field.fmt.underline ? "underline" : "";
    t.style.color = field.fmt.color ? "#" + field.fmt.color : "";
    t.classList.toggle("se-changed", fieldChanged(field));
}

function makeToggle(label, title, key, field) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "se-tool se-" + key;
    btn.textContent = label;
    btn.title = title;
    const sync = () => btn.classList.toggle("se-active", !!field.fmt[key]);
    btn.addEventListener("click", () => {
        field.fmt[key] = !field.fmt[key];
        sync();
        applyPreviewStyle(field);
        refreshDirty();
    });
    sync();
    return btn;
}

function makeFormatBar(field) {
    const bar = document.createElement("div");
    bar.className = "se-format";
    bar.append(
        makeToggle("G", "Gras", "bold", field),
        makeToggle("I", "Italique", "italic", field),
        makeToggle("S", "Souligné", "underline", field),
    );
    const size = document.createElement("input");
    size.type = "number";
    size.min = "1";
    size.max = "400";
    size.step = "1";
    size.className = "se-size";
    size.title = "Taille (points)";
    size.placeholder = "Taille";
    size.value = field.fmt0.size ?? "";
    size.addEventListener("input", () => {
        const value = parseFloat(size.value);
        field.fmt.size = Number.isFinite(value) && value >= 1 && value <= 400 ? value : field.fmt0.size;
        applyPreviewStyle(field);
        refreshDirty();
    });
    const sizeLabel = document.createElement("span");
    sizeLabel.className = "se-unit";
    sizeLabel.textContent = "pt";
    const color = document.createElement("input");
    color.type = "color";
    color.className = "se-color";
    color.title = "Couleur du texte";
    color.value = "#" + (field.fmt0.color || "000000");
    color.addEventListener("input", () => {
        field.fmt.color = color.value.replace("#", "").toUpperCase();
        applyPreviewStyle(field);
        refreshDirty();
    });
    bar.append(size, sizeLabel, color);
    field.controls = { size, color };
    return bar;
}

function makeAnimationSelect(slide, shape) {
    const wrap = document.createElement("label");
    wrap.className = "se-anim";
    wrap.textContent = "Animation ";
    const select = document.createElement("select");
    for (const [value, label] of ANIMATIONS) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        select.appendChild(option);
    }
    select.value = shape.animation || "";
    if (!slide.animations_editable) {
        select.disabled = true;
        wrap.title = "Cette diapositive contient des animations avancées : elles sont conservées mais ne peuvent pas être modifiées ici.";
    }
    const field = { slide: slide.number, spid: shape.id, original: select.value, select };
    select.addEventListener("change", () => {
        select.classList.toggle("se-changed", select.value !== field.original);
        refreshDirty();
    });
    animFields.push(field);
    wrap.appendChild(select);
    return wrap;
}

function buildSlides(slides) {
    slidesEl.textContent = "";
    fields = [];
    animFields = [];
    let pageNumber = 0;
    for (const slide of slides) {
        const row = document.createElement("section");
        row.className = "se-slide";

        const visual = document.createElement("div");
        visual.className = "se-visual";
        const label = document.createElement("div");
        label.className = "se-number";
        label.textContent = `Diapositive ${slide.number}` + (slide.hidden ? " (masquée)" : "");
        visual.appendChild(label);
        if (slide.hidden) {
            const ph = document.createElement("div");
            ph.className = "se-hidden";
            ph.textContent = "Diapositive masquée : pas d'aperçu";
            visual.appendChild(ph);
        } else {
            pageNumber += 1;
            const canvas = document.createElement("canvas");
            canvas.className = "se-thumb";
            canvas.dataset.page = String(pageNumber);
            visual.appendChild(canvas);
        }
        row.appendChild(visual);

        const form = document.createElement("div");
        form.className = "se-texts";
        if (!slide.shapes.length) {
            const empty = document.createElement("p");
            empty.className = "se-empty";
            empty.textContent = "Aucun texte modifiable sur cette diapositive.";
            form.appendChild(empty);
        }
        for (const shape of slide.shapes) {
            const group = document.createElement("fieldset");
            group.className = "se-shape";
            const legend = document.createElement("legend");
            legend.textContent = shapeLabel(shape);
            group.appendChild(legend);
            if (shape.kind === "text" && shape.id) {
                group.appendChild(makeAnimationSelect(slide, shape));
            }
            for (const paragraph of shape.paragraphs) {
                const textarea = document.createElement("textarea");
                textarea.rows = 1;
                textarea.value = paragraph.text;
                textarea.placeholder = "(vide)";
                textarea.spellcheck = true;
                const fmt0 = { ...paragraph.format };
                const field = {
                    slide: slide.number, index: paragraph.index, original: paragraph.text,
                    textarea, fmt0, fmt: { ...fmt0 },
                };
                textarea.addEventListener("input", () => {
                    autoSize(textarea);
                    applyPreviewStyle(field);
                    refreshDirty();
                });
                fields.push(field);
                const block = document.createElement("div");
                block.className = "se-paragraph";
                block.append(textarea, makeFormatBar(field));
                group.appendChild(block);
                applyPreviewStyle(field);
            }
            form.appendChild(group);
        }
        row.appendChild(form);
        slidesEl.appendChild(row);
    }
    requestAnimationFrame(() => fields.forEach((f) => autoSize(f.textarea)));
}

async function renderThumbnails(version) {
    const canvases = [...slidesEl.querySelectorAll("canvas.se-thumb")];
    if (!canvases.length) {
        return;
    }
    try {
        const pdf = await pdfjsLib.getDocument({ url: `${config.pdfUrl}?v=${encodeURIComponent(version || "")}`, withCredentials: true }).promise;
        for (const canvas of canvases) {
            const pageNumber = Number(canvas.dataset.page);
            if (pageNumber > pdf.numPages) {
                continue;
            }
            const page = await pdf.getPage(pageNumber);
            const base = page.getViewport({ scale: 1 });
            const scale = (canvas.parentElement.clientWidth * (window.devicePixelRatio || 1)) / base.width;
            const viewport = page.getViewport({ scale });
            canvas.width = Math.floor(viewport.width);
            canvas.height = Math.floor(viewport.height);
            await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
        }
    } catch (error) {
        console.warn("[Aperçu PowerPoint] miniatures indisponibles", error);
        for (const canvas of canvases) {
            const ph = document.createElement("div");
            ph.className = "se-hidden";
            ph.textContent = "Aperçu indisponible";
            canvas.replaceWith(ph);
        }
    }
}

async function load() {
    try {
        const response = await fetch(config.dataUrl, { credentials: "same-origin" });
        const result = await response.json();
        if (!response.ok || !result.ok) {
            throw new Error(result.error || `Erreur ${response.status}`);
        }
        checksum = result.checksum;
        buildSlides(result.slides);
        messageEl.hidden = true;
        refreshDirty();
        renderThumbnails(checksum);
    } catch (error) {
        console.error("[Aperçu PowerPoint]", error);
        showError("Impossible d'ouvrir la présentation : " + error.message);
    }
}

async function save() {
    const changed = changedFields();
    const changedAnims = changedAnimations();
    if ((!changed.length && !changedAnims.length) || saving) {
        return;
    }
    saving = true;
    saveBtn.disabled = true;
    setStatus("Enregistrement…");
    const changes = {};
    for (const field of changed) {
        const entry = {};
        if (field.textarea.value !== field.original) {
            entry.text = field.textarea.value;
        }
        Object.assign(entry, formatChanges(field));
        ((changes[field.slide] ||= {}).paragraphs ||= {})[field.index] = entry;
    }
    for (const anim of changedAnims) {
        ((changes[anim.slide] ||= {}).animations ||= {})[anim.spid] = anim.select.value;
    }
    try {
        const form = new FormData();
        form.append("csrf_token", config.csrfToken);
        form.append("payload", JSON.stringify({ checksum, changes }));
        const response = await fetch(config.saveUrl, { method: "POST", body: form, credentials: "same-origin" });
        let result = {};
        try {
            result = await response.json();
        } catch (error) {
            // réponse non JSON (session expirée…)
        }
        if (!response.ok || !result.ok) {
            throw new Error(result.error || `Erreur ${response.status}`);
        }
        checksum = result.checksum;
        for (const field of changed) {
            field.original = field.textarea.value;
            field.fmt0 = { ...field.fmt };
            applyPreviewStyle(field);
        }
        for (const anim of changedAnims) {
            anim.original = anim.select.value;
            anim.select.classList.remove("se-changed");
        }
        const time = new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
        saving = false;
        refreshDirty();
        setStatus(`Enregistré dans Documents à ${time}`, "ok");
        renderThumbnails(checksum); // miniatures mises à jour (nouvelle conversion)
    } catch (error) {
        console.error("[Aperçu PowerPoint]", error);
        saving = false;
        refreshDirty();
        setStatus("Échec de l'enregistrement : " + error.message, "error");
    }
}

/** Retour à Documents : page précédente si elle vient d'Odoo, sinon Documents. */
function goBack(steps) {
    let fromOdoo = false;
    try {
        fromOdoo = !!document.referrer && new URL(document.referrer).origin === window.location.origin;
    } catch (error) {
        fromOdoo = false;
    }
    if (window.opener && !window.opener.closed) {
        window.close(); // ouvert dans un nouvel onglet : on le ferme
        return;
    }
    if (fromOdoo && window.history.length > steps) {
        window.history.go(-steps);
    } else {
        window.location.href = "/odoo/documents";
    }
}

saveBtn.addEventListener("click", save);
closeBtn.addEventListener("click", () => {
    if ((changedFields().length || changedAnimations().length) && !window.confirm("Des modifications ne sont pas enregistrées. Fermer quand même ?")) {
        return;
    }
    fields = [];
    animFields = [];
    goBack(1);
});
// « Aperçu » remplace la page courante : « Fermer » revient toujours à Documents.
document.getElementById("se-preview").addEventListener("click", (ev) => {
    ev.preventDefault();
    window.location.replace(ev.currentTarget.href);
});
document.addEventListener(
    "keydown",
    (ev) => {
        if ((ev.ctrlKey || ev.metaKey) && !ev.shiftKey && !ev.altKey && ev.key.toLowerCase() === "s") {
            ev.preventDefault();
            save();
        }
    },
    true
);
window.addEventListener("beforeunload", (ev) => {
    if (changedFields().length || changedAnimations().length) {
        ev.preventDefault();
        ev.returnValue = "";
    }
});

load();
