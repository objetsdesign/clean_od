# -*- coding: utf-8 -*-
"""Générateur de fichiers glTF binaires (.glb) en **Python pur**.

Aucune dépendance externe, aucun appel réseau : le serveur Odoo fabrique
lui-même le fichier 3D à partir de l'image du produit, projetée sur une forme
paramétrable (plan, carte, boîte, cylindre, coussin).

Le .glb produit embarque l'image comme texture (baseColorTexture) et reste
donc personnalisable par le configurateur (texte / logo appliqués par-dessus).
"""
import json
import math
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
def _geo_plane(curved=False, seg=16, w=1.4, h=1.4, bend=0.18):
    pos, nor, uv, idx = [], [], [], []
    for j in range(seg + 1):
        for i in range(seg + 1):
            u = i / seg
            v = j / seg
            x = (u - 0.5) * w
            y = (v - 0.5) * h
            z = 0.0
            nx, ny, nz = 0.0, 0.0, 1.0
            if curved:
                # Légère courbure cylindrique autour de l'axe Y.
                ang = (u - 0.5) * math.pi * bend
                z = math.cos(ang) * (w * 0.5) - (w * 0.5)
                x = math.sin(ang) * (w * 0.5)
                nx, nz = math.sin(ang), math.cos(ang)
            pos += [x, y, z]
            nor += [nx, ny, nz]
            uv += [u, 1.0 - v]
    for j in range(seg):
        for i in range(seg):
            a = j * (seg + 1) + i
            b = a + 1
            c = a + (seg + 1)
            d = c + 1
            idx += [a, c, b, b, c, d]
    return pos, nor, uv, idx


def _geo_box(w=1.1, h=1.1, d=1.1):
    hw, hh, hd = w / 2, h / 2, d / 2
    # 6 faces, 4 sommets chacune, UV plein (0..1) par face.
    faces = [
        # (normale, 4 sommets ccw)
        ((0, 0, 1), [(-hw, -hh, hd), (hw, -hh, hd), (hw, hh, hd), (-hw, hh, hd)]),
        ((0, 0, -1), [(hw, -hh, -hd), (-hw, -hh, -hd), (-hw, hh, -hd), (hw, hh, -hd)]),
        ((1, 0, 0), [(hw, -hh, hd), (hw, -hh, -hd), (hw, hh, -hd), (hw, hh, hd)]),
        ((-1, 0, 0), [(-hw, -hh, -hd), (-hw, -hh, hd), (-hw, hh, hd), (-hw, hh, -hd)]),
        ((0, 1, 0), [(-hw, hh, hd), (hw, hh, hd), (hw, hh, -hd), (-hw, hh, -hd)]),
        ((0, -1, 0), [(-hw, -hh, -hd), (hw, -hh, -hd), (hw, -hh, hd), (-hw, -hh, hd)]),
    ]
    pos, nor, uv, idx = [], [], [], []
    uvq = [(0, 1), (1, 1), (1, 0), (0, 0)]
    for n, verts in faces:
        base = len(pos) // 3
        for k, vert in enumerate(verts):
            pos += list(vert)
            nor += list(n)
            uv += list(uvq[k])
        idx += [base, base + 1, base + 2, base, base + 2, base + 3]
    return pos, nor, uv, idx


def _geo_cylinder(r=0.8, height=1.7, seg=48):
    pos, nor, uv, idx = [], [], [], []
    hh = height / 2
    for j in range(2):
        y = -hh if j == 0 else hh
        for i in range(seg + 1):
            t = i / seg
            ang = t * 2 * math.pi
            x = math.cos(ang) * r
            z = math.sin(ang) * r
            pos += [x, y, z]
            nor += [math.cos(ang), 0.0, math.sin(ang)]
            uv += [t, 1.0 - (j)]
    for i in range(seg):
        a = i
        b = i + 1
        c = (seg + 1) + i
        d = c + 1
        idx += [a, c, b, b, c, d]
    return pos, nor, uv, idx


def _geo_pillow(r=1.0, seg=40, flat=0.55):
    pos, nor, uv, idx = [], [], [], []
    for j in range(seg + 1):
        v = j / seg
        phi = v * math.pi
        for i in range(seg + 1):
            u = i / seg
            theta = u * 2 * math.pi
            x = math.sin(phi) * math.cos(theta) * r
            y = math.cos(phi) * r
            z = math.sin(phi) * math.sin(theta) * r * flat
            length = math.sqrt(x * x + y * y + z * z) or 1.0
            pos += [x, y, z]
            nor += [x / length, y / length, z / length]
            uv += [u, 1.0 - v]
    row = seg + 1
    for j in range(seg):
        for i in range(seg):
            a = j * row + i
            b = a + 1
            c = a + row
            d = c + 1
            idx += [a, c, b, b, c, d]
    return pos, nor, uv, idx


_SHAPES = {
    "plane": lambda: _geo_plane(curved=False, w=1.6, h=1.6),
    "card": lambda: _geo_plane(curved=True, w=1.45, h=1.9),
    "box": lambda: _geo_box(),
    "cylinder": lambda: _geo_cylinder(),
    "pillow": lambda: _geo_pillow(),
}


def build_glb(image_bytes: bytes, shape: str = "card") -> bytes:
    """Construit un .glb (bytes) : la forme choisie texturée par `image_bytes`."""
    pos, nor, uv, idx = _SHAPES.get(shape, _SHAPES["card"])()

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
