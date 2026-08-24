# -*- coding: utf-8 -*-
from odoo import models, _
from odoo.exceptions import UserError
import contextlib
import logging

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _action_reset_password(self, signup_type="reset"):
        """Bypass crm.lead pour portail ET internes"""
        if self.env.context.get('install_mode') or self.env.context.get('import_file'):
            return
        if self.filtered(lambda u: not u.active):
            raise UserError(_("You cannot perform this action on an archived user."))

        create_mode = bool(self.env.context.get('create_user'))

        # sudo() sur signup_prepare — bypass crm.lead
        self.mapped('partner_id').sudo().signup_prepare(signup_type=signup_type)

        account_created_template = None
        if create_mode:
            account_created_template = self.env.ref(
                'newsletter_crm_direct.set_password_email_newsletter',
                raise_if_not_found=False
            )

        email_values = {
            'email_cc': False,
            'auto_delete': True,
            'message_type': 'user_notification',
            'recipient_ids': [],
            'partner_ids': [],
            'scheduled_date': False,
        }

        for user in self:
            if not user.email:
                raise UserError(_(
                    "Cannot send email: user %s has no email address.", user.name
                ))
            email_values['email_to'] = user.email
            with contextlib.closing(self.env.cr.savepoint()):
                if account_created_template:
                    account_created_template.send_mail(
                        user.id, force_send=True,
                        raise_exception=True, email_values=email_values
                    )
                else:
                    user_lang = user.lang or self.env.lang or 'en_US'
                    body = self.env['mail.render.mixin'].with_context(
                        lang=user_lang
                    )._render_template(
                        self.env.ref('auth_signup.reset_password_email'),
                        model='res.users', res_ids=user.ids,
                        engine='qweb_view', options={'post_process': True}
                    )[user.id]
                    mail = self.env['mail.mail'].sudo().create({
                        'subject': self.with_context(lang=user_lang).env._('Password reset'),
                        'email_from': user.company_id.email_formatted or user.email_formatted,
                        'body_html': body,
                        **email_values,
                    })
                    mail.send()

            if signup_type == 'reset':
                _logger.info("Password reset email sent for <%s> to <%s>", user.login, user.email)
                message = _('A reset password link was sent by email')
            else:
                _logger.info("Signup email sent for <%s> to <%s>", user.login, user.email)
                message = _('A signup link was sent by email')

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': 'Notification', 'message': message, 'sticky': False}
        }
