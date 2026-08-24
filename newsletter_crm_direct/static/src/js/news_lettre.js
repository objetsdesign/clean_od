/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.subscribeCRM = publicWidget.Widget.extend({
    selector: '.js_subscribe',

    events: {
        'click .js_subscribe_btn': '_onSubscribeClick',
    },

    async _onSubscribeClick(ev) {
        ev.preventDefault();
        ev.stopPropagation();

        const $form = $(ev.currentTarget).closest('.js_subscribe');
        const $input = $form.find('.js_subscribe_value:visible');

        if (!$input.length) {
            return;
        }

        const email = $input.val();
        const source = $form.attr('data-source') || 'Website';

        console.log("📩 Subscribe CRM:", email, source);

        if (!email || !/.+@.+\..+/.test(email)) {
            $form.addClass('o_has_error');
            $input.addClass('is-invalid');
            return;
        }

        $form.removeClass('o_has_error');
        $input.removeClass('is-invalid');

        try {
            const result = await rpc('/website_mass_mailing/subscribe/crm', {
                value: email,
                source: source,
            });

            if (result.success) {
                $form.find(".js_subscribe_wrap").addClass('d-none');
                $form.find(".js_subscribed_wrap")
                    .removeClass('d-none')
                    .find('p')
                    .text(result.message);

                $input.val('');
            }
        } catch (error) {
            console.error("❌ Subscribe CRM error:", error);
        }
    },
});
