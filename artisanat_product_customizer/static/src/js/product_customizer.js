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
        "change .js_art_image_input": "_onUploadImage",
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
        this.view3d = false;
        this.has3D = false;

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

        // ----- 3D = vue principale -----------------------------------
        const m = this.config.model_3d || {};
        this.has3D = !!m.url;

        if (this.has3D) {
            // Produit 3D : on NE charge PAS la photo de fond (elle créerait un
            // repère différent de l'UV 3D). La zone est juste mémorisée ; le
            // fond du canvas portera la couleur produit.
            this._currentArea = this.config.areas[0] || null;
            this.activeAreaId = this._currentArea ? this._currentArea.id : null;
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
        this.canvas.on("object:removed", () => this._recomputePrice());
        // Chaque rendu du canvas rafraîchit la texture 3D (binding "live").
        this.canvas.on("after:render", () => {
            if (this._three && this._three.liveTex) {
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
        grid.innerHTML = "";
        if (!this.config.cliparts.length) {
            grid.innerHTML = '<p class="small text-muted">Aucun clipart disponible.</p>';
            return;
        }
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
        // Produit 3D (ou vue 3D active) : fond = couleur produit, sans photo
        // ni cadre, pour garder un repère IDENTIQUE entre la 2D à plat et la 3D.
        if (this.view3d || this.has3D) {
            this._apply3DCanvasBackground();
            if (this._frame) {
                this.canvas.remove(this._frame);
                this._frame = null;
            }
            this.canvas.renderAll();
            return;
        }
        const self = this;
        let bgUrl = area.image_url;
        if (this.activeColorway && this.activeColorway.image_url) {
            bgUrl = this.activeColorway.image_url;
        }
        window.fabric.Image.fromURL(
            bgUrl,
            (img) => {
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

    /** Cadre visuel matérialisant la zone imprimable (2D sans modèle 3D). */
    _drawAreaFrame(area) {
        if (this.view3d || this.has3D) return;
        if (this._frame) this.canvas.remove(this._frame);
        const b = area.box;
        this._frame = new window.fabric.Rect({
            left: (b.left / 100) * this.canvasSize,
            top: (b.top / 100) * this.canvasSize,
            width: (b.width / 100) * this.canvasSize,
            height: (b.height / 100) * this.canvasSize,
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
        const box = this.el.querySelector(".js_art_colorway_swatches");
        if (box && swatchEl) {
            box.querySelectorAll(".art-colorway-swatch").forEach((s) =>
                s.classList.remove("active"));
            swatchEl.classList.add("active");
        }
        const lbl = this.el.querySelector(".js_art_colorway_name");
        if (lbl) lbl.textContent = cw.name;

        if (!silent) {
            if (this.view3d) {
                // 3D : la couleur du produit = fond de la texture live.
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
        const hex = (this.activeColorway && this.activeColorway.material_hex)
            || "#ffffff";
        this.canvas.setBackgroundImage(null, () => {});
        this.canvas.setBackgroundColor(hex, this.canvas.renderAll.bind(this.canvas));
    },

    // ===============================================================
    //  BASCULE 2D / 3D
    // ===============================================================
    _onView2D() {
        this.view3d = false;
        this.el.querySelector(".js_art_2d").classList.remove("d-none");
        this.el.querySelector(".js_art_3d").classList.add("d-none");
        this.el.querySelector(".js_art_view2d").classList.add("active");
        this.el.querySelector(".js_art_view2d").classList.replace(
            "btn-outline-dark", "btn-dark");
        const b3 = this.el.querySelector(".js_art_view3d");
        b3.classList.remove("active");
        b3.classList.replace("btn-dark", "btn-outline-dark");

        // Vue 2D :
        //  - produit 3D -> on affiche la MÊME texture à plat (fond couleur,
        //    sans photo ni cadre) : positions identiques à la 3D ;
        //  - produit sans 3D -> photo de fond + cadre (comportement historique).
        if (this._currentArea) {
            this._loadArea(this._currentArea);
        } else if (this.has3D) {
            this._apply3DCanvasBackground();
        }
        this._hideMotifTools();
    },

    async _onView3D() {
        this.view3d = true;
        this.el.querySelector(".js_art_2d").classList.add("d-none");
        this.el.querySelector(".js_art_3d").classList.remove("d-none");
        const b3 = this.el.querySelector(".js_art_view3d");
        b3.classList.add("active");
        b3.classList.replace("btn-outline-dark", "btn-dark");
        const b2 = this.el.querySelector(".js_art_view2d");
        b2.classList.remove("active");
        b2.classList.replace("btn-dark", "btn-outline-dark");

        // En 3D : on retire la photo et le cadre du canvas, fond = couleur produit.
        if (this._frame) {
            this.canvas.remove(this._frame);
            this._frame = null;
        }
        this._apply3DCanvasBackground();

        if (!this._three) {
            await this._init3D();
        }
        this._showMotifTools();
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

        const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
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

        // Charger le modèle
        const url = (this.config.model_3d || {}).url;
        const loader = new THREE.GLTFLoader();
        const self = this;
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

            // Branche la texture LIVE (canvas -> mesh) puis applique la couleur.
            self._attachLiveTexture();
            if (self.activeColorway) {
                self._apply3DColor(self.activeColorway.material_hex);
            }
        });

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
     * Branche le canvas Fabric comme texture temps réel du mesh cible.
     * Le fond du canvas porte la couleur produit ; les textes / logos
     * apparaissent par-dessus -> le tout s'affiche directement sur la 3D.
     */
    _attachLiveTexture() {
        const t = this._three;
        if (!t || !t.targetMesh || t.liveTex) return;
        const THREE = t.THREE;
        const tex = new THREE.CanvasTexture(this.canvas.lowerCanvasEl);
        tex.flipY = false;
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

    _apply3DColor(hex) {
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
        const text = new window.fabric.IText(value, {
            left: this.canvasSize / 2,
            top: this.canvasSize / 2,
            originX: "center",
            originY: "center",
            fontFamily: this.activeFont,
            fill: this.activeColor,
            fontSize: size,
            _artType: "text",
        });
        this.canvas.add(text);
        this.canvas.setActiveObject(text);
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
                const max = self.canvasSize * 0.4;
                img.scaleToWidth(max);
                img.set({
                    left: self.canvasSize / 2,
                    top: self.canvasSize / 2,
                    originX: "center",
                    originY: "center",
                    _artType: "image",
                });
                self.canvas.add(img);
                self.canvas.setActiveObject(img);
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
                img.scaleToWidth(self.canvasSize * 0.3);
                img.set({
                    left: self.canvasSize / 2,
                    top: self.canvasSize / 2,
                    originX: "center",
                    originY: "center",
                    _artType: "clipart",
                    _extraPrice: cp.extra_price || 0,
                });
                self.canvas.add(img);
                self.canvas.setActiveObject(img);
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
        this.canvas.getObjects().slice().forEach((o) => {
            if (o !== this._frame) this.canvas.remove(o);
        });
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
        });
        const area = this.config.areas.find((a) => a.id === this.activeAreaId);
        if (area) extra += area.extra_price || 0;
        if (this.activeColorway && this.activeColorway.extra_price) {
            extra += this.activeColorway.extra_price;
        }
        this.currentExtra = this._userObjects().length || this.activeColorway
            ? extra : 0;
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
        this._userObjects().forEach((o) => {
            if (o._artType === "text") {
                summary.elements.push({
                    type: "text",
                    value: o.text,
                    font: o.fontFamily,
                    color: o.fill,
                    size: o.fontSize,
                });
            } else {
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
        if (!this._userObjects().length && !this.activeColorway) {
            alert("Ajoutez un élément ou choisissez un coloris avant de valider.");
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
                this.canvas.toJSON(["_artType", "_extraPrice"]));

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
