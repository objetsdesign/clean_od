/** @odoo-module */
/**
 * Documents : un simple clic sur un fichier Word ouvre l'éditeur Word
 * (même écran que « Action > Modifier dans Odoo (Word) »).
 *
 * Indépendant du code interne de Documents :
 *  1. chaque enregistrement `documents.document` chargé est mémorisé avec
 *     son identifiant d'affichage (data-id des cartes / lignes) ;
 *  2. un écouteur global (phase de capture sur window) intercepte le clic
 *     sur une carte / ligne Word avant que Documents ne le traite.
 * Ctrl / Maj / Cmd + clic, case à cocher, étoile, boutons : comportement normal.
 */
import { Record } from "@web/model/relational_model/record";
import { patch } from "@web/core/utils/patch";

const VERSION = "18.0.2.0.0";
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
const IGNORED_TARGETS = [
    "input", "button", "a", "select", "textarea", "label",
    ".dropdown", ".dropdown-menu", ".o-checkbox", ".form-check",
    ".o_record_selector", ".o_list_record_selector",
    "[role='button']", "[role='menuitem']", ".fa-star", ".fa-star-o",
].join(", ");

/* 1. Mémorisation des enregistrements documents.document ------------- */
const records = new Map();
const canWeakRef = typeof WeakRef === "function";

patch(Record.prototype, {
    setup() {
        super.setup(...arguments);
        try {
            if (this.resModel === DOCUMENT_MODEL) {
                records.set(this.id, canWeakRef ? new WeakRef(this) : this);
            }
        } catch (error) {
            console.warn(LOG, error);
        }
    },
});

function getRecord(datapointId) {
    const ref = records.get(datapointId);
    return ref ? (canWeakRef ? ref.deref() || null : ref) : null;
}

/* 2. Détection d'un fichier Word ------------------------------------ */
function isWordRecord(record) {
    if (!record || record.resModel !== DOCUMENT_MODEL || !record.resId) {
        return false;
    }
    const data = record.data || {};
    if (data.type && data.type !== "binary") {
        return false;
    }
    const name = (data.name || data.display_name || "").trim();
    const ext = name.includes(".") ? name.split(".").pop().toLowerCase() : "";
    return WORD_MIMETYPES.includes(data.mimetype) || WORD_EXTENSIONS.includes(ext);
}

/* 3. Écouteur global du clic ---------------------------------------- */
function findClickedRecord(target) {
    let el = target?.closest?.("[data-id]");
    while (el) {
        const record = getRecord(el.dataset.id);
        if (record) {
            return { record, container: el };
        }
        el = el.parentElement?.closest("[data-id]");
    }
    return null;
}

function isPlainClick(ev, container) {
    if (ev.button !== 0 || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey) {
        return false;
    }
    const ignored = ev.target.closest?.(IGNORED_TARGETS);
    return !(ignored && container.contains(ignored) && ignored !== container);
}

function onGlobalClick(ev) {
    try {
        const found = findClickedRecord(ev.target);
        if (!found || !isWordRecord(found.record) || !isPlainClick(ev, found.container)) {
            return;
        }
        ev.preventDefault();
        ev.stopImmediatePropagation();
        ev.stopPropagation();
        const name = found.record.data?.name;
        console.info(LOG, "ouverture de", name, `(document ${found.record.resId})`);
        window.open(`/docx_preview/open/${found.record.resId}`, "_blank");
    } catch (error) {
        console.error(LOG, "erreur au clic :", error);
    }
}

window.addEventListener("click", onGlobalClick, true);
console.info(LOG, `clic Word actif – version ${VERSION}`);
