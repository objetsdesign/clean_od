# -*- coding: utf-8 -*-
"""Générateur de fichiers glTF binaires (.glb) en **Python pur** (+ Pillow/numpy,
déjà fournis par Odoo).

Deux modes :

- ``mode="inflate"`` (par défaut) : à partir d'UNE image, on extrait la
  silhouette du produit (suppression du fond uni) puis on la « gonfle » en un
  volume bombé recto/verso. Le résultat est un VRAI maillage 3D avec du volume,
  rotatif comme un objet solide (pas un simple panneau plat).
  Limite honnête : le dos est un miroir du devant et il n'y a pas d'intérieur ;
  pour une reconstruction fidèle (dos/côtés réels) il faut une IA image→3D.

- ``mode="plane"`` : ancien comportement (image projetée sur un panneau plat).

Aucune dépendance réseau, aucun service externe.
"""
import io
import json
import struct

try:
    import numpy as np
    from PIL import Image, ImageFilter
except Exception:  # pragma: no cover
    np = None
    Image = None


def _detect_mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    return "image/png"


# ==========================================================================
#  Géométrie : panneau plat (ancien mode)
# ==========================================================================
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


# ==========================================================================
#  Silhouette : masque avant-plan à partir d'une image à fond uni
# ==========================================================================
def _foreground_mask(im, N):
    """Renvoie un masque NxN (bool, True = produit) + un booléen de succès.
    Gère la transparence native, sinon estime la couleur de fond via les coins."""
    rgba = im.convert("RGBA")
    arr = np.asarray(rgba)
    alpha = arr[:, :, 3]

    if int(alpha.min()) < 250:
        fg = (alpha > 128).astype(np.float32)
    else:
        rgb = arr[:, :, :3].astype(np.float32)
        h, w = rgb.shape[:2]
        m = max(2, min(h, w) // 20)
        corners = np.concatenate([
            rgb[:m, :m].reshape(-1, 3), rgb[:m, -m:].reshape(-1, 3),
            rgb[-m:, :m].reshape(-1, 3), rgb[-m:, -m:].reshape(-1, 3),
        ], axis=0)
        bg = corners.mean(axis=0)
        dist = np.sqrt(((rgb - bg) ** 2).sum(axis=2))
        thr = max(28.0, float(corners.std(axis=0).mean()) * 3.0)
        fg = (dist > thr).astype(np.float32)

    mimg = Image.fromarray((fg * 255).astype(np.uint8), mode="L")
    mimg = mimg.resize((N, N), Image.BILINEAR)
    mimg = mimg.filter(ImageFilter.MaxFilter(3))
    mimg = mimg.filter(ImageFilter.MinFilter(3))
    mask = np.asarray(mimg) > 110

    ratio = float(mask.mean())
    ok = 0.02 < ratio < 0.98
    return mask, ok


def _distance_transform(mask):
    """Distance (chamfer) au bord du masque, en deux passes."""
    N = mask.shape[0]
    INF = 1e9
    d = np.where(mask, INF, 0.0).astype(np.float64)
    SQ2 = 1.4142135623730951
    rng = range(N)
    for i in rng:
        for j in rng:
            if not mask[i, j]:
                continue
            best = d[i, j]
            if i > 0:
                best = min(best, d[i - 1, j] + 1.0)
                if j > 0:
                    best = min(best, d[i - 1, j - 1] + SQ2)
                if j < N - 1:
                    best = min(best, d[i - 1, j + 1] + SQ2)
            if j > 0:
                best = min(best, d[i, j - 1] + 1.0)
            d[i, j] = best
    for i in range(N - 1, -1, -1):
        for j in range(N - 1, -1, -1):
            if not mask[i, j]:
                continue
            best = d[i, j]
            if i < N - 1:
                best = min(best, d[i + 1, j] + 1.0)
                if j < N - 1:
                    best = min(best, d[i + 1, j + 1] + SQ2)
                if j > 0:
                    best = min(best, d[i + 1, j - 1] + SQ2)
            if j < N - 1:
                best = min(best, d[i, j + 1] + 1.0)
            d[i, j] = best
    return d


# ==========================================================================
#  Géométrie : silhouette gonflée (vrai volume)
# ==========================================================================
def _geo_inflate(im, N=120, max_extent=1.6, thickness=0.45):
    """Maillage 3D bombé recto/verso issu de la silhouette. None si échec."""
    if np is None or Image is None:
        return None

    W, H = im.size
    mask, ok = _foreground_mask(im, N)
    if not ok:
        return None

    dist = _distance_transform(mask)
    dmax = float(dist.max()) or 1.0
    height = thickness * np.sqrt(np.clip(dist / dmax, 0.0, 1.0))

    agrid = max(W, H)
    pw = max_extent * (W / agrid)
    ph = max_extent * (H / agrid)

    front = -np.ones((N, N), dtype=np.int64)
    back = -np.ones((N, N), dtype=np.int64)
    pos, nor, uv = [], [], []

    def add_vertex(i, j, z, nz):
        u = j / (N - 1)
        v = i / (N - 1)
        x = (u - 0.5) * pw
        y = (0.5 - v) * ph
        pos.extend((x, y, z))
        nor.extend((0.0, 0.0, nz))
        uv.extend((u, v))
        return (len(pos) // 3) - 1

    for i in range(N):
        for j in range(N):
            if mask[i, j]:
                z = float(height[i, j])
                front[i, j] = add_vertex(i, j, z, 1.0)
                back[i, j] = add_vertex(i, j, -z, -1.0)

    idx = []

    def cell_full(i, j):
        return (mask[i, j] and mask[i, j + 1]
                and mask[i + 1, j] and mask[i + 1, j + 1])

    for i in range(N - 1):
        for j in range(N - 1):
            if not cell_full(i, j):
                continue
            fa, fb = front[i, j], front[i, j + 1]
            fc, fd = front[i + 1, j], front[i + 1, j + 1]
            idx += [fa, fc, fb, fb, fc, fd]
            ba, bb = back[i, j], back[i, j + 1]
            bc, bd = back[i + 1, j], back[i + 1, j + 1]
            idx += [ba, bb, bc, bb, bd, bc]

    def is_boundary_edge(i0, j0, i1, j1):
        if i0 == i1:
            j = min(j0, j1)
            above = (i0 > 0) and cell_full(i0 - 1, j)
            below = (i0 < N - 1) and cell_full(i0, j)
            return not (above and below)
        else:
            i = min(i0, i1)
            left = (j0 > 0) and cell_full(i, j0 - 1)
            right = (j0 < N - 1) and cell_full(i, j0)
            return not (left and right)

    for i in range(N):
        for j in range(N):
            if not mask[i, j]:
                continue
            if j < N - 1 and mask[i, j + 1] and is_boundary_edge(i, j, i, j + 1):
                a, b = front[i, j], front[i, j + 1]
                c, d = back[i, j], back[i, j + 1]
                idx += [a, b, d, a, d, c]
            if i < N - 1 and mask[i + 1, j] and is_boundary_edge(i, j, i + 1, j):
                a, b = front[i, j], front[i + 1, j]
                c, d = back[i, j], back[i + 1, j]
                idx += [a, d, b, a, c, d]

    if not idx:
        return None
    return pos, nor, uv, idx


# ==========================================================================
#  Assemblage GLB
# ==========================================================================
def _assemble_glb(pos, nor, uv, idx, image_bytes):
    pos_b = struct.pack("<%df" % len(pos), *pos)
    nor_b = struct.pack("<%df" % len(nor), *nor)
    uv_b = struct.pack("<%df" % len(uv), *uv)
    idx_b = struct.pack("<%dI" % len(idx), *idx)

    def pad4(b, fill=b"\x00"):
        while len(b) % 4 != 0:
            b += fill
        return b

    pos_b, nor_b, uv_b, idx_b = pad4(pos_b), pad4(nor_b), pad4(uv_b), pad4(idx_b)
    img_b = pad4(bytes(image_bytes))

    buffer = pos_b + nor_b + uv_b + idx_b + img_b
    o_pos = 0
    o_nor = o_pos + len(pos_b)
    o_uv = o_nor + len(nor_b)
    o_idx = o_uv + len(uv_b)
    o_img = o_idx + len(idx_b)

    n_vert = len(pos) // 3
    px, py, pz = pos[0::3], pos[1::3], pos[2::3]
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
                "roughnessFactor": 0.85,
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
    bin_chunk = buffer

    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    out = bytearray()
    out += b"glTF"
    out += struct.pack("<II", 2, total)
    out += struct.pack("<I", len(json_chunk)) + b"JSON" + json_chunk
    out += struct.pack("<I", len(bin_chunk)) + b"BIN\x00" + bin_chunk
    return bytes(out)


def build_glb(image_bytes: bytes, mode: str = "inflate") -> bytes:
    """Construit un .glb à partir de `image_bytes`.

    mode="inflate" : volume bombé issu de la silhouette (par défaut).
    mode="plane"   : panneau plat texturé (ancien comportement / repli)."""
    pos, nor, uv, idx = _get_geo(image_bytes, mode)
    return _assemble_glb(pos, nor, uv, idx, image_bytes)


# ==========================================================================
#  Récupération de géométrie (commune à tous les formats)
# ==========================================================================
def _get_geo(image_bytes, mode="inflate"):
    geo = None
    if mode == "inflate" and np is not None and Image is not None:
        try:
            im = Image.open(io.BytesIO(bytes(image_bytes)))
            geo = _geo_inflate(im)
        except Exception:
            geo = None
    if geo is None:
        geo = _geo_plane()
    return geo


# ==========================================================================
#  Export OBJ (+ MTL + texture) et STL — MÊME géométrie, autres conteneurs
# ==========================================================================
def build_obj(image_bytes, mode="inflate", tex_name="texture.png"):
    """Renvoie un dict {nom_fichier: octets} : model.obj + model.mtl + texture.
    OBJ texturé, ouvrable dans Blender, MeshLab, etc."""
    pos, nor, uv, idx = _get_geo(image_bytes, mode)
    nv = len(pos) // 3
    lines = ["# artisanat_product_customizer", "mtllib model.mtl", "o product"]
    for k in range(nv):
        lines.append("v %.6f %.6f %.6f" % (pos[3 * k], pos[3 * k + 1], pos[3 * k + 2]))
    for k in range(nv):
        # OBJ : v texture vers le haut -> on inverse v.
        lines.append("vt %.6f %.6f" % (uv[2 * k], 1.0 - uv[2 * k + 1]))
    for k in range(nv):
        lines.append("vn %.4f %.4f %.4f" % (nor[3 * k], nor[3 * k + 1], nor[3 * k + 2]))
    lines.append("usemtl product")
    for t in range(0, len(idx), 3):
        a, b, c = idx[t] + 1, idx[t + 1] + 1, idx[t + 2] + 1
        lines.append("f %d/%d/%d %d/%d/%d %d/%d/%d" % (a, a, a, b, b, b, c, c, c))
    obj = ("\n".join(lines) + "\n").encode("utf-8")

    mtl = ("\n".join([
        "newmtl product",
        "Ka 1.000 1.000 1.000",
        "Kd 1.000 1.000 1.000",
        "Ks 0.000 0.000 0.000",
        "d 1.0", "illum 2",
        "map_Kd %s" % tex_name,
    ]) + "\n").encode("utf-8")

    # Texture : on normalise en PNG pour la fiabilité.
    tex = bytes(image_bytes)
    if Image is not None:
        try:
            buf = io.BytesIO()
            Image.open(io.BytesIO(bytes(image_bytes))).convert("RGBA").save(
                buf, format="PNG")
            tex = buf.getvalue()
        except Exception:
            pass
    return {"model.obj": obj, "model.mtl": mtl, tex_name: tex}


def build_stl(image_bytes, mode="inflate"):
    """Renvoie un STL binaire (octets). Géométrie seule (ni texture ni couleur),
    idéal pour l'impression 3D / visionneuses génériques."""
    pos, nor, uv, idx = _get_geo(image_bytes, mode)

    def vtx(k):
        return (pos[3 * k], pos[3 * k + 1], pos[3 * k + 2])

    ntri = len(idx) // 3
    out = bytearray()
    out += b"\x00" * 80                      # en-tête
    out += struct.pack("<I", ntri)
    for t in range(ntri):
        a = vtx(idx[3 * t]); b = vtx(idx[3 * t + 1]); c = vtx(idx[3 * t + 2])
        # Normale de facette.
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        ln = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
        out += struct.pack("<3f", nx / ln, ny / ln, nz / ln)
        for p in (a, b, c):
            out += struct.pack("<3f", *p)
        out += struct.pack("<H", 0)
    return bytes(out)


def build_all_formats_zip(image_bytes, base_name="produit", mode="inflate"):
    """Renvoie un .zip (octets) contenant le modèle en GLB + OBJ(+MTL+texture)
    + STL, tous issus de la même image."""
    import zipfile
    safe = (base_name or "produit").strip().replace(" ", "_")[:40] or "produit"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("%s.glb" % safe, build_glb(image_bytes, mode))
        for fname, data in build_obj(image_bytes, mode).items():
            zf.writestr(fname, data)
        zf.writestr("%s.stl" % safe, build_stl(image_bytes, mode))
    return buf.getvalue()
