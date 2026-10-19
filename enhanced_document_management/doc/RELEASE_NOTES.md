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
