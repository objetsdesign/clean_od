(function () {
    "use strict";

    const statusEl = document.getElementById("status");
    const containerEl = document.getElementById("container");

    function showError(message) {
        statusEl.className = "status error";
        statusEl.innerHTML = "";
        const p = document.createElement("p");
        p.textContent = message;
        statusEl.appendChild(p);
    }

    /**
     * N'accepte qu'un chemin relatif au même serveur Odoo (ex. /web/content/42?...)
     * pour éviter que la page serve à charger des fichiers d'un autre site.
     */
    function getFileUrl() {
        const file = new URLSearchParams(window.location.search).get("file");
        if (!file || !file.startsWith("/") || file.startsWith("//")) {
            return null;
        }
        const resolved = new URL(file, window.location.origin);
        return resolved.origin === window.location.origin ? resolved.href : null;
    }

    async function render() {
        const fileUrl = getFileUrl();
        if (!fileUrl) {
            showError("Fichier introuvable : lien d'aperçu invalide.");
            return;
        }
        if (!window.docx || !window.JSZip) {
            showError("Les bibliothèques d'aperçu n'ont pas pu être chargées.");
            return;
        }
        let blob;
        try {
            const response = await fetch(fileUrl, { credentials: "same-origin" });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            blob = await response.blob();
        } catch (error) {
            console.error(error);
            showError("Impossible de récupérer le fichier (droits d'accès ou session expirée ?).");
            return;
        }
        try {
            await window.docx.renderAsync(blob, containerEl, null, {
                className: "docx",
                inWrapper: true,
                ignoreWidth: false,
                ignoreHeight: false,
                ignoreFonts: false,
                breakPages: true,
                ignoreLastRenderedPageBreak: true,
                experimental: true,
                renderHeaders: true,
                renderFooters: true,
                renderFootnotes: true,
                renderEndnotes: true,
                useBase64URL: true,
            });
            statusEl.className = "status hidden";
        } catch (error) {
            console.error(error);
            showError(
                "Ce fichier ne peut pas être affiché. S'il s'agit d'un ancien .doc " +
                    "(Word 97-2003) ou d'un fichier endommagé, utilisez « Télécharger »."
            );
        }
    }

    render();
})();
