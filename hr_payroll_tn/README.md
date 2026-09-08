# Paie Tunisie — hr_payroll_tn

Module Odoo 18 (Enterprise) **original**, développé pour couvrir les mêmes
besoins fonctionnels que les modules commerciaux de paie tunisienne
(structure salariale, CNSS, IRPP, bulletin de paie, prêts, congés, pointage,
traitement par lot, télédéclaration CNSS) — code et vues propres à ce
module, sans reprise de code tiers.

## Installation

1. Copier le dossier `hr_payroll_tn` dans votre répertoire d'addons custom.
2. Redémarrer Odoo avec `--update=hr_payroll_tn` (ou activer le mode
   développeur puis "Mettre à jour la liste des applications").
3. Installer le module **Paie Tunisie** depuis Apps.

Prérequis : Odoo Enterprise (le module `hr_payroll` est Enterprise-only),
avec les modules `hr`, `hr_contract`, `hr_holidays`, `hr_attendance`,
`calendar`, `mail`.

## Configuration à faire avant toute utilisation en production

⚠️ **Important** : les taux et tranches fournis par défaut sont indicatifs.

1. **Paramètres généraux > Paie Tunisie** : vérifier/ajuster
   - le taux CNSS salarié (par défaut 9,18 %)
   - le taux CNSS patronal (par défaut 16,57 %)
   - le taux Accident du Travail (variable selon secteur, 0,4 % à 4 %)
   - les déductions IRPP (chef de famille, par enfant) et le taux CSS
2. **Paie Tunisie > Configuration > Barème IRPP** : vérifier/mettre à jour
   les tranches selon la dernière Loi de Finances en vigueur.
3. Sur chaque **contrat** : définir le mode de traitement (mensuel /
   journalier / horaire), et si le salarié est soumis à la CNSS / exonéré
   d'IRPP.
4. Sur chaque **fiche employé** : renseigner CIN, n° CNSS, situation
   familiale et enfants à charge (utilisés pour le calcul de l'IRPP).

## Fonctionnement du calcul de paie

La structure **"Salaire Tunisien"** applique, dans l'ordre :
`SALBASE` (selon mode de traitement) → `PRIMES` (saisies manuelles,
type d'entrée "PRIME") → `BRUT` → `BASECNSS` → `CNSSSAL` / `CNSSPAT` →
`IRPPCSS` (barème progressif + CSS) → `PRET` (retenue des échéances de
prêt en cours) → `NET`.

La logique de calcul (CNSS, IRPP, prêts) est centralisée dans les méthodes
`_tn_*` du modèle `hr.payslip` (`models/hr_payslip.py`), afin d'être
facilement auditable et ajustable.

## Points à vérifier / compléter selon votre version exacte d'Odoo 18

Ce module a été écrit hors environnement Odoo (sans accès à une instance
pour test direct). Avant mise en production, vérifiez notamment :

- Les XPath des vues héritées (`views/hr_contract_views.xml`,
  `views/res_config_settings_views.xml`, `views/hr_payslip_views.xml`)
  peuvent nécessiter un ajustement si la structure exacte des vues natives
  `hr_contract` / `hr_payroll` diffère légèrement selon votre build 18.0.
- Les codes des jours travaillés (`WORK100`) supposent la configuration
  standard `hr_payroll` ; adaptez-les si vous utilisez des codes de feuille
  de temps personnalisés.
- Ajoutez une icône `static/description/icon.png` (128x128) pour
  l'affichage dans Apps.

## Licence

LGPL-3 (module original, librement modifiable).
