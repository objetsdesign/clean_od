/**
 * Application Documents : ouverture de l'aperçu au clic sur un .docx.
 *
 * Méthode indépendante du code interne de Documents (Enterprise) :
 *  1. Chaque enregistrement `documents.document` chargé par une vue (kanban,
 *     liste...) est mémorisé, avec son identifiant d'affichage (data-id).
 *  2. Un écouteur global, placé avant tous les autres (phase de capture sur
 *     window), repère le clic sur une carte / ligne .docx et ouvre l'aperçu
 *     avant que Documents ne traite le clic.
 *
 * Ctrl / Maj / Cmd + clic, la case à cocher, l'étoile et les boutons gardent
 * leur comportement normal (sélection, favoris, menus...).
 */
import { Record } from "@web/model/relational_model/record";
import { createFileViewer } from "@web/core/file_viewer/file_viewer_hook";
import { patch } from "@web/core/utils/patch";
import { url } from "@web/core/utils/urls";
import { DOCX_MIMETYPE, buildDocxViewerUrl, isDocxFile } from "./docx_file_model_patch";

const VERSION = "18.0.1.4.0";
const DOCUMENT_MODEL = "documents.document";
const LOG = "[Aperçu Word]";

const IGNORED_TARGETS = [
    "input",
    "button",
    "a",
    "select",
    "textarea",
    "label",
    ".dropdown",
    ".dropdown-menu",
    ".o-checkbox",
    ".form-check",
    ".o_record_selector",
    ".o_list_record_selector",
    "[role='button']",
    "[role='menuitem']",
    ".fa-star",
    ".fa-star-o",
].join(", ");

/* ------------------------------------------------------------------ */
/* 1. Mémorisation des enregistrements documents.document              */
/* ------------------------------------------------------------------ */

/** @type {Map<string, WeakRef<object>|object>} */
const documentRecords = new Map();
const canWeakRef = typeof WeakRef === "function";

function rememberRecord(record) {
    documentRecords.set(record.id, canWeakRef ? new WeakRef(record) : record);
    if (documentRecords.size > 5000) {
        // nettoyage des enregistrements disparus
        for (const [id, ref] of documentRecords) {
            if (canWeakRef && !ref.deref()) {
                documentRecords.delete(id);
            }
        }
    }
}

function getRecord(datapointId) {
    const ref = documentRecords.get(datapointId);
    if (!ref) {
        return null;
    }
    return canWeakRef ? ref.deref() || null : ref;
}

patch(Record.prototype, {
    setup() {
        super.setup(...arguments);
        try {
            if (this.resModel === DOCUMENT_MODEL) {
                rememberRecord(this);
            }
        } catch (error) {
            console.warn(LOG, error);
        }
    },
});

/* ------------------------------------------------------------------ */
/* 2. Ouverture de l'aperçu                                            */
/* ------------------------------------------------------------------ */

const viewer = createFileViewer();

/** @returns {number|false} */
function many2oneId(value) {
    if (!value) {
        return false;
    }
    if (Array.isArray(value)) {
        return value[0];
    }
    if (typeof value === "object") {
        return value.id || false;
    }
    return typeof value === "number" ? value : false;
}

/** Infos du document si c'est un .docx de l'application Documents, sinon null. */
function getDocxDocument(record) {
    if (!record || record.resModel !== DOCUMENT_MODEL || !record.resId) {
        return null;
    }
    const data = record.data || {};
    const name = data.name || data.display_name || "";
    if (!isDocxFile(data.mimetype, name)) {
        return null;
    }
    if (data.type && data.type !== "binary") {
        return null; // lien URL ou dossier
    }
    return {
        id: record.resId,
        name,
        attachmentId: many2oneId(data.attachment_id),
        accessToken: data.access_token || false,
    };
}

function openDocxDocument(doc) {
    const fileUrls = [url(`/docx_preview/${doc.id}/content`)];
    if (doc.attachmentId) {
        fileUrls.push(url(`/web/content/${doc.attachmentId}`));
    }
    fileUrls.push(
        url("/web/content", { model: DOCUMENT_MODEL, id: doc.id, field: "datas", filename: doc.name })
    );
    if (doc.accessToken) {
        fileUrls.push(url(`/documents/content/${doc.accessToken}`));
    }
    viewer.open({
        displayName: doc.name,
        name: doc.name,
        mimetype: DOCX_MIMETYPE,
        isDocx: true,
        isViewable: true,
        defaultSource: buildDocxViewerUrl(fileUrls),
        downloadUrl: url(`/docx_preview/${doc.id}/content`, { download: "1" }),
    });
}

/* ------------------------------------------------------------------ */
/* 3. Écouteur global du clic                                          */
/* ------------------------------------------------------------------ */

/** Remonte les éléments [data-id] jusqu'à trouver un enregistrement mémorisé. */
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
        if (ev.target?.closest?.(".o-FileViewer")) {
            return; // clic à l'intérieur de l'aperçu lui-même
        }
        const found = findClickedRecord(ev.target);
        if (!found) {
            return;
        }
        const doc = getDocxDocument(found.record);
        if (!doc || !isPlainClick(ev, found.container)) {
            return;
        }
        ev.preventDefault();
        ev.stopImmediatePropagation();
        ev.stopPropagation();
        console.info(LOG, "ouverture de", doc.name, `(document ${doc.id})`);
        openDocxDocument(doc);
    } catch (error) {
        console.error(LOG, "erreur au clic :", error);
    }
}

window.addEventListener("click", onGlobalClick, true);
console.info(LOG, `module chargé – version ${VERSION}`);
