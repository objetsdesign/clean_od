/* Éditeur Word (SuperDoc) pour les fichiers .docx de Documents. */
(function () {
    "use strict";

    const DOCX_MIMETYPE =
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
    const root = document.getElementById("sd-root");
    const config = JSON.parse(root.dataset.config);
    const statusEl = document.getElementById("sd-status");
    const messageEl = document.getElementById("sd-message");
    const saveBtn = document.getElementById("sd-save");
    const downloadBtn = document.getElementById("sd-download");
    const closeBtn = document.getElementById("sd-close");

    let superdoc = null;
    let ready = false;
    let dirty = false;
    let saving = false;

    function setStatus(text, kind) {
        statusEl.textContent = text || "";
        statusEl.className = "sd-status" + (kind ? " sd-" + kind : "");
    }

    function showMessage(text, isError) {
        messageEl.textContent = text;
        messageEl.className = "sd-message" + (isError ? " sd-error" : "");
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

    function baseName() {
        return (config.name || "document").replace(/\.(docx|docm|dotx)$/i, "");
    }

    async function exportBlob() {
        return superdoc.export({ triggerDownload: false, exportedName: baseName() });
    }

    async function save() {
        if (!ready || saving || !config.canWrite) {
            return;
        }
        saving = true;
        saveBtn.disabled = true;
        setStatus("Enregistrement…");
        try {
            const blob = await exportBlob();
            const form = new FormData();
            form.append("csrf_token", config.csrfToken);
            form.append("file", new File([blob], config.name, { type: DOCX_MIMETYPE }));
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
        if (!ready) {
            window.location.href = config.contentUrl;
            return;
        }
        try {
            const blob = await exportBlob();
            const link = document.createElement("a");
            link.href = URL.createObjectURL(blob);
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
        const SuperDocClass = window.SuperDoc && (window.SuperDoc.SuperDoc || window.SuperDoc);
        if (typeof SuperDocClass !== "function") {
            showMessage("L'éditeur Word n'a pas pu être chargé.", true);
            return;
        }
        let file;
        try {
            const response = await fetch(config.contentUrl, { credentials: "same-origin" });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const blob = await response.blob();
            file = new File([blob], config.name, { type: DOCX_MIMETYPE });
        } catch (error) {
            console.error("[Aperçu Word]", error);
            showMessage("Impossible de récupérer le fichier (droits d'accès ou session expirée ?).", true);
            return;
        }
        superdoc = new SuperDocClass({
            selector: "#sd-editor",
            toolbar: "#sd-toolbar",
            document: file,
            documentMode: config.canWrite ? "editing" : "viewing",
            telemetry: { enabled: false }, // aucune donnée envoyée à l'extérieur
            user: config.user,
            onReady: () => {
                ready = true;
                messageEl.hidden = true;
                if (config.canWrite) {
                    saveBtn.hidden = false;
                } else {
                    setStatus("Lecture seule");
                }
            },
            onEditorUpdate: markDirty,
            onContentError: (payload) => {
                console.error("[Aperçu Word]", payload);
                showMessage("Ce document ne peut pas être ouvert dans l'éditeur. Utilisez « Télécharger ».", true);
            },
            onException: (payload) => console.error("[Aperçu Word]", payload),
        });
        window.__docxEditor = superdoc;
    }

    saveBtn.addEventListener("click", save);
    downloadBtn.addEventListener("click", download);
    closeBtn.addEventListener("click", close);
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
        if (dirty) {
            ev.preventDefault();
            ev.returnValue = "";
        }
    });

    start();
})();
