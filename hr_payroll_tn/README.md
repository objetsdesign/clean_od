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

## Organisation « calcul IRPP / fiche de paie / CSS » (séparés)

Ces trois aspects sont volontairement isolés les uns des autres :

* **Calcul IRPP seul** : `models/hr_irpp_bareme.py`, méthode
  `hr.irpp.bareme.calculer_irpp_mensuel()`. Ne dépend d'aucun bulletin
  de paie ni contrat : elle prend uniquement des montants/taux en
  paramètres et renvoie un détail du calcul (CNSS annuelle, abattement,
  revenu imposable, IRPP, CSS, retenues mensuelles séparées et
  cumulées...). Elle peut donc être appelée/testée isolément
  (simulateur, script, tests unitaires).
  `hr_payslip.py::_tn_irpp_mensuel()` (ligne IRPP) et
  `_tn_css_mensuelle()` (ligne CSS) ne sont que de petits adaptateurs
  qui rassemblent les taux de la société / déductions de l'employé,
  appellent ce calcul commun, et renvoient chacun leur part.
* **IRPP et CSS = deux lignes distinctes du bulletin** : la structure
  de paie applique désormais deux règles de salaire séparées, `IRPP`
  et `CSS` (au lieu d'une seule règle combinée `IRPPCSS`), chacune
  avec sa propre catégorie de règle. Elles apparaissent donc comme
  deux lignes différentes sur le bulletin de paie.
* **Fiche de paie seule** : `report/bulletin_paie_template.xml`
  (gabarit QWeb) + `report/bulletin_paie_report.xml` (action de
  rapport). Ce gabarit ne fait plus référence à Bootstrap pour le
  style : il n'utilise que des classes dédiées (`bp-*`).
* **CSS seul** : `static/src/css/bulletin_paie.css`. Toute la mise en
  forme visuelle du bulletin (couleurs, tableau, encadré Net à payer,
  badges Catégorie/Échelon...) est dans ce fichier unique, chargé via
  `'assets': {'web.report_assets_common': [...]}` dans
  `__manifest__.py`.

## Catégorie professionnelle et échelon (classification tunisienne)

Deux champs ont été ajoutés sur le **contrat** (`hr.contract`,
`models/hr_contract.py`) :

* `categorie_pro` : catégorie professionnelle (1 à 18 par défaut,
  à adapter selon la grille de la convention collective sectorielle
  ou du statut particulier applicable) ;
* `echelon` : échelon d'ancienneté dans la catégorie (1 à 6 par
  défaut).

Ils sont visibles :
* dans l'onglet **Paie Tunisie** du contrat ;
* directement sur la **fiche de paie**, dans le panneau d'en-tête
  (à côté de « Structure »), via des champs `related` sur
  `hr.payslip` ;
* en badges sur le **bulletin de paie PDF**.

⚠️ Ces champs ne sont visibles sur une fiche de paie que si :
1. le module a bien été mis à jour (`--update=hr_payroll_tn` ou
   *Mettre à jour la liste des applications* + bouton *Mettre à
   niveau* sur le module dans Apps) ;
2. la catégorie/l'échelon sont renseignés sur le **contrat** de
   l'employé (`Employés > Contrats`, onglet *Paie Tunisie*) — sinon
   les champs s'affichent vides.

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
