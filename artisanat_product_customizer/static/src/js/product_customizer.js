/** @odoo-module **/
/*
 * Configurateur de personnalisation produit (type Zakeke)
 * Widget public Odoo 18 — moteur canvas basé sur Fabric.js
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
        this._setup3DToggle();
        this._loadArea(this.config.areas[0]);
        this._recomputePrice();
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
        this.canvas.on("selection:created", () => this._syncToolbarFromSelection());
        this.canvas.on("selection:updated", () => this._syncToolbarFromSelection());
        this.canvas.on("object:added", () => this._recomputePrice());
        this.canvas.on("object:removed", () => this._recomputePrice());
    },

    _hideDefaultCart() {
        // Masque le formulaire d'achat standard d'Odoo pour ne garder que
        // le bouton "Ajouter au panier (personnalisé)" du configurateur.
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
        const self = this;
        // Si un coloris avec photo est sélectionné, il remplace l'image de zone.
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

    /** Cadre visuel matérialisant la zone imprimable. */
    _drawAreaFrame(area) {
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
        // Sélection par défaut
        this._selectColorway(cws[0], box.querySelector(".art-colorway-swatch"));
    },

    _selectColorway(cw, swatchEl) {
        this.activeColorway = cw;
        const box = this.el.querySelector(".js_art_colorway_swatches");
        if (box && swatchEl) {
            box.querySelectorAll(".art-colorway-swatch").forEach((s) =>
                s.classList.remove("active"));
            swatchEl.classList.add("active");
        }
        const lbl = this.el.querySelector(".js_art_colorway_name");
        if (lbl) lbl.textContent = cw.name;

        // 2D : on recharge le fond avec la photo du coloris
        if (this._currentArea && cw.image_url) {
            this._loadArea(this._currentArea);
        }
        // 3D : on recolore la matière
        if (this.view3d && this._three) {
            this._apply3DColor(cw.material_hex);
        }
        this._recomputePrice();
    },

    // ===============================================================
    //  BASCULE 2D / 3D
    // ===============================================================
    _setup3DToggle() {
        const m = this.config.model_3d || {};
        if (!m.url) return; // pas de modèle => pas de bouton 3D
        this.el.querySelector(".art-viewmode").classList.remove("d-none");
    },

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

        if (!this._three) {
            await this._init3D();
        }
        // Appliquer le design 2D et la couleur courante sur le modèle
        this._syncDesignTo3D();
        if (this.activeColorway) {
            this._apply3DColor(this.activeColorway.material_hex);
        }
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

        this._three = { THREE, scene, camera, renderer, controls, meshes: [] };

        // Charger le modèle
        const url = (this.config.model_3d || {}).url;
        const loader = new THREE.GLTFLoader();
        const self = this;
        loader.load(url, (gltf) => {
            const root = gltf.scene;
            // Centrer / normaliser
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

            // Mesh cible pour le design
            const meshName = (self.config.model_3d || {}).mesh;
            self._three.targetMesh = meshName
                ? self._three.meshes.find((m) => m.name === meshName)
                : self._three.meshes[0];

            // Appliquer couleur + design initiaux
            if (self.activeColorway) {
                self._apply3DColor(self.activeColorway.material_hex);
            }
            self._syncDesignTo3D();
        });

        // Boucle de rendu
        const animate = () => {
            if (!self._three) return;
            self._three.raf = requestAnimationFrame(animate);
            controls.update();
            renderer.render(scene, camera);
        };
        animate();
    },

    _apply3DColor(hex) {
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

    /** Projette le design 2D (canvas Fabric) comme texture sur le mesh cible. */
    _syncDesignTo3D() {
        if (!this._three || !this._three.targetMesh) return;
        const THREE = this._three.THREE;
        // Cacher temporairement le cadre pour la texture
        const hadFrame = this._frame && this.canvas.contains(this._frame);
        if (hadFrame) this.canvas.remove(this._frame);
        this.canvas.renderAll();

        const tex = new THREE.CanvasTexture(this.canvas.lowerCanvasEl);
        tex.flipY = false;
        tex.needsUpdate = true;
        const mat = this._three.targetMesh.material;
        mat.map = tex;
        mat.needsUpdate = true;
        this._three.designTexture = tex;

        if (hadFrame && this._currentArea) this._drawAreaFrame(this._currentArea);
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
            // Masquer le cadre pour les rendus exportés
            this.canvas.remove(this._frame);
            this.canvas.discardActiveObject();
            this.canvas.renderAll();

            const preview = this.canvas.toDataURL({ format: "png", quality: 0.7 });
            const printImg = this.canvas.toDataURL({
                format: "png",
                multiplier: 3, // rendu HD pour la production
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

            const res = await rpc("/shop/customizer/add", {
                product_id: this.productId,
                customization_id: saved.customization_id,
                add_qty: 1,
            });

            // Redirection vers le panier
            window.location.href = "/shop/cart";
        } catch (e) {
            console.error("[Customizer]", e);
            alert("Une erreur est survenue. Merci de réessayer.");
            btn.disabled = false;
            btn.innerHTML =
                '<i class="fa fa-shopping-cart me-2"/>Ajouter au panier (personnalisé)';
            // ré-afficher le cadre
            const area = this.config.areas.find((a) => a.id === this.activeAreaId);
            if (area) this._drawAreaFrame(area);
        }
    },
});

export default publicWidget.registry.ArtProductCustomizer;
