# -*- coding: utf-8 -*-
from odoo import http, _
from odoo.http import request
from odoo.exceptions import UserError
import logging
from odoo.addons.auth_signup.controllers.main import AuthSignupHome

_logger = logging.getLogger(__name__)


class PortalResetPassword(http.Controller):

    @http.route('/signup/success', type='http', auth='public', website=True, sitemap=False)
    def signup_success(self, **kw):
        return request.render('newsletter_crm_direct.signup_success')

    @http.route(
        '/web/reset_password',
        type='http', auth='public', website=True, sitemap=False
    )
    def portal_reset_password(self, **kw):
        """
        SECURITE (corrigé - H6) :

        1) su=True global supprimé. La requête ne s'exécute plus en
           superuser de bout en bout ; chaque opération qui nécessite
           une élévation de privilège (recherche sur res.users, envoi
           du lien de reset) utilise désormais un sudo() ciblé, comme
           dans login_sign.py.

        2) Anti-énumération : que l'identifiant fourni corresponde à
           un compte existant ou non, la réponse renvoyée à
           l'utilisateur est strictement identique (même message
           générique). Le cas "compte inconnu" n'est plus signalé par
           un message d'erreur distinct.
        """
        auth_signup = AuthSignupHome()
        try:
            qcontext = auth_signup.get_auth_signup_qcontext()
        except Exception as e:
            _logger.warning("qcontext fallback: %s", e)
            qcontext = dict(request.params)

        token = qcontext.get('token')
        login = qcontext.get('login')

        # Message volontairement identique que le compte existe ou non,
        # pour ne jamais permettre l'énumération d'emails/logins.
        generic_message = _(
            "Si un compte existe pour cet identifiant, des instructions "
            "de réinitialisation viennent de lui être envoyées par email."
        )

        if request.httprequest.method == 'POST':
            try:
                if token:
                    # Le token à usage unique est vérifié en interne par
                    # signup(). sudo() ciblé uniquement pour l'écriture du
                    # nouveau mot de passe (nécessaire pour un utilisateur
                    # non authentifié).
                    #
                    # CORRECTIF : si signup() échoue ici (token invalide,
                    # déjà consommé, ou expiré), on ne renvoie plus le
                    # message générique "erreur interne" qui masquait la
                    # vraie cause et laissait croire à l'utilisateur que
                    # son mot de passe avait été changé. Comme l'appelant
                    # possède déjà le token (reçu par email), donner un
                    # message explicite ici ne crée pas de risque
                    # d'énumération de comptes.
                    try:
                        request.env['res.users'].sudo().signup(
                            {
                                'login': qcontext.get('login'),
                                'password': qcontext.get('password'),
                            },
                            token,
                        )
                    except Exception:
                        _logger.exception(
                            "Echec signup() avec token pour login=%s",
                            qcontext.get('login'),
                        )
                        qcontext['error'] = _(
                            "Ce lien de réinitialisation est invalide, a "
                            "expiré ou a déjà été utilisé. Merci de "
                            "redemander un nouveau lien depuis la page de "
                            "connexion."
                        )
                        return request.render(
                            'auth_signup.reset_password', qcontext
                        )

                    return request.redirect('/signup/success')

                else:
                    if not login:
                        raise UserError(_("Identifiant requis."))

                    # sudo() ciblé uniquement pour la recherche : un
                    # utilisateur public n'a pas accès en lecture à
                    # res.users.
                    #
                    # CORRECTIF : comparaison insensible à la casse
                    # (=ilike) car le login est le plus souvent une
                    # adresse email, et un email diffère parfois par la
                    # casse entre ce que l'utilisateur tape et ce qui est
                    # stocké en base (ex: Achourranda428@gmail.com vs
                    # achourranda428@gmail.com). Avec '=' strict, la
                    # recherche ne trouvait pas le compte et aucun email
                    # de reset n'était jamais envoyé, sans que
                    # l'utilisateur ne le sache (message générique).
                    user = request.env['res.users'].sudo().search([
                        '|',
                        ('login', '=ilike', login),
                        ('email', '=ilike', login),
                    ], limit=1)

                    if user:
                        try:
                            user.sudo().reset_password(login)
                        except Exception:
                            _logger.exception(
                                "Echec d'envoi du lien de reset pour %s",
                                login,
                            )
                    else:
                        _logger.info(
                            "Tentative de reset sur un identifiant inconnu: %s",
                            login,
                        )

                    # Même message, que le compte existe ou non.
                    qcontext['message'] = generic_message
                    return request.render('auth_signup.reset_password', qcontext)

            except UserError as e:
                qcontext['error'] = str(e)
            except Exception:
                _logger.exception("Erreur reset password")
                # Message générique : on n'expose jamais le détail de
                # l'exception interne à l'utilisateur final.
                qcontext['error'] = _(
                    "Une erreur est survenue. Merci de réessayer plus tard."
                )

        return request.render('auth_signup.reset_password', qcontext)
