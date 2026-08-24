from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        for order in orders:
            # Vérifier que la RFQ a bien un acheteur avec email
            if order.user_id and order.user_id.email:
                try:
                    template = self.env.ref(
                        'newsletter_crm_direct.email_template_rfq_notify_acheteur',
                        raise_if_not_found=False
                    )
                    if template:
                        template.send_mail(
                            order.id,
                            force_send=True,
                            email_values={
                                'email_from': self.env.user.email_formatted or self.env.user.email,
                                'email_to': order.user_id.email,  # ✅ Acheteur interne
                            }
                        )
                        _logger.info(
                            "Notification RFQ envoyée à l'acheteur %s pour la commande %s",
                            order.user_id.email,
                            order.name
                        )
                except Exception as e:
                    _logger.error(
                        "Erreur envoi notification RFQ %s : %s",
                        order.name, e
                    )
        return orders

    def write(self, vals):
        # Notifier si l'acheteur change sur une RFQ existante
        old_buyers = {order.id: order.user_id for order in self}
        result = super().write(vals)

        if 'user_id' in vals:
            for order in self:
                new_buyer = order.user_id
                old_buyer = old_buyers.get(order.id)

                # Notifier seulement si l'acheteur a changé
                if new_buyer and new_buyer != old_buyer and new_buyer.email:
                    try:
                        template = self.env.ref(
                            'newsletter_crm_direct.email_template_rfq_notify_acheteur',
                            raise_if_not_found=False
                        )
                        if template:
                            template.send_mail(
                                order.id,
                                force_send=True,
                                email_values={
                                    'email_from': self.env.user.email_formatted or self.env.user.email,
                                    'email_to': new_buyer.email,  # ✅ Nouvel acheteur
                                }
                            )
                            _logger.info(
                                "Notification changement acheteur envoyée à %s pour RFQ %s",
                                new_buyer.email,
                                order.name
                            )
                    except Exception as e:
                        _logger.error(
                            "Erreur notification changement acheteur RFQ %s : %s",
                            order.name, e
                        )
        return result