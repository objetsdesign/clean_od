# -*- coding: utf-8 -*-
"""Générateur de fichiers glTF binaires (.glb) en **Python pur**.

Aucune dépendance externe, aucun appel réseau : le serveur Odoo fabrique
lui-même le fichier 3D à partir de l'image du produit, projetée sur un
panneau plat (l'image telle quelle, visible en 3D, rotative).

Le .glb produit embarque l'image comme texture (baseColorTexture) et reste
donc personnalisable par le configurateur (texte / logo appliqués par-dessus).
"""
import json
import struct


def _detect_mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    # Par défaut on suppose du PNG (Odoo stocke souvent en PNG).
    return "image/png"


# --------------------------------------------------------------------------
#  Génération de géométrie : renvoie (positions, normals, uvs, indices)
#  positions/normals : liste de float (x,y,z...) ; uvs : float (u,v...) ;
#  indices : liste d'entiers (triangles).
# --------------------------------------------------------------------------
def _geo_plane(seg=16, w=1.6, h=1.6):
    pos, nor, uv, idx = [], [], [], []
    for j in range(seg + 1):
        for i in range(seg + 1):
            u = i / seg
            v = j / seg
            x = (u - 0.5) * w
            y = (v - 0.5) * h
            pos += [x, y, 0.0]
            nor += [0.0, 0.0, 1.0]
            uv += [u, 1.0 - v]
    for j in range(seg):
        for i in range(seg):
            a = j * (seg + 1) + i
            b = a + 1
            c = a + (seg + 1)
            d = c + 1
            idx += [a, c, b, b, c, d]
    return pos, nor, uv, idx


_SHAPES = {
    "plane": lambda: _geo_plane(),
}


def build_glb(image_bytes: bytes) -> bytes:
    """Construit un .glb (bytes) : un panneau plat texturé par `image_bytes`
    (l'image fournie devient directement le visuel affiché en 3D)."""
    pos, nor, uv, idx = _SHAPES["plane"]()

    pos_b = struct.pack("<%df" % len(pos), *pos)
    nor_b = struct.pack("<%df" % len(nor), *nor)
    uv_b = struct.pack("<%df" % len(uv), *uv)
    idx_b = struct.pack("<%dI" % len(idx), *idx)

    def pad4(b, fill=b"\x00"):
        while len(b) % 4 != 0:
            b += fill
        return b

    pos_b, nor_b, uv_b, idx_b = (pad4(pos_b), pad4(nor_b), pad4(uv_b), pad4(idx_b))
    img_b = pad4(bytes(image_bytes))

    buffer = pos_b + nor_b + uv_b + idx_b + img_b
    o_pos = 0
    o_nor = o_pos + len(pos_b)
    o_uv = o_nor + len(nor_b)
    o_idx = o_uv + len(uv_b)
    o_img = o_idx + len(idx_b)

    n_vert = len(pos) // 3
    px = pos[0::3]
    py = pos[1::3]
    pz = pos[2::3]
    pos_min = [min(px), min(py), min(pz)]
    pos_max = [max(px), max(py), max(pz)]

    gltf = {
        "asset": {"version": "2.0", "generator": "artisanat_product_customizer"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{
            "primitives": [{
                "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
                "indices": 3,
                "material": 0,
            }]
        }],
        "materials": [{
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": 0},
                "metallicFactor": 0.0,
                "roughnessFactor": 0.9,
            },
            "doubleSided": True,
        }],
        "textures": [{"source": 0, "sampler": 0}],
        "samplers": [{"magFilter": 9729, "minFilter": 9987,
                      "wrapS": 10497, "wrapT": 10497}],
        "images": [{"bufferView": 4, "mimeType": _detect_mime(bytes(image_bytes))}],
        "buffers": [{"byteLength": len(buffer)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": o_pos, "byteLength": len(pos_b),
             "target": 34962},
            {"buffer": 0, "byteOffset": o_nor, "byteLength": len(nor_b),
             "target": 34962},
            {"buffer": 0, "byteOffset": o_uv, "byteLength": len(uv_b),
             "target": 34962},
            {"buffer": 0, "byteOffset": o_idx, "byteLength": len(idx_b),
             "target": 34963},
            {"buffer": 0, "byteOffset": o_img, "byteLength": len(img_b)},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": n_vert,
             "type": "VEC3", "min": pos_min, "max": pos_max},
            {"bufferView": 1, "componentType": 5126, "count": n_vert,
             "type": "VEC3"},
            {"bufferView": 2, "componentType": 5126, "count": n_vert,
             "type": "VEC2"},
            {"bufferView": 3, "componentType": 5125, "count": len(idx),
             "type": "SCALAR"},
        ],
    }

    json_chunk = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    while len(json_chunk) % 4 != 0:
        json_chunk += b" "
    bin_chunk = buffer  # déjà aligné

    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    out = bytearray()
    out += b"glTF"
    out += struct.pack("<II", 2, total)
    out += struct.pack("<I", len(json_chunk)) + b"JSON" + json_chunk
    out += struct.pack("<I", len(bin_chunk)) + b"BIN\x00" + bin_chunk
    return bytes(out)
