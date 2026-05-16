"""Construye un favicon.ico multi-resolución a partir de los PNGs del
A_classic. Embebe los frames 16/32/48 (los 3 tamaños clásicos que pide
Windows / browsers legacy).

Run: python scripts/build_favicon_ico.py
"""
from PIL import Image

STATIC = r'C:\Users\Shaggy\source\repos\Ideas 2.0\edTech\static'
ICO_PATH = f'{STATIC}\\favicon.ico'

# Pillow's ICO writer toma `sizes` y downsamplea desde la imagen base.
# La mejor estrategia para no perder calidad en 16/32: arrancar del
# PNG de 48px (alta resolución, perfecto bicubic downsample en Pillow).
base = Image.open(f'{STATIC}\\favicon-48.png').convert('RGBA')
base.save(
    ICO_PATH,
    format='ICO',
    sizes=[(16, 16), (32, 32), (48, 48)],
)

# Validación post-save.
ico = Image.open(ICO_PATH)
ico.load()
sizes = sorted(ico.info.get('sizes', []))
print(f'favicon.ico regenerado con sizes={sizes}')
assert len(sizes) == 3, 'Esperaba 3 frames embebidos'
