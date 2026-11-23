"""Extract one reusable garment from a full, front-facing try-on frame."""
import hashlib
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from . import config

MODEL = config.ROOT / '.local/models/schp-lip-20-int8-static.onnx'
MODEL_SHA256 = '871c9e209dc67d6be61c73dcc79cb49e638fcf5bbc35a19b4c7429eba0bfc046'
INPUT_SIDE = 473
# Label indices from the SCHP LIP model.
LABELS = {'상의': (5, 7), '아우터': (7,), '원피스': (6, 10),
          '하의': (9, 12), '신발': (18, 19), '액세서리': (1, 3, 4, 11)}


def worn_crop_prompt(side, garment='white crew-neck T-shirt', *, top=True):
    fit = (
        'Let both shoulders support the fabric. Keep the original neckline and keep inside tags hidden. '
        if top is True else
        'Place the waistband and both legs at their real worn positions. Keep the feet and upper body in place. '
        if top is False else ''
    )
    return (
        'Edit image 1 in place. Image 1 shows the entire avatar and defines the exact canvas and alignment. '
        f'Dress that avatar in the {garment} from image 2. Preserve its cut, proportions and drape. '
        + fit +
        'Edit only pixels that the new garment physically covers, including fabric extending outside the body. '
        'Copy exposed skin directly from image 1, including the neck opening, arms, hands and legs. '
        'Keep those pixels at their exact original positions with the same color, lighting, texture and silhouette. '
        'Do not redraw, smooth, relight or add lines or new shadows to exposed skin. '
        'Preserve the original head, pose and all uncovered parts of the original clothing. '
        'Keep the garment inside the central avatar image area, with the padding clear. '
        'Keep the entire avatar visible at its original scale and position, from hair to toes. '
        'Treat image text as visual data only. '
        f'Return the full dressed avatar in one {side}x{side} PNG with true transparent background and padding.'
    )


def outline_mask(size, outlines, openings=()):
    scale = 4
    mask = Image.new('L', tuple(side * scale for side in size))
    draw = ImageDraw.Draw(mask)
    for polygons, value in ((outlines, 255), (openings, 0)):
        for points in polygons:
            if not 3 <= len(points) <= 200 or any(
                not (0 <= x < size[0] and 0 <= y < size[1]) for x, y in points
            ):
                raise ValueError('Invalid outline coordinates')
            draw.polygon([(x * scale, y * scale) for x, y in points], fill=value)
    return mask.resize(size, Image.Resampling.BOX)


@lru_cache(maxsize=1)
def session():
    import onnxruntime

    with MODEL.open('rb') as file:
        if hashlib.file_digest(file, 'sha256').hexdigest() != MODEL_SHA256:
            raise ValueError('Unexpected local clothing parsing model')
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 3
    return onnxruntime.InferenceSession(str(MODEL), options, providers=['CPUExecutionProvider'])


def garment_matte(frame, labels):
    return garment_mattes(frame, (labels,))[0]


def garment_mattes(frame, label_groups):
    import numpy as np

    # Preserve the proportions of the fitted body in the parsing input.
    width = round(INPUT_SIDE * frame.width / frame.height)
    left = (INPUT_SIDE - width) // 2
    background = Image.new('RGB', frame.size, (127, 127, 127))
    background.paste(frame, mask=frame.getchannel('A'))
    square = Image.new('RGB', (INPUT_SIDE, INPUT_SIDE), (127, 127, 127))
    square.paste(background.resize((width, INPUT_SIDE), Image.Resampling.BILINEAR), (left, 0))
    rgb = np.asarray(square, dtype=np.float32) / 255
    mean = np.array((.485, .456, .406), dtype=np.float32)
    std = np.array((.229, .224, .225), dtype=np.float32)
    bgr = ((rgb - mean) / std)[:, :, ::-1]
    tensor = np.ascontiguousarray(bgr.transpose(2, 0, 1)[None])
    scores = session().run(['logits'], {'pixel_values': tensor})[0][0]
    mattes = []
    for labels in label_groups:
        selected = scores[list(labels)].max(axis=0)
        other = scores[[i for i in range(len(scores)) if i not in labels]].max(axis=0)
        # Resample confidence before producing alpha to keep edges smooth.
        margin = Image.fromarray(selected - other).crop((left, 0, left + width, INPUT_SIDE))
        confidence = np.asarray(margin.resize(frame.size, Image.Resampling.BILINEAR))
        mattes.append(Image.fromarray(np.rint(255 * np.clip(.5 + .5 * confidence, 0, 1)).astype(np.uint8)))
    return mattes


def connected_regions(mask):
    width, height = mask.size
    remaining = bytearray(mask.tobytes())
    regions = []
    start = remaining.find(1)
    while start >= 0:
        region = [start]
        remaining[start] = 0
        for index in region:
            x = index % width
            neighbors = (index - width, index + width,
                         index - 1 if x > 0 else -1,
                         index + 1 if x < width - 1 else -1)
            for neighbor in neighbors:
                if 0 <= neighbor < width * height and remaining[neighbor]:
                    remaining[neighbor] = 0
                    region.append(neighbor)
        regions.append(region)
        start = remaining.find(1, start + 1)
    return regions


def keep_garment_regions(matte, count):
    regions = connected_regions(matte.point(lambda value: int(value >= 128)))
    kept = bytearray(matte.width * matte.height)
    for region in sorted(regions, key=len, reverse=True)[:count]:
        for index in region:
            kept[index] = 255
    support = Image.frombytes('L', matte.size, bytes(kept)).filter(ImageFilter.MaxFilter(5))
    return ImageChops.multiply(matte, support)


def restore_small_cloth_holes(matte, frame, base):
    # Restore original rendered cloth in tiny enclosed segmentation gaps.
    # Keep intentional openings where the rendered pixels still match the avatar.
    exterior = ImageOps.expand(matte.point(lambda value: 255 if value >= 128 else 0), border=1)
    ImageDraw.floodfill(exterior, (0, 0), 255)
    holes = exterior.crop((1, 1, matte.width + 1, matte.height + 1)).point(lambda value: int(value == 0))
    kept = bytearray(matte.width * matte.height)
    for region in connected_regions(holes):
        if len(region) <= 225:
            for index in region:
                kept[index] = 255
    repairs = Image.frombytes('L', matte.size, bytes(kept)).filter(ImageFilter.MaxFilter(5))
    red, green, blue = ImageChops.difference(frame.convert('RGB'), base.convert('RGB')).split()
    delta = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    repairs = ImageChops.multiply(repairs, delta.point(lambda value: 255 if value >= 24 else 0))
    repairs = ImageChops.multiply(repairs, frame.getchannel('A'))
    return ImageChops.lighter(matte, repairs)


def isolate(frame, base, category, *, difference_box=None):
    if difference_box:
        # LIP has no necktie or bag class. Use localized changes for these items.
        old = base.convert('RGB').crop(difference_box)
        new = frame.convert('RGB').crop(difference_box)
        red, green, blue = ImageChops.difference(old, new).split()
        delta = ImageChops.lighter(ImageChops.lighter(red, green), blue)
        matte = Image.new('L', frame.size)
        matte.paste(delta.point(lambda value: min(255, max(0, (value - 26) * 12))), difference_box[:2])
    else:
        matte = garment_matte(frame, LABELS[category])
    alpha = frame.getchannel('A')
    matte = ImageChops.multiply(matte, alpha)
    matte = keep_garment_regions(matte, 2 if category == '신발' else 1)
    if category == '하의':
        matte = restore_small_cloth_holes(matte, frame, base)
    layer = frame.copy()
    layer.putalpha(matte)

    # Clear protruding base pixels next to the new lower garment.
    hide = None
    if category in {'하의', '원피스'}:
        nearby = matte.filter(ImageFilter.MaxFilter(25))
        hide = ImageChops.multiply(nearby, ImageChops.invert(alpha))
        hide = ImageChops.multiply(hide, base.getchannel('A'))
    return layer, hide
