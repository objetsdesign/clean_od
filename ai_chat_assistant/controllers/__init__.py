# Pas de contrôleur HTTP dédié: le widget frontend utilise l'ORM standard
# d'Odoo (this.orm.call / this.orm.create) qui passe déjà par /web/dataset,
# donc les CSRF, sessions et droits d'accès Odoo s'appliquent normalement.
