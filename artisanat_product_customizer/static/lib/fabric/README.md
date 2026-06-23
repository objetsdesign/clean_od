# Fabric.js (auto-hébergement optionnel)

Par défaut, le module charge Fabric.js depuis un CDN automatiquement.

Pour l'héberger vous-même (recommandé en production, sans dépendance externe) :

1. Téléchargez Fabric.js v5.3.1 :
   https://cdnjs.cloudflare.com/ajax/libs/fabric.js/5.3.1/fabric.min.js
2. Déposez le fichier ici sous le nom : fabric.min.js
3. Dans __manifest__.py, décommentez la ligne fabric.min.js du bundle
   web.assets_frontend.
4. Dans static/src/js/product_customizer.js, méthode _ensureFabric(),
   remplacez l'URL du CDN par :
   /artisanat_product_customizer/static/lib/fabric/fabric.min.js
