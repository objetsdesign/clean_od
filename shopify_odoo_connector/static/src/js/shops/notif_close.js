/** @odoo-module **/
// Rapports Shopify (diagnostic, comptes rendus) : touche Échap pour les
// fermer, en plus de la croix en haut à droite.
document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") {
        return;
    }
    const buttons = document.querySelectorAll(
        ".o_shopify_notif .o_notification_close, .o_shopify_notif .btn-close"
    );
    buttons.forEach((btn) => btn.click());
});
