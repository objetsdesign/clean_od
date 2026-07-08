/* Clerieu theme - extracted JS from website_header.xml */

(function() {
    function syncLogos() {
        var header = document.querySelector('header');
        var def = document.querySelector('.header-text-default');
        var scr = document.querySelector('.header-text-scroll');
        if (!def || !scr) return;
        var affixed = header && header.classList.contains('o_header_affixed');
        def.style.setProperty('opacity', affixed ? '0' : '1', 'important');
        def.style.setProperty('visibility', affixed ? 'hidden' : 'visible', 'important');
        def.style.setProperty('pointer-events', affixed ? 'none' : 'auto', 'important');
        scr.style.setProperty('opacity', affixed ? '1' : '0', 'important');
        scr.style.setProperty('visibility', affixed ? 'visible' : 'hidden', 'important');
        scr.style.setProperty('pointer-events', affixed ? 'auto' : 'none', 'important');
    }

    function init() {
        syncLogos();
        var header = document.querySelector('header');
        if (header && window.MutationObserver) {
            new MutationObserver(syncLogos).observe(header, { attributes: true, attributeFilter: ['class'] });
        }
        window.addEventListener('scroll', syncLogos, { passive: true });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

/* ---- next block ---- */

(function() {
    function initBadges() {

        /* ── PANIER ── */
        var cartLink = document.querySelector('li.nav-item a[href="/shop/cart"]');
        if (cartLink) {
            var cartLi = cartLink.closest('li');
            cartLi.style.position = 'relative';
            var cartBadge = document.createElement('span');
            cartBadge.id = 'gaia_cart_badge';
            cartBadge.style.cssText = 'position:absolute;top:0px;right:-4px;background:#e63946;color:#fff;border-radius:50%;min-width:16px;height:16px;font-size:9px;font-weight:700;display:none;align-items:center;justify-content:center;font-family:Poppins,sans-serif;line-height:1;padding:0 3px;z-index:99;pointer-events:none;';
            cartLi.appendChild(cartBadge);

            function updateCart(qty) {
                qty = parseInt(qty) || 0;
                cartBadge.textContent = qty;
                cartBadge.style.display = qty > 0 ? 'flex' : 'none';
            }

            var domQty = document.querySelector('.my_cart_quantity');
            if (domQty) {
                updateCart(domQty.textContent.trim());
            } else {
                var xhr = new XMLHttpRequest();
                xhr.open('POST', '/web/dataset/call_kw', true);
                xhr.setRequestHeader('Content-Type', 'application/json');
                xhr.onload = function() {
                    try {
                        var data = JSON.parse(xhr.responseText);
                        if (typeof data.result === 'number') updateCart(data.result);
                    } catch(e) {}
                };
                xhr.send(JSON.stringify({
                    jsonrpc: '2.0',
                    method: 'call',
                    id: 1,
                    params: {
                        model: 'sale.order',
                        method: 'search_count',
                        args: [[['state', '=', 'draft'], ['website_id', '!=', false]]],
                        kwargs: { context: {} }
                    }
                }));
            }

            var origOpen = XMLHttpRequest.prototype.open;
            XMLHttpRequest.prototype.open = function(method, url) {
                this.addEventListener('load', function() {
                    try {
                        var json = JSON.parse(this.responseText);
                        var qty = json && json.result && json.result.cart_quantity;
                        if (qty !== undefined) updateCart(qty);
                    } catch(e) {}
                });
                origOpen.apply(this, arguments);
            };
        }

        /* ── WISHLIST ── */
        var wishlistLi = document.getElementById('gaia_wishlist_item');
        if (wishlistLi) {
            var wBadge = document.createElement('span');
            wBadge.id = 'gaia_wishlist_badge';
            wBadge.style.cssText = 'position:absolute;top:-6px;right:-8px;background:#e8372d;color:#fff;border-radius:8px;min-width:16px;height:16px;font-size:10px;font-weight:500;display:none;align-items:center;justify-content:center;font-family:Poppins,sans-serif;line-height:1;padding:0 3px;z-index:99;pointer-events:none;';
            wishlistLi.appendChild(wBadge);

            function updateWishlist(qty) {
                qty = parseInt(qty) || 0;
                wBadge.textContent = qty > 99 ? '99+' : qty;
                wBadge.style.display = qty > 0 ? 'flex' : 'none';
            }

            function fetchWishlist() {
                var xhr = new XMLHttpRequest();
                xhr.open('POST', '/web/dataset/call_kw', true);
                xhr.setRequestHeader('Content-Type', 'application/json');
                xhr.onload = function() {
                    try {
                        var data = JSON.parse(xhr.responseText);
                        if (typeof data.result === 'number') updateWishlist(data.result);
                    } catch(e) {}
                };
                xhr.send(JSON.stringify({
                    jsonrpc: '2.0',
                    method: 'call',
                    id: 2,
                    params: {
                        model: 'product.wishlist',
                        method: 'search_count',
                        args: [[]],
                        kwargs: { context: {} }
                    }
                }));
            }

            fetchWishlist();

            document.addEventListener('click', function(e) {
                var btn = e.target.closest('[data-action="add_to_wishlist"], .o_add_wishlist, .o_wishlist_btn');
                if (btn) setTimeout(fetchWishlist, 800);
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initBadges);
    } else {
        initBadges();
    }
})();

/* ---- next block ---- */

(function() {
    var PERSON_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>';

    function ensureAccountIcon() {
        var toggle = document.querySelector('#o_main_nav .o_header_search_right_col .dropdown > .btn, #o_main_nav .o_header_search_right_col .dropdown > a.dropdown-toggle');
        if (!toggle) return;

        // Une icône existe déjà (svg/i/img fourni par le template par défaut,
        // ou avatar utilisateur connecté) : on ne touche à rien.
        if (toggle.children.length > 0 || toggle.querySelector('svg, img, i')) return;

        // Rien d'affiché (cas observé : juste la petite flèche du dropdown) : on injecte notre icône par défaut.
        toggle.insertAdjacentHTML('afterbegin', PERSON_SVG);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', ensureAccountIcon);
    } else {
        ensureAccountIcon();
    }
})();


