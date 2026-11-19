"""Lecture et modification d'un fichier PowerPoint (.pptx) : textes, mise en
forme simple et animations d'entrée.

Module autonome (zipfile + lxml, déjà fournis avec Odoo) :

* ``read_slides(data)`` : diapositives, zones de texte (titres, zones,
  cellules de tableaux), paragraphes avec leur texte et leur mise en forme,
  et animations d'entrée de chaque zone ;
* ``apply_changes(data, changes)`` : applique les modifications et renvoie le
  nouveau fichier. Tout ce qui n'est pas modifié (images, formes, mise en page,
  notes, autres animations…) est recopié à l'identique.

Format de ``changes`` ::

    {numéro de diapositive: {
        "paragraphs": {index: {"text": str, "bold": bool, "italic": bool,
                               "underline": bool, "size": float (pt),
                               "color": "RRGGBB"}},   # chaque clé est facultative
        "animations": {id de la zone: "appear" | "fade" | "fly" | ""},
    }}

L'ancien format ``{numéro: {index: texte}}`` reste accepté.

Animations : seuls les effets d'entrée « Apparition », « Fondu » et « Entrée
par le bas », déclenchés au clic, sont gérés. Si une diapositive contient
d'autres animations, elles sont conservées telles quelles et leur
modification est refusée pour cette diapositive.
"""
import copy
import io
import posixpath
import re
import zipfile

from lxml import etree

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
A = "{%s}" % NS["a"]
P = "{%s}" % NS["p"]
MAX_PART_SIZE = 25 * 1024 * 1024  # taille max. d'une partie XML décompressée
MAX_TEXT_LENGTH = 20000           # taille max. d'un paragraphe envoyé
COLOR_RE = re.compile(r"^[0-9A-Fa-f]{6}$")

# Effets d'entrée gérés : nom -> (presetID, presetSubtype)
EFFECTS = {"appear": (1, 0), "fade": (10, 0), "fly": (2, 4)}
EFFECT_BY_PRESET = {(pid, sub): name for name, (pid, sub) in EFFECTS.items()}
# Ordre des éléments dans a:rPr (schéma DrawingML) : la couleur (a:solidFill…)
# doit suivre a:ln et précéder les autres éléments.
FILL_TAGS = {A + t for t in ("noFill", "solidFill", "gradFill", "blipFill", "pattFill", "grpFill")}


class PptxTextError(ValueError):
    """Fichier illisible ou modification refusée."""


def _parser():
    # Pas d'entités externes ni d'accès réseau : le fichier vient d'un utilisateur.
    return etree.XMLParser(resolve_entities=False, no_network=True,
                           remove_blank_text=False, huge_tree=False)


def _read_part(zf, name):
    try:
        info = zf.getinfo(name)
    except KeyError:
        raise PptxTextError("Partie manquante : %s" % name)
    if info.file_size > MAX_PART_SIZE:
        raise PptxTextError("Partie trop volumineuse : %s" % name)
    return zf.read(name)


def _open_zip(data):
    try:
        return zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise PptxTextError("Ce fichier n'est pas un PowerPoint (.pptx) valide.")


def _slide_parts(zf):
    """Noms des parties XML des diapositives, dans l'ordre de la présentation."""
    pres = etree.fromstring(_read_part(zf, "ppt/presentation.xml"), _parser())
    rels = etree.fromstring(_read_part(zf, "ppt/_rels/presentation.xml.rels"), _parser())
    targets = {
        rel.get("Id"): rel.get("Target")
        for rel in rels.findall("rel:Relationship", NS)
    }
    parts = []
    for sld_id in pres.findall("p:sldIdLst/p:sldId", NS):
        target = targets.get(sld_id.get("{%s}id" % NS["r"]))
        if not target:
            continue
        if target.startswith("/"):
            name = target.lstrip("/")
        else:
            name = posixpath.normpath(posixpath.join("ppt", target))
        parts.append(name)
    return parts


# ----------------------------------------------------------------------
# Textes
# ----------------------------------------------------------------------
def _paragraph_text(p):
    chunks = []
    for child in p:
        if child.tag in (A + "r", A + "fld"):
            t = child.find("a:t", NS)
            chunks.append(t.text or "" if t is not None else "")
        elif child.tag == A + "br":
            chunks.append("\n")
    return "".join(chunks)


def _text_containers(slide):
    """Zones de texte de la diapositive, dans l'ordre du document :
    (type, nom, identifiant de la zone, liste des paragraphes a:p)."""
    containers = []
    for el in slide.iter(P + "sp", P + "graphicFrame"):
        c_nv = el.find(".//p:cNvPr", NS)
        name = c_nv.get("name", "") if c_nv is not None else ""
        spid = c_nv.get("id", "") if c_nv is not None else ""
        if el.tag == P + "sp":
            body = el.find("p:txBody", NS)
            if body is not None:
                containers.append(("text", name, spid, body.findall("a:p", NS)))
        else:
            table = el.find(".//a:tbl", NS)
            if table is not None:
                cells = []
                for row in table.findall("a:tr", NS):
                    for cell in row.findall("a:tc", NS):
                        cells.extend(cell.findall("a:txBody/a:p", NS))
                containers.append(("table", name, spid, cells))
    return containers


def _iter_paragraphs(slide):
    """Tous les paragraphes éditables, numérotés dans un ordre stable."""
    index = 0
    for kind, name, spid, paragraphs in _text_containers(slide):
        for p in paragraphs:
            yield index, kind, name, spid, p
            index += 1


def _first_rpr(p):
    """Propriétés du premier fragment (ou de fin de paragraphe)."""
    for child in p:
        if child.tag in (A + "r", A + "fld"):
            rpr = child.find("a:rPr", NS)
            if rpr is not None:
                return rpr
    return p.find("a:endParaRPr", NS)


def _format_of(p):
    """Mise en forme affichée pour le paragraphe (celle de son début).
    Une valeur absente (héritée du modèle) vaut None."""
    rpr = _first_rpr(p)
    fmt = {"bold": None, "italic": None, "underline": None, "size": None, "color": None}
    if rpr is None:
        return fmt
    if rpr.get("b") is not None:
        fmt["bold"] = rpr.get("b") in ("1", "true")
    if rpr.get("i") is not None:
        fmt["italic"] = rpr.get("i") in ("1", "true")
    if rpr.get("u") is not None:
        fmt["underline"] = rpr.get("u") not in ("none",)
    if rpr.get("sz"):
        try:
            fmt["size"] = int(rpr.get("sz")) / 100
        except ValueError:
            pass
    clr = rpr.find("a:solidFill/a:srgbClr", NS)
    if clr is not None and COLOR_RE.match(clr.get("val", "")):
        fmt["color"] = clr.get("val").upper()
    return fmt


def _set_paragraph_text(p, text):
    """Remplace le texte du paragraphe en gardant la mise en forme du premier
    fragment (et les propriétés de paragraphe : alignement, puces…)."""
    runs = [c for c in p if c.tag in (A + "r", A + "fld")]
    template_rpr = None
    for run in runs:
        rpr = run.find("a:rPr", NS)
        if rpr is not None:
            template_rpr = rpr
            break
    if template_rpr is None:
        end = p.find("a:endParaRPr", NS)
        if end is not None:
            template_rpr = etree.Element(A + "rPr", dict(end.attrib))
            for child in end:
                template_rpr.append(copy.deepcopy(child))
    for child in list(p):
        if child.tag in (A + "r", A + "fld", A + "br"):
            p.remove(child)
    end = p.find("a:endParaRPr", NS)
    insert_at = list(p).index(end) if end is not None else len(p)
    lines = text.split("\n")
    new_nodes = []
    for i, line in enumerate(lines):
        if i > 0:
            br = etree.Element(A + "br")
            if template_rpr is not None:
                br.append(copy.deepcopy(template_rpr))
            new_nodes.append(br)
        if line or len(lines) == 1:
            run = etree.Element(A + "r")
            if template_rpr is not None:
                run.append(copy.deepcopy(template_rpr))
            t = etree.SubElement(run, A + "t")
            t.text = line
            new_nodes.append(run)
    for offset, node in enumerate(new_nodes):
        p.insert(insert_at + offset, node)


def _paragraph_rprs(p):
    """Toutes les propriétés de caractères du paragraphe (créées si besoin)."""
    rprs = []
    for child in p:
        if child.tag in (A + "r", A + "fld", A + "br"):
            rpr = child.find("a:rPr", NS)
            if rpr is None:
                rpr = etree.Element(A + "rPr")
                # a:rPr est toujours le premier enfant d'un fragment.
                child.insert(0, rpr)
            rprs.append(rpr)
    end = p.find("a:endParaRPr", NS)
    if end is None:
        end = etree.SubElement(p, A + "endParaRPr")
    rprs.append(end)
    return rprs


def _set_color(rpr, color):
    for child in list(rpr):
        if child.tag in FILL_TAGS:
            rpr.remove(child)
    fill = etree.Element(A + "solidFill")
    etree.SubElement(fill, A + "srgbClr", val=color.upper())
    ln = rpr.find("a:ln", NS)
    rpr.insert(list(rpr).index(ln) + 1 if ln is not None else 0, fill)


def _apply_format(p, fmt):
    for rpr in _paragraph_rprs(p):
        if "bold" in fmt:
            rpr.set("b", "1" if fmt["bold"] else "0")
        if "italic" in fmt:
            rpr.set("i", "1" if fmt["italic"] else "0")
        if "underline" in fmt:
            rpr.set("u", "sng" if fmt["underline"] else "none")
        if "size" in fmt:
            rpr.set("sz", str(int(round(fmt["size"] * 100))))
        if "color" in fmt:
            _set_color(rpr, fmt["color"])


def _clean_text(value):
    if not isinstance(value, str):
        raise PptxTextError("Texte invalide.")
    if len(value) > MAX_TEXT_LENGTH:
        raise PptxTextError("Texte trop long.")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    # Caractères interdits en XML (sauf tabulation et saut de ligne).
    return "".join(ch for ch in value if ch in "\t\n" or ord(ch) >= 0x20)


def _clean_paragraph_change(value):
    """Valide une modification de paragraphe (ancien format : texte seul)."""
    if isinstance(value, str):
        return {"text": _clean_text(value)}
    if not isinstance(value, dict):
        raise PptxTextError("Modification invalide.")
    clean = {}
    if "text" in value:
        clean["text"] = _clean_text(value["text"])
    for key in ("bold", "italic", "underline"):
        if key in value:
            if not isinstance(value[key], bool):
                raise PptxTextError("Valeur invalide pour %s." % key)
            clean[key] = value[key]
    if "size" in value:
        try:
            size = float(value["size"])
        except (TypeError, ValueError):
            raise PptxTextError("Taille invalide.")
        if not 1 <= size <= 400:
            raise PptxTextError("La taille doit être comprise entre 1 et 400 points.")
        clean["size"] = size
    if "color" in value:
        color = str(value["color"]).lstrip("#")
        if not COLOR_RE.match(color):
            raise PptxTextError("Couleur invalide.")
        clean["color"] = color
    return clean


# ----------------------------------------------------------------------
# Animations d'entrée
# ----------------------------------------------------------------------
def _timing_effects(slide):
    """Animations de la diapositive.

    Renvoie (gérables, effets) : ``effets`` = liste ordonnée de
    (id de zone, nom d'effet). ``gérables`` est faux si la diapositive
    contient des animations que ce module ne sait pas représenter."""
    timing = slide.find("p:timing", NS)
    if timing is None:
        return True, []
    effects = []
    manageable = True
    for ctn in timing.iter(P + "cTn"):
        preset_class = ctn.get("presetClass")
        if preset_class is None:
            continue
        try:
            key = (int(ctn.get("presetID", "-1")), int(ctn.get("presetSubtype", "0")))
        except ValueError:
            key = None
        name = EFFECT_BY_PRESET.get(key) if preset_class == "entr" else None
        targets = ctn.findall(".//p:spTgt", NS)
        spids = {t.get("spid") for t in targets}
        if (not name or ctn.get("nodeType") != "clickEffect" or len(spids) != 1
                or any(t.find("p:txEl", NS) is not None for t in targets)):
            manageable = False
            continue
        effects.append((spids.pop(), name))
    # Autres déclencheurs (sons, médias…) non représentables.
    if timing.find(".//p:cMediaNode", NS) is not None or timing.find(".//p:audio", NS) is not None:
        manageable = False
    return manageable, effects


def _el(tag, parent=None, **attrs):
    prefix, local = tag.split(":")
    qname = "{%s}%s" % (NS[prefix], local)
    node = etree.SubElement(parent, qname) if parent is not None else etree.Element(qname)
    for key, value in attrs.items():
        node.set(key, str(value))
    return node


def _cond(parent, delay="0"):
    st = _el("p:stCondLst", parent)
    _el("p:cond", st, delay=delay)


def _behaviors(child_list, spid, effect, next_id):
    """Comportements d'un effet ; renvoie le prochain identifiant libre."""
    # Rendre la zone visible (commun à tous les effets d'entrée).
    set_ = _el("p:set", child_list)
    cbhvr = _el("p:cBhvr", set_)
    ctn = _el("p:cTn", cbhvr, id=next_id, dur="1", fill="hold")
    next_id += 1
    _cond(ctn)
    tgt = _el("p:tgtEl", cbhvr)
    _el("p:spTgt", tgt, spid=spid)
    names = _el("p:attrNameLst", cbhvr)
    _el("p:attrName", names).text = "style.visibility"
    to = _el("p:to", set_)
    _el("p:strVal", to, val="visible")
    if effect == "fade":
        anim = _el("p:animEffect", child_list, transition="in", filter="fade")
        cbhvr = _el("p:cBhvr", anim)
        _el("p:cTn", cbhvr, id=next_id, dur="500")
        next_id += 1
        tgt = _el("p:tgtEl", cbhvr)
        _el("p:spTgt", tgt, spid=spid)
    elif effect == "fly":
        for attr, start, end in (("ppt_x", "#ppt_x", "#ppt_x"), ("ppt_y", "1+#ppt_h/2", "#ppt_y")):
            anim = _el("p:anim", child_list, calcmode="lin", valueType="num")
            cbhvr = _el("p:cBhvr", anim, additive="base")
            _el("p:cTn", cbhvr, id=next_id, dur="500", fill="hold")
            next_id += 1
            tgt = _el("p:tgtEl", cbhvr)
            _el("p:spTgt", tgt, spid=spid)
            names = _el("p:attrNameLst", cbhvr)
            _el("p:attrName", names).text = attr
            tav_list = _el("p:tavLst", anim)
            for tm, value in (("0", start), ("100000", end)):
                tav = _el("p:tav", tav_list, tm=tm)
                val = _el("p:val", tav)
                _el("p:strVal", val, val=value)
    return next_id


def _build_timing(effects):
    """Élément p:timing pour une liste ordonnée de (id de zone, effet)."""
    timing = _el("p:timing")
    tn_lst = _el("p:tnLst", timing)
    root_par = _el("p:par", tn_lst)
    root = _el("p:cTn", root_par, id=1, dur="indefinite", restart="never", nodeType="tmRoot")
    root_children = _el("p:childTnLst", root)
    seq = _el("p:seq", root_children, concurrent="1", nextAc="seek")
    main = _el("p:cTn", seq, id=2, dur="indefinite", nodeType="mainSeq")
    main_children = _el("p:childTnLst", main)
    next_id = 3
    for spid, effect in effects:
        preset_id, subtype = EFFECTS[effect]
        click_par = _el("p:par", main_children)
        click = _el("p:cTn", click_par, id=next_id, fill="hold")
        next_id += 1
        _cond(click, delay="indefinite")
        click_children = _el("p:childTnLst", click)
        group_par = _el("p:par", click_children)
        group = _el("p:cTn", group_par, id=next_id, fill="hold")
        next_id += 1
        _cond(group)
        group_children = _el("p:childTnLst", group)
        effect_par = _el("p:par", group_children)
        effect_ctn = _el("p:cTn", effect_par, id=next_id, presetID=preset_id, presetClass="entr",
                         presetSubtype=subtype, fill="hold", grpId="0", nodeType="clickEffect")
        next_id += 1
        _cond(effect_ctn)
        behaviors = _el("p:childTnLst", effect_ctn)
        next_id = _behaviors(behaviors, spid, effect, next_id)
    prev = _el("p:prevCondLst", seq)
    cond = _el("p:cond", prev, evt="onPrev", delay="0")
    _el("p:sldTgt", _el("p:tgtEl", cond))
    nxt = _el("p:nextCondLst", seq)
    cond = _el("p:cond", nxt, evt="onNext", delay="0")
    _el("p:sldTgt", _el("p:tgtEl", cond))
    bld = _el("p:bldLst", timing)
    for spid, _effect in effects:
        _el("p:bldP", bld, spid=spid, grpId="0", animBg="1")
    return timing


def _set_timing(slide, effects):
    old = slide.find("p:timing", NS)
    if old is not None:
        slide.remove(old)
    if not effects:
        return
    timing = _build_timing(effects)
    # Ordre du schéma : … p:clrMapOvr, p:transition, p:timing, p:extLst.
    ext = slide.find("p:extLst", NS)
    if ext is not None:
        slide.insert(list(slide).index(ext), timing)
    else:
        slide.append(timing)


# ----------------------------------------------------------------------
# Lecture / écriture
# ----------------------------------------------------------------------
def read_slides(data):
    """Diapositives, zones, paragraphes (texte + mise en forme) et animations."""
    with _open_zip(data) as zf:
        slides = []
        for number, part in enumerate(_slide_parts(zf), start=1):
            slide = etree.fromstring(_read_part(zf, part), _parser())
            manageable, effects = _timing_effects(slide)
            effect_by_spid = dict(effects)
            shapes = []
            current = None
            for index, kind, name, spid, p in _iter_paragraphs(slide):
                key = (kind, name, spid)
                if current is None or current["key"] != key:
                    current = {
                        "key": key, "kind": kind, "name": name, "id": spid,
                        "animation": effect_by_spid.get(spid, "") if kind == "text" else None,
                        "paragraphs": [],
                    }
                    shapes.append(current)
                current["paragraphs"].append({
                    "index": index,
                    "text": _paragraph_text(p),
                    "format": _format_of(p),
                })
            for shape in shapes:
                shape.pop("key")
            # Diapositive masquée (show="0") : absente de l'export PDF.
            hidden = slide.get("show") in ("0", "false")
            slides.append({
                "number": number, "part": part, "hidden": hidden, "shapes": shapes,
                "animations_editable": manageable,
            })
        return slides


def _normalize_slide_changes(edits):
    """Accepte {index: texte} (ancien format) ou {"paragraphs":…, "animations":…}."""
    if not isinstance(edits, dict):
        raise PptxTextError("Modification invalide.")
    if "paragraphs" in edits or "animations" in edits:
        paragraphs = edits.get("paragraphs") or {}
        animations = edits.get("animations")
    else:
        paragraphs, animations = edits, None
    if not isinstance(paragraphs, dict) or (animations is not None and not isinstance(animations, dict)):
        raise PptxTextError("Modification invalide.")
    clean_paragraphs = {}
    for key, value in paragraphs.items():
        try:
            index = int(key)
        except (TypeError, ValueError):
            raise PptxTextError("Paragraphe invalide.")
        clean_paragraphs[index] = _clean_paragraph_change(value)
    paragraphs = clean_paragraphs
    if animations is not None:
        clean = {}
        for spid, effect in animations.items():
            effect = effect or ""
            if effect and effect not in EFFECTS:
                raise PptxTextError("Animation inconnue : %s" % effect)
            clean[str(spid)] = effect
        animations = clean
    return paragraphs, animations


def apply_changes(data, changes):
    """Applique les modifications et renvoie le nouveau fichier .pptx (bytes)."""
    if not changes:
        return data
    with _open_zip(data) as zf:
        parts = _slide_parts(zf)
        new_parts = {}
        for number, edits in changes.items():
            number = int(number)
            if number < 1 or number > len(parts):
                raise PptxTextError("Diapositive inconnue : %s" % number)
            part = parts[number - 1]
            slide = etree.fromstring(_read_part(zf, part), _parser())
            paragraphs, animations = _normalize_slide_changes(edits)
            found = set()
            text_spids = []
            for index, kind, _name, spid, p in _iter_paragraphs(slide):
                if kind == "text" and spid not in text_spids:
                    text_spids.append(spid)
                change = paragraphs.get(index)
                if change is None:
                    continue
                found.add(index)
                if "text" in change and _paragraph_text(p) != change["text"]:
                    _set_paragraph_text(p, change["text"])
                fmt = {k: v for k, v in change.items() if k != "text"}
                if fmt:
                    _apply_format(p, fmt)
            if set(paragraphs) - found:
                raise PptxTextError("Paragraphe introuvable sur la diapositive %s." % number)
            if animations is not None:
                manageable, effects = _timing_effects(slide)
                if not manageable:
                    raise PptxTextError(
                        "La diapositive %s contient des animations avancées : elles ne "
                        "peuvent pas être modifiées ici." % number)
                unknown = set(animations) - set(text_spids)
                if unknown:
                    raise PptxTextError("Zone inconnue sur la diapositive %s." % number)
                current = dict(effects)
                current.update(animations)
                # Ordre d'apparition : celui des zones sur la diapositive.
                ordered = [(spid, current[spid]) for spid in text_spids if current.get(spid)]
                _set_timing(slide, ordered)
            new_parts[part] = etree.tostring(
                slide, xml_declaration=True, encoding="UTF-8", standalone=True)
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as dst:
            for info in zf.infolist():
                payload = new_parts.get(info.filename)
                if payload is None:
                    payload = zf.read(info.filename)
                new_info = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                new_info.compress_type = info.compress_type
                new_info.external_attr = info.external_attr
                dst.writestr(new_info, payload)
        return out.getvalue()
