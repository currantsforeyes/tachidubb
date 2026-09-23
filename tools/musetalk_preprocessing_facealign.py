"""MuseTalk landmark extraction without OpenMMLab (Blackwell / RTX 50 friendly).

Drop-in replacement for ``MuseTalk/musetalk/utils/preprocessing.py``.

Upstream imports ``mmpose``/``mmcv`` (DWPose) to refine the face box. Those
wheels are only published for torch<=2.1 / CUDA<=12.1, which have no native
kernels for Blackwell (compute capability 12.0) GPUs — so on an RTX 50-series
card MuseTalk either fails or crawls. This version uses MuseTalk's own vendored
``face_detection`` package for the face box instead, so inference runs on a
modern torch (cu128) at full speed.

The public API is unchanged (``get_landmark_and_bbox``, ``get_bbox_range``,
``read_imgs``, ``resize_landmark``, ``coord_placeholder``), so
``scripts/inference.py`` needs no changes.

The worker (``pipeline/musetalk_worker.py``) installs this file automatically.
"""
import cv2
import numpy as np
import torch
from tqdm import tqdm

from face_detection import FaceAlignment, LandmarksType

device = "cuda" if torch.cuda.is_available() else "cpu"
fa = FaceAlignment(LandmarksType._2D, flip_input=False, device=device)

# marker used when no face is found (matches upstream)
coord_placeholder = (0.0, 0.0, 0.0, 0.0)


def resize_landmark(landmark, w, h, new_w, new_h):
    landmark_norm = landmark / [w, h]
    return landmark_norm * [new_w, new_h]


def read_imgs(img_list):
    frames = []
    print('reading images...')
    for img_path in tqdm(img_list):
        frames.append(cv2.imread(img_path))
    return frames


def _detect_boxes(frames, upperbondrange=0):
    coords_list = []
    batch_size_fa = 1
    batches = [frames[i:i + batch_size_fa] for i in range(0, len(frames), batch_size_fa)]
    if upperbondrange != 0:
        print('get face bounding boxes with the bbox_shift:', upperbondrange)
    else:
        print('get face bounding boxes with the default value')
    for fb in tqdm(batches):
        bbox = fa.get_detections_for_batch(np.asarray(fb))
        for f in bbox:
            if f is None:  # no face in the image
                coords_list += [coord_placeholder]
                continue
            x1, y1, x2, y2 = (int(v) for v in f)
            if upperbondrange != 0:
                # positive shifts the top edge down, negative up
                y1 = int(y1 + upperbondrange)
            coords_list.append((x1, y1, x2, y2))
    print("********************************************face detector mode (no DWPose)**********************************************************")
    print(f"Total frame:「{len(frames)}」 current bbox_shift: {upperbondrange}")
    print("*************************************************************************************************************************************")
    return coords_list


def get_bbox_range(img_list, upperbondrange=0):
    """Kept for API compatibility (used by MuseTalk's gradio app).

    DWPose was what suggested an ideal bbox_shift; in face-detector mode we
    can't compute that, so this just reports the current value.
    """
    frames = read_imgs(img_list)
    _detect_boxes(frames, upperbondrange)
    return (f"Total frame:「{len(frames)}」 bbox shift auto-tuning is unavailable "
            f"in face-detector mode, current value: {upperbondrange}")


def get_landmark_and_bbox(img_list, upperbondrange=0):
    frames = read_imgs(img_list)
    coords_list = _detect_boxes(frames, upperbondrange)
    return coords_list, frames


if __name__ == "__main__":
    img_list = ["./results/lyria/00000.png"]
    coords_list, full_frames = get_landmark_and_bbox(img_list)
    print(coords_list)