"""
Procedural test-image generator.

Ported from StamperEL (C:\\nb\\tests\\generate_test_images.py).
Generates deterministic colourful checkerboard PNGs — better than solid
colours for catching framing/upscale artefacts, and better than grey for
human inspection.

generate_checkerboard() is called lazily by the source_image_cache fixture
in conftest.py; images are written to tests/fixtures/generated/ and reused
across runs.  That directory is git-ignored.

SOURCE_SIZES  — 16 sizes covering small/medium/large square, widescreen,
                portrait.  Used for the standard resolution-matrix tests.
SOURCE_SIZES_SLOW — 4 extreme sizes (5k–10k px).  Skipped unless -m slow.
"""

import random
from pathlib import Path
from PIL import Image

Image.MAX_IMAGE_PIXELS = None  # allow large test images

# (width, height, description, seed)
SOURCE_SIZES = [
    (50,   50,   "very_small_square",  1001),
    (100,  100,  "small_square",       1002),
    (64,   48,   "small_widescreen",   1003),
    (48,   64,   "small_portrait",     1004),
    (200,  200,  "square_200",         1005),
    (320,  240,  "widescreen_240p",    1006),
    (240,  320,  "portrait_240w",      1007),
    (500,  500,  "square_500",         1008),
    (800,  600,  "widescreen_600h",    1009),
    (600,  800,  "portrait_600w",      1010),
    (1000, 1000, "square_1000",        1011),
    (1920, 1080, "widescreen_1080p",   1012),
    (1080, 1920, "portrait_1080w",     1013),
    (2000, 2000, "square_2000",        1014),
    (4000, 3000, "widescreen_3000h",   1015),
    (3000, 4000, "portrait_3000w",     1016),
]

SOURCE_SIZES_SLOW = [
    (5000,  5000,  "square_5000",        1017),
    (10000, 10000, "square_10000",       1018),
    (8000,  6000,  "widescreen_extreme", 1019),
    (6000,  8000,  "portrait_extreme",   1020),
]


def generate_checkerboard(width: int, height: int, seed: int | None = None) -> Image.Image:
    """
    Return a colourful checkerboard PIL image.

    Uses a two-step approach for memory efficiency:
    1. Create a small base image (one pixel per square)
    2. Upscale by an integer factor with nearest-neighbour
    3. Crop to exact target dimensions
    """
    if seed is not None:
        random.seed(seed)

    check_size = max(4, min(128, min(width, height) // 20))
    base_w = (width  + check_size - 1) // check_size
    base_h = (height + check_size - 1) // check_size

    base_img = Image.new("RGB", (base_w, base_h))
    px = base_img.load()
    for y in range(base_h):
        for x in range(base_w):
            px[x, y] = (
                random.randint(50, 255),
                random.randint(50, 255),
                random.randint(50, 255),
            )

    img = base_img.resize((base_w * check_size, base_h * check_size), Image.Resampling.NEAREST)
    return img.crop((0, 0, width, height))
