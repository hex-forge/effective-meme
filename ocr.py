"""
math_ocr.py - OCR + solve simple "a + b = ?" / "a - b = ?" images.
(Combines solve_math_ocr.py and ocr_test.py into one file.)

Setup:
    sudo apt-get install -y tesseract-ocr
    pip install pytesseract opencv-python-headless pillow

Usage:
    python math_ocr.py image.png               # prints the answer
    python math_ocr.py samples/                # every image in a folder
    python math_ocr.py image.png --verbose     # show every OCR attempt
    python math_ocr.py image.png --debug       # save preprocessed images to debug_out/

Use from other code:
    from math_ocr import solve_image
    answer = solve_image("image.png")          # int, or None if unreadable
"""
import argparse
import re
import sys
from pathlib import Path

import cv2
import pytesseract
#ocr.py

IMG_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
WHITELIST = "0123456789+-=?xX"
PSM = 7  # single line of text
DEBUG_DIR = Path("debug_out")


# ------------------------------------------------------------
# Image loading + preprocessing
# ------------------------------------------------------------

def load_image(path):
    """Read an image; flatten transparency onto white (text may live in alpha)."""
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(f"Could not read image: {path}")
    if img.ndim == 3 and img.shape[2] == 4:
        alpha = img[:, :, 3:4].astype("float32") / 255.0
        rgb = img[:, :, :3].astype("float32")
        img = (rgb * alpha + 255.0 * (1.0 - alpha)).astype("uint8")
    return img


def _gray_upscaled(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)


def _finish(binary):
    if binary.mean() < 127:  # dark text on light background
        binary = cv2.bitwise_not(binary)
    return cv2.copyMakeBorder(binary, 20, 20, 20, 20,
                              cv2.BORDER_CONSTANT, value=255)


def v_otsu(img):
    _, t = cv2.threshold(_gray_upscaled(img), 0, 255,
                         cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return _finish(t)


def v_blur_otsu(img):
    g = cv2.GaussianBlur(_gray_upscaled(img), (5, 5), 0)
    _, t = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return _finish(t)


def v_adaptive(img):
    t = cv2.adaptiveThreshold(_gray_upscaled(img), 255,
                              cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                              cv2.THRESH_BINARY, 31, 15)
    return _finish(t)


def v_gray(img):
    return _finish(_gray_upscaled(img))


VARIANTS = {"otsu": v_otsu, "blur_otsu": v_blur_otsu,
            "adaptive": v_adaptive, "gray": v_gray}


# ------------------------------------------------------------
# OCR + parsing
# ------------------------------------------------------------

def clean(text):
    text = text.replace(" ", "").replace("\n", "")
    text = text.replace("—", "-").replace("–", "-").replace("_", "-")
    return text.replace("x", "+").replace("X", "+")  # '+' often read as 'x'


def parse_and_solve(text):
    m = re.search(r"(\d+)([+-])(\d+)", text)
    if not m:
        return None
    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
    return a + b if op == "+" else a - b


def ocr_attempts(path, debug=False):
    """Run every preprocessing variant; return list of attempt dicts."""
    img = load_image(path)
    cfg = f"--psm {PSM} -c tessedit_char_whitelist={WHITELIST}"
    attempts = []
    for name, func in VARIANTS.items():
        processed = func(img)
        if debug:
            DEBUG_DIR.mkdir(exist_ok=True)
            cv2.imwrite(str(DEBUG_DIR / f"{Path(path).stem}_{name}.png"), processed)
        raw = pytesseract.image_to_string(processed, config=cfg).strip()
        cleaned = clean(raw)
        attempts.append({"variant": name, "raw": raw, "cleaned": cleaned,
                         "answer": parse_and_solve(cleaned)})
    return attempts


def solve_image(path, debug=False, verbose=False):
    """Return the answer (int) by majority vote across variants, or None."""
    attempts = ocr_attempts(path, debug=debug)
    if verbose:
        for a in attempts:
            print(f"    {a['variant']:<10} raw={a['raw']!r:<14} "
                  f"clean={a['cleaned']!r:<12} ans={a['answer']}")
    votes = {}
    for a in attempts:
        if a["answer"] is not None:
            votes[a["answer"]] = votes.get(a["answer"], 0) + 1
    return max(votes, key=votes.get) if votes else None


# ------------------------------------------------------------
# CLI
# ------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="image file or folder of images")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    target = Path(args.target)
    files = (sorted(p for p in target.iterdir() if p.suffix.lower() in IMG_EXTS)
             if target.is_dir() else [target])
    if not files:
        sys.exit("No images found.")

    for path in files:
        if args.verbose:
            print(path.name)
        answer = solve_image(path, debug=args.debug, verbose=args.verbose)
        print(f"{path.name}: {answer if answer is not None else 'COULD NOT READ'}")


if __name__ == "__main__":
    main()