import config


def snap():
    """One webcam frame as JPEG bytes."""
    import cv2
    cap = cv2.VideoCapture(config.CAMERA_INDEX)
    try:
        if not cap.isOpened():
            raise RuntimeError("camera not available, check Camera permission for your terminal")
        for _ in range(8):  # let exposure settle
            cap.read()
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError("could not read from the camera")
    finally:
        cap.release()
    h, w = frame.shape[:2]
    if w > 1024:
        frame = cv2.resize(frame, (1024, round(h * 1024 / w)))
    return cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()
