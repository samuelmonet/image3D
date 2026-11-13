"""Interface Streamlit : photo -> lithophanie 3D pour Bambu Lab A1."""

import io
from dataclasses import asdict
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import streamlit as st
from PIL import Image

from lithophane import (
    A1_BED_MM,
    LithophaneParams,
    generate,
    mesh_to_3mf,
    mesh_to_stl,
    simulate_backlight,
)

st.set_page_config(page_title="Photo → Lithophanie 3D", page_icon="🖨️", layout="wide")
st.title("🖨️ Photo → Lithophanie 3D (Bambu Lab A1)")
st.caption(
    "Glissez une photo : elle est convertie en plaque de 2-3 mm dont l'épaisseur varie "
    "selon la luminosité. Imprimée en blanc et éclairée par derrière, la photo apparaît."
)

# ---------------------------------------------------------------- Paramètres
with st.sidebar:
    st.header("Dimensions")
    width_mm = st.slider("Largeur de la photo (mm)", 40, 240, 100, 5)
    min_t, max_t = st.slider(
        "Épaisseur min / max (mm)", 0.4, 5.0, (0.8, 3.0), 0.1,
        help="Min = zones blanches (≥ 0.6 mm conseillé). Max = zones noires.",
    )
    resolution = st.select_slider(
        "Résolution (mm / pixel)", options=[0.1, 0.15, 0.2, 0.25, 0.3, 0.4], value=0.2,
        help="0.2 mm est un bon compromis avec une buse 0.4 mm. Plus fin = fichier plus lourd.",
    )
    frame_mm = st.slider("Largeur du cadre (mm)", 0.0, 10.0, 3.0, 0.5)

    st.header("Image")
    contrast = st.checkbox("Contraste automatique", value=True)
    gamma = st.slider("Gamma", 0.4, 2.5, 1.0, 0.05,
                      help=">1 éclaircit les tons moyens, <1 les assombrit.")
    smooth = st.slider("Lissage", 0.0, 3.0, 0.0, 0.25)
    invert = st.checkbox("Négatif", value=False)
    mirror = st.checkbox("Miroir horizontal", value=False,
                         help="À cocher si vous regardez la plaque côté face plate.")

    st.header("Export")
    fmt = st.radio("Format", ["3MF (recommandé Bambu Studio)", "STL"], index=0)

params = LithophaneParams(
    width_mm=width_mm,
    min_thickness=min_t,
    max_thickness=max_t,
    resolution_mm=resolution,
    frame_mm=frame_mm,
    gamma=gamma,
    contrast=contrast,
    smooth=smooth,
    invert=invert,
    mirror=mirror,
)

uploaded = st.file_uploader(
    "Déposez votre photo ici", type=["jpg", "jpeg", "png", "bmp", "webp", "tif", "tiff"]
)

if uploaded is None:
    st.info("⬆️ Glissez-déposez une photo pour commencer.")
    st.stop()


@st.cache_data(show_spinner=False, max_entries=4)
def build(file_bytes: bytes, p_dict: dict):
    img = Image.open(io.BytesIO(file_bytes))
    return generate(img, LithophaneParams(**p_dict))


@st.cache_data(show_spinner=False, max_entries=4)
def export(file_bytes: bytes, p_dict: dict, kind: str, name: str) -> bytes:
    _, v, f = build(file_bytes, p_dict)
    return mesh_to_3mf(v, f, name=name) if kind == "3mf" else mesh_to_stl(v, f)


with st.spinner("Génération du modèle 3D…"):
    file_bytes = uploaded.getvalue()
    p_dict = asdict(params)
    h, vertices, faces = build(file_bytes, p_dict)

ny, nx = h.shape
size_x = (nx - 1) * resolution
size_y = (ny - 1) * resolution

# ---------------------------------------------------------------- Infos
c1, c2, c3, c4 = st.columns(4)
c1.metric("Largeur", f"{size_x:.1f} mm")
c2.metric("Hauteur", f"{size_y:.1f} mm")
c3.metric("Épaisseur", f"{h.min():.1f} – {h.max():.1f} mm")
c4.metric("Triangles", f"{len(faces):,}".replace(",", " "))

if size_x > A1_BED_MM or size_y > A1_BED_MM:
    st.error(
        f"⚠️ La pièce ({size_x:.0f} × {size_y:.0f} mm) dépasse le plateau de l'A1 "
        f"({A1_BED_MM:.0f} × {A1_BED_MM:.0f} mm). Réduisez la largeur."
    )

# ---------------------------------------------------------------- Aperçus
col_a, col_b = st.columns(2)
with col_a:
    st.subheader("Photo d'origine")
    st.image(file_bytes, width="stretch")
with col_b:
    st.subheader("Aperçu rétroéclairé (simulation)")
    st.image(simulate_backlight(h, params), width="stretch")

with st.expander("Aperçu 3D du relief"):
    step = max(1, int(np.ceil(max(nx, ny) / 250)))  # sous-échantillonnage pour l'affichage
    hs = h[::step, ::step]
    fig = go.Figure(go.Surface(
        z=hs[::-1], colorscale="Greys", reversescale=True, showscale=False,
        x=np.arange(hs.shape[1]) * resolution * step,
        y=np.arange(hs.shape[0]) * resolution * step,
    ))
    fig.update_layout(
        height=550, margin=dict(l=0, r=0, t=0, b=0),
        scene=dict(aspectmode="manual",
                   aspectratio=dict(x=1, y=size_y / size_x, z=0.15),
                   xaxis_title="X (mm)", yaxis_title="Y (mm)", zaxis_title="Z (mm)"),
    )
    st.plotly_chart(fig, width="stretch")

# ---------------------------------------------------------------- Export
stem = Path(uploaded.name).stem
kind = "3mf" if fmt.startswith("3MF") else "stl"
with st.spinner(f"Création du fichier {kind.upper()}…"):
    data = export(file_bytes, p_dict, kind, stem)
fname = f"{stem}_lithophane.{kind}"
mime = "model/3mf" if kind == "3mf" else "model/stl"

st.download_button(
    f"⬇️ Télécharger {fname} ({len(data) / 1e6:.1f} Mo)",
    data=data, file_name=fname, mime=mime, type="primary", width="stretch",
)

with st.expander("💡 Réglages conseillés dans Bambu Studio (A1)"):
    st.markdown(
        """
- **Filament** : PLA **blanc** (mat ou basique), pas de blanc « silk ».
- **Orientation** : laisser à plat, face en relief vers le haut (comme généré).
- **Hauteur de couche** : 0.12 mm (ou 0.08 mm pour plus de détails).
- **Remplissage** : 100 % (ou nombre de parois élevé, ex. 10) pour éviter les motifs de remplissage visibles.
- **Vitesse** : réduite (profil « Fine » / 0.12 mm) pour une surface propre.
- **Éclairage** : LED blanche placée à 2-5 cm derrière la plaque.
"""
    )
