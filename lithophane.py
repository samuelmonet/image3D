"""Conversion d'une photo en lithophanie 3D imprimable (STL / 3MF).

Principe : chaque pixel devient une hauteur. Plus le pixel est sombre, plus la
matière est épaisse (moins de lumière passe à travers). Imprimée en blanc et
éclairée par derrière, la plaque fait apparaître la photo.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter, ImageOps

# Plateau Bambu Lab A1 : 256 x 256 x 256 mm
A1_BED_MM = 256.0


@dataclass
class LithophaneParams:
    width_mm: float = 100.0        # largeur de la photo (hors cadre)
    min_thickness: float = 0.8     # épaisseur zones claires (mm)
    max_thickness: float = 3.0     # épaisseur zones sombres (mm)
    resolution_mm: float = 0.2     # taille d'un pixel sur la pièce (mm)
    frame_mm: float = 3.0          # largeur du cadre (0 = pas de cadre)
    frame_thickness: float | None = None  # épaisseur du cadre (None = max_thickness)
    gamma: float = 1.0             # >1 éclaircit les tons moyens, <1 les assombrit
    contrast: bool = True          # étirement automatique du contraste
    smooth: float = 0.0            # flou gaussien (rayon en pixels) pour lisser
    invert: bool = False           # négatif (clair = épais)
    mirror: bool = False           # miroir horizontal (si vue côté face plate)


def prepare_image(img: Image.Image, p: LithophaneParams) -> Image.Image:
    """Redresse (EXIF), passe en niveaux de gris et redimensionne à la résolution voulue."""
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        # Fond blanc pour les zones transparentes
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img)
    gray = img.convert("L")

    nx = max(2, int(round(p.width_mm / p.resolution_mm)) + 1)
    ny = max(2, int(round(nx * gray.height / gray.width)))
    gray = gray.resize((nx, ny), Image.Resampling.LANCZOS)

    if p.contrast:
        gray = ImageOps.autocontrast(gray, cutoff=0.5)
    if p.smooth > 0:
        gray = gray.filter(ImageFilter.GaussianBlur(p.smooth))
    if p.mirror:
        gray = ImageOps.mirror(gray)
    return gray


def image_to_heightmap(gray: Image.Image, p: LithophaneParams) -> np.ndarray:
    """Convertit l'image en carte d'épaisseurs (mm), cadre inclus."""
    lum = np.asarray(gray, dtype=np.float64) / 255.0
    if p.gamma != 1.0:
        lum = lum ** (1.0 / p.gamma)
    if p.invert:
        lum = 1.0 - lum
    h = p.max_thickness - lum * (p.max_thickness - p.min_thickness)

    if p.frame_mm > 0:
        pad = int(round(p.frame_mm / p.resolution_mm))
        ft = p.frame_thickness if p.frame_thickness is not None else p.max_thickness
        h = np.pad(h, pad, mode="constant", constant_values=ft)
    return h


def heightmap_to_mesh(h: np.ndarray, pixel_mm: float) -> tuple[np.ndarray, np.ndarray]:
    """Construit un maillage fermé (étanche) : surface en relief + fond plat + bords.

    Retourne (vertices[N,3] float32, faces[M,3] int64). La ligne 0 de l'image
    correspond au haut de la pièce (Y max) pour que la photo soit à l'endroit
    vue de dessus.
    """
    ny, nx = h.shape
    xs = np.arange(nx) * pixel_mm
    ys = (ny - 1 - np.arange(ny)) * pixel_mm
    X, Y = np.meshgrid(xs, ys)

    top = np.column_stack([X.ravel(), Y.ravel(), h.ravel()])
    idx = np.arange(ny * nx).reshape(ny, nx)

    # --- Surface supérieure (2 triangles par cellule, normales vers +Z)
    a = idx[:-1, :-1].ravel()   # haut-gauche  (y grand)
    b = idx[:-1, 1:].ravel()    # haut-droite
    c = idx[1:, :-1].ravel()    # bas-gauche   (y petit)
    d = idx[1:, 1:].ravel()     # bas-droite
    top_faces = np.concatenate([
        np.column_stack([c, d, a]),
        np.column_stack([a, d, b]),
    ])

    # --- Contour (sens anti-horaire vu de dessus)
    bottom_row = idx[-1, :]            # y = 0, x croissant
    right_col = idx[::-1, -1][1:]      # x max, y croissant
    top_row = idx[0, ::-1][1:]         # y max, x décroissant
    left_col = idx[:, 0][1:-1]         # x = 0, y décroissant
    loop = np.concatenate([bottom_row, right_col, top_row, left_col])

    n_top = len(top)
    # Sommets du fond : copie du contour à z = 0 + un centre
    bot_xy = top[loop, :2]
    bottom = np.column_stack([bot_xy, np.zeros(len(loop))])
    center = np.array([[xs[-1] / 2, ys[0] / 2, 0.0]])
    bot_idx = n_top + np.arange(len(loop))
    center_idx = n_top + len(loop)

    nxt = np.roll(np.arange(len(loop)), -1)

    # --- Murs latéraux (normales vers l'extérieur)
    t0, t1 = loop, loop[nxt]
    b0, b1 = bot_idx, bot_idx[nxt]
    side_faces = np.concatenate([
        np.column_stack([b0, b1, t1]),
        np.column_stack([b0, t1, t0]),
    ])

    # --- Fond : éventail depuis le centre (normales vers -Z)
    bottom_faces = np.column_stack([
        np.full(len(loop), center_idx), b1, b0,
    ])

    vertices = np.vstack([top, bottom, center]).astype(np.float32)
    faces = np.concatenate([top_faces, side_faces, bottom_faces]).astype(np.int64)
    return vertices, faces


def mesh_to_stl(vertices: np.ndarray, faces: np.ndarray) -> bytes:
    """Encode le maillage en STL binaire."""
    tri = vertices[faces]  # (M, 3, 3)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    norm = np.linalg.norm(n, axis=1, keepdims=True)
    norm[norm == 0] = 1
    n = (n / norm).astype(np.float32)

    dtype = np.dtype([
        ("normal", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2"),
    ])
    data = np.zeros(len(faces), dtype=dtype)
    data["normal"] = n
    data["v"] = tri
    header = b"Lithophane generated by image3D".ljust(80, b" ")
    return header + np.uint32(len(faces)).tobytes() + data.tobytes()


def mesh_to_3mf(vertices: np.ndarray, faces: np.ndarray, name: str = "Lithophane") -> bytes:
    """Encode le maillage en 3MF (format natif de Bambu Studio)."""
    v_xml = "".join(
        f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in vertices.tolist()
    )
    t_xml = "".join(
        f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in faces.tolist()
    )
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        f'<metadata name="Title">{name}</metadata>'
        '<resources><object id="1" type="model">'
        f'<mesh><vertices>{v_xml}</vertices><triangles>{t_xml}</triangles></mesh>'
        '</object></resources>'
        '<build><item objectid="1"/></build></model>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
        '</Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        '</Relationships>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)
    return buf.getvalue()


def simulate_backlight(h: np.ndarray, p: LithophaneParams) -> Image.Image:
    """Aperçu approximatif de la photo vue en rétroéclairage (loi de Beer-Lambert)."""
    span = max(p.max_thickness - p.min_thickness, 1e-6)
    k = 1.6  # coefficient d'atténuation approximatif du PLA blanc (1/mm)
    trans = np.exp(-k * (h - p.min_thickness))
    trans_min = np.exp(-k * span)
    lum = np.clip((trans - trans_min) / (1 - trans_min), 0, 1)
    # Teinte chaude d'une LED derrière du PLA blanc
    rgb = np.stack([lum * 255, lum * 235, lum * 200], axis=-1)
    return Image.fromarray(rgb.astype(np.uint8), "RGB")


def generate(img: Image.Image, p: LithophaneParams):
    """Pipeline complet. Retourne (heightmap, vertices, faces)."""
    gray = prepare_image(img, p)
    h = image_to_heightmap(gray, p)
    v, f = heightmap_to_mesh(h, p.resolution_mm)
    return h, v, f
