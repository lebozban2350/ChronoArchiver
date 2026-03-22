import os
import sys
try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False
import threading
import time
import pathlib
import queue
from typing import List, Callable, Optional

try:
    from .debug_logger import debug, UTILITY_AI_MEDIA_SCANNER
except ImportError:
    from core.debug_logger import debug, UTILITY_AI_MEDIA_SCANNER

class ScannerEngine:
    """
    AI Media Scanner using OpenCV YuNet (Face) and SSD MobileNet (Animals).
    Logic: 
    - Subject (Person/Animal) Detected -> 'Keep'
    - Not Detected -> 'Others'
    """
    
    def __init__(self, logger_callback: Optional[Callable[[str], None]] = None,
                 model_dir: Optional[str] = None):
        self.logger = logger_callback or (lambda x: print(x))
        self.stop_event = threading.Event()
        self._model_dir = model_dir
        
        # Results
        self.others_list: List[str] = [] # Files to be moved/archived
        self.keep_list: List[str] = []   # Files containing subjects (people/animals)
        
        # Progress Callbacks (current, total, eta_seconds)
        self.progress_callback: Optional[Callable[[int, int, float], None]] = None

    def cancel(self):
        self.stop_event.set()

    def run_scan(self, directory: str, include_subfolders: bool = True, keep_animals: bool = False,
                 animal_threshold: float = 0.4):
        if not OPENCV_AVAILABLE:
            self.logger("Error: OpenCV (python-opencv) is not installed. AI features are disabled.")
            debug(UTILITY_AI_MEDIA_SCANNER, "ERROR: OpenCV not installed")
            return

        if not os.path.exists(directory):
            self.logger(f"Error: Directory not found: {directory}")
            debug(UTILITY_AI_MEDIA_SCANNER, f"ERROR: Directory not found: {directory}")
            return

        debug(UTILITY_AI_MEDIA_SCANNER, f"Scan start: dir={directory}, recursive={include_subfolders}, keep_animals={keep_animals}, threshold={animal_threshold}")
        self.others_list.clear()
        self.keep_list.clear()
        self.stop_event.clear()

        # Gather files with sizes (queue: path, size for byte-weighted progress)
        self.logger("Scanning directory structure...")
        image_exts = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff'}
        all_files = []

        for root, dirs, files in os.walk(directory):
            for f in files:
                if pathlib.Path(f).suffix.lower() in image_exts:
                    full_path = os.path.join(root, f)
                    try:
                        size = os.path.getsize(full_path)
                    except OSError:
                        size = 0
                    all_files.append((full_path, size))
            if not include_subfolders:
                break

        total = len(all_files)
        total_bytes = sum(s for _, s in all_files)
        debug(UTILITY_AI_MEDIA_SCANNER, f"Found {total} images ({total_bytes} bytes), initializing models")
        self.logger(f"Found {total} images ({total_bytes / (1024*1024):.1f} MB). Starting Pipeline (GPU/OpenCV)...")
        
        # Models
        face_engine = None
        animal_engine = None
        
        try:
            face_engine = self._init_opencv_face()
                
            # If keep_animals is True (Checked), User wants to EXCLUDE animals (per new request).
            if keep_animals:
                animal_engine = self._init_animal_detector()
                self.logger("Animal Filter Enabled (Keeping Animals).")
            else:
                self.logger("Animal Filter Disabled.")
                
        except Exception as e:
            self.logger(f"Model Init Failed: {e}")
            debug(UTILITY_AI_MEDIA_SCANNER, f"ERROR: Model init failed — {e}")
            return

        # Pipeline
        img_queue = queue.Queue(maxsize=20)

        def producer():
            for f_path, size in all_files:
                if self.stop_event.is_set():
                    break
                try:
                    img = cv2.imread(f_path)
                    if img is not None:
                        img_queue.put((f_path, size, img))
                except Exception:
                    pass
            img_queue.put(None)  # Sentinel

        # Start Producer
        t_prod = threading.Thread(target=producer, daemon=True)
        t_prod.start()

        # Consumer (Main Thread Context)
        start_time = time.time()
        bytes_done = 0

        while True:
            if self.stop_event.is_set():
                break

            try:
                item = img_queue.get(timeout=1)
            except queue.Empty:
                if not t_prod.is_alive():
                    break
                continue

            if item is None:
                break

            f_path, size, image = item
            
            # 1. Face Detect (OpenCV)
            has_face = False
            try:
                has_face = self._detect_face_opencv(face_engine, image)
            except Exception:
                pass

            # 2. Logic
            is_excluded = False
            
            if has_face:
                is_excluded = True
            else:
                # No human. Check animal?
                if keep_animals and animal_engine:
                    if self._detect_animal(animal_engine, image, animal_threshold):
                        is_excluded = True

            fname_base = os.path.basename(f_path)
            
            if is_excluded:
                # SUBJECT DETECTED (Keep)
                self.keep_list.append(f_path)
            else:
                # OTHERS (Move candidates)
                self.others_list.append(f_path)
                # Log MOVE candidates
                self.logger(f"[MOVE] >> {fname_base}")
                
            bytes_done += size
            self._report_progress(bytes_done, total_bytes, start_time, fname_base)

        # Cleanup
        if face_engine: 
             # FaceDetectorYN doesn't strictly need close, but good practice if wrapper changes
             pass

        if self.stop_event.is_set():
            self.logger("Scan Cancelled.")
            debug(UTILITY_AI_MEDIA_SCANNER, "Scan cancelled by user")
        else:
            self.logger(f"Done. Subjects Found: {len(self.keep_list)}, Others: {len(self.others_list)}")
            debug(UTILITY_AI_MEDIA_SCANNER, f"Scan complete: keep={len(self.keep_list)}, move={len(self.others_list)}")

    def _init_opencv_face(self):
        model = self._get_model_path('face_detection_yunet_2023mar.onnx')
        return cv2.FaceDetectorYN.create(
            model=model, config="", input_size=(320, 320),
            score_threshold=0.5, nms_threshold=0.3, top_k=5000,
            backend_id=cv2.dnn.DNN_BACKEND_OPENCV, target_id=cv2.dnn.DNN_TARGET_OPENCL
        )

    def _detect_face_opencv(self, detector, image):
        h, w, _ = image.shape
        detector.setInputSize((w, h))
        _, faces = detector.detect(image)
        return faces is not None and len(faces) > 0

    def _init_animal_detector(self):
        """Initialize animal detector using OpenCV DNN with frozen graph (SSD MobileNet V1)."""
        pb_path = self._get_model_path('ssd_mobilenet_v1_coco.pb')
        pbtxt_path = self._get_model_path('ssd_mobilenet_v1_coco.pbtxt')
        net = cv2.dnn.readNetFromTensorflow(pb_path, pbtxt_path)
        return net

    def _detect_animal(self, net, image, threshold: float = 0.4):
        """Performs animal detection using OpenCV DNN (SSD Format)."""
        blob = cv2.dnn.blobFromImage(image, 1.0, (300, 300), swapRB=True, crop=False)
        net.setInput(blob)
        detections = net.forward()
        animal_ids = {16, 17, 18, 19, 20, 21, 23, 24, 25}
        for i in range(detections.shape[2]):
            score = detections[0, 0, i, 2]
            if score > threshold:
                class_id = int(detections[0, 0, i, 1])
                if class_id in animal_ids:
                    return True
        return False

    def _get_model_path(self, filename):
        if self._model_dir:
            return os.path.join(self._model_dir, filename)
        if getattr(sys, 'frozen', False):
            base_dir = sys._MEIPASS
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, 'core', 'models', filename)

    def _report_progress(self, bytes_done, total_bytes, start_time, filename=""):
        if not self.progress_callback:
            return
        elapsed = time.time() - start_time
        if bytes_done > 0 and total_bytes > 0 and elapsed > 0:
            rate = bytes_done / elapsed
            remaining = (total_bytes - bytes_done) / rate if rate > 0 else 0
            self.progress_callback(bytes_done, total_bytes, remaining, filename)
        else:
            self.progress_callback(bytes_done, total_bytes, 0, filename)

