/* Éditeur « Word » d'Odoo : ruban + page A4 modifiable, enregistrement dans
 * le fichier .docx (conversion LibreOffice côté serveur). */
(function () {
    "use strict";
    var app = document.getElementById("ws-app");
    var page = document.getElementById("ws-page");
    var zoomBox = document.getElementById("ws-zoom");
    var canvas = document.getElementById("ws-canvas");
    var attachmentId = app.dataset.attachmentId;
    var canWrite = app.dataset.canWrite === "1";
    var downloadUrl = app.dataset.downloadUrl;
    var savedRange = null;
    var dirty = false;
    var zoom = 1;
    var painterStyle = null;

    // ------------------------------------------------------------------
    // Outils
    // ------------------------------------------------------------------
    function $(id) { return document.getElementById(id); }
    function setStatus(text) { $("ws-status").textContent = text || ""; }
    function markDirty() {
        if (!dirty) { dirty = true; $("ws-saved").textContent = "Modifications non enregistrées"; $("ws-saved").style.color = "#a4262c"; }
        updateCounts();
    }
    function saveSelection() {
        var sel = window.getSelection();
        if (sel.rangeCount && page.contains(sel.getRangeAt(0).commonAncestorContainer)) {
            savedRange = sel.getRangeAt(0).cloneRange();
        }
    }
    function restoreSelection() {
        page.focus({ preventScroll: true });
        if (savedRange) {
            var sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(savedRange);
        }
    }
    function exec(cmd, value) {
        restoreSelection();
        document.execCommand("styleWithCSS", false, true);
        document.execCommand(cmd, false, value === undefined ? null : value);
        saveSelection();
        markDirty();
        refreshState();
    }
    function currentNode() {
        var sel = window.getSelection();
        if (!sel.rangeCount) { return null; }
        var node = sel.getRangeAt(0).startContainer;
        return node.nodeType === 3 ? node.parentNode : node;
    }
    function closest(node, selector) {
        while (node && node !== page) {
            if (node.nodeType === 1 && node.matches(selector)) { return node; }
            node = node.parentNode;
        }
        return null;
    }
    var BLOCKS = "p,h1,h2,h3,h4,h5,h6,li,blockquote,pre,div,td,th";
    function selectedBlocks() {
        restoreSelection();
        var sel = window.getSelection();
        if (!sel.rangeCount) { return []; }
        var range = sel.getRangeAt(0);
        var result = [];
        page.querySelectorAll("p,h1,h2,h3,h4,h5,h6,li,blockquote,pre").forEach(function (el) {
            if (range.intersectsNode(el)) { result.push(el); }
        });
        if (!result.length) {
            var b = closest(currentNode(), BLOCKS);
            if (b) { result.push(b); }
        }
        return result;
    }
    function wrapSelection(style) {
        restoreSelection();
        var sel = window.getSelection();
        if (!sel.rangeCount || sel.isCollapsed) { return false; }
        var range = sel.getRangeAt(0);
        var span = document.createElement("span");
        Object.keys(style).forEach(function (k) { span.style[k] = style[k]; });
        span.appendChild(range.extractContents());
        range.insertNode(span);
        // Nettoie les tailles imbriquées pour que la nouvelle s'applique.
        if (style.fontSize) { span.querySelectorAll("[style*='font-size']").forEach(function (el) { el.style.fontSize = ""; }); }
        if (style.fontFamily) { span.querySelectorAll("[style*='font-family']").forEach(function (el) { el.style.fontFamily = ""; }); }
        sel.removeAllRanges();
        var r = document.createRange();
        r.selectNodeContents(span);
        sel.addRange(r);
        saveSelection();
        markDirty();
        return true;
    }
    function currentFontSizePt() {
        var node = currentNode();
        if (!node) { return 11; }
        var px = parseFloat(window.getComputedStyle(node).fontSize) || 14.67;
        return Math.round(px * 0.75 * 2) / 2;
    }

    // ------------------------------------------------------------------
    // État du ruban (gras actif, police, taille…)
    // ------------------------------------------------------------------
    function refreshState() {
        ["bold", "italic", "underline", "strikeThrough", "subscript", "superscript",
            "insertUnorderedList", "insertOrderedList", "justifyLeft", "justifyCenter",
            "justifyRight", "justifyFull"].forEach(function (cmd) {
            var on = false;
            try { on = document.queryCommandState(cmd); } catch (e) { /* ignore */ }
            document.querySelectorAll('.ws-ribbon button[data-cmd="' + cmd + '"]').forEach(function (b) {
                b.classList.toggle("on", on);
            });
        });
        var node = currentNode();
        if (node && page.contains(node)) {
            var cs = window.getComputedStyle(node);
            var family = (cs.fontFamily || "").split(",")[0].replace(/["']/g, "").trim();
            var fontSel = $("ws-font");
            if (family && !Array.prototype.some.call(fontSel.options, function (o) { return o.value === family; })) {
                fontSel.add(new Option(family, family));
            }
            if (family) { fontSel.value = family; }
            var pt = String(currentFontSizePt()).replace(/\.0$/, "");
            var sizeSel = $("ws-size");
            if (!Array.prototype.some.call(sizeSel.options, function (o) { return o.value === pt; })) {
                sizeSel.add(new Option(pt, pt));
            }
            sizeSel.value = pt;
        }
    }

    function updateCounts() {
        var text = page.innerText || "";
        var words = (text.match(/\S+/g) || []).length;
        $("ws-words").textContent = words + (words > 1 ? " mots" : " mot");
        var pageHeight = page.offsetWidth * 29.7 / 21;
        var breaks = page.querySelectorAll("[style*='page-break-before'], [style*='break-before']").length;
        var pages = Math.max(1, Math.ceil(page.scrollHeight / pageHeight), breaks + 1);
        $("ws-pages").textContent = "Page(s) : " + pages;
    }

    // ------------------------------------------------------------------
    // Enregistrement
    // ------------------------------------------------------------------
    function rpc(url, params) {
        return fetch(url, {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: params || {} }),
        }).then(function (r) { return r.json(); }).then(function (data) {
            if (data.error) {
                var msg = (data.error.data && data.error.data.message) || data.error.message;
                throw new Error(msg);
            }
            return data.result;
        });
    }
    function cleanHtml() {
        var clone = page.cloneNode(true);
        clone.querySelectorAll(".ws-selected").forEach(function (el) { el.classList.remove("ws-selected"); });
        return clone.innerHTML;
    }
    function save(toSource) {
        setStatus(toSource ? "Enregistrement…" : "Sauvegarde du brouillon…");
        return rpc("/word_editor/sheet/" + attachmentId + "/save", {
            html: cleanHtml(),
            to_source: !!(toSource && canWrite),
        }).then(function (res) {
            if (!res.ok) { throw new Error(res.error); }
            dirty = false;
            var now = new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
            $("ws-saved").style.color = "#107c10";
            $("ws-saved").textContent = res.saved_to_source
                ? "Enregistré dans le fichier à " + now
                : "Brouillon enregistré à " + now + (canWrite ? "" : " (lecture seule)");
            setStatus("");
            return res;
        }).catch(function (err) {
            setStatus("");
            $("ws-saved").style.color = "#a4262c";
            $("ws-saved").textContent = "Erreur d'enregistrement";
            alert("Enregistrement impossible :\n" + err.message);
        });
    }
    setInterval(function () { if (dirty) { save(false); } }, 60000);
    window.addEventListener("beforeunload", function (ev) {
        if (dirty) { ev.preventDefault(); ev.returnValue = ""; }
    });

    // ------------------------------------------------------------------
    // Tableaux
    // ------------------------------------------------------------------
    function insertTable() {
        var spec = window.prompt("Taille du tableau (colonnes x lignes)", "3x3");
        if (!spec) { return; }
        var m = spec.match(/(\d+)\s*[x×*]\s*(\d+)/i);
        if (!m) { return; }
        var cols = Math.min(+m[1], 20), rows = Math.min(+m[2], 100);
        var html = '<table style="width:100%;border-collapse:collapse">';
        for (var r = 0; r < rows; r++) {
            html += "<tr>";
            for (var c = 0; c < cols; c++) { html += '<td style="border:1px solid #000;padding:2pt 5pt"><br></td>'; }
            html += "</tr>";
        }
        html += "</table><p><br></p>";
        exec("insertHTML", html);
    }
    function tableOp(op) {
        restoreSelection();
        var cell = closest(currentNode(), "td,th");
        if (!cell) { alert("Placez le curseur dans une cellule du tableau."); return; }
        var row = cell.parentNode, table = closest(row, "table");
        var index = Array.prototype.indexOf.call(row.children, cell);
        function newCell(ref) {
            var td = document.createElement(ref ? ref.tagName : "td");
            td.setAttribute("style", ref ? ref.getAttribute("style") || "" : "");
            td.innerHTML = "<br>";
            return td;
        }
        if (op === "rowAbove" || op === "rowBelow") {
            var tr = document.createElement("tr");
            Array.prototype.forEach.call(row.children, function (c) { tr.appendChild(newCell(c)); });
            row.parentNode.insertBefore(tr, op === "rowAbove" ? row : row.nextSibling);
        } else if (op === "colLeft" || op === "colRight") {
            table.querySelectorAll("tr").forEach(function (tr) {
                var ref = tr.children[Math.min(index, tr.children.length - 1)];
                if (!ref) { return; }
                tr.insertBefore(newCell(ref), op === "colLeft" ? ref : ref.nextSibling);
            });
        } else if (op === "delRow") {
            row.remove();
            if (!table.querySelector("tr")) { table.remove(); }
        } else if (op === "delCol") {
            table.querySelectorAll("tr").forEach(function (tr) { if (tr.children[index]) { tr.children[index].remove(); } });
            if (!table.querySelector("td,th")) { table.remove(); }
        } else if (op === "delTable") {
            table.remove();
        } else if (op === "borders") {
            var none = cell.style.borderStyle === "none";
            table.querySelectorAll("td,th").forEach(function (c) {
                c.style.border = none ? "1px solid #000" : "none";
            });
        }
        markDirty();
    }

    // ------------------------------------------------------------------
    // Rechercher / remplacer
    // ------------------------------------------------------------------
    function textNodes() {
        var walker = document.createTreeWalker(page, NodeFilter.SHOW_TEXT, null);
        var list = [], n;
        while ((n = walker.nextNode())) { list.push(n); }
        return list;
    }
    function findNext() {
        var needle = $("ws-find-text").value;
        if (!needle) { return false; }
        var lower = needle.toLowerCase();
        var nodes = textNodes();
        var sel = window.getSelection();
        var startNode = null, startOffset = 0;
        if (sel.rangeCount && page.contains(sel.getRangeAt(0).endContainer)) {
            startNode = sel.getRangeAt(0).endContainer;
            startOffset = sel.getRangeAt(0).endOffset;
        }
        var started = !startNode;
        for (var pass = 0; pass < 2; pass++) {
            for (var i = 0; i < nodes.length; i++) {
                var node = nodes[i];
                var from = 0;
                if (!started) {
                    if (node !== startNode) { continue; }
                    started = true;
                    from = startOffset;
                }
                var pos = node.data.toLowerCase().indexOf(lower, from);
                if (pos !== -1) {
                    var r = document.createRange();
                    r.setStart(node, pos);
                    r.setEnd(node, pos + needle.length);
                    sel.removeAllRanges();
                    sel.addRange(r);
                    savedRange = r.cloneRange();
                    var el = node.parentNode;
                    if (el && el.scrollIntoView) { el.scrollIntoView({ block: "center" }); }
                    $("ws-find-info").textContent = "";
                    return true;
                }
            }
            started = true;
            startOffset = 0;
        }
        $("ws-find-info").textContent = "Aucun résultat";
        return false;
    }
    function replaceOne() {
        var sel = window.getSelection();
        var needle = $("ws-find-text").value;
        if (sel.rangeCount && sel.toString().toLowerCase() === needle.toLowerCase() && needle) {
            savedRange = sel.getRangeAt(0).cloneRange();
            exec("insertText", $("ws-replace-text").value);
        }
        findNext();
    }
    function replaceAll() {
        var needle = $("ws-find-text").value;
        if (!needle) { return; }
        var re = new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
        var count = 0;
        textNodes().forEach(function (n) {
            var replaced = n.data.replace(re, function () { count++; return $("ws-replace-text").value; });
            if (replaced !== n.data) { n.data = replaced; }
        });
        $("ws-find-info").textContent = count + " remplacement(s)";
        if (count) { markDirty(); }
    }

    // ------------------------------------------------------------------
    // Zoom
    // ------------------------------------------------------------------
    function setZoom(z) {
        zoom = Math.max(0.5, Math.min(2, Math.round(z * 10) / 10));
        zoomBox.style.zoom = zoom;
        $("ws-zoom-range").value = Math.round(zoom * 100);
        $("ws-zoom-label").textContent = Math.round(zoom * 100) + " %";
    }

    // ------------------------------------------------------------------
    // Symboles
    // ------------------------------------------------------------------
    function symbolMenu(button) {
        var old = document.querySelector(".ws-symbols");
        if (old) { old.remove(); return; }
        var menu = document.createElement("div");
        menu.className = "ws-symbols";
        menu.setAttribute("style", "position:fixed;z-index:50;background:#fff;border:1px solid #c8c6c4;" +
            "box-shadow:0 4px 12px rgba(0,0,0,.2);padding:6px;display:grid;grid-template-columns:repeat(8,28px);gap:2px");
        "©®™€£$¥°±×÷≈≠≤≥§¶•…«»“”‘’–—←→↑↓✓✗★☐☑αβπΩµ∞√∑".split("").forEach(function (ch) {
            var b = document.createElement("button");
            b.textContent = ch;
            b.setAttribute("style", "width:28px;height:28px;border:1px solid #eee;background:#fff;cursor:pointer;font-size:15px");
            b.addEventListener("mousedown", function (ev) { ev.preventDefault(); });
            b.addEventListener("click", function () { exec("insertText", ch); menu.remove(); });
            menu.appendChild(b);
        });
        var rect = button.getBoundingClientRect();
        menu.style.left = rect.left + "px";
        menu.style.top = rect.bottom + 2 + "px";
        document.body.appendChild(menu);
    }

    // ------------------------------------------------------------------
    // Commandes du ruban
    // ------------------------------------------------------------------
    var commands = {
        save: function () { save(true); },
        download: function () { save(false).then(function () { window.location.href = downloadUrl; }); },
        print: function () { window.print(); },
        reload: function () {
            if (!confirm("Annuler toutes les modifications et recharger le fichier Word d'origine ?")) { return; }
            rpc("/word_editor/sheet/" + attachmentId + "/reload", {}).then(function () {
                dirty = false;
                window.location.reload();
            }).catch(function (err) { alert(err.message); });
        },
        undo: function () { exec("undo"); },
        redo: function () { exec("redo"); },
        paste: function () {
            restoreSelection();
            if (navigator.clipboard && navigator.clipboard.readText) {
                navigator.clipboard.readText().then(function (t) { exec("insertText", t); })
                    .catch(function () { alert("Utilisez Ctrl+V pour coller."); });
            } else { alert("Utilisez Ctrl+V pour coller."); }
        },
        cut: function () { exec("cut"); },
        copy: function () { exec("copy"); },
        formatPainter: function (btn) {
            var node = currentNode();
            if (!node || !page.contains(node)) { return; }
            var cs = window.getComputedStyle(node);
            painterStyle = {
                fontFamily: cs.fontFamily, fontSize: cs.fontSize, fontWeight: cs.fontWeight,
                fontStyle: cs.fontStyle, textDecoration: cs.textDecorationLine, color: cs.color,
            };
            btn.classList.add("on");
            setStatus("Sélectionnez le texte où appliquer la mise en forme");
        },
        growFont: function () {
            var steps = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36, 48, 72];
            var cur = currentFontSizePt();
            var next = steps.find(function (s) { return s > cur; }) || 72;
            wrapSelection({ fontSize: next + "pt" });
            refreshState();
        },
        shrinkFont: function () {
            var steps = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36, 48, 72];
            var cur = currentFontSizePt();
            var prev = steps.slice().reverse().find(function (s) { return s < cur; }) || 8;
            wrapSelection({ fontSize: prev + "pt" });
            refreshState();
        },
        removeFormat: function () { exec("removeFormat"); },
        find: function () { $("ws-findbar").hidden = false; $("ws-replace-text").style.display = "none"; $("ws-find-text").focus(); },
        replace: function () { $("ws-findbar").hidden = false; $("ws-replace-text").style.display = ""; $("ws-find-text").focus(); },
        closeFind: function () { $("ws-findbar").hidden = true; },
        findNext: findNext,
        replaceOne: replaceOne,
        replaceAll: replaceAll,
        selectAll: function () { page.focus(); exec("selectAll"); },
        pageBreak: function () { exec("insertHTML", '<p style="page-break-before: always"><br></p>'); },
        table: insertTable,
        rowAbove: function () { tableOp("rowAbove"); },
        rowBelow: function () { tableOp("rowBelow"); },
        colLeft: function () { tableOp("colLeft"); },
        colRight: function () { tableOp("colRight"); },
        delRow: function () { tableOp("delRow"); },
        delCol: function () { tableOp("delCol"); },
        delTable: function () { tableOp("delTable"); },
        borders: function () { tableOp("borders"); },
        image: function () { saveSelection(); $("ws-image-input").click(); },
        link: function () {
            var url = window.prompt("Adresse du lien (https://…)", "https://");
            if (url) { exec("createLink", url); }
        },
        unlink: function () { exec("unlink"); },
        hr: function () { exec("insertHorizontalRule"); },
        date: function () {
            exec("insertText", new Date().toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" }));
        },
        symbol: function (btn) { symbolMenu(btn); },
        zoomIn: function () { setZoom(zoom + 0.1); },
        zoomOut: function () { setZoom(zoom - 0.1); },
        zoom100: function () { setZoom(1); },
        pageWidth: function () { setZoom((canvas.clientWidth - 40) / page.offsetWidth); },
    };
    ["bold", "italic", "underline", "strikeThrough", "subscript", "superscript",
        "insertUnorderedList", "insertOrderedList", "indent", "outdent",
        "justifyLeft", "justifyCenter", "justifyRight", "justifyFull"].forEach(function (cmd) {
        commands[cmd] = function () { exec(cmd); };
    });

    document.querySelectorAll("[data-cmd]").forEach(function (btn) {
        btn.addEventListener("mousedown", function (ev) {
            if (btn.closest(".ws-findbar")) { return; }
            ev.preventDefault();   // garde la sélection dans la page
        });
        btn.addEventListener("click", function () {
            var fn = commands[btn.dataset.cmd];
            if (fn) { fn(btn); }
        });
    });
    document.querySelectorAll(".ws-style").forEach(function (btn) {
        btn.addEventListener("mousedown", function (ev) { ev.preventDefault(); });
        btn.addEventListener("click", function () { exec("formatBlock", "<" + btn.dataset.block + ">"); });
    });

    // Onglets
    document.querySelectorAll(".ws-tab").forEach(function (tab) {
        tab.addEventListener("click", function () {
            document.querySelectorAll(".ws-tab").forEach(function (t) { t.classList.toggle("active", t === tab); });
            document.querySelectorAll(".ws-panel").forEach(function (p) {
                p.classList.toggle("active", p.dataset.panel === tab.dataset.tab);
            });
        });
    });

    // Listes déroulantes et couleurs
    $("ws-font").addEventListener("change", function () {
        if (!wrapSelection({ fontFamily: this.value })) { exec("fontName", this.value); }
    });
    $("ws-size").addEventListener("change", function () { wrapSelection({ fontSize: this.value + "pt" }); });
    $("ws-line").addEventListener("change", function () {
        var v = this.value;
        if (v) { selectedBlocks().forEach(function (b) { b.style.lineHeight = v; }); markDirty(); }
        this.value = "";
    });
    $("ws-fore").addEventListener("input", function () {
        $("ws-fore-sw").style.borderBottomColor = this.value; exec("foreColor", this.value);
    });
    $("ws-back").addEventListener("input", function () {
        $("ws-back-sw").style.borderBottomColor = this.value; exec("hiliteColor", this.value);
    });
    $("ws-shade").addEventListener("input", function () {
        var v = this.value;
        selectedBlocks().forEach(function (b) { b.style.backgroundColor = v; });
        markDirty();
    });
    $("ws-cell").addEventListener("input", function () {
        restoreSelection();
        var cell = closest(currentNode(), "td,th");
        if (cell) { cell.style.backgroundColor = this.value; markDirty(); }
    });
    $("ws-zoom-range").addEventListener("input", function () { setZoom(this.value / 100); });
    $("ws-find-text").addEventListener("keydown", function (ev) { if (ev.key === "Enter") { ev.preventDefault(); findNext(); } });

    // Images
    $("ws-image-input").addEventListener("change", function () {
        var file = this.files && this.files[0];
        if (!file) { return; }
        var reader = new FileReader();
        reader.onload = function () {
            exec("insertHTML", '<img src="' + reader.result + '" style="max-width:100%"/>');
        };
        reader.readAsDataURL(file);
        this.value = "";
    });
    page.addEventListener("click", function (ev) {
        page.querySelectorAll("img.ws-selected").forEach(function (i) { i.classList.remove("ws-selected"); });
        if (ev.target.tagName === "IMG") { ev.target.classList.add("ws-selected"); setStatus("Double-cliquez sur l'image pour la redimensionner"); }
    });
    page.addEventListener("dblclick", function (ev) {
        if (ev.target.tagName !== "IMG") { return; }
        var w = window.prompt("Largeur de l'image (en % de la page)", "50");
        if (w) { ev.target.style.width = Math.max(5, Math.min(100, +w)) + "%"; ev.target.style.height = "auto"; markDirty(); }
    });

    // Sélection / modifications
    document.addEventListener("selectionchange", function () {
        saveSelection();
        refreshState();
    });
    page.addEventListener("input", markDirty);
    page.addEventListener("mouseup", function () {
        if (painterStyle) {
            var s = painterStyle;
            painterStyle = null;
            document.querySelector('[data-cmd="formatPainter"]').classList.remove("on");
            setStatus("");
            saveSelection();
            wrapSelection({ fontFamily: s.fontFamily, fontSize: s.fontSize, fontWeight: s.fontWeight,
                fontStyle: s.fontStyle, textDecoration: s.textDecoration, color: s.color });
        }
    });

    // Raccourcis clavier (comme Word)
    document.addEventListener("keydown", function (ev) {
        if (!(ev.ctrlKey || ev.metaKey)) { return; }
        var k = ev.key.toLowerCase();
        var map = { s: "save", g: "bold", e: "justifyCenter", l: "justifyLeft", r: "justifyRight",
            j: "justifyFull", f: "find", h: "replace", p: "print" };
        if (ev.shiftKey) { return; }
        if (map[k]) {
            ev.preventDefault();
            commands[map[k]](document.querySelector('[data-cmd="' + map[k] + '"]'));
        }
    });

    // Démarrage
    document.execCommand("defaultParagraphSeparator", false, "p");
    if (!page.innerHTML.trim()) { page.innerHTML = "<p><br></p>"; }
    if (!canWrite) {
        setStatus("Lecture seule : vous ne pouvez pas modifier le fichier d'origine");
        document.querySelectorAll('[data-cmd="save"]').forEach(function (b) { b.title = "Enregistrer un brouillon (lecture seule)"; });
    }
    setZoom(1);
    updateCounts();
    window.addEventListener("resize", updateCounts);
    document.body.dataset.ready = "1";
})();
