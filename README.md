# Photo → Lithophanie 3D (Bambu Lab A1)

Application Streamlit : glissez une photo, récupérez un fichier **3MF** (ou STL)
à ouvrir dans Bambu Studio. La photo devient une plaque de 0.8 à 3 mm
d'épaisseur : imprimée en PLA blanc et éclairée par derrière, l'image apparaît.

## Installation

```bash
sudo apt install python3.14-venv      # une seule fois (Ubuntu/Debian)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Lancement

```bash
.venv/bin/streamlit run app.py
```

Ouvrir http://localhost:8501, déposer une photo, régler, télécharger le fichier.

## Paramètres principaux

| Paramètre | Défaut | Rôle |
|---|---|---|
| Largeur | 100 mm | Taille de la photo (plateau A1 : 256 × 256 mm) |
| Épaisseur min / max | 0.8 / 3.0 mm | Zones blanches / zones noires |
| Résolution | 0.2 mm/pixel | Finesse du relief (buse 0.4 mm) |
| Cadre | 3 mm | Bordure pleine pour la rigidité |
| Gamma / contraste | 1.0 / auto | Ajustement des tons |

## Impression conseillée (Bambu Studio)

- PLA blanc (pas « silk »), à plat, relief vers le haut
- Couche 0.12 mm (ou 0.08 mm), remplissage 100 %
- Vitesse réduite ; LED blanche à 2-5 cm derrière la plaque

## Fichiers

- `lithophane.py` : moteur (image → carte d'épaisseurs → maillage fermé → STL/3MF)
- `app.py` : interface Streamlit
