/* Éditeur Word (docx-editor) pour les fichiers .docx de Documents. */
import "/documents_docx_preview/static/lib/docx-editor/docx-editor.js";

const DOCX_MIMETYPE =
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const root = document.getElementById("dx-root");
const config = JSON.parse(root.dataset.config);
const statusEl = document.getElementById("dx-status");
const messageEl = document.getElementById("dx-message");
const saveBtn = document.getElementById("dx-save");
const downloadBtn = document.getElementById("dx-download");
const closeBtn = document.getElementById("dx-close");

let handle = null;
let ready = false;
let dirty = false;
let saving = false;

function setStatus(text, kind) {
    statusEl.textContent = text || "";
    statusEl.className = "dx-status" + (kind ? " dx-" + kind : "");
}

function showMessage(text, isError) {
    messageEl.textContent = text;
    messageEl.className = "dx-message" + (isError ? " dx-error" : "");
    messageEl.hidden = false;
}

function markDirty() {
    if (!ready || !config.canWrite) {
        return;
    }
    if (!dirty) {
        dirty = true;
        setStatus("Modifications non enregistrées", "warn");
    }
}

async function currentBytes() {
    return new Uint8Array(await handle.save());
}

async function save() {
    if (!ready || saving || !config.canWrite) {
        return;
    }
    saving = true;
    saveBtn.disabled = true;
    setStatus("Enregistrement…");
    try {
        const bytes = await currentBytes();
        const form = new FormData();
        form.append("csrf_token", config.csrfToken);
        form.append("file", new File([bytes], config.name, { type: DOCX_MIMETYPE }));
        const response = await fetch(config.saveUrl, {
            method: "POST",
            body: form,
            credentials: "same-origin",
        });
        let result = {};
        try {
            result = await response.json();
        } catch (error) {
            // réponse non JSON (session expirée, erreur serveur…)
        }
        if (!response.ok || !result.ok) {
            throw new Error(result.error || `Erreur ${response.status}`);
        }
        dirty = false;
        const time = new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
        setStatus(`Enregistré dans Documents à ${time}`, "ok");
    } catch (error) {
        console.error("[Aperçu Word]", error);
        setStatus("Échec de l'enregistrement : " + error.message, "error");
    } finally {
        saving = false;
        saveBtn.disabled = false;
    }
}

async function download() {
    try {
        const bytes = ready ? await currentBytes() : null;
        if (!bytes) {
            window.location.href = config.contentUrl;
            return;
        }
        const link = document.createElement("a");
        link.href = URL.createObjectURL(new Blob([bytes], { type: DOCX_MIMETYPE }));
        link.download = config.name;
        document.body.appendChild(link);
        link.click();
        setTimeout(() => {
            URL.revokeObjectURL(link.href);
            link.remove();
        }, 1000);
    } catch (error) {
        console.error("[Aperçu Word]", error);
        window.location.href = config.contentUrl;
    }
}

function close() {
    if (dirty && !window.confirm("Des modifications ne sont pas enregistrées. Fermer quand même ?")) {
        return;
    }
    dirty = false;
    window.close();
    // Si l'onglet n'a pas été ouvert par Odoo, retour à Documents.
    setTimeout(() => {
        window.location.href = "/odoo/documents";
    }, 200);
}

async function start() {
    if (typeof window.mountDocxEditor !== "function") {
        showMessage("L'éditeur Word n'a pas pu être chargé.", true);
        return;
    }
    let bytes;
    try {
        const response = await fetch(config.contentUrl, { credentials: "same-origin" });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        bytes = new Uint8Array(await response.arrayBuffer());
    } catch (error) {
        console.error("[Aperçu Word]", error);
        showMessage("Impossible de récupérer le fichier (droits d'accès ou session expirée ?).", true);
        return;
    }
    messageEl.hidden = true;
    handle = window.mountDocxEditor(document.getElementById("dx-editor"), {
        bytes,
        title: config.name,
        author: config.user?.name || "",
        mode: config.canWrite ? "edit" : "view",
        // « Fichier › Enregistrer » du menu de l'éditeur → enregistrement dans Documents
        onSave: config.canWrite ? save : undefined,
        onReady: () => {
            // Les changements signalés pendant l'ouverture ne comptent pas.
            setTimeout(() => {
                ready = true;
                if (config.canWrite) {
                    saveBtn.hidden = false;
                } else {
                    setStatus("Lecture seule");
                }
            }, 300);
        },
        onChange: markDirty,
    });
    window.__docxEditor = handle;
}

saveBtn.addEventListener("click", save);
downloadBtn.addEventListener("click", download);
closeBtn.addEventListener("click", close);
document.addEventListener(
    "keydown",
    (ev) => {
        if ((ev.ctrlKey || ev.metaKey) && !ev.shiftKey && !ev.altKey && ev.key.toLowerCase() === "s") {
            ev.preventDefault();
            ev.stopPropagation();
            save();
        }
    },
    true
);
window.addEventListener("beforeunload", (ev) => {
    if (dirty) {
        ev.preventDefault();
        ev.returnValue = "";
    }
});

start();
