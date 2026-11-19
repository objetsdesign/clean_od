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
     * Lit les liens passés en paramètre (?file=...&file=...) et ne garde que
     * ceux du même serveur Odoo, pour que la page ne puisse pas charger des
     * fichiers d'un autre site. Plusieurs liens = essais successifs.
     */
    function getFileUrls() {
        const urls = [];
        for (const file of new URLSearchParams(window.location.search).getAll("file")) {
            try {
                const resolved = new URL(file, window.location.origin);
                if (resolved.origin === window.location.origin) {
                    urls.push(resolved.href);
                }
            } catch (error) {
                // lien invalide : ignoré
            }
        }
        return urls;
    }

    async function fetchFirst(urls) {
        let lastError;
        for (const fileUrl of urls) {
            try {
                const response = await fetch(fileUrl, { credentials: "same-origin" });
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status} – ${fileUrl}`);
                }
                return await response.blob();
            } catch (error) {
                console.warn("[docx preview]", error);
                lastError = error;
            }
        }
        throw lastError || new Error("Aucun lien");
    }

    async function render() {
        const fileUrls = getFileUrls();
        if (!fileUrls.length) {
            showError("Fichier introuvable : lien d'aperçu invalide.");
            return;
        }
        if (!window.docx || !window.JSZip) {
            showError("Les bibliothèques d'aperçu n'ont pas pu être chargées.");
            return;
        }
        let blob;
        try {
            blob = await fetchFirst(fileUrls);
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
