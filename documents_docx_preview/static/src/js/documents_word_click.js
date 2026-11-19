/** @odoo-module */
/**
 * Documents : un simple clic sur un fichier Word ouvre l'éditeur Word,
 * un clic sur une présentation PowerPoint ouvre la visionneuse de diapositives.
 *
 * Le module retrouve le document cliqué par trois méthodes indépendantes,
 * pour ne pas dépendre du code interne de Documents (Enterprise) :
 *   1. lien direct « élément affiché → document », posé quand chaque carte
 *      kanban s'affiche (sans dépendre d'un attribut HTML) ;
 *   2. attribut data-id des cartes / lignes (vues standard d'Odoo) ;
 *   3. en dernier recours, le nom du fichier affiché sur la carte.
 * La carte est repérée dès l'appui sur le bouton de la souris, avant que
 * Documents ne la redessine en la sélectionnant.
 *
 * Ctrl / Maj / Cmd + clic, case à cocher, étoile, boutons : comportement normal.
 */
import { onMounted, onPatched } from "@odoo/owl";
import { KanbanRecord } from "@web/views/kanban/kanban_record";
import { Record } from "@web/model/relational_model/record";
import { patch } from "@web/core/utils/patch";

const VERSION = "18.0.8.0.0";
const LOG = "[Aperçu Word]";
const DOCUMENT_MODEL = "documents.document";
const WORD_MIMETYPES = [
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.template",
    "application/vnd.ms-word.document.macroenabled.12",
    "application/msword",
    "application/vnd.oasis.opendocument.text",
    "application/rtf",
    "text/rtf",
];
const WORD_EXTENSIONS = ["docx", "doc", "odt", "rtf", "docm", "dotx", "dot"];
const SLIDE_MIMETYPES = [
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.presentationml.slideshow",
    "application/vnd.openxmlformats-officedocument.presentationml.template",
    "application/vnd.ms-powerpoint",
    "application/vnd.ms-powerpoint.presentation.macroenabled.12",
    "application/vnd.oasis.opendocument.presentation",
];
const SLIDE_EXTENSIONS = ["pptx", "ppt", "odp", "pptm", "ppsx", "pps", "potx"];
const IGNORED_TARGETS = [
    "input", "button", "a", "select", "textarea", "label",
    ".dropdown", ".dropdown-menu", ".o-checkbox", ".form-check",
    ".o_record_selector", ".o_list_record_selector",
    "[role='button']", "[role='menuitem']", ".fa-star", ".fa-star-o",
].join(", ");
const CARD_SELECTOR = ".o_kanban_record, .o_data_row, article, tr";

/* ------------------------------------------------------------------ */
/* Mémorisation des documents chargés                                  */
/* ------------------------------------------------------------------ */
const canWeakRef = typeof WeakRef === "function";
/** datapoint id -> record */
const recordsById = new Map();
/** élément HTML d'une carte -> fonction renvoyant le record courant */
const recordsByElement = new WeakMap();

function deref(ref) {
    return ref ? (canWeakRef ? ref.deref() || null : ref) : null;
}

patch(Record.prototype, {
    setup() {
        super.setup(...arguments);
        try {
            if (this.resModel === DOCUMENT_MODEL) {
                recordsById.set(this.id, canWeakRef ? new WeakRef(this) : this);
            }
        } catch (error) {
            console.warn(LOG, error);
        }
    },
});

patch(KanbanRecord.prototype, {
    setup() {
        super.setup(...arguments);
        const register = () => {
            try {
                if (this.props.record?.resModel !== DOCUMENT_MODEL) {
                    return;
                }
                const el = this.rootRef?.el || this.__owl__?.firstNode?.();
                if (el && el.nodeType === 1) {
                    recordsByElement.set(el, () => this.props.record);
                }
            } catch (error) {
                console.warn(LOG, error);
            }
        };
        onMounted(register);
        onPatched(register);
    },
});

function liveRecords() {
    const result = [];
    for (const [id, ref] of recordsById) {
        const record = deref(ref);
        if (record) {
            result.push(record);
        } else {
            recordsById.delete(id);
        }
    }
    return result;
}

/* ------------------------------------------------------------------ */
/* Détection d'un fichier Word                                         */
/* ------------------------------------------------------------------ */
function recordName(record) {
    const data = record?.data || {};
    return (data.name || data.display_name || "").trim();
}

/** "word", "slides" ou null selon le type du fichier. */
function fileKind(record) {
    if (!record || record.resModel !== DOCUMENT_MODEL || !record.resId) {
        return null;
    }
    const data = record.data || {};
    if (data.type && data.type !== "binary") {
        return null;
    }
    const name = recordName(record);
    const ext = name.includes(".") ? name.split(".").pop().toLowerCase() : "";
    if (WORD_MIMETYPES.includes(data.mimetype) || WORD_EXTENSIONS.includes(ext)) {
        return "word";
    }
    if (SLIDE_MIMETYPES.includes(data.mimetype) || SLIDE_EXTENSIONS.includes(ext)) {
        return "slides";
    }
    return null;
}

const OPEN_URL = {
    word: (id) => `/docx_preview/open/${id}`,
    slides: (id) => `/slides_preview/${id}`,
};

/* ------------------------------------------------------------------ */
/* Retrouver le document à partir de l'élément cliqué                  */
/* ------------------------------------------------------------------ */
function findClickedRecord(target) {
    if (!target || target.nodeType !== 1) {
        return null;
    }
    // Méthodes 1 et 2 : remonter les éléments parents
    for (let el = target; el && el !== document.body; el = el.parentElement) {
        const getter = recordsByElement.get(el);
        if (getter) {
            const record = getter();
            if (record) {
                return { record, container: el, method: "carte" };
            }
        }
        const datapointId = el.dataset?.id;
        if (datapointId) {
            const record = deref(recordsById.get(datapointId));
            if (record) {
                return { record, container: el, method: "data-id" };
            }
        }
    }
    // Méthode 3 : nom du fichier affiché sur la carte
    const card = target.closest(CARD_SELECTOR);
    if (!card) {
        return null;
    }
    const text = card.innerText || card.textContent || "";
    let best = null;
    for (const record of liveRecords()) {
        const name = recordName(record);
        if (name && text.includes(name) && (!best || name.length > recordName(best).length)) {
            best = record;
        }
    }
    return best ? { record: best, container: card, method: "nom" } : null;
}

function isPlainClick(ev, target, container) {
    if (ev.button !== 0 || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey) {
        return false;
    }
    const ignored = target.closest?.(IGNORED_TARGETS);
    return !(ignored && container.contains(ignored) && ignored !== container);
}

/* ------------------------------------------------------------------ */
/* Écouteurs globaux (phase de capture, avant Documents)               */
/* ------------------------------------------------------------------ */
let pressed = null; // carte repérée à l'appui du bouton

function onPointerDown(ev) {
    try {
        const found = findClickedRecord(ev.target);
        pressed = found && isPlainClick(ev, ev.target, found.container)
            ? { found, x: ev.clientX, y: ev.clientY, time: Date.now() }
            : null;
    } catch (error) {
        pressed = null;
        console.warn(LOG, error);
    }
}

function onClick(ev) {
    try {
        let found = findClickedRecord(ev.target);
        if (found && !isPlainClick(ev, ev.target, found.container)) {
            return;
        }
        if (!found && pressed) {
            // La carte a pu être redessinée entre l'appui et le relâchement.
            const moved = Math.hypot(ev.clientX - pressed.x, ev.clientY - pressed.y);
            if (Date.now() - pressed.time < 1500 && moved < 8 && ev.button === 0
                && !ev.ctrlKey && !ev.metaKey && !ev.shiftKey && !ev.altKey) {
                found = { ...pressed.found, method: pressed.found.method + " (appui)" };
            }
        }
        pressed = null;
        if (!found) {
            const card = ev.target?.closest?.(CARD_SELECTOR);
            const text = (card?.innerText || "").toLowerCase();
            if (card && [...WORD_EXTENSIONS, ...SLIDE_EXTENSIONS].some((ext) => text.includes("." + ext))) {
                console.warn(LOG, "clic sur une carte Word / PowerPoint non reconnue", {
                    classe_carte: card.className,
                    documents_charges: liveRecords().length,
                });
            }
            return;
        }
        const kind = fileKind(found.record);
        if (!kind) {
            return;
        }
        ev.preventDefault();
        ev.stopImmediatePropagation();
        ev.stopPropagation();
        console.info(LOG, "ouverture de", recordName(found.record),
            `(document ${found.record.resId}, détecté par : ${found.method})`);
        window.open(OPEN_URL[kind](found.record.resId), "_blank");
    } catch (error) {
        console.error(LOG, "erreur au clic :", error);
    }
}

window.addEventListener("pointerdown", onPointerDown, true);
window.addEventListener("click", onClick, true);
console.info(LOG, `clic Word actif – version ${VERSION}`);
