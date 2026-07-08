/* Clerieu theme - extracted JS from website_product_page.xml */

                (function() {
                    var _images = [];
                    var _current = 0;
                    function init() {
                        var thumbs = document.querySelectorAll('#gaiaThumbsRow .gaia-thumb');
                        thumbs.forEach(function(t) { _images.push({ src: t.dataset.src }); });
                        updateCounter();
                        var prev = document.getElementById('gaiaArrowPrev');
                        var next = document.getElementById('gaiaArrowNext');
                        if (prev) prev.addEventListener('click', function(e){ e.stopPropagation(); navigate(-1); });
                        if (next) next.addEventListener('click', function(e){ e.stopPropagation(); navigate(1); });
                        if (_images.length <= 1) {
                            if (prev) prev.style.display = 'none';
                            if (next) next.style.display = 'none';
                            var counter = document.getElementById('gaiaCounter');
                            if (counter) counter.style.display = 'none';
                        }
                    }
                    function navigate(dir) {
                        var total = _images.length;
                        if (!total) return;
                        _current = (_current + dir + total) % total;
                        setImage(_current);
                        syncThumbs();
                    }
                    function setImage(index) {
                        var img = document.getElementById('gaiaMainImg');
                        if (!img || !_images[index]) return;
                        img.classList.add('gaia-fading');
                        setTimeout(function() {
                            img.src = _images[index].src;
                            img.onload = function() { img.classList.remove('gaia-fading'); };
                        }, 200);
                        _current = index;
                        updateCounter();
                    }
                    function syncThumbs() {
                        document.querySelectorAll('#gaiaThumbsRow .gaia-thumb').forEach(function(t, i){
                            t.classList.toggle('active', i === _current);
                        });
                    }
                    function updateCounter() {
                        var el = document.getElementById('gaiaCounter');
                        if (el) el.textContent = (_current + 1) + ' / ' + (_images.length || 1);
                    }
                    window.gaiaSelectThumb = function(el) {
                        var idx = parseInt(el.dataset.index, 10);
                        document.querySelectorAll('#gaiaThumbsRow .gaia-thumb').forEach(function(t){ t.classList.remove('active'); });
                        el.classList.add('active');
                        setImage(idx);
                    };
                    if (document.readyState === 'loading') {
                        document.addEventListener('DOMContentLoaded', init);
                    } else { init(); }
                })();
                

/* ---- next block ---- */

(function() {
    document.addEventListener('DOMContentLoaded', function() {
        var wishBtn = document.querySelector('.gaia-wishlist-btn');
        if (!wishBtn) return;

        var productId = parseInt(wishBtn.dataset.productProductId) || 0;

        function getCsrf() {
            var input = document.querySelector('input[name="csrf_token"]');
            if (input && input.value) return input.value;
            var m = document.cookie.match(/\bcsrf_token=([^;]+)/);
            return m ? decodeURIComponent(m[1]) : '';
        }

        function setActive(active) {
            var svg = wishBtn.querySelector('svg');
            if (active) {
                wishBtn.classList.add('o_wsale_my_wish_on');
                if (svg) { svg.style.fill = '#A48F82'; svg.style.stroke = '#A48F82'; }
            } else {
                wishBtn.classList.remove('o_wsale_my_wish_on');
                if (svg) { svg.style.fill = 'none'; svg.style.stroke = 'currentColor'; }
            }
        }

        function updateHeaderCounter(delta) {
            var badge = document.getElementById('gaia_wishlist_badge');
            if (!badge) return;
            var current = parseInt(badge.textContent) || 0;
            var next = Math.max(0, current + delta);
            badge.textContent = next > 99 ? '99+' : next;
            badge.style.display = next > 0 ? 'flex' : 'none';
        }

        function addToWishlist() {
            fetch('/shop/wishlist/add', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify({
                    jsonrpc: '2.0',
                    method: 'call',
                    id: 1,
                    params: {
                        product_id: productId,
                        csrf_token: getCsrf()
                    }
                })
            })
            .then(function(r) {
                console.log('[Wishlist] status =', r.status);
                return r.json();
            })
            .then(function(d) {
                console.log('[Wishlist] result =', d);
                if (d.result !== undefined || d.result === null) {
                    setActive(true);
                    updateHeaderCounter(1);
                }
            })
            .catch(function(e) { console.error('[Wishlist] erreur:', e); });
        }

        function removeFromWishlist() {
            fetch('/web/dataset/call_kw', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    jsonrpc: '2.0', method: 'call', id: 2,
                    params: {
                        model: 'product.wishlist',
                        method: 'search_read',
                        args: [[['product_id', '=', productId]]],
                        kwargs: { fields: ['id'], context: {} }
                    }
                })
            })
            .then(function(r) { return r.json(); })
            .then(function(d) {
                if (!d.result || !d.result.length) return;
                var ids = d.result.map(function(x) { return x.id; });
                return fetch('/web/dataset/call_kw', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        jsonrpc: '2.0', method: 'call', id: 3,
                        params: {
                            model: 'product.wishlist',
                            method: 'unlink',
                            args: [ids],
                            kwargs: { context: {} }
                        }
                    })
                });
            })
            .then(function() {
                setActive(false);
                updateHeaderCounter(-1);
            });
        }

        function checkWishlist() {
            fetch('/web/dataset/call_kw', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    jsonrpc: '2.0', method: 'call', id: 4,
                    params: {
                        model: 'product.wishlist',
                        method: 'search_count',
                        args: [[['product_id', '=', productId]]],
                        kwargs: { context: {} }
                    }
                })
            })
            .then(function(r) { return r.json(); })
            .then(function(d) {
                if (d.result > 0) setActive(true);
            });
        }

        wishBtn.addEventListener('click', function(e) {
            e.preventDefault();
            if (!productId) return;
            if (wishBtn.classList.contains('o_wsale_my_wish_on')) {
                removeFromWishlist();
            } else {
                addToWishlist();
            }
        });

        if (productId) checkWishlist();
    });
})();

/* ---- next block ---- */

        (function () {

            /* ─── Formatage prix ─── */
            function fmt(n) {
                return n.toFixed(2).replace('.', ',') + ' \u20ac';
            }

            /* ─── Récupère les infos du produit depuis la page ─── */
            function getProductData() {
                var nameEl  = document.querySelector('[itemprop="name"]');
                var imgEl   = document.getElementById('gaiaMainImg');
                var skuEl   = document.querySelector('.gaia-sku');
                var pidEl   = document.querySelector('.product_id');

                var name  = nameEl ? nameEl.textContent.trim() : 'Produit';
                var img   = imgEl  ? imgEl.src : '';
                var ref   = skuEl  ? skuEl.textContent.replace('SKU :', '').trim() : '';
                var pid   = pidEl  ? pidEl.value : '';

                /* Prix : cherche dans la zone .oe_price */
                var price = 0;
                var priceEl = document.querySelector('.js_main_product .oe_price .oe_currency_value');
                if (priceEl) {
                    price = parseFloat(priceEl.textContent.replace(/\s/g, '').replace(',', '.')) || 0;
                }
                if (!price) {
                    var priceBlock = document.querySelector('.gaia-price');
                    if (priceBlock) {
                        var m = priceBlock.textContent.match(/[\d]+[,.][\d]+/);
                        if (m) price = parseFloat(m[0].replace(',', '.'));
                    }
                }

                /* Variante sélectionnée */
                var variantLabel = '';
                document.querySelectorAll('.js_main_product .o_variant_pills .active, .js_main_product .o_variant_btn.active').forEach(function(el) {
                    var txt = el.dataset.value_name || el.textContent.trim();
                    if (txt) variantLabel += (variantLabel ? ' / ' : '') + txt;
                });
                if (!variantLabel) {
                    document.querySelectorAll('.js_main_product select').forEach(function(sel) {
                        if (sel.selectedIndex >= 0) {
                            variantLabel += (variantLabel ? ' / ' : '') + sel.options[sel.selectedIndex].text.trim();
                        }
                    });
                }

                return { name: name, img: img, ref: ref, price: price, pid: pid, variant: variantLabel };
            }

            /* ─── État local du panier ─── */
            var cartItems    = [];
            var itemIdCounter = 0;

            function addItem(product) {
                var existing = cartItems.find(function(i) {
                    return i.pid === product.pid && i.variant === product.variant;
                });
                if (existing) {
                    existing.qty += 1;
                } else {
                    cartItems.push({
                        id:      ++itemIdCounter,
                        name:    product.name,
                        img:     product.img,
                        ref:     product.ref,
                        price:   product.price,
                        pid:     product.pid,
                        variant: product.variant,
                        qty:     1,
                        lineId:  null
                    });
                }
            }

            /* ─── Rendu du panier ─── */
            function renderCart() {
                var body = document.getElementById('gaiaCartBody');
                if (!body) return;

                if (cartItems.length === 0) {
                    body.innerHTML = '<div class="gcm-empty">Votre panier est vide.</div>';
                    return;
                }

                var html = '<table class="gcm-table"><thead><tr>' +
                    '<th>Produit</th><th>Variante</th><th>Quantit\u00e9</th><th>Prix</th><th>Total</th><th></th>' +
                    '</tr></thead><tbody>';

                cartItems.forEach(function(item) {
                    var rowTotal = item.price * item.qty;
                    html += '<tr id="gcm-row-' + item.id + '">' +
                        '<td><div class="gcm-product-cell">' +
                        (item.img
                            ? '<img class="gcm-product-img" src="' + item.img + '" alt="' + item.name + '"/>'
                            : '<div class="gcm-product-img"></div>') +
                        '<div><div class="gcm-product-name">' + item.name + '</div>' +
                        (item.ref ? '<div class="gcm-product-ref">R\u00e9f. ' + item.ref + '</div>' : '') +
                        '</div></div></td>' +
                        '<td><div class="gcm-variant-cell">' + (item.variant || '—') + '</div></td>' +
                        '<td><div class="gcm-qty">' +
                        '<button class="gcm-qty-btn" data-id="' + item.id + '" data-dir="-1">\u2212</button>' +
                        '<span class="gcm-qty-val" id="gcm-qty-' + item.id + '">' + item.qty + '</span>' +
                        '<button class="gcm-qty-btn" data-id="' + item.id + '" data-dir="1">+</button>' +
                        '</div></td>' +
                        '<td><div class="gcm-price-cell">' + fmt(item.price) + '</div></td>' +
                        '<td><div class="gcm-total-cell" id="gcm-total-' + item.id + '">' + fmt(rowTotal) + '</div></td>' +
                        '<td><button class="gcm-delete-btn" data-id="' + item.id + '" title="Retirer">\uD83D\uDDD1</button></td>' +
                        '</tr>';
                });

                html += '</tbody></table>';

                var grand = cartItems.reduce(function(s, i) { return s + i.price * i.qty; }, 0);
                html += '<div class="gcm-grand-total-row">Total : <strong>' + fmt(grand) + '</strong></div>';
                html += '<textarea class="gcm-comment" id="gcmComment" placeholder="\u00c9cris un commentaire\u2026"></textarea>';

                body.innerHTML = html;

                /* Quantité */
                body.querySelectorAll('.gcm-qty-btn').forEach(function(btn) {
                    btn.addEventListener('click', function() {
                        var id  = parseInt(this.dataset.id);
                        var dir = parseInt(this.dataset.dir);
                        var item = cartItems.find(function(i) { return i.id === id; });
                        if (!item) return;
                        item.qty = Math.max(1, item.qty + dir);
                        updateOdooQty(item);
                        renderCart();
                    });
                });

                /* Suppression */
                body.querySelectorAll('.gcm-delete-btn').forEach(function(btn) {
                    btn.addEventListener('click', function() {
                        var id   = parseInt(this.dataset.id);
                        var item = cartItems.find(function(i) { return i.id === id; });
                        if (item && item.lineId) removeOdooLine(item.lineId);
                        cartItems = cartItems.filter(function(i) { return i.id !== id; });
                        renderCart();
                    });
                });
            }

            /* ─── Appels Odoo RPC ─── */
            function odooPost(params, callback) {
                fetch('/shop/cart/update_json', {
                    method:  'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body:    JSON.stringify({ jsonrpc: '2.0', method: 'call', id: 1, params: params })
                })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data && data.result) {
                        /* Met à jour le compteur panier du header */
                        var qty = data.result.cart_quantity;
                        if (qty !== undefined) {
                            var el = document.querySelector('.my_cart_quantity');
                            if (el) el.textContent = qty;
                        }
                        if (callback) callback(data.result);
                    }
                })
                .catch(function(err) { console.warn('Cart RPC error', err); });
            }

            function addToOdooCart(product, callback) {
                odooPost({ product_id: parseInt(product.pid) || 0, add_qty: 1, display: false }, callback);
            }

            function updateOdooQty(item) {
                if (!item.lineId) return;
                odooPost({ line_id: item.lineId, set_qty: item.qty, display: false }, null);
            }

            function removeOdooLine(lineId) {
                odooPost({ line_id: lineId, set_qty: 0, display: false }, null);
            }

            /* ─── Ouverture / Fermeture ─── */
            function openModal() {
                var modal = document.getElementById('gaiaCartModal');
                if (!modal) return;
                modal.style.display = 'flex';
                modal.offsetHeight; /* force reflow */
                modal.classList.add('open');
                document.body.style.overflow = 'hidden';
            }

            function closeModal() {
                var modal = document.getElementById('gaiaCartModal');
                if (!modal) return;
                modal.classList.remove('open');
                document.body.style.overflow = '';
                setTimeout(function() { modal.style.display = 'none'; }, 280);
            }

            /* ─── Événements ─── */
            document.addEventListener('DOMContentLoaded', function() {

                /* Bouton Ajouter au panier */
                var openBtn = document.getElementById('gaia_open_cart_popup');
                if (openBtn) {
                    openBtn.addEventListener('click', function() {
                        /* Vérifie combinaison valide */
                        var notAvail = document.querySelector('.css_not_available_msg');
                        if (notAvail && notAvail.style.display !== 'none') return;

                        var product = getProductData();

                        /* Si pas de prix trouvé, fallback soumission formulaire */
                        if (!product.price) {
                            var form = openBtn.closest('form');
                            if (form) { form.submit(); }
                            return;
                        }

                        /* Ajout au panier Odoo puis ouverture popup */
                        addToOdooCart(product, function(result) {
                            /* Stocke le lineId retourné par Odoo si disponible */
                            var existing = cartItems.find(function(i) {
                                return i.pid === product.pid && i.variant === product.variant;
                            });
                            if (existing && result.last_order_line) {
                                existing.lineId = result.last_order_line[0];
                            }
                        });

                        addItem(product);
                        renderCart();
                        openModal();
                    });
                }

                /* Fermer : bouton ✕ */
                var closeBtn = document.getElementById('gaiaCartClose');
                if (closeBtn) closeBtn.addEventListener('click', closeModal);

                /* Fermer : clic overlay */
                var modal = document.getElementById('gaiaCartModal');
                if (modal) {
                    modal.addEventListener('click', function(e) {
                        if (e.target === modal) closeModal();
                    });
                }

                /* Fermer : Échap */
                document.addEventListener('keydown', function(e) {
                    if (e.key === 'Escape') closeModal();
                });

                /* Continuer vos achats */
                var contBtn = document.getElementById('gaiaCartContinue');
                if (contBtn) contBtn.addEventListener('click', closeModal);
            });

        })();
        
