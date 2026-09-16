# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HrIrppBareme(models.Model):
    """Barème progressif de l'IRPP tunisien.

    Chaque enregistrement représente une tranche annuelle du barème.
    Le barème est daté (date_from/date_to) afin de pouvoir tenir compte
    des changements introduits par les lois de finances successives.
    """
    _name = 'hr.irpp.bareme'
    _description = "Tranche du barème IRPP"
    _order = 'date_from desc, sequence asc'

    name = fields.Char(compute='_compute_name', store=True)
    sequence = fields.Integer(default=10)
    date_from = fields.Date(string="Applicable à partir du", required=True)
    date_to = fields.Date(string="Applicable jusqu'au")
    tranche_min = fields.Float(string="Revenu annuel min. (TND)", required=True)
    tranche_max = fields.Float(
        string="Revenu annuel max. (TND)",
        help="Laisser vide pour la dernière tranche (sans plafond).")
    taux = fields.Float(string="Taux (%)", required=True)
    company_id = fields.Many2one(
        'res.company', default=lambda s: s.env.company, required=True)

    @api.depends('tranche_min', 'tranche_max', 'taux')
    def _compute_name(self):
        for rec in self:
            if rec.tranche_max:
                rec.name = "De %.3f à %.3f TND : %.2f%%" % (
                    rec.tranche_min, rec.tranche_max, rec.taux)
            else:
                rec.name = "Au-delà de %.3f TND : %.2f%%" % (
                    rec.tranche_min, rec.taux)

    @api.model
    def compute_irpp(self, revenu_imposable_annuel, company=None, date=None):
        """Calcule l'IRPP annuel dû par application du barème progressif
        par tranches (méthode par différence, tranche par tranche).
        """
        company = company or self.env.company
        date = date or fields.Date.context_today(self)
        domain = [
            ('company_id', '=', company.id),
            ('date_from', '<=', date),
            '|', ('date_to', '=', False), ('date_to', '>=', date),
        ]
        tranches = self.search(domain, order='tranche_min asc')
        if not tranches:
            return 0.0

        revenu = max(revenu_imposable_annuel, 0.0)
        impot = 0.0
        for tranche in tranches:
            borne_inf = tranche.tranche_min
            borne_sup = tranche.tranche_max or float('inf')
            if revenu <= borne_inf:
                continue
            base_tranche = min(revenu, borne_sup) - borne_inf
            if base_tranche > 0:
                impot += base_tranche * (tranche.taux / 100.0)
        return round(impot, 3)

    # ------------------------------------------------------------------
    # Calcul IRPP + CSS 100% autonome (aucune dépendance à hr.payslip).
    #
    # Cette méthode ne prend que des montants/taux en paramètres : elle
    # peut donc être appelée et testée isolément (simulateur de salaire,
    # script, tests unitaires, module tiers...) sans passer par un
    # bulletin de paie. C'est le module de calcul IRPP "seul".
    # ------------------------------------------------------------------
    @api.model
    def calculer_irpp_mensuel(self, salaire_brut_imposable_mensuel,
                               base_cnss_mensuelle,
                               taux_cnss_salarie,
                               taux_abattement_frais_pro,
                               plafond_abattement_frais_pro,
                               deduction_familiale_annuelle=0.0,
                               nb_parents_charge=0,
                               taux_deduction_parent=0.0,
                               plafond_deduction_parent_annuel=0.0,
                               taux_css=0.0,
                               company=None, date=None):
        """Calcule la retenue IRPP + CSS mensuelle à partir de montants
        et taux fournis explicitement (aucun accès à un contrat ou un
        bulletin de paie n'est nécessaire).

        :param salaire_brut_imposable_mensuel: salaire brut mensuel
            soumis à l'IRPP (float, TND).
        :param base_cnss_mensuelle: base mensuelle cotisable CNSS
            (float, TND), utilisée pour déduire la CNSS annuelle.
        :param taux_cnss_salarie: taux CNSS part salariale, en % (ex: 9.18).
        :param taux_abattement_frais_pro: taux de l'abattement forfaitaire
            pour frais professionnels, en % (ex: 10.0).
        :param plafond_abattement_frais_pro: plafond annuel de cet
            abattement, en TND.
        :param deduction_familiale_annuelle: déductions annuelles à
            montant fixe (chef de famille + enfants à charge), en TND.
        :param nb_parents_charge: nombre de parents à charge (déjà
            plafonné par l'appelant selon la limite configurée).
        :param taux_deduction_parent: taux de déduction par parent à
            charge, en % du revenu après abattement frais professionnels
            (ex: 5.0).
        :param plafond_deduction_parent_annuel: plafond annuel de la
            déduction, par parent à charge, en TND.
        :param taux_css: taux de la Contribution Sociale de Solidarité,
            en % (ex: 0.5). 0 si non applicable.
        :param company: res.company sur laquelle chercher le barème
            IRPP applicable (par défaut : société courante).
        :param date: date de référence pour choisir le barème IRPP
            applicable (par défaut : aujourd'hui).
        :return: dict détaillé du calcul, avec en particulier
            'irpp_mensuel' et 'css_mensuelle' (montants positifs à
            retenir sur le salaire du mois, chacun sur sa propre ligne),
            ainsi que 'irpp_css_mensuel' (le cumul des deux).
        """
        brut_annuel = salaire_brut_imposable_mensuel * 12.0
        cnss_annuelle = base_cnss_mensuelle * 12.0 * (taux_cnss_salarie / 100.0)
        revenu_apres_cnss = max(brut_annuel - cnss_annuelle, 0.0)

        abattement = min(
            revenu_apres_cnss * (taux_abattement_frais_pro / 100.0),
            plafond_abattement_frais_pro)

        base_avant_familiales = max(revenu_apres_cnss - abattement, 0.0)

        # Déduction pour parent(s) à charge : proportionnelle au revenu
        # (après abattement frais pro), plafonnée par parent.
        deduction_parents = min(
            base_avant_familiales * (taux_deduction_parent / 100.0),
            plafond_deduction_parent_annuel) * max(nb_parents_charge, 0)

        revenu_imposable = max(
            base_avant_familiales - deduction_familiale_annuelle
            - deduction_parents, 0.0)

        irpp_annuel = self.compute_irpp(revenu_imposable, company=company, date=date)
        css_annuelle = round(revenu_imposable * (taux_css / 100.0), 3)

        irpp_mensuel = round(irpp_annuel / 12.0, 3)
        css_mensuelle = round(css_annuelle / 12.0, 3)
        irpp_css_mensuel = round(irpp_mensuel + css_mensuelle, 3)

        return {
            'brut_annuel': round(brut_annuel, 3),
            'cnss_annuelle': round(cnss_annuelle, 3),
            'revenu_apres_cnss': round(revenu_apres_cnss, 3),
            'abattement_frais_pro': round(abattement, 3),
            'deduction_familiale': round(deduction_familiale_annuelle, 3),
            'deduction_parents': round(deduction_parents, 3),
            'revenu_imposable': round(revenu_imposable, 3),
            'irpp_annuel': round(irpp_annuel, 3),
            'css_annuelle': css_annuelle,
            # Retenues mensuelles, disponibles séparément (deux lignes
            # distinctes sur le bulletin de paie) et cumulées :
            'irpp_mensuel': irpp_mensuel,
            'css_mensuelle': css_mensuelle,
            'irpp_css_mensuel': irpp_css_mensuel,
        }
