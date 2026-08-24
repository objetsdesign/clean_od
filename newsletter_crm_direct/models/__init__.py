# -*- coding: utf-8 -*-
from . import event_registration
from . import crm_lead
from . import purchase_od
from . import sale_order
from . import res_users
from . import res_partner
# SECURITE : ir_http.py supprimé (H2 de l'audit) — le hook _pre_dispatch
# forçait su=True (superuser) sur toute URL contenant "/signup" ou
# "/web/reset_password" (comparaison non ancrée, donc trop large).
# Il était totalement redondant : les deux controllers concernés
# (login_sign.py, reset_password.py) gèrent déjà leurs propres élévations
# de privilège de façon explicite et ciblée (sudo() ou update_env(su=True)
# dans leur propre méthode). Rien d'autre dans ce module n'en dépendait.
