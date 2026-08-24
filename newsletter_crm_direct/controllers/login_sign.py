from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)


class PortalSignup(http.Controller):

    @http.route('/my/signup', type='http', auth='public', website=True, csrf=True)
    def portal_signup(self, **post):
        """
        SECURITE:
        Cet endpoint ne DOIT JAMAIS écrire un mot de passe reçu en clair
        depuis une requête non authentifiée (auth='public'), car cela
        permet une prise de contrôle de n'importe quel compte, y compris
        admin, sans aucune vérification d'identité.

        Correctif : on ne fait plus qu'envoyer un email de réinitialisation
        sécurisé (token à usage unique, généré et vérifié par Odoo lui-même
        via auth_signup / res.users.reset_password), exactement comme le
        flux standard "mot de passe oublié". Aucun mot de passe n'est
        jamais accepté ni écrit directement depuis cette route publique.
        """
        email = post.get('login')

        if not email:
            return request.render('web.login', {
                'error': 'Email requis'
            })

        # Recherche du compte (lecture seule, aucune écriture ici)
        # CORRECTIF : comparaison insensible à la casse (=ilike), voir
        # explication détaillée dans reset_password.py.
        user = request.env['res.users'].sudo().search([
            '|',
            ('login', '=ilike', email),
            ('email', '=ilike', email),
        ], limit=1)

        # Message volontairement générique : ne jamais révéler si le
        # compte existe ou non (anti-énumération de comptes).
        generic_message = (
            "Si un compte existe pour cet email, un lien de "
            "réinitialisation vient de lui être envoyé."
        )

        if user:
            try:
                # Envoie un email avec un token sécurisé (aléatoire,
                # à usage unique, expirant) — ne modifie PAS le mot de
                # passe directement.
                user.sudo().reset_password(user.login)
                _logger.info(
                    "Lien de réinitialisation envoyé pour login=%s",
                    user.login,
                )
            except Exception:
                _logger.exception(
                    "Échec d'envoi du lien de réinitialisation pour %s",
                    email,
                )
        else:
            _logger.info(
                "Tentative de reset sur un email inconnu: %s", email
            )

        return request.render(
            'newsletter_crm_direct.signup_success',
            {'email': email, 'message': generic_message}
        )