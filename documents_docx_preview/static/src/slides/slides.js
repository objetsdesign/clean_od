/* Visionneuse de diapositives PowerPoint (PDF généré par LibreOffice). */
(function () {
    "use strict";

    const root = document.getElementById("sv-root");
    const config = JSON.parse(root.dataset.config);
    const messageEl = document.getElementById("sv-message");
    const viewer = document.getElementById("sv-viewer");
    const presentBtn = document.getElementById("sv-present");
    const closeBtn = document.getElementById("sv-close");
    const statusEl = document.getElementById("sv-status");

    function showError(text) {
        messageEl.innerHTML = "";
        messageEl.className = "sv-message sv-error";
        messageEl.textContent = text;
        messageEl.hidden = false;
    }

    async function start() {
        // Conversion (ou lecture du cache) avant d'afficher : permet un
        // message d'erreur clair si LibreOffice échoue.
        try {
            const response = await fetch(config.pdfUrl, { credentials: "same-origin" });
            if (!response.ok) {
                const text = response.status === 422 ? await response.text() : `Erreur ${response.status}`;
                throw new Error(text);
            }
            await response.arrayBuffer();
        } catch (error) {
            console.error("[Aperçu PowerPoint]", error);
            showError("Aperçu indisponible : " + error.message + " Utilisez « Télécharger ».");
            return;
        }
        viewer.addEventListener("load", () => {
            messageEl.hidden = true;
            viewer.hidden = false;
            presentBtn.hidden = false;
            try {
                const app = viewer.contentWindow.PDFViewerApplication;
                app?.initializedPromise?.then(() => {
                    app.eventBus?.on("pagesloaded", (ev) => {
                        statusEl.textContent = `${ev.pagesCount} diapositive${ev.pagesCount > 1 ? "s" : ""}`;
                    });
                });
            } catch (error) {
                // visionneuse d'un autre domaine : pas de compteur
            }
        });
        viewer.src = config.viewerUrl;
    }

    presentBtn.addEventListener("click", () => {
        try {
            const app = viewer.contentWindow.PDFViewerApplication;
            if (app?.requestPresentationMode) {
                app.requestPresentationMode();
                return;
            }
        } catch (error) {
            // repli ci-dessous
        }
        viewer.requestFullscreen?.();
    });


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

    closeBtn.addEventListener("click", () => goBack(1));

    // « Modifier les textes » remplace la page courante : « Fermer » revient
    // toujours à Documents.
    const editLink = document.getElementById("sv-edit");
    editLink?.addEventListener("click", (ev) => {
        ev.preventDefault();
        window.location.replace(editLink.href);
    });

    start();
})();
