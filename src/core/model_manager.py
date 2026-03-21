import os
import requests
import pathlib
import threading
import logging
import hashlib
import tarfile

try:
    from .debug_logger import debug, UTILITY_AI_MEDIA_SCANNER
except ImportError:
    from core.debug_logger import debug, UTILITY_AI_MEDIA_SCANNER

class ModelManager:
    """Handles checking and downloading AI models for the scanner."""
    
    MODELS = {
        "face_detection": {
            "filename": "face_detection_yunet_2023mar.onnx",
            "url": "https://github.com/opencv/opencv_zoo/raw/master/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
            "sha256": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
        },
        "animal_detection_pb": {
            "filename": "ssd_mobilenet_v1_coco.pb",
            "url": "http://download.tensorflow.org/models/object_detection/ssd_mobilenet_v1_coco_2017_11_17.tar.gz",
            "tar_extract": "ssd_mobilenet_v1_coco_2017_11_17/frozen_inference_graph.pb",
            "sha256": "cb3ce31b95a54162c25d951780a740a8767e6f9987298ec53d3146f0a5506858"
        },
        "animal_detection_pbtxt": {
            "filename": "ssd_mobilenet_v1_coco.pbtxt",
            "url": "https://raw.githubusercontent.com/opencv/opencv_extra/master/testdata/dnn/ssd_mobilenet_v1_coco_2017_11_17.pbtxt",
            "sha256": "c15a9ac2df5cdb379e3a294adc73f13c796da8d682d763f4ec15831af1e11923"
        }
    }
    
    def __init__(self, model_dir: str):
        self.model_dir = pathlib.Path(model_dir)
        self.logger = logging.getLogger("ChronoArchiver")
        self.stop_event = threading.Event()

    def verify_hash(self, file_path: pathlib.Path, expected_sha: str) -> bool:
        """Verify the SHA-256 hash of a file."""
        sha256_hash = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            actual_sha = sha256_hash.hexdigest()
            if actual_sha != expected_sha:
                self.logger.warning(f"Hash mismatch for {file_path.name}! Expected: {expected_sha}, Actual: {actual_sha}")
                return False
            return True
        except Exception as e:
            self.logger.error(f"Error during hash verification: {e}")
            return False

    def get_missing_models(self):
        """Returns a list of model keys that are missing or corrupt."""
        missing = []
        for key, info in self.MODELS.items():
            path = self.model_dir / info["filename"]
            if not path.exists() or not self.verify_hash(path, info["sha256"]):
                missing.append(key)
        return missing

    def is_up_to_date(self):
        """Returns True if all models are present and valid."""
        return len(self.get_missing_models()) == 0

    def download_models(self, progress_callback=None):
        """Downloads all missing/corrupt models. progress_callback(current_size, total_size, filename)"""
        missing = self.get_missing_models()
        if not missing:
            debug(UTILITY_AI_MEDIA_SCANNER, "Model download: all models present")
            return True

        debug(UTILITY_AI_MEDIA_SCANNER, f"Model download start: missing={missing}")
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.stop_event.clear()

        for key in missing:
            if self.stop_event.is_set():
                break
            
            info = self.MODELS[key]
            url = info["url"]
            dest = self.model_dir / info["filename"]
            
            self.logger.info(f"Downloading model: {info['filename']}")
            
            try:
                # Remove if exists (might be corrupt)
                if dest.exists(): dest.unlink()

                response = requests.get(url, stream=True, timeout=30)
                response.raise_for_status()
                total_size = int(response.headers.get('content-length', 0))
                
                is_tar = "tar_extract" in info
                dl_dest = dest if not is_tar else dest.with_suffix(".tar.gz")
                
                with open(dl_dest, 'wb') as f:
                    downloaded = 0
                    for chunk in response.iter_content(chunk_size=8192):
                        if self.stop_event.is_set():
                            break
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_callback:
                                progress_callback(downloaded, total_size, dl_dest.name)
                
                if self.stop_event.is_set():
                    if dl_dest.exists(): dl_dest.unlink()
                    self.logger.info(f"Download cancelled for {info['filename']}")
                    debug(UTILITY_AI_MEDIA_SCANNER, f"Model download cancelled: {info['filename']}")
                    return False

                # Extract tar if needed
                if "tar_extract" in info:
                    if progress_callback:
                        progress_callback(total_size, total_size, f"Extracting {info['filename']}...")
                    with tarfile.open(dl_dest, "r:gz") as tar:
                        member = tar.getmember(info["tar_extract"])
                        member.name = dest.name
                        if hasattr(tarfile, 'data_filter'):
                            tar.extract(member, path=dest.parent, filter='data')
                        else:
                            tar.extract(member, path=dest.parent)
                    dl_dest.unlink()

                # Verify after download
                if not self.verify_hash(dest, info["sha256"]):
                    self.logger.error(f"Integrity check failed for {info['filename']}")
                    debug(UTILITY_AI_MEDIA_SCANNER, f"Model hash mismatch: {info['filename']}")
                    if dest.exists(): dest.unlink()
                    return False

            except Exception as e:
                self.logger.error(f"Failed to download {info['filename']}: {e}")
                debug(UTILITY_AI_MEDIA_SCANNER, f"Model download failed: {info['filename']} — {e}")
                if dest.exists(): dest.unlink()
                if 'dl_dest' in locals() and dl_dest.exists(): dl_dest.unlink()
                return False

        ok = self.is_up_to_date()
        debug(UTILITY_AI_MEDIA_SCANNER, f"Model download complete: ok={ok}")
        return ok

    def cancel(self):
        self.stop_event.set()
