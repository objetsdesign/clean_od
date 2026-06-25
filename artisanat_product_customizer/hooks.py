# -*- coding: utf-8 -*-
import base64
import os
import logging

_logger = logging.getLogger(__name__)

# (fichier, Nom affiché, catégorie, échelle)
_TEXTURES = [
    ("linen.png", "Lin / Toile", "Tissu", 1.0),
    ("denim.png", "Denim", "Tissu", 1.0),
    ("carbon.png", "Carbone", "Technique", 1.0),
    ("wood.png", "Bois", "Naturel", 1.0),
    ("marble.png", "Marbre", "Naturel", 1.0),
    ("polka.png", "Pois", "Motif", 1.0),
    ("camo.png", "Camouflage", "Motif", 1.0),
    ("stripes.png", "Rayures", "Motif", 1.0),
]


def post_init_hook(env):
    """Charge la bibliothèque de textures par défaut depuis les fichiers
    livrés dans static/src/img/textures/ (aucun appel à un service externe)."""
    Texture = env['product.customization.texture'].sudo()
    base_dir = os.path.join(os.path.dirname(__file__), 'static', 'src', 'img', 'textures')
    seq = 10
    for fname, name, category, scale in _TEXTURES:
        if Texture.search_count([('name', '=', name)]):
            continue
        path = os.path.join(base_dir, fname)
        if not os.path.exists(path):
            _logger.warning("Texture introuvable : %s", path)
            continue
        with open(path, 'rb') as fp:
            data = base64.b64encode(fp.read())
        Texture.create({
            'name': name,
            'category': category,
            'image': data,
            'tiled': True,
            'texture_scale': scale,
            'sequence': seq,
        })
        seq += 10
    _logger.info("Bibliothèque de textures initialisée.")
