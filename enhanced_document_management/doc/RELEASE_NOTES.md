## Module <enhanced_document_management>

#### 26.02.2025
#### Version 17.0.1.0.0
#### ADD

- Initial commit for Document Management

#### 30.09.2026
#### Version 18.0.1.1.0
##### ADD
- Hiérarchie de dossiers (parent / sous-dossiers, chemin complet, vue arbre).
- Arborescence standard automatique par entreprise (dossier racine au nom de
  l'entreprise + sous-dossiers Finance, RH, Projets, ...).
- Dossiers employés rangés dans « RH / Dossiers employés », dossiers projets
  dans « Projets ».
- Règles multi-entreprise sur les dossiers et documents.

#### 19.10.2026
#### Version 18.0.1.2.0
##### ADD
- Dossier « Meridian » dans l'arborescence de chaque entreprise.
- Partage externe : à l'upload, saisie de l'email d'une personne sans compte
  Odoo -> email avec bouton « Consulter le document » (lien à jeton secret,
  date d'expiration facultative) et page publique de consultation /
  téléchargement.
##### FIX (droits d'accès)
- Portail : un utilisateur portail ne voit plus que ses propres documents et
  demandes (avant : tous les documents), et ne peut plus modifier les dossiers.
- /get/document (zip) : réservé aux utilisateurs connectés, plus d'eval(),
  droits vérifiés sur chaque document.

#### 13.11.2026
#### Version 18.0.1.3.0
##### FIX (suppression)
- Suppression directe, sans fenêtre : le bouton corbeille de la barre
  d'actions et l'entrée « Supprimer » du menu d'un document suppriment le
  document ET son fichier (ir.attachment). L'ancienne fenêtre « Choose One »
  n'est plus utilisée (l'ancien menu « Delete » supprime aussi directement).
- Droits vérifiés côté serveur : un Manager supprime tout document visible,
  un User supprime ses propres documents ; un document verrouillé doit être
  déverrouillé avant. En cas de refus, un message clair s'affiche.
- Le fichier n'est pas supprimé s'il est encore utilisé ailleurs (copie d'un
  document, corbeille, tâche projet, piste CRM).
##### FIX (dossiers)
- Les utilisateurs « Document Management / User » peuvent renommer un
  dossier (nom et description) ; les autres réglages restent réservés aux
  Managers.

#### 13.11.2026
#### Version 18.0.1.4.0
##### ADD
- Bouton « Nouveau dossier » dans la barre d'actions de l'écran Documents :
  crée le dossier dans le dossier sélectionné dans le panneau de gauche
  (sinon à la racine de l'entreprise), puis rafraîchit l'arborescence.
##### FIX (dossiers)
- Les utilisateurs « Document Management / User » peuvent créer des dossiers
  (nom, emplacement, description). Ils restent sans droit de suppression et
  ne peuvent pas créer de dossier système / employé / projet.
- Un sous-dossier hérite de la confidentialité de son parent, ainsi que de
  son rattachement employé / projet : un sous-dossier d'un dossier personnel
  ou de projet reste réservé aux mêmes personnes.
