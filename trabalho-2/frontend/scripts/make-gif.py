"""Gera o GIF didático a partir das capturas de npm run capture (requer Pillow)."""
from pathlib import Path
from PIL import Image

directory = Path(__file__).resolve().parents[2] / 'docs' / 'img'
frames = [Image.open(directory / f'frame-{i}.png').convert('RGB').resize((1008, 700)) for i in range(5)]
frames[0].save(directory / 'demo.gif', save_all=True, append_images=frames[1:],
               duration=[1600, 1300, 1300, 2300, 1800], loop=0, optimize=True)
for i in range(5):
    (directory / f'frame-{i}.png').unlink()
print(f'GIF salvo em {directory / "demo.gif"}')
