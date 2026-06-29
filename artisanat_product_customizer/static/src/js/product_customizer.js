/** @odoo-module **/
/*
 * Configurateur de personnalisation produit (type Zakeke)
 * Widget public Odoo 18.
 *
 * NOUVEAU : la VUE 3D est la surface principale d'édition.
 *  - Ajout de texte, ajout de logo/image, changement de couleur, police,
 *    taille : tout se répercute EN TEMPS RÉEL sur le modèle 3D.
 *  - On peut cliquer-glisser un motif directement SUR le produit 3D pour le
 *    déplacer ; glisser le fond fait pivoter le produit.
 *  - Le canvas Fabric.js reste le moteur de design (texte/image) mais sert
 *    désormais de TEXTURE LIVE appliquée sur le mesh.
 *  - Repli automatique en 2D si le produit n'a pas de modèle .glb.
 */
import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.ArtProductCustomizer = publicWidget.Widget.extend({
    selector: "#art_customizer",
    events: {
        "click .nav-link[data-tool]": "_onSwitchTool",
        "click .js_art_add_text": "_onAddText",
        "change .js_art_motif_input": "_onUploadImage",
        "input .js_art_size": "_onChangeSize",
        "click .js_art_delete": "_onDeleteSelected",
        "click .js_art_reset": "_onReset",
        "click .js_art_add_cart": "_onAddToCart",
        "click .js_art_view2d": "_onView2D",
        "click .js_art_view3d": "_onView3D",
        "input .js_art_rotate": "_onRotateSlider",
        "click .js_art_rot_l": "_onRotateStep",
        "click .js_art_rot_r": "_onRotateStep",
        "input .js_art_scale": "_onScaleSlider",
        "click .js_art_smaller": "_onScaleStep",
        "click .js_art_bigger": "_onScaleStep",
        "click .js_art_apply": "_onApplyMotif",
        "change .js_art_texture_input": "_onUploadTexture",
        "click .js_art_texture_clear": "_onClearTexture",
        "click .js_art_pocket_clear": "_onClearPocket",
    },

    /**
     * @override
     */
    async start() {
        await this._super(...arguments);
        this.productTmplId = parseInt(this.el.dataset.productTmplId);
        this.productId = parseInt(this.el.dataset.productId);
        this.currency = this.el.dataset.currency || "";
        this.activeColor = "#000000";
        this.activeFont = "Roboto";
        this.activeAreaId = null;
        this.activeColorway = null;
        this.activeMaterial = null;
        this.activeDimension = null;
        this.activeTexture = null;     // URL/dataURL de la texture plein produit
        this.activePocket = null;      // poche appliquée (mutuellement exclusive)
        // Suivi des choix RÉELLEMENT faits par le client : tant qu'une catégorie
        // n'a pas été activement choisie, son supplément n'est PAS facturé (le
        // prix ne bouge donc pas tout seul au chargement avec les valeurs par
        // défaut de dimension / coloris).
        this._userChose = {
            colorway: false,
            material: false,
            texture: false,
            dimension: false,
        };
        this.view3d = false;
        this.has3D = false;
        this._realGlb = false;   // vrai modèle .glb chargé (≠ panneau auto)

        await this._ensureFabric();
        if (typeof window.fabric === "undefined") {
            console.error("[Customizer] Fabric.js introuvable.");
            return;
        }

        this.config = await rpc("/shop/customizer/config", {
            product_tmpl_id: this.productTmplId,
        });
        if (!this.config || this.config.error) {
            this.el.classList.add("d-none");
            return;
        }

        this._loadGoogleFonts();
        this._hideDefaultCart();
        this._initCanvas();
        this._buildFontSelect();
        this._buildColorSwatches();
        this._buildClipartGrid();
        this._buildAreaTabs();
        this._buildColorways();
        this._buildMaterials();
        this._buildTextureLibrary();
        this._buildProductColors();
        this._buildDimensions();
        this._buildPockets();

        // ----- 3D = vue principale -----------------------------------
        const m = this.config.model_3d || {};
        const auto = this.config.auto_3d || {};
        this.autoPanel3D = !!auto.enabled;
        this.has3D = !!m.url || this.autoPanel3D;
        this._realGlb = !!m.url;   // un vrai fichier .glb est fourni

        if (this.has3D) {
            // Produit 3D : on NE charge PAS la photo de fond (elle créerait un
            // repère différent de l'UV 3D). La zone est juste mémorisée ; le
            // fond du canvas portera la couleur produit.
            this._currentArea = this.config.areas[0] || null;
            this.activeAreaId = this._currentArea ? this._currentArea.id : null;
            this._computeZone(this._currentArea);
            // 3D AUTO depuis l'image : la photo produit sert de base au mesh.
            if (this.autoPanel3D && auto.image_url) {
                this._basePhotoUrl = auto.image_url;
                this._setBasePhoto(auto.image_url);
            }
        } else {
            this._loadArea(this.config.areas[0]);
        }
        this._recomputePrice();

        if (this.has3D) {
            // On affiche la bascule et on démarre directement en 3D.
            this.el.querySelector(".art-viewmode").classList.remove("d-none");
            this.el.querySelector(".art-3d-hint").classList.remove("d-none");
            await this._onView3D();
        } else {
            // Pas de modèle 3D -> on reste en 2D (comportement historique).
            this._onView2D();
        }
    },

    // ---------------------------------------------------------------
    //  Dépendance Fabric.js (auto-hébergée ou CDN)
    // ---------------------------------------------------------------
    _ensureFabric() {
        if (typeof window.fabric !== "undefined") {
            return Promise.resolve();
        }
        return new Promise((resolve) => {
            const script = document.createElement("script");
            // Auto-héberger : remplacez l'URL par
            // "/artisanat_product_customizer/static/lib/fabric/fabric.min.js"
            script.src =
                "https://cdnjs.cloudflare.com/ajax/libs/fabric.js/5.3.1/fabric.min.js";
            script.onload = () => resolve();
            script.onerror = () => resolve();
            document.head.appendChild(script);
        });
    },

    // ---------------------------------------------------------------
    //  Initialisation
    // ---------------------------------------------------------------
    _initCanvas() {
        const wrap = this.el.querySelector(".art-canvas-wrap");
        const size = Math.min(wrap.clientWidth || 480, 520);
        this.canvasSize = size;
        this.canvas = new window.fabric.Canvas("art_canvas", {
            width: size,
            height: size,
            backgroundColor: "#f4f4f4",
            preserveObjectStacking: true,
        });
        this.canvas.on("selection:created", () => this._onSelectionChange());
        this.canvas.on("selection:updated", () => this._onSelectionChange());
        this.canvas.on("selection:cleared", () => this._hideMotifTools());
        this.canvas.on("object:added", () => this._recomputePrice());
        this.canvas.on("object:moving", (e) => this._clampToZone(e.target));
        this.canvas.on("object:modified", (e) => this._clampToZone(e.target));
        this.canvas.on("object:removed", () => this._recomputePrice());
        // Chaque rendu du canvas rafraîchit la texture 3D (binding "live").
        this.canvas.on("after:render", () => {
            if (!this._three) return;
            if (this._realGlb) {
                // Vrai modèle : on recompose (texture d'origine + design).
                this._recompositeNow();
            } else if (this._three.liveTex) {
                this._three.liveTex.needsUpdate = true;
            }
        });
    },

    _hideDefaultCart() {
        const main = document.querySelector("#product_detail_main");
        if (!main) return;
        const defaultBtn = main.querySelector("#add_to_cart, #o_wsale_cta_wrapper");
        const formCart = main.querySelector("form[action='/shop/cart/update']");
        const target = defaultBtn || formCart;
        if (target) {
            target.classList.add("d-none");
        }
    },

    _loadGoogleFonts() {
        const fams = this.config.fonts
            .filter((f) => f.google)
            .map((f) => f.family.replace(/ /g, "+") + ":wght@400;700");
        if (!fams.length) return;
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = "https://fonts.googleapis.com/css2?" +
            fams.map((f) => "family=" + f).join("&") + "&display=swap";
        document.head.appendChild(link);
    },

    _buildFontSelect() {
        const sel = this.el.querySelector(".js_art_font");
        sel.innerHTML = "";
        this.config.fonts.forEach((f) => {
            const opt = document.createElement("option");
            opt.value = f.family;
            opt.textContent = f.name;
            opt.style.fontFamily = f.family;
            sel.appendChild(opt);
        });
        sel.addEventListener("change", (ev) => {
            this.activeFont = ev.target.value;
            this._applyToSelection("fontFamily", this.activeFont);
        });
        if (this.config.fonts.length) {
            this.activeFont = this.config.fonts[0].family;
        }
    },

    _buildColorSwatches() {
        const box = this.el.querySelector(".js_art_colors");
        box.innerHTML = "";
        this.config.colors.forEach((c, idx) => {
            const sw = document.createElement("span");
            sw.className = "art-swatch" + (idx === 0 ? " active" : "");
            sw.style.background = c.color;
            sw.title = c.name;
            sw.addEventListener("click", () => {
                box.querySelectorAll(".art-swatch").forEach((s) =>
                    s.classList.remove("active"));
                sw.classList.add("active");
                this.activeColor = c.color;
                this._applyToSelection("fill", c.color);
            });
            box.appendChild(sw);
        });
        if (this.config.colors.length) {
            this.activeColor = this.config.colors[0].color;
        }
    },

    _buildClipartGrid() {
        const grid = this.el.querySelector(".js_art_clipart_grid");
        const wrap = this.el.querySelector(".js_art_clipart_wrap");
        grid.innerHTML = "";
        if (!this.config.cliparts.length) {
            // Aucun motif prédéfini : on masque le bloc "choisir un existant",
            // le client peut toujours parcourir le sien.
            if (wrap) wrap.classList.add("d-none");
            return;
        }
        if (wrap) wrap.classList.remove("d-none");
        this.config.cliparts.forEach((cp) => {
            const img = document.createElement("img");
            img.src = cp.url;
            img.className = "art-clipart-item";
            img.title = cp.name;
            img.dataset.extra = cp.extra_price || 0;
            img.addEventListener("click", () => this._addClipart(cp));
            grid.appendChild(img);
        });
    },

    _buildAreaTabs() {
        const box = this.el.querySelector(".art-areas");
        box.innerHTML = "";
        if (this.config.areas.length <= 1) return;
        this.config.areas.forEach((area, idx) => {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "btn btn-outline-secondary btn-sm" +
                (idx === 0 ? " active" : "");
            btn.textContent = area.name;
            btn.addEventListener("click", () => {
                box.querySelectorAll("button").forEach((b) =>
                    b.classList.remove("active"));
                btn.classList.add("active");
                this._loadArea(area);
            });
            box.appendChild(btn);
        });
    },

    _loadArea(area) {
        if (!area) return;
        this.activeAreaId = area.id;
        this._currentArea = area;
        this._computeZone(area);

        // VUE 3D active : fond = couleur produit (texture), pas de photo ni cadre.
        if (this.view3d) {
            this._apply3DCanvasBackground();
            if (this._frame) {
                this.canvas.remove(this._frame);
                this._frame = null;
            }
            this.canvas.renderAll();
            return;
        }

        // VUE 2D : on affiche la photo/texture du produit + le cadre de la zone
        // imprimable, pour tous les produits (3D inclus). Le motif reste confiné
        // à cette zone -> même repère qu'en 3D (l'UV de la zone).
        const self = this;
        let bgUrl = area.image_url;
        if (this.activeColorway && this.activeColorway.image_url) {
            bgUrl = this.activeColorway.image_url;
        }
        window.fabric.Image.fromURL(
            bgUrl,
            (img) => {
                // Si on est repassé en 3D entre-temps, on n'applique pas la photo.
                if (self.view3d) return;
                const scale = self.canvasSize / Math.max(img.width, img.height);
                img.scale(scale);
                img.set({ selectable: false, evented: false });
                self.canvas.setBackgroundImage(
                    img, self.canvas.renderAll.bind(self.canvas), {
                        top: (self.canvasSize - img.height * scale) / 2,
                        left: (self.canvasSize - img.width * scale) / 2,
                    });
                self._drawAreaFrame(area);
            },
            { crossOrigin: "anonymous" }
        );
    },

    /** Calcule la zone imprimable (en pixels canvas) à partir d'area.box (%). */
    _computeZone(area) {
        const b = (area && area.box) ? area.box
            : { left: 20, top: 20, width: 60, height: 60 };
        this._zone = {
            left: (b.left / 100) * this.canvasSize,
            top: (b.top / 100) * this.canvasSize,
            width: (b.width / 100) * this.canvasSize,
            height: (b.height / 100) * this.canvasSize,
        };
    },

    /** Centre de la zone imprimable (fallback : centre du canvas). */
    _zoneCenter() {
        if (!this._zone) return { x: this.canvasSize / 2, y: this.canvasSize / 2 };
        return {
            x: this._zone.left + this._zone.width / 2,
            y: this._zone.top + this._zone.height / 2,
        };
    },

    /** Contraint le centre d'un motif à rester dans la zone imprimable. */
    _clampToZone(obj) {
        if (!obj || !this._zone || obj === this._frame || !obj._artType) return;
        const z = this._zone;
        const c = obj.getCenterPoint();
        const x = Math.min(Math.max(c.x, z.left), z.left + z.width);
        const y = Math.min(Math.max(c.y, z.top), z.top + z.height);
        if (Math.abs(x - c.x) > 0.01 || Math.abs(y - c.y) > 0.01) {
            obj.setPositionByOrigin(
                new window.fabric.Point(x, y), "center", "center");
            obj.setCoords();
        }
    },

    /** Cadre visuel matérialisant la zone imprimable (vue 2D). */
    _drawAreaFrame(area) {
        if (this.view3d) return;
        if (this._frame) this.canvas.remove(this._frame);
        const z = this._zone || { left: 0, top: 0,
            width: this.canvasSize, height: this.canvasSize };
        this._frame = new window.fabric.Rect({
            left: z.left,
            top: z.top,
            width: z.width,
            height: z.height,
            fill: "rgba(0,0,0,0)",
            stroke: "#7a5cff",
            strokeDashArray: [6, 4],
            selectable: false,
            evented: false,
        });
        this.canvas.add(this._frame);
        this.canvas.renderAll();
    },

    // ===============================================================
    //  COLORIS (changement de couleur du produit)
    // ===============================================================
    _buildColorways() {
        const cws = this.config.colorways || [];
        if (!cws.length) return;
        const box = this.el.querySelector(".js_art_colorway_swatches");
        const wrap = this.el.querySelector(".art-colorways");
        wrap.classList.remove("d-none");
        box.innerHTML = "";
        cws.forEach((cw, idx) => {
            const sw = document.createElement("span");
            sw.className = "art-colorway-swatch" + (idx === 0 ? " active" : "");
            sw.style.background = cw.swatch || cw.material_hex || "#ccc";
            sw.title = cw.name + (cw.extra_price
                ? " (+" + cw.extra_price + this.currency + ")" : "");
            sw.addEventListener("click", () => this._selectColorway(cw, sw));
            box.appendChild(sw);
        });
        // Sélection par défaut (sans recharger la 3D, pas encore prête)
        this._selectColorway(cws[0], box.querySelector(".art-colorway-swatch"), true);
    },

    _selectColorway(cw, swatchEl, silent) {
        this.activeColorway = cw;
        if (!silent) this._userChose.colorway = true;
        const box = this.el.querySelector(".js_art_colorway_swatches");
        if (box && swatchEl) {
            box.querySelectorAll(".art-colorway-swatch").forEach((s) =>
                s.classList.remove("active"));
            swatchEl.classList.add("active");
        }
        const lbl = this.el.querySelector(".js_art_colorway_name");
        if (lbl) lbl.textContent = cw.name;

        if (!silent) {
            if (this.activeTexture) {
                // Une texture plein-produit est active : on la garde (la matière
                // / texture prime sur la couleur du coloris).
                this._restoreBackground();
            } else if (this.view3d && this.autoPanel3D) {
                // 3D auto depuis l'image : la couleur du coloris ne remplace
                // pas la photo (sinon le panneau ne montre plus l'image).
                this._restoreBackground();
            } else if (this.view3d) {
                // 3D (vrai .glb) : la couleur du produit = fond de la texture live.
                this._apply3DCanvasBackground();
                this._apply3DColor(cw.material_hex);
            } else if (this._currentArea && cw.image_url) {
                // 2D : on recharge le fond avec la photo du coloris.
                this._loadArea(this._currentArea);
            }
        }
        this._recomputePrice();
    },

    /** Applique la couleur du coloris courant comme fond du canvas (mode 3D). */
    _apply3DCanvasBackground() {
        // Vrai modèle .glb : le canvas ne sert que de calque de design (texte/
        // logo) posé PAR-DESSUS la texture d'origine -> il doit rester
        // transparent, sinon il recouvrirait tout le produit.
        if (this._realGlb) {
            this.canvas.setBackgroundImage(null, () => {});
            this.canvas.setBackgroundColor(
                "rgba(0,0,0,0)", this.canvas.renderAll.bind(this.canvas));
            return;
        }
        const hex = (this.activeColorway && this.activeColorway.material_hex)
            || "#ffffff";
        this.canvas.setBackgroundImage(null, () => {});
        this.canvas.setBackgroundColor(hex, this.canvas.renderAll.bind(this.canvas));
    },

    // ===============================================================
    //  MATIÈRE (+ texture plein produit / DIY)
    // ===============================================================
    _buildMaterials() {
        const mats = this.config.materials || [];
        const box = this.el.querySelector(".js_art_material_swatches");
        const diy = this.el.querySelector(".js_art_diy_texture");
        if (box) box.innerHTML = "";

        if (this.config.allow_diy_texture && diy) {
            diy.classList.remove("d-none");
        }
        if (!mats.length) {
            if (box && !this.config.allow_diy_texture) {
                box.innerHTML =
                    '<p class="small text-muted mb-0">Aucune matière disponible.</p>';
            }
            return;
        }
        mats.forEach((mt) => {
            const sw = document.createElement("span");
            sw.className = "art-material-swatch";
            sw.title = mt.name + (mt.extra_price
                ? " (+" + mt.extra_price + this.currency + ")" : "");
            if (mt.texture_url) {
                sw.style.backgroundImage = "url('" + mt.texture_url + "')";
            } else {
                sw.style.background = mt.swatch || mt.material_hex || "#ccc";
            }
            sw.addEventListener("click", () => this._selectMaterial(mt, sw));
            box.appendChild(sw);
        });
    },

    _selectMaterial(mt, swatchEl) {
        this.activeMaterial = mt;
        this._userChose.material = true;
        const box = this.el.querySelector(".js_art_material_swatches");
        if (box && swatchEl) {
            box.querySelectorAll(".art-material-swatch").forEach((s) =>
                s.classList.remove("active"));
            swatchEl.classList.add("active");
        }
        const lbl = this.el.querySelector(".js_art_material_name");
        if (lbl) lbl.textContent = mt.name;
        const desc = this.el.querySelector(".js_art_material_desc");
        if (desc) desc.textContent = mt.description || "";

        // Choisir une matière efface une éventuelle texture DIY / de galerie.
        this._diyTexture = null;
        this.activeTextureRec = null;
        const grid = this.el.querySelector(".js_art_texture_grid");
        if (grid) {
            grid.querySelectorAll(".art-texture-item").forEach((s) =>
                s.classList.remove("active"));
        }
        const clr = this.el.querySelector(".js_art_texture_clear");
        if (clr) clr.classList.add("d-none");

        if (mt.texture_url) {
            // Remplit TOUT le produit avec la texture de la matière.
            this._applyProductTexture(mt.texture_url, {
                tiled: mt.tiled !== false,
                scale: mt.tex_scale || 1.0,
            });
        } else {
            // Pas de texture : on applique la couleur matière en fond plein.
            this.activeTexture = null;
            this._restoreBackground();
        }
        this._recomputePrice();
    },

    _onUploadTexture(ev) {
        const file = ev.target.files[0];
        if (!file) return;
        if (file.size > 5 * 1024 * 1024) {
            alert("Image trop lourde (5 Mo max).");
            ev.target.value = "";
            return;
        }
        const reader = new FileReader();
        const self = this;
        reader.onload = (e) => {
            self._diyTexture = e.target.result;
            self._userChose.texture = true;
            // Désélectionne la matière catalogue (on est en DIY).
            const box = self.el.querySelector(".js_art_material_swatches");
            if (box) {
                box.querySelectorAll(".art-material-swatch").forEach((s) =>
                    s.classList.remove("active"));
            }
            self.activeMaterial = null;
            self.activeTextureRec = null;
            const grid = self.el.querySelector(".js_art_texture_grid");
            if (grid) {
                grid.querySelectorAll(".art-texture-item").forEach((s) =>
                    s.classList.remove("active"));
            }
            const lbl = self.el.querySelector(".js_art_material_name");
            if (lbl) lbl.textContent = "Ma texture";
            const clr = self.el.querySelector(".js_art_texture_clear");
            if (clr) clr.classList.remove("d-none");
            self._applyProductTexture(e.target.result);
            self._recomputePrice();
        };
        reader.readAsDataURL(file);
        ev.target.value = "";
    },

    _onClearTexture() {
        this._diyTexture = null;
        this.activeTexture = null;
        this.activeTextureRec = null;
        const grid = this.el.querySelector(".js_art_texture_grid");
        if (grid) {
            grid.querySelectorAll(".art-texture-item").forEach((s) =>
                s.classList.remove("active"));
        }
        const clr = this.el.querySelector(".js_art_texture_clear");
        if (clr) clr.classList.add("d-none");
        const lbl = this.el.querySelector(".js_art_material_name");
        if (lbl) lbl.textContent = this.activeMaterial
            ? this.activeMaterial.name : "";
        this._restoreBackground();
        this._recomputePrice();
    },

    /** Remplit TOUT le produit avec une image de texture (fond plein du canvas).
     *  opts.tiled = true -> mosaïque répétée ; sinon image étirée (cover). */
    _applyProductTexture(url, opts) {
        const self = this;
        this.activeTexture = url;
        this._textureOpts = opts || { tiled: false, scale: 1.0 };
        window.fabric.Image.fromURL(
            url,
            (img) => {
                if (!self.canvas) return;
                self.canvas.setBackgroundColor(null, () => {});

                if (self._textureOpts.tiled && img._element) {
                    // Mosaïque : motif répété sur tout le canvas.
                    const scale = self._textureOpts.scale || 1.0;
                    const pattern = new window.fabric.Pattern({
                        source: img._element,
                        repeat: "repeat",
                        patternTransform: [scale, 0, 0, scale, 0, 0],
                    });
                    self.canvas.setBackgroundColor(
                        pattern, self.canvas.renderAll.bind(self.canvas));
                    self.canvas.setBackgroundImage(null, () => {});
                } else {
                    // Cover : on couvre tout le canvas (= tout le produit).
                    const sc = Math.max(
                        self.canvasSize / img.width,
                        self.canvasSize / img.height);
                    img.scale(sc);
                    img.set({ originX: "center", originY: "center" });
                    self.canvas.setBackgroundImage(
                        img, self.canvas.renderAll.bind(self.canvas), {
                            originX: "center",
                            originY: "center",
                            top: self.canvasSize / 2,
                            left: self.canvasSize / 2,
                        });
                }
                if (self._three && self._three.liveTex) {
                    self._three.liveTex.needsUpdate = true;
                }
            },
            { crossOrigin: "anonymous" }
        );
    },

    /** Restaure le fond produit (texture DIY > matière/coloris > photo). */
    _restoreBackground() {
        if (this._diyTexture) {
            // Image personnelle : on l'affiche en entier (cover), pas tuilée.
            this._applyProductTexture(this._diyTexture, { tiled: false, scale: 1.0 });
            return;
        }
        if (this.activeTexture) {
            this._applyProductTexture(this.activeTexture, this._textureOpts);
            return;
        }
        const hex = (this.activeMaterial && this.activeMaterial.material_hex)
            || (this.activeColorway && this.activeColorway.material_hex)
            || "#ffffff";
        // 3D auto depuis l'image : on retombe sur la photo produit de base.
        if (this._basePhotoUrl && !this.activeMaterial) {
            this._setBasePhoto(this._basePhotoUrl);
            return;
        }
        if (this.view3d) {
            this.canvas.setBackgroundImage(null, () => {});
            this.canvas.setBackgroundColor(
                hex, this.canvas.renderAll.bind(this.canvas));
        } else if (this._currentArea) {
            this._loadArea(this._currentArea);
        } else {
            this.canvas.setBackgroundImage(null, () => {});
            this.canvas.setBackgroundColor(
                hex, this.canvas.renderAll.bind(this.canvas));
        }
    },

    // ===============================================================
    //  COULEUR PRODUIT (onglet dédié, basé sur les coloris)
    // ===============================================================
    _buildProductColors() {
        const cws = this.config.colorways || [];
        const box = this.el.querySelector(".js_art_product_colors");
        const empty = this.el.querySelector(".js_art_color_empty");
        if (!box) return;
        box.innerHTML = "";
        if (!cws.length) {
            if (empty) empty.classList.remove("d-none");
            return;
        }
        cws.forEach((cw, idx) => {
            const sw = document.createElement("span");
            sw.className = "art-colorway-swatch" + (idx === 0 ? " active" : "");
            sw.style.background = cw.swatch || cw.material_hex || "#ccc";
            sw.title = cw.name + (cw.extra_price
                ? " (+" + cw.extra_price + this.currency + ")" : "");
            sw.addEventListener("click", () => {
                box.querySelectorAll(".art-colorway-swatch").forEach((s) =>
                    s.classList.remove("active"));
                sw.classList.add("active");
                const nm = this.el.querySelector(".js_art_color_name");
                if (nm) nm.textContent = cw.name;
                // Réutilise la logique coloris (et synchronise les pastilles
                // affichées sous l'aperçu).
                this._selectColorway(cw, null);
                this._syncColorwaySwatches(cw);
            });
            box.appendChild(sw);
        });
        const nm = this.el.querySelector(".js_art_color_name");
        if (nm && cws.length) nm.textContent = cws[0].name;
    },

    /** Garde les pastilles "sous l'aperçu" et celles de l'onglet synchronisées. */
    _syncColorwaySwatches(cw) {
        const under = this.el.querySelector(".js_art_colorway_swatches");
        if (!under) return;
        const list = this.config.colorways || [];
        const idx = list.indexOf(cw);
        const items = under.querySelectorAll(".art-colorway-swatch");
        items.forEach((s, i) => s.classList.toggle("active", i === idx));
    },

    // ===============================================================
    //  DIMENSION
    // ===============================================================
    _buildDimensions() {
        const dims = this.config.dimensions || [];
        const box = this.el.querySelector(".js_art_dimensions");
        const empty = this.el.querySelector(".js_art_dimension_empty");
        if (!box) return;
        box.innerHTML = "";
        if (!dims.length) {
            if (empty) empty.classList.remove("d-none");
            return;
        }
        dims.forEach((d, idx) => {
            const opt = document.createElement("button");
            opt.type = "button";
            opt.className = "art-dim-option" + (idx === 0 ? " active" : "");
            const price = d.extra_price
                ? ' <span class="art-dim-price">+' + d.extra_price
                  + this.currency + "</span>" : "";
            opt.innerHTML = '<span class="art-dim-label">' + (d.label || d.name)
                + "</span>" + price;
            opt.addEventListener("click", () => {
                box.querySelectorAll(".art-dim-option").forEach((b) =>
                    b.classList.remove("active"));
                opt.classList.add("active");
                this._selectDimension(d);
            });
            box.appendChild(opt);
        });
        // Sélection par défaut (sans surfacturer tant que rien n'est validé).
        this.activeDimension = dims[0];
        this._recomputePrice();
    },

    _selectDimension(d) {
        this.activeDimension = d;
        this._userChose.dimension = true;
        this._recomputePrice();
    },

    // ===============================================================
    //  POCHES (onglet « Poche »)
    //  - 3 types proposés (ou ceux définis côté back-office).
    //  - Emplacement DÉJÀ PRÉCISÉ : la poche se pose à des coordonnées
    //    fixes (centre X/Y + largeur en %), non déplaçable par le client.
    //  - MUTUELLEMENT EXCLUSIVES : appliquer une poche retire la précédente ;
    //    re-cliquer sur la poche active la retire (bascule).
    // ===============================================================

    /** Liste des poches : config back-office, sinon 3 poches par défaut. */
    _pocketList() {
        const fromCfg = (this.config && this.config.pockets) || [];
        if (fromCfg.length) return fromCfg;
        // Repli : 3 types de poche prêts à l'emploi, emplacement déjà précisé.
        const base = "/artisanat_product_customizer/static/src/img/pockets/";
        return [
            {
                id: "default-patch", name: "Poche plaquée",
                description: "Poche simple cousue à plat.",
                image_url: base + "pocket_patch.png",
                pos: { left: 50, top: 62, width: 32 }, extra_price: 0,
            },
            {
                id: "default-zip", name: "Poche zippée",
                description: "Poche fermée par une glissière.",
                image_url: base + "pocket_zip.png",
                pos: { left: 50, top: 62, width: 32 }, extra_price: 0,
            },
            {
                id: "default-flap", name: "Poche à rabat",
                description: "Poche à rabat avec bouton.",
                image_url: base + "pocket_flap.png",
                pos: { left: 50, top: 62, width: 32 }, extra_price: 0,
            },
        ];
    },

    _buildPockets() {
        const box = this.el.querySelector(".js_art_pocket_swatches");
        if (!box) return;
        box.innerHTML = "";
        const pockets = this._pocketList();
        if (!pockets.length) {
            box.innerHTML =
                '<p class="small text-muted mb-0">Aucune poche disponible.</p>';
            return;
        }
        pockets.forEach((pk) => {
            if (!pk.image_url) return;
            const img = document.createElement("img");
            img.src = pk.image_url;
            img.alt = pk.name || "Poche";
            img.title = (pk.name || "Poche") + (pk.extra_price
                ? " (+" + pk.extra_price + this.currency + ")" : "");
            img.className = "art-pocket-swatch";
            img.dataset.pocketId = pk.id;
            img.addEventListener("click", () => this._selectPocket(pk, img));
            box.appendChild(img);
        });
    },

    _selectPocket(pk, swatchEl) {
        // Bascule : re-cliquer la poche active la retire.
        if (this.activePocket && this.activePocket.id === pk.id) {
            this._onClearPocket();
            return;
        }
        // Mutuellement exclusives : on retire l'éventuelle poche précédente.
        this._removePocketObject();
        this.activePocket = pk;

        // État visuel des vignettes (une seule active).
        const box = this.el.querySelector(".js_art_pocket_swatches");
        if (box) {
            box.querySelectorAll(".art-pocket-swatch").forEach((s) =>
                s.classList.remove("active"));
            if (swatchEl) swatchEl.classList.add("active");
        }
        const lbl = this.el.querySelector(".js_art_pocket_name");
        if (lbl) lbl.textContent = pk.name || "";
        const desc = this.el.querySelector(".js_art_pocket_desc");
        if (desc) desc.textContent = pk.description || "";
        const clr = this.el.querySelector(".js_art_pocket_clear");
        if (clr) clr.classList.remove("d-none");

        this._applyPocketOverlay(pk);
    },

    /** Pose le visuel de la poche à l'emplacement déjà précisé (fixe). */
    _applyPocketOverlay(pk) {
        const self = this;
        const pos = pk.pos || { left: 50, top: 62, width: 32 };
        window.fabric.Image.fromURL(
            pk.image_url,
            (img) => {
                const w = ((pos.width || 32) / 100) * self.canvasSize;
                img.scaleToWidth(w);
                img.set({
                    left: ((pos.left != null ? pos.left : 50) / 100)
                        * self.canvasSize,
                    top: ((pos.top != null ? pos.top : 62) / 100)
                        * self.canvasSize,
                    originX: "center",
                    originY: "center",
                    // Emplacement déjà précisé => non déplaçable / non sélectionnable.
                    selectable: false,
                    evented: false,
                    hoverCursor: "default",
                    _artType: "pocket",
                    _pocketId: pk.id,
                    _extraPrice: pk.extra_price || 0,
                });
                // La poche reste sous les textes/motifs ajoutés ensuite.
                self.canvas.add(img);
                self._pocketObject = img;
                if (typeof img.sendToBack === "function") img.sendToBack();
                self.canvas.renderAll();
                self._recomputePrice();
            },
            { crossOrigin: "anonymous" }
        );
    },

    /** Retire l'objet poche du canvas (sans toucher à l'état des vignettes). */
    _removePocketObject() {
        if (this._pocketObject) {
            this.canvas.remove(this._pocketObject);
            this._pocketObject = null;
        } else {
            // Sécurité : retire tout objet poche résiduel.
            this.canvas.getObjects().slice().forEach((o) => {
                if (o._artType === "pocket") this.canvas.remove(o);
            });
        }
    },

    _onClearPocket() {
        this._removePocketObject();
        this.activePocket = null;
        const box = this.el.querySelector(".js_art_pocket_swatches");
        if (box) {
            box.querySelectorAll(".art-pocket-swatch").forEach((s) =>
                s.classList.remove("active"));
        }
        const lbl = this.el.querySelector(".js_art_pocket_name");
        if (lbl) lbl.textContent = "";
        const desc = this.el.querySelector(".js_art_pocket_desc");
        if (desc) desc.textContent = "";
        const clr = this.el.querySelector(".js_art_pocket_clear");
        if (clr) clr.classList.add("d-none");
        this.canvas.renderAll();
        this._recomputePrice();
    },

    // ===============================================================
    //  BIBLIOTHÈQUE DE TEXTURES (prêtes à l'emploi) + base photo
    // ===============================================================
    _buildTextureLibrary() {
        const txs = this.config.textures || [];
        const wrap = this.el.querySelector(".js_art_texture_lib");
        const grid = this.el.querySelector(".js_art_texture_grid");
        if (!grid) return;
        grid.innerHTML = "";
        if (!txs.length) return;
        if (wrap) wrap.classList.remove("d-none");
        txs.forEach((tx) => {
            const img = document.createElement("img");
            img.src = tx.url;
            img.className = "art-texture-item";
            img.title = tx.name + (tx.extra_price
                ? " (+" + tx.extra_price + this.currency + ")" : "");
            img.addEventListener("click", () => this._selectTexture(tx, img));
            grid.appendChild(img);
        });
    },

    _selectTexture(tx, el) {
        // Désélectionne matière catalogue + DIY (une seule source à la fois).
        const matBox = this.el.querySelector(".js_art_material_swatches");
        if (matBox) {
            matBox.querySelectorAll(".art-material-swatch").forEach((s) =>
                s.classList.remove("active"));
        }
        this.activeMaterial = null;
        this._diyTexture = null;
        const clr = this.el.querySelector(".js_art_texture_clear");
        if (clr) clr.classList.add("d-none");

        const grid = this.el.querySelector(".js_art_texture_grid");
        if (grid && el) {
            grid.querySelectorAll(".art-texture-item").forEach((s) =>
                s.classList.remove("active"));
            el.classList.add("active");
        }
        const lbl = this.el.querySelector(".js_art_material_name");
        if (lbl) lbl.textContent = tx.name;

        this.activeTextureRec = tx;   // pour le prix / récapitulatif
        this._userChose.texture = true;
        this._applyProductTexture(tx.url, {
            tiled: tx.tiled !== false,
            scale: tx.tex_scale || 1.0,
        });
        this._recomputePrice();
    },

    /** Pose la photo produit comme fond de base (3D auto) sans la compter
     *  comme un choix de personnalisation (ni prix, ni blocage panier). */
    _setBasePhoto(url) {
        const self = this;
        window.fabric.Image.fromURL(
            url,
            (img) => {
                if (!self.canvas) return;
                const sc = Math.max(
                    self.canvasSize / img.width, self.canvasSize / img.height);
                img.scale(sc);
                img.set({ originX: "center", originY: "center" });
                self.canvas.setBackgroundColor(null, () => {});
                self.canvas.setBackgroundImage(
                    img, self.canvas.renderAll.bind(self.canvas), {
                        originX: "center", originY: "center",
                        top: self.canvasSize / 2, left: self.canvasSize / 2,
                    });
                if (self._three && self._three.liveTex) {
                    self._three.liveTex.needsUpdate = true;
                }
            },
            { crossOrigin: "anonymous" }
        );
    },

    // ===============================================================
    //  BASCULE 2D / 3D
    // ===============================================================
    _onView2D() {
        this.view3d = false;
        this.el.querySelector(".js_art_3d").classList.add("d-none");
        this.el.querySelector(".js_art_view2d").classList.add("active");
        this.el.querySelector(".js_art_view2d").classList.replace(
            "btn-outline-dark", "btn-dark");
        const b3 = this.el.querySelector(".js_art_view3d");
        b3.classList.remove("active");
        b3.classList.replace("btn-dark", "btn-outline-dark");

        const canvasWrap = this.el.querySelector(".js_art_2d");
        const snap = this.el.querySelector(".art-2d-snapshot");
        const cap = this.el.querySelector(".art-2d-caption");

        if (this.has3D) {
            // Produit 3D : la 2D est un APERÇU DE FACE du modèle (sac + motif
            // alignés). La photo marketing ne peut pas s'aligner sur l'UV, on
            // ne l'utilise donc pas ici.
            const url = this._render2DSnapshot();
            if (url && snap) {
                snap.querySelector("img").src = url;
                snap.classList.remove("d-none");
                canvasWrap.classList.add("d-none");
                if (cap) {
                    cap.textContent =
                        "Aperçu du sac (vue courante) — modifiez le design en 3D.";
                    cap.classList.remove("d-none");
                }
            } else {
                // Repli : texture à plat éditable (fond couleur ou photo).
                if (snap) snap.classList.add("d-none");
                canvasWrap.classList.remove("d-none");
                if (this.autoPanel3D && this._basePhotoUrl && !this.activeMaterial
                    && !this.activeTexture) {
                    this._setBasePhoto(this._basePhotoUrl);
                } else {
                    this._apply3DCanvasBackground();
                }
                if (cap) cap.classList.add("d-none");
            }
        } else {
            // Produit sans 3D : 2D éditable (photo + cadre, historique).
            if (snap) snap.classList.add("d-none");
            canvasWrap.classList.remove("d-none");
            if (this._currentArea) {
                this._loadArea(this._currentArea);
            }
            if (cap) cap.classList.remove("d-none");
        }
        this._hideMotifTools();
    },

    /**
     * Capture la vue 3D actuelle et renvoie une image (dataURL).
     * On garde l'angle courant : l'aperçu montre exactement le côté que
     * l'utilisateur regardait (donc son motif), parfaitement aligné.
     */
    _render2DSnapshot() {
        const t = this._three;
        if (!t || !t.renderer || !t.targetMesh) return null;
        try {
            t.renderer.render(t.scene, t.camera);
            return t.renderer.domElement.toDataURL("image/png");
        } catch (e) {
            return null;
        }
    },

    async _onView3D() {
        this.view3d = true;
        this.el.querySelector(".js_art_2d").classList.add("d-none");
        const snap = this.el.querySelector(".art-2d-snapshot");
        if (snap) snap.classList.add("d-none");
        this.el.querySelector(".js_art_3d").classList.remove("d-none");
        const b3 = this.el.querySelector(".js_art_view3d");
        b3.classList.add("active");
        b3.classList.replace("btn-outline-dark", "btn-dark");
        const b2 = this.el.querySelector(".js_art_view2d");
        b2.classList.remove("active");
        b2.classList.replace("btn-dark", "btn-outline-dark");

        // En 3D : on retire le cadre du canvas. Le fond devient soit la photo
        // (mode "3D auto depuis l'image"), soit la couleur produit (vrai .glb).
        if (this._frame) {
            this.canvas.remove(this._frame);
            this._frame = null;
        }
        if (this.autoPanel3D && this._basePhotoUrl && !this.activeMaterial
            && !this.activeTexture) {
            this._setBasePhoto(this._basePhotoUrl);
        } else {
            this._apply3DCanvasBackground();
        }

        if (!this._three) {
            await this._init3D();
        }
        this._showMotifTools();
        const cap = this.el.querySelector(".art-2d-caption");
        if (cap) cap.classList.add("d-none");
    },

    // ===============================================================
    //  MOTEUR 3D (Three.js)
    // ===============================================================
    _ensureThree() {
        if (window.THREE && window.THREE.GLTFLoader && window.THREE.OrbitControls) {
            return Promise.resolve();
        }
        const load = (src) => new Promise((res) => {
            const s = document.createElement("script");
            s.src = src;
            s.onload = res;
            s.onerror = res;
            document.head.appendChild(s);
        });
        const base = "https://unpkg.com/three@0.128.0";
        return (window.THREE ? Promise.resolve() : load(base + "/build/three.min.js"))
            .then(() => load(base + "/examples/js/loaders/GLTFLoader.js"))
            .then(() => load(base + "/examples/js/controls/OrbitControls.js"));
    },

    async _init3D() {
        await this._ensureThree();
        if (!window.THREE || !window.THREE.GLTFLoader) {
            console.error("[Customizer] Three.js indisponible.");
            return;
        }
        const THREE = window.THREE;
        const container = this.el.querySelector("#art_3d_container");
        const w = container.clientWidth || this.canvasSize;
        const h = w;

        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0xf4f4f4);

        const camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 1000);
        const dist = (this.config.model_3d || {}).camera_dist || 3;
        camera.position.set(0, dist * 0.4, dist);

        const renderer = new THREE.WebGLRenderer({
            antialias: true, alpha: true, preserveDrawingBuffer: true });
        renderer.setSize(w, h);
        renderer.setPixelRatio(window.devicePixelRatio || 1);
        if ("outputColorSpace" in renderer) {
            renderer.outputColorSpace = THREE.SRGBColorSpace;
        }
        container.innerHTML = "";
        container.appendChild(renderer.domElement);

        // Lumières
        scene.add(new THREE.AmbientLight(0xffffff, 0.9));
        const dir = new THREE.DirectionalLight(0xffffff, 0.8);
        dir.position.set(2, 4, 3);
        scene.add(dir);
        const dir2 = new THREE.DirectionalLight(0xffffff, 0.4);
        dir2.position.set(-2, 1, -3);
        scene.add(dir2);

        const controls = new THREE.OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.enablePan = false;

        this._three = {
            THREE, scene, camera, renderer, controls,
            meshes: [], raycaster: new THREE.Raycaster(),
            pointer: new THREE.Vector2(), dragging: null, liveTex: null,
        };

        // Interactions de placement direct sur la 3D.
        this._bind3DPointer(renderer.domElement);

        // Charger le modèle : .glb importé en priorité, sinon 3D AUTO
        // générée depuis l'image (forme procédurale, aucun service externe).
        const url = (this.config.model_3d || {}).url;
        const self = this;
        if (url) {
            const loader = new THREE.GLTFLoader();
            loader.load(url, (gltf) => {
                const root = gltf.scene;
                const box = new THREE.Box3().setFromObject(root);
                const center = box.getCenter(new THREE.Vector3());
                const size = box.getSize(new THREE.Vector3());
                const maxDim = Math.max(size.x, size.y, size.z) || 1;
                root.position.sub(center);
                root.scale.multiplyScalar(2 / maxDim);

                root.traverse((o) => {
                    if (o.isMesh) {
                        o.material = o.material.clone();
                        self._three.meshes.push(o);
                    }
                });
                scene.add(root);
                self._three.root = root;

                const meshName = (self.config.model_3d || {}).mesh;
                self._three.targetMesh = meshName
                    ? self._three.meshes.find((m) => m.name === meshName)
                    : self._three.meshes[0];

                self._attachLiveTexture();
                if (self.activeColorway && self._userChose.colorway) {
                    self._apply3DColor(self.activeColorway.material_hex);
                }
            });
        } else if (this.autoPanel3D) {
            // ----- 3D AUTOMATIQUE depuis l'image (sans .glb) -----
            const mesh = self._buildAutoMesh(THREE);
            scene.add(mesh);
            self._three.root = mesh;
            self._three.meshes.push(mesh);
            self._three.targetMesh = mesh;
            self._attachLiveTexture();
        }

        // Boucle de rendu
        const animate = () => {
            if (!self._three) return;
            self._three.raf = requestAnimationFrame(animate);
            controls.update();
            renderer.render(scene, camera);
        };
        animate();

        // Redimensionnement responsive (garde un carré).
        this._onResize3D = () => {
            if (!this._three) return;
            const nw = container.clientWidth || w;
            this._three.renderer.setSize(nw, nw);
            this._three.camera.aspect = 1;
            this._three.camera.updateProjectionMatrix();
        };
        window.addEventListener("resize", this._onResize3D);
    },

    /**
     * Construit le mesh 3D (panneau plat) sur lequel l'image du produit
     * (via la texture live du canvas) sera projetée. Permet une 3D rotative
     * SANS fichier .glb ni convertisseur externe.
     */
    _buildAutoMesh(THREE) {
        const geo = new THREE.BoxGeometry(1.8, 1.8, 0.05);
        const mat = new THREE.MeshStandardMaterial({
            color: 0xffffff, roughness: 0.85, metalness: 0.0,
        });
        return new THREE.Mesh(geo, mat);
    },

    /**
     * Branche le canvas Fabric comme texture temps réel du mesh cible.
     * Le fond du canvas porte la couleur produit ; les textes / logos
     * apparaissent par-dessus -> le tout s'affiche directement sur la 3D.
     */
    _attachLiveTexture() {
        const t = this._three;
        if (!t || !t.targetMesh || t.liveTex) return;
        // Vrai modèle .glb : on PRÉSERVE sa texture d'origine et on compose le
        // design par-dessus. Le panneau "auto" garde, lui, l'ancien binding.
        if (this._realGlb) {
            this._setupCompositeTexture();
            return;
        }
        const THREE = t.THREE;
        const tex = new THREE.CanvasTexture(this.canvas.lowerCanvasEl);
        // UV glTF -> flipY false ; géométrie procédurale (3D auto) -> flipY true.
        tex.flipY = (!(this.config.model_3d || {}).url) && this.autoPanel3D;
        if ("colorSpace" in tex) tex.colorSpace = THREE.SRGBColorSpace;
        const mat = t.targetMesh.material;
        // La carte porte les vraies couleurs : on neutralise la teinte de base.
        if (mat.color) mat.color.set(0xffffff);
        mat.map = tex;
        mat.transparent = false;
        mat.needsUpdate = true;
        t.liveTex = tex;
        tex.needsUpdate = true;
    },

    /**
     * Vrai modèle .glb : prépare une texture COMPOSITE = (texture d'origine du
     * mesh cible) + (design Fabric : texte / logo) dessiné par-dessus à la
     * bonne position UV. Le modèle garde donc son apparence d'origine.
     */
    _setupCompositeTexture() {
        const t = this._three;
        const THREE = t.THREE;
        const mat = t.targetMesh.material;

        // Texture d'origine (baseColorTexture) et couleur de base du matériau.
        t.baseMap = (mat.map && mat.map.image) ? mat.map.image : null;
        t.baseColor = (mat.color && mat.color.clone)
            ? mat.color.clone() : new THREE.Color(0xffffff);

        // Dimensions du composite : celles de la texture d'origine si dispo,
        // sinon un carré confortable.
        const bw = (t.baseMap && (t.baseMap.width || t.baseMap.naturalWidth)) || 1024;
        const bh = (t.baseMap && (t.baseMap.height || t.baseMap.naturalHeight)) || 1024;
        const cnv = document.createElement("canvas");
        cnv.width = bw;
        cnv.height = bh;
        t.composite = cnv;
        t.compositeCtx = cnv.getContext("2d");

        const tex = new THREE.CanvasTexture(cnv);
        tex.flipY = false;                       // convention glTF
        if ("colorSpace" in tex) tex.colorSpace = THREE.SRGBColorSpace;
        // On garde les autres réglages d'échantillonnage de l'original.
        if (mat.map) {
            tex.wrapS = mat.map.wrapS;
            tex.wrapT = mat.map.wrapT;
        }
        // La carte composite porte déjà les vraies couleurs -> teinte neutre.
        if (mat.color) mat.color.set(0xffffff);
        mat.map = tex;
        mat.transparent = false;
        mat.needsUpdate = true;
        t.liveTex = tex;

        this._recompositeNow();
    },

    /** Redessine la texture composite (origine + design) pour le vrai modèle. */
    _recompositeNow() {
        const t = this._three;
        if (!t || !t.composite || !t.compositeCtx) return;
        const ctx = t.compositeCtx;
        const w = t.composite.width;
        const h = t.composite.height;

        // 1) Fond = texture d'origine (ou couleur de base si le modèle n'a pas
        //    de texture).
        ctx.clearRect(0, 0, w, h);
        if (t.baseMap) {
            try {
                ctx.drawImage(t.baseMap, 0, 0, w, h);
            } catch (e) {
                ctx.fillStyle = "#" + t.baseColor.getHexString();
                ctx.fillRect(0, 0, w, h);
            }
        } else {
            ctx.fillStyle = "#" + t.baseColor.getHexString();
            ctx.fillRect(0, 0, w, h);
        }

        // 2) Design du client (canvas Fabric, fond transparent) étiré sur tout
        //    l'espace UV : le texte / logo apparaît là où il est placé.
        try {
            ctx.drawImage(this.canvas.lowerCanvasEl, 0, 0, w, h);
        } catch (e) { /* canvas pas prêt */ }

        if (t.liveTex) t.liveTex.needsUpdate = true;
    },

    _apply3DColor(hex) {
        // Vrai modèle .glb : le coloris teinte la matière du produit (la texture
        // d'origine + le design composite restent visibles).
        if (this._realGlb) {
            if (!this._three || !hex) return;
            const THREE = this._three.THREE;
            const color = new THREE.Color(hex);
            this._three.meshes.forEach((m) => {
                if (m.material && m.material.color) {
                    m.material.color.set(color);
                    m.material.needsUpdate = true;
                }
            });
            return;
        }
        // En texture live, la couleur produit passe par le fond du canvas.
        if (this._three && this._three.liveTex) {
            this._apply3DCanvasBackground();
            return;
        }
        if (!this._three || !hex) return;
        const THREE = this._three.THREE;
        const color = new THREE.Color(hex);
        this._three.meshes.forEach((m) => {
            if (m.material && m.material.color) {
                m.material.color.set(color);
                m.material.needsUpdate = true;
            }
        });
    },

    // ---------------------------------------------------------------
    //  Placement direct du motif SUR la 3D (raycasting + UV)
    // ---------------------------------------------------------------
    _bind3DPointer(dom) {
        const self = this;
        this._3dDom = dom;
        this._3dDown = (ev) => self._on3DPointerDown(ev);
        this._3dMove = (ev) => self._on3DPointerMove(ev);
        this._3dUp = () => self._on3DPointerUp();
        this._3dWheel = (ev) => self._on3DWheel(ev);
        dom.addEventListener("pointerdown", this._3dDown);
        window.addEventListener("pointermove", this._3dMove);
        window.addEventListener("pointerup", this._3dUp);
        // Capture : intercepte la molette AVANT OrbitControls quand un motif
        // est sélectionné (molette = redimensionner le motif).
        dom.addEventListener("wheel", this._3dWheel, { passive: false, capture: true });
    },

    /** Molette sur la 3D : agrandit / réduit le motif sélectionné. */
    _on3DWheel(ev) {
        const o = this._activeMotif();
        if (!o) return; // aucun motif -> zoom caméra normal
        ev.preventDefault();
        ev.stopImmediatePropagation();
        const up = ev.deltaY < 0;
        o.scale(Math.max(0.05, (o.scaleX || 1) * (up ? 1.08 : 0.92)));
        o.setCoords();
        this.canvas.renderAll();
        this._selRefScale = o.scaleX;
        const sc = this.el.querySelector(".js_art_scale");
        if (sc) sc.value = 100;
    },

    /** Coordonnées NDC + intersection UV avec le mesh cible. */
    _raycastUV(ev) {
        const t = this._three;
        if (!t || !t.targetMesh) return null;
        const dom = t.renderer.domElement;
        const rect = dom.getBoundingClientRect();
        t.pointer.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
        t.pointer.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
        t.raycaster.setFromCamera(t.pointer, t.camera);
        const hits = t.raycaster.intersectObject(t.targetMesh, true);
        if (!hits.length || !hits[0].uv) return null;
        return { u: hits[0].uv.x, v: hits[0].uv.y };
    },

    _uvToCanvasPoint(uv) {
        // flipY=false -> (u,v)=(0,0) coin haut-gauche du canvas.
        return {
            x: uv.u * this.canvasSize,
            y: uv.v * this.canvasSize,
        };
    },

    _on3DPointerDown(ev) {
        const uv = this._raycastUV(ev);
        if (!uv) return; // clic hors produit -> rotation libre (OrbitControls)
        const pt = this._uvToCanvasPoint(uv);
        // Cherche le motif (texte/logo) sous le point, du plus haut au plus bas.
        const objs = this._userObjects();
        let picked = null;
        for (let i = objs.length - 1; i >= 0; i--) {
            const o = objs[i];
            if (o.containsPoint && o.containsPoint(new window.fabric.Point(pt.x, pt.y))) {
                picked = o;
                break;
            }
        }
        // Maj enfoncée sans motif sous le curseur : on agit sur la sélection.
        if (!picked && ev.shiftKey) picked = this._activeMotif();
        if (picked) {
            // On saisit ce motif : on désactive la rotation caméra pendant le geste.
            this._three.controls.enabled = false;
            this.canvas.setActiveObject(picked);
            this.canvas.renderAll();
            this._syncToolbarFromSelection();
            this._showMotifTools();
            if (ev.shiftKey) {
                // Mode ROTATION : glisser horizontalement fait tourner le motif.
                this._three.dragging = {
                    obj: picked, mode: "rotate",
                    startX: ev.clientX, startAngle: picked.angle || 0,
                };
            } else {
                // Mode DÉPLACEMENT.
                const c = picked.getCenterPoint();
                this._three.dragging = {
                    obj: picked, mode: "move",
                    offX: pt.x - c.x, offY: pt.y - c.y,
                };
            }
        }
        // Sinon : on laisse OrbitControls faire pivoter le produit.
    },

    _on3DPointerMove(ev) {
        const drag = this._three && this._three.dragging;
        if (!drag) return;
        if (drag.mode === "rotate") {
            const a = (((drag.startAngle + (ev.clientX - drag.startX) * 0.5) % 360)
                + 360) % 360;
            drag.obj.rotate(a);
            drag.obj.setCoords();
            this.canvas.renderAll();
            const rot = this.el.querySelector(".js_art_rotate");
            if (rot) rot.value = Math.round(a);
            return;
        }
        const uv = this._raycastUV(ev);
        if (!uv) return;
        const pt = this._uvToCanvasPoint(uv);
        drag.obj.setPositionByOrigin(
            new window.fabric.Point(pt.x - drag.offX, pt.y - drag.offY),
            "center", "center"
        );
        this._clampToZone(drag.obj);
        drag.obj.setCoords();
        this.canvas.renderAll();
    },

    _on3DPointerUp() {
        if (this._three && this._three.dragging) {
            this._three.dragging = null;
            this._three.controls.enabled = true;
        }
    },

    // ---------------------------------------------------------------
    //  Rotation / taille du motif (barre d'outils flottante 3D)
    // ---------------------------------------------------------------
    /** Renvoie le motif (texte/image/clipart) actuellement sélectionné. */
    _activeMotif() {
        const o = this.canvas && this.canvas.getActiveObject();
        return o && o._artType ? o : null;
    },

    _onSelectionChange() {
        this._syncToolbarFromSelection();
        this._showMotifTools();
    },

    /** Affiche et synchronise la barre rotation/taille (vue 3D uniquement). */
    _showMotifTools() {
        const bar = this.el.querySelector(".art-3d-tools");
        if (!bar) return;
        const o = this._activeMotif();
        if (!this.view3d || !o) {
            bar.classList.add("d-none");
            return;
        }
        bar.classList.remove("d-none");
        const rot = this.el.querySelector(".js_art_rotate");
        if (rot) rot.value = Math.round((((o.angle || 0) % 360) + 360) % 360);
        // Référence d'échelle figée au moment de la sélection ; slider à 100 %.
        this._selRefScale = o.scaleX || 1;
        const sc = this.el.querySelector(".js_art_scale");
        if (sc) sc.value = 100;
    },

    _hideMotifTools() {
        const bar = this.el.querySelector(".art-3d-tools");
        if (bar) bar.classList.add("d-none");
    },

    _onRotateSlider(ev) {
        const o = this._activeMotif();
        if (!o) return;
        o.rotate(parseInt(ev.target.value) || 0);
        o.setCoords();
        this.canvas.renderAll();
    },

    _onRotateStep(ev) {
        const o = this._activeMotif();
        if (!o) return;
        const dir = ev.currentTarget.classList.contains("js_art_rot_l") ? -15 : 15;
        const a = ((((o.angle || 0) + dir) % 360) + 360) % 360;
        o.rotate(a);
        o.setCoords();
        this.canvas.renderAll();
        const rot = this.el.querySelector(".js_art_rotate");
        if (rot) rot.value = Math.round(a);
    },

    _onScaleSlider(ev) {
        const o = this._activeMotif();
        if (!o) return;
        const factor = (parseInt(ev.target.value) || 100) / 100;
        const base = this._selRefScale || 1;
        o.scale(Math.max(0.05, base * factor));
        o.setCoords();
        this.canvas.renderAll();
    },

    _onScaleStep(ev) {
        const o = this._activeMotif();
        if (!o) return;
        const up = ev.currentTarget.classList.contains("js_art_bigger");
        o.scale(Math.max(0.05, (o.scaleX || 1) * (up ? 1.1 : 0.9)));
        o.setCoords();
        this.canvas.renderAll();
        this._selRefScale = o.scaleX;
        const sc = this.el.querySelector(".js_art_scale");
        if (sc) sc.value = 100;
    },

    /**
     * « Appliquer » : fige la modification courante sur le produit.
     * Concrètement, on désélectionne le motif (les poignées disparaissent),
     * on rafraîchit la texture 3D et on referme la barre d'outils.
     */
    _onApplyMotif() {
        this.canvas.discardActiveObject();
        this.canvas.renderAll();
        if (this._three && this._three.liveTex) {
            this._three.liveTex.needsUpdate = true;
        }
        this._hideMotifTools();
        // Petit retour visuel "Appliqué ✓"
        const bar = this.el.querySelector(".art-3d-tools");
        if (bar) {
            const flash = document.createElement("div");
            flash.className = "art-3d-applied";
            flash.innerHTML = '<i class="fa fa-check me-1"/>Modifications appliquées';
            const wrap = this.el.querySelector(".art-3d-wrap");
            if (wrap) {
                wrap.appendChild(flash);
                setTimeout(() => flash.classList.add("show"), 10);
                setTimeout(() => {
                    flash.classList.remove("show");
                    setTimeout(() => flash.remove(), 250);
                }, 1300);
            }
        }
    },

    // ---------------------------------------------------------------
    //  Outils
    // ---------------------------------------------------------------
    _onSwitchTool(ev) {
        const tool = ev.currentTarget.dataset.tool;
        this.el.querySelectorAll(".nav-link[data-tool]").forEach((b) =>
            b.classList.toggle("active", b === ev.currentTarget));
        this.el.querySelectorAll(".art-panel").forEach((p) =>
            p.classList.toggle("d-none", p.dataset.panel !== tool));
    },

    _onAddText() {
        const input = this.el.querySelector(".js_art_text_input");
        const value = (input.value || "").trim();
        if (!value) return;
        const size = parseInt(this.el.querySelector(".js_art_size").value) || 40;
        const ctr = this._zoneCenter();
        const text = new window.fabric.IText(value, {
            left: ctr.x,
            top: ctr.y,
            originX: "center",
            originY: "center",
            fontFamily: this.activeFont,
            fill: this.activeColor,
            fontSize: size,
            _artType: "text",
        });
        this.canvas.add(text);
        this.canvas.setActiveObject(text);
        this._clampToZone(text);
        this.canvas.renderAll();
        input.value = "";
    },

    _onUploadImage(ev) {
        const file = ev.target.files[0];
        if (!file) return;
        if (file.size > 5 * 1024 * 1024) {
            alert("Image trop lourde (5 Mo max).");
            return;
        }
        const reader = new FileReader();
        const self = this;
        reader.onload = (e) => {
            window.fabric.Image.fromURL(e.target.result, (img) => {
                const zw = (self._zone && self._zone.width) || self.canvasSize;
                img.scaleToWidth(zw * 0.6);
                const ctr = self._zoneCenter();
                img.set({
                    left: ctr.x,
                    top: ctr.y,
                    originX: "center",
                    originY: "center",
                    _artType: "image",
                });
                self.canvas.add(img);
                self.canvas.setActiveObject(img);
                self._clampToZone(img);
                self.canvas.renderAll();
            });
        };
        reader.readAsDataURL(file);
        ev.target.value = "";
    },

    _addClipart(cp) {
        const self = this;
        window.fabric.Image.fromURL(
            cp.url,
            (img) => {
                const zw = (self._zone && self._zone.width) || self.canvasSize;
                img.scaleToWidth(zw * 0.45);
                const ctr = self._zoneCenter();
                img.set({
                    left: ctr.x,
                    top: ctr.y,
                    originX: "center",
                    originY: "center",
                    _artType: "clipart",
                    _extraPrice: cp.extra_price || 0,
                });
                self.canvas.add(img);
                self.canvas.setActiveObject(img);
                self._clampToZone(img);
                self.canvas.renderAll();
            },
            { crossOrigin: "anonymous" }
        );
    },

    _onChangeSize(ev) {
        const v = parseInt(ev.target.value);
        this.el.querySelector(".js_art_size_val").textContent = v;
        this._applyToSelection("fontSize", v);
    },

    _applyToSelection(prop, value) {
        const obj = this.canvas && this.canvas.getActiveObject();
        if (obj && (prop !== "fontSize" || obj._artType === "text")) {
            obj.set(prop, value);
            this.canvas.renderAll();
        }
    },

    _syncToolbarFromSelection() {
        const obj = this.canvas.getActiveObject();
        if (!obj) return;
        if (obj._artType === "text") {
            if (obj.fill) this.activeColor = obj.fill;
            if (obj.fontFamily) {
                this.el.querySelector(".js_art_font").value = obj.fontFamily;
            }
            if (obj.fontSize) {
                this.el.querySelector(".js_art_size").value = obj.fontSize;
                this.el.querySelector(".js_art_size_val").textContent = obj.fontSize;
            }
        }
    },

    _onDeleteSelected() {
        const obj = this.canvas.getActiveObject();
        if (obj && obj !== this._frame) {
            this.canvas.remove(obj);
            this.canvas.discardActiveObject();
            this.canvas.renderAll();
        }
    },

    _onReset() {
        // 1) Retire tous les éléments ajoutés par le client (texte / images /
        //    motifs), en gardant le cadre de zone.
        this.canvas.getObjects().slice().forEach((o) => {
            if (o !== this._frame) this.canvas.remove(o);
        });
        this.canvas.discardActiveObject();

        // Retire la poche éventuellement appliquée + nettoie son état visuel.
        this._pocketObject = null;
        this.activePocket = null;
        this.el.querySelectorAll(".art-pocket-swatch.active").forEach((s) =>
            s.classList.remove("active"));
        const pkName = this.el.querySelector(".js_art_pocket_name");
        if (pkName) pkName.textContent = "";
        const pkDesc = this.el.querySelector(".js_art_pocket_desc");
        if (pkDesc) pkDesc.textContent = "";
        const pkClr = this.el.querySelector(".js_art_pocket_clear");
        if (pkClr) pkClr.classList.add("d-none");

        // 2) Réinitialise toutes les sélections (matière, texture, couleur,
        //    dimension) et le suivi des choix => le prix repart à 0.
        this.activeMaterial = null;
        this.activeTexture = null;
        this.activeTextureRec = null;
        this._diyTexture = null;
        this._userChose = {
            colorway: false, material: false, texture: false, dimension: false,
        };

        // 3) Nettoie l'état visuel des pastilles / vignettes.
        this.el.querySelectorAll(
            ".art-material-swatch.active, .art-texture-item.active"
        ).forEach((s) => s.classList.remove("active"));
        const matName = this.el.querySelector(".js_art_material_name");
        if (matName) matName.textContent = "";
        const matDesc = this.el.querySelector(".js_art_material_desc");
        if (matDesc) matDesc.textContent = "";
        const clr = this.el.querySelector(".js_art_texture_clear");
        if (clr) clr.classList.add("d-none");

        // 4) Vide les champs "parcourir" (motif + texture DIY).
        this.el.querySelectorAll(
            ".js_art_motif_input, .js_art_texture_input"
        ).forEach((inp) => { inp.value = ""; });

        // 5) Remet le coloris et la dimension sur leur valeur par défaut
        //    (sélection silencieuse : pas de surcoût).
        const cws = this.config.colorways || [];
        if (cws.length) {
            this.el.querySelectorAll(".art-colorway-swatch").forEach((s, i) =>
                s.classList.toggle("active", i === 0));
            this._selectColorway(cws[0], null, true);
            const cn = this.el.querySelector(".js_art_color_name");
            if (cn) cn.textContent = cws[0].name;
            const cwn = this.el.querySelector(".js_art_colorway_name");
            if (cwn) cwn.textContent = cws[0].name;
        } else {
            this.activeColorway = null;
        }
        const dims = this.config.dimensions || [];
        if (dims.length) {
            this.el.querySelectorAll(".art-dim-option").forEach((b, i) =>
                b.classList.toggle("active", i === 0));
            this.activeDimension = dims[0];
        } else {
            this.activeDimension = null;
        }

        // 6) Restaure le fond produit d'origine et recalcule le prix (=> 0).
        this._restoreBackground();
        this._recomputePrice();
        this.canvas.renderAll();
    },

    // ---------------------------------------------------------------
    //  Prix & contenu
    // ---------------------------------------------------------------
    _userObjects() {
        return this.canvas.getObjects().filter((o) => o._artType);
    },

    _recomputePrice() {
        if (!this.canvas) return 0;
        let extra = this.config.base_price || 0;
        this._userObjects().forEach((o) => {
            if (o._artType === "text") extra += this.config.text_price || 0;
            if (o._artType === "image") extra += this.config.image_price || 0;
            if (o._artType === "clipart") extra += o._extraPrice || 0;
            if (o._artType === "pocket") extra += o._extraPrice || 0;
        });
        const area = this.config.areas.find((a) => a.id === this.activeAreaId);
        if (area) extra += area.extra_price || 0;
        // On ne facture une catégorie QUE si le client l'a choisie activement
        // (les valeurs par défaut ne font pas grimper le prix toutes seules).
        if (this._userChose.colorway && this.activeColorway
                && this.activeColorway.extra_price) {
            extra += this.activeColorway.extra_price;
        }
        if (this._userChose.material && this.activeMaterial
                && this.activeMaterial.extra_price) {
            extra += this.activeMaterial.extra_price;
        }
        if (this._userChose.dimension && this.activeDimension
                && this.activeDimension.extra_price) {
            extra += this.activeDimension.extra_price;
        }
        if (this._userChose.texture && this.activeTextureRec
                && this.activeTextureRec.extra_price) {
            extra += this.activeTextureRec.extra_price;
        }
        const hasChoice = this._userObjects().length
            || (this._userChose.colorway && this.activeColorway)
            || (this._userChose.material && this.activeMaterial)
            || (this._userChose.texture && (this._diyTexture || this.activeTextureRec))
            || (this._userChose.dimension && this.activeDimension);
        this.currentExtra = hasChoice ? extra : 0;
        const span = this.el.querySelector(".js_art_extra");
        if (span) span.textContent = this.currentExtra.toFixed(2);
        return this.currentExtra;
    },

    _buildSummary() {
        const summary = { area: this.activeAreaId, elements: [] };
        if (this.activeColorway) {
            summary.colorway = {
                id: this.activeColorway.id,
                name: this.activeColorway.name,
                color: this.activeColorway.material_hex,
            };
        }
        if (this.activeMaterial) {
            summary.material = {
                id: this.activeMaterial.id,
                name: this.activeMaterial.name,
                textured: !!this.activeMaterial.texture_url,
            };
        }
        if (this._diyTexture) {
            summary.material = { name: "Texture personnalisée (DIY)", diy: true };
        }
        if (this.activeTextureRec) {
            summary.texture = {
                id: this.activeTextureRec.id,
                name: this.activeTextureRec.name,
            };
        }
        if (this.activeDimension) {
            summary.dimension = {
                id: this.activeDimension.id,
                name: this.activeDimension.label || this.activeDimension.name,
                width: this.activeDimension.width,
                height: this.activeDimension.height,
                depth: this.activeDimension.depth,
            };
        }
        if (this.activePocket) {
            summary.pocket = {
                id: this.activePocket.id,
                name: this.activePocket.name,
                extra_price: this.activePocket.extra_price || 0,
            };
        }
        this._userObjects().forEach((o) => {
            if (o._artType === "text") {
                summary.elements.push({
                    type: "text",
                    value: o.text,
                    font: o.fontFamily,
                    color: o.fill,
                    size: o.fontSize,
                });
            } else if (o._artType !== "pocket") {
                // La poche est déjà décrite dans summary.pocket.
                summary.elements.push({ type: o._artType });
            }
        });
        return summary;
    },

    /** Capture une vignette du rendu 3D courant (si dispo). */
    _capture3DPreview() {
        const t = this._three;
        if (!t || !t.renderer) return null;
        try {
            t.renderer.render(t.scene, t.camera);
            return t.renderer.domElement.toDataURL("image/png");
        } catch (e) {
            return null;
        }
    },

    // ---------------------------------------------------------------
    //  Ajout au panier
    // ---------------------------------------------------------------
    async _onAddToCart(ev) {
        const btn = ev.currentTarget;
        const hasChoice = this._userObjects().length
            || (this._userChose.colorway && this.activeColorway)
            || (this._userChose.material && this.activeMaterial)
            || (this._userChose.texture && (this._diyTexture || this.activeTextureRec))
            || (this._userChose.dimension && this.activeDimension);
        if (!hasChoice) {
            alert("Choisissez une matière, une couleur, une dimension ou ajoutez "
                + "un élément avant de valider.");
            return;
        }
        btn.disabled = true;
        btn.innerHTML = '<i class="fa fa-spinner fa-spin me-2"/>Traitement...';

        try {
            if (this._frame) this.canvas.remove(this._frame);
            this.canvas.discardActiveObject();
            this.canvas.renderAll();

            // Aperçu : la vue 3D si on y est, sinon le canvas.
            const preview = (this.view3d && this._capture3DPreview())
                || this.canvas.toDataURL({ format: "png", quality: 0.7 });
            // Fichier d'impression HD : toujours le design à plat (canvas).
            const printImg = this.canvas.toDataURL({
                format: "png",
                multiplier: 3,
            });
            const designJson = JSON.stringify(
                this.canvas.toJSON(["_artType", "_extraPrice", "_pocketId"]));

            const saved = await rpc("/shop/customizer/save", {
                product_tmpl_id: this.productTmplId,
                product_id: this.productId,
                design_json: designJson,
                preview: preview,
                print_image: printImg,
                summary: this._buildSummary(),
                extra_price: this._recomputePrice(),
            });
            if (saved.error) throw new Error(saved.error);

            await rpc("/shop/customizer/add", {
                product_id: this.productId,
                customization_id: saved.customization_id,
                add_qty: 1,
            });

            window.location.href = "/shop/cart";
        } catch (e) {
            console.error("[Customizer]", e);
            alert("Une erreur est survenue. Merci de réessayer.");
            btn.disabled = false;
            btn.innerHTML =
                '<i class="fa fa-shopping-cart me-2"/>Ajouter au panier (personnalisé)';
            if (!this.view3d) {
                const area = this.config.areas.find((a) => a.id === this.activeAreaId);
                if (area) this._drawAreaFrame(area);
            }
        }
    },

    /**
     * @override  Nettoyage des écouteurs globaux / 3D.
     */
    destroy() {
        if (this._onResize3D) {
            window.removeEventListener("resize", this._onResize3D);
        }
        if (this._3dMove) window.removeEventListener("pointermove", this._3dMove);
        if (this._3dUp) window.removeEventListener("pointerup", this._3dUp);
        if (this._3dDom && this._3dWheel) {
            this._3dDom.removeEventListener("wheel", this._3dWheel, { capture: true });
        }
        if (this._three && this._three.raf) {
            cancelAnimationFrame(this._three.raf);
        }
        this._super(...arguments);
    },
});

export default publicWidget.registry.ArtProductCustomizer;
