# -*- coding: utf-8 -*-
from odoo import fields, models

GUIDE_HTML = """
<div class="o_b2fa_guide">
  <h2>📘 Principe général</h2>
  <ul>
    <li><b>Deux onglets liés :</b> Devis → Commandes via le numéro de référence commun.</li>
    <li><b>N° Devis :</b> format DEV-[ACTIVITÉ]-AAAA-NNN (ex : DEV-B2B-2026-001), généré automatiquement.</li>
    <li><b>N° Commande :</b> format CMD-[ACTIVITÉ]-AAAA-NNN (ex : CMD-B2B-2026-001), généré automatiquement.</li>
    <li><b>Lien devis ↔ commande :</b> se fait directement via le champ « N° Devis lié » sur la commande,
        ou en cliquant sur « Transférer en commande » depuis le devis.</li>
  </ul>

  <h2>📝 Onglet Devis</h2>
  <ul>
    <li><b>À la création :</b> N° Devis (auto), Date, Client, Contact, Description, Quantité, Montant.</li>
    <li><b>À mettre à jour :</b> Statut, Relances (1/2/3), Réponse client, Probabilité de conversion.</li>
    <li><b>Transfert en commande :</b> dès acceptation, cliquez sur le bouton « Transférer en commande » —
        une commande est créée automatiquement et pré-remplie.</li>
  </ul>

  <h2>📦 Onglet Commandes</h2>
  <ul>
    <li><b>À la création :</b> N° Commande (auto), Devis lié, Montant, Acompte, Source de production.</li>
    <li><b>À mettre à jour :</b> Statut, dates de production / expédition / livraison, N° tracking.</li>
    <li><b>Solde automatique :</b> le champ « Solde à recevoir » se calcule automatiquement
        (Montant HT − Acompte reçu).</li>
  </ul>

  <h2>📊 Tableau de bord</h2>
  <ul>
    <li><b>Mise à jour :</b> automatique et en temps réel à chaque ouverture.</li>
    <li><b>KPIs clés :</b> taux de conversion, chiffre d'affaires total, solde à encaisser,
        répartition des commandes par statut, pour chaque activité et en vue consolidée.</li>
  </ul>

  <h2>✅ Bonnes pratiques</h2>
  <ul>
    <li><b>Fréquence :</b> mise à jour quotidienne recommandée.</li>
    <li><b>Archivage :</b> utilisez les filtres et l'archivage Odoo pour les dossiers clôturés en fin d'année
        (les enregistrements archivés restent consultables mais n'apparaissent plus par défaut).</li>
    <li><b>Partage :</b> utilisez les droits d'accès (Utilisateur / Responsable) pour donner un accès
        adapté à chaque collaborateur.</li>
  </ul>
</div>
"""


class B2faGuideWizard(models.TransientModel):
    _name = 'b2fa.guide.wizard'
    _description = "Guide d'utilisation"

    content = fields.Html(string="Guide", default=GUIDE_HTML, readonly=True, sanitize=False)
