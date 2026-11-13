/* Aperçu Word : rendu d'un .docx « comme dans Word » (pages, polices,
 * tableaux, images, en-têtes / pieds de page) avec docx-preview.
 * En cas d'échec, bascule sur l'aperçu PDF (conversion LibreOffice). */
(function () {
    "use strict";
    var root = document.getElementById("wv-root");
    var contentUrl = root.dataset.contentUrl;
    var pdfUrl = root.dataset.pdfUrl;
    var docEl = document.getElementById("wv-doc");
    var msgEl = document.getElementById("wv-message");
    var zoom = 1;

    function showMessage(html) {
        msgEl.innerHTML = html;
        msgEl.style.display = "block";
    }

    function fallbackToPdf() {
        msgEl.style.display = "none";
        docEl.style.display = "none";
        var frame = document.getElementById("wv-pdf");
        frame.src = "/web/static/lib/pdfjs/web/viewer.html?file=" +
            encodeURIComponent(pdfUrl) + "#pagemode=none";
        frame.style.display = "block";
        document.getElementById("wv-zoom-box").style.display = "none";
    }

    function applyZoom() {
        var wrapper = docEl.querySelector(".docx-wrapper");
        if (wrapper) {
            wrapper.style.zoom = zoom;
        }
        document.getElementById("wv-zoom-value").textContent =
            Math.round(zoom * 100) + "%";
    }

    document.getElementById("wv-zoom-in").addEventListener("click", function () {
        zoom = Math.min(3, zoom + 0.1); applyZoom();
    });
    document.getElementById("wv-zoom-out").addEventListener("click", function () {
        zoom = Math.max(0.3, zoom - 0.1); applyZoom();
    });
    document.getElementById("wv-print").addEventListener("click", function () {
        window.print();
    });

    if (root.dataset.mode === "pdf") {
        fallbackToPdf();
        return;
    }

    fetch(contentUrl, { credentials: "same-origin" })
        .then(function (response) {
            if (!response.ok) {
                throw new Error("HTTP " + response.status);
            }
            return response.blob();
        })
        .then(function (blob) {
            return window.docx.renderAsync(blob, docEl, null, {
                className: "docx",
                inWrapper: true,
                ignoreWidth: false,
                ignoreHeight: false,
                ignoreFonts: false,
                breakPages: true,
                renderHeaders: true,
                renderFooters: true,
                renderFootnotes: true,
                renderEndnotes: true,
                renderComments: false,
                useBase64URL: true,
                experimental: true,
            });
        })
        .then(function () {
            msgEl.style.display = "none";
            applyZoom();
            document.body.dataset.rendered = "1";
        })
        .catch(function (error) {
            console.warn("Aperçu Word : rendu direct impossible, bascule PDF", error);
            fallbackToPdf();
        });
})();
