# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from __future__ import annotations

import atexit
import json
import multiprocessing
import os
import pickle
import shutil
import socket
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import numpy as np
import zerorpc

from module.exception import ScriptError
from module.logger import logger
from module.ocr.common import BoxedResult, OcrLogger

if TYPE_CHECKING:
    from module.ocr.ppocr import TextSystem

_OCR_SERVER_PROCESS: Optional[multiprocessing.Process] = None
_OCR_CLIENT_CACHE: dict[str, "ModelProxy"] = {}
_OCR_LOGGING_ENABLED = False
_OCR_MODEL_SIZE = "medium"

_BUNDLED_MODEL_DIRS = (
    "PP-OCRv6_medium_det_onnx",
    "PP-OCRv6_medium_rec_onnx",
)
_BUNDLED_MODEL_FILES = (
    "inference.json",
    "inference.onnx",
    "inference.yml",
)
_OCR_STARTUP_TIMEOUT_SECONDS = 90.0
_OCR_REQUEST_TIMEOUT_SECONDS = 10.0
_OCR_MODEL_DOWNLOAD_TIMEOUT_SECONDS = 900.0
_OCR_MODEL_MIN_FILE_SIZE = {
    "inference.json": 1024,
    "inference.onnx": 1024 * 1024,
    "inference.yml": 128,
}
_OCR_DOWNLOAD_CONTEXT = multiprocessing.get_context("spawn")




def _bundled_ocr_cache_home() -> Path:
    return Path(__file__).resolve().parents[2] / "toolkit" / ".paddlex"


def _bundled_ocr_model_issues(official_models: Path | None = None) -> list[str]:
    """检查中模型所需文件是否存在、大小合理且JSON配置可解析。"""
    if official_models is None:
        official_models = _bundled_ocr_cache_home() / "official_models"

    issues: list[str] = []
    for model_dir in _BUNDLED_MODEL_DIRS:
        for filename in _BUNDLED_MODEL_FILES:
            path = official_models / model_dir / filename
            relative_path = str(Path(model_dir) / filename)
            if not path.is_file():
                issues.append(f"missing:{relative_path}")
                continue
            minimum_size = _OCR_MODEL_MIN_FILE_SIZE[filename]
            try:
                actual_size = path.stat().st_size
            except OSError as exc:
                issues.append(f"unreadable:{relative_path}:{exc}")
                continue
            if actual_size < minimum_size:
                issues.append(
                    f"truncated:{relative_path}:{actual_size}<{minimum_size}"
                )
                continue
            if filename == "inference.json":
                try:
                    json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    issues.append(f"invalid-json:{relative_path}:{exc}")
    return issues


def _download_bundled_ocr_models(cache_home: str) -> None:
    """在独立进程中下载PaddleOCR medium ONNX模型到指定缓存。"""
    os.environ["PADDLE_PDX_CACHE_HOME"] = cache_home
    os.environ["PADDLE_PDX_MODEL_SOURCE"] = "bos"
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

    from paddleocr import PaddleOCR

    PaddleOCR(
        text_detection_model_name="PP-OCRv6_medium_det",
        text_recognition_model_name="PP-OCRv6_medium_rec",
        engine="onnxruntime",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )


def _remove_model_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _install_repaired_ocr_models(repair_cache: Path) -> None:
    """验证下载内容后，用完整模型目录替换损坏目录，失败则回滚。"""
    repair_official_models = repair_cache / "official_models"
    issues = _bundled_ocr_model_issues(repair_official_models)
    if issues:
        raise RuntimeError(f"Downloaded OCR models are incomplete: {issues}")

    official_models = _bundled_ocr_cache_home() / "official_models"
    official_models.mkdir(parents=True, exist_ok=True)
    suffix = f".incomplete-{os.getpid()}-{time.time_ns()}"
    backups: dict[Path, Path] = {}
    installed: list[Path] = []
    try:
        for model_dir in _BUNDLED_MODEL_DIRS:
            source = repair_official_models / model_dir
            target = official_models / model_dir
            backup = official_models / f"{model_dir}{suffix}"
            if target.exists():
                target.replace(backup)
                backups[target] = backup
            source.replace(target)
            installed.append(target)

        final_issues = _bundled_ocr_model_issues(official_models)
        if final_issues:
            raise RuntimeError(f"Installed OCR models are incomplete: {final_issues}")
    except Exception:
        for target in installed:
            _remove_model_path(target)
        for target, backup in backups.items():
            if backup.exists():
                backup.replace(target)
        raise
    else:
        for backup in backups.values():
            _remove_model_path(backup)


def _repair_bundled_ocr_models() -> bool:
    """下载并原子替换损坏的中模型资源。"""
    toolkit_dir = _bundled_ocr_cache_home().parent
    toolkit_dir.mkdir(parents=True, exist_ok=True)
    repair_cache = Path(
        tempfile.mkdtemp(prefix=".paddlex-repair-", dir=str(toolkit_dir))
    )
    process = _OCR_DOWNLOAD_CONTEXT.Process(
        target=_download_bundled_ocr_models,
        args=(str(repair_cache),),
        name="ocr_model_downloader",
        daemon=False,
    )
    try:
        logger.warning("Downloading complete PaddleOCR medium model resources")
        process.start()
        process.join(timeout=_OCR_MODEL_DOWNLOAD_TIMEOUT_SECONDS)
        if process.is_alive():
            logger.error(
                "OCR model download timed out after "
                f"{_OCR_MODEL_DOWNLOAD_TIMEOUT_SECONDS:.0f}s"
            )
            process.terminate()
            process.join(timeout=5.0)
            return False
        if process.exitcode != 0:
            logger.error(f"OCR model downloader exited with code {process.exitcode}")
            return False
        _install_repaired_ocr_models(repair_cache)
        logger.info("PaddleOCR medium model resources repaired successfully")
        return True
    except Exception as exc:
        logger.exception(exc)
        return False
    finally:
        shutil.rmtree(repair_cache, ignore_errors=True)


def _configure_bundled_paddlex_cache() -> Path | None:
    """Use models shipped in ``toolkit/.paddlex`` when they are complete.

    PaddleX otherwise stores and downloads official models under the current
    user's profile.  The easy-install release is intended to be portable, so
    it carries the two medium OCR models beside its Python runtime instead.
    Environment variables must be set before importing PaddleOCR/PaddleX.
    """
    cache_home = _bundled_ocr_cache_home()
    official_models = cache_home / "official_models"
    issues = _bundled_ocr_model_issues(official_models)
    if issues:
        if cache_home.exists():
            logger.warning(
                "Bundled PaddleOCR models are incomplete; fallback to the "
                f"default PaddleX cache (issues={issues})"
            )
        return None

    os.environ["PADDLE_PDX_CACHE_HOME"] = str(cache_home)
    # No hoster connectivity checks are needed when all required files exist.
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    logger.info(f"Use bundled PaddleOCR models: {official_models}")
    return cache_home


def _normalize_address(address: str) -> str:
    if address.startswith("tcp://"):
        return address
    return f"tcp://{address}"


def _split_host_port(address: str) -> tuple[str, int]:
    addr = address.replace("tcp://", "")
    if ":" not in addr:
        return addr, 22268
    host, port = addr.rsplit(":", 1)
    return host, int(port)


def _is_port_in_use(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(0.5)
        sock.connect((host, port))
        sock.shutdown(2)
        return True
    except Exception:
        return False
    finally:
        sock.close()


@dataclass(slots=True)
class OcrServerSettings:
    worker_count: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "OcrServerSettings":
        if not data:
            return cls()
        return cls(worker_count=int(data.get("worker_count", 0)))


class OcrTaskScheduler:
    def __init__(self, worker_count: int = 0) -> None:
        self.worker_count = max(
            1,
            worker_count or (multiprocessing.cpu_count() or 1),
        )
        self._executor = ThreadPoolExecutor(
            max_workers=self.worker_count,
            thread_name_prefix="ocr_worker",
        )
        self._pending_lock = threading.Lock()
        self._pending = 0

    def submit(self, func, *args, **kwargs):
        with self._pending_lock:
            self._pending += 1
        future = self._executor.submit(func, *args, **kwargs)
        future.add_done_callback(self._on_done)
        return future

    def stats(self) -> dict[str, int]:
        with self._pending_lock:
            pending = self._pending
        return {
            "worker_count": self.worker_count,
            "pending": pending,
        }

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _on_done(self, _future) -> None:
        with self._pending_lock:
            self._pending = max(0, self._pending - 1)


class OcrRuntime:
    def __init__(self, settings: dict[str, Any] | OcrServerSettings | None = None) -> None:
        if isinstance(settings, OcrServerSettings):
            self.settings = settings
        else:
            self.settings = OcrServerSettings.from_dict(settings)
        self._scheduler = OcrTaskScheduler(self.settings.worker_count)
        self._thread_local = threading.local()
        self._lock = threading.Lock()
        self._loaded_workers: set[str] = set()
        self._request_stats = {
            "requests_total": 0,
            "requests_succeeded": 0,
            "requests_failed": 0,
        }
        logger.info(f"OCR runtime initialized (workers={self._scheduler.worker_count})")

    def ping(self) -> bool:
        return True

    def get_server_info(self) -> dict[str, Any]:
        with self._lock:
            request_stats = dict(self._request_stats)
            loaded_worker_count = len(self._loaded_workers)
        return {
            "scheduler": self._scheduler.stats(),
            "request_stats": request_stats,
            "loaded_worker_count": loaded_worker_count,
        }

    def ocr_single_line(
        self,
        image_bytes: bytes,
        save_log: bool = False,
        model_size: str = "medium",
    ):
        image = self._decode_image(image_bytes)
        return self._run_request(
            self._ocr_single_line,
            image,
            save_log=bool(save_log),
            model_size=_normalize_model_size(model_size),
        )

    def detect_and_ocr(
        self,
        image_bytes: bytes,
        drop_score: float = 0.5,
        unclip_ratio: Optional[float] = None,
        box_thresh: Optional[float] = None,
        vertical: bool = False,
        save_log: bool = False,
        model_size: str = "medium",
    ) -> List[Dict[str, Any]]:
        image = self._decode_image(image_bytes)
        return self._run_request(
            self._detect_and_ocr,
            image,
            drop_score=drop_score,
            unclip_ratio=unclip_ratio,
            box_thresh=box_thresh,
            vertical=vertical,
            save_log=bool(save_log),
            model_size=_normalize_model_size(model_size),
        )

    def shutdown(self) -> bool:
        self._scheduler.shutdown()
        return True

    def warmup(self, model_size: str = "medium") -> bool:
        """Load and run inference before reporting the worker ready."""
        model_size = _normalize_model_size(model_size)
        logger.info(f"Warming up OCR worker model: size={model_size}")
        future = self._scheduler.submit(self._warm_model, model_size)
        future.result()
        logger.info(f"OCR worker model warmup completed: size={model_size}")
        return True

    def _warm_model(self, model_size: str):
        model = self._get_model(model_size)
        warmed = getattr(self._thread_local, 'warmed_sizes', set())
        if model_size in warmed:
            return
        # 白底黑字确保同时经过检测和识别；空白图片不会预热识别网络。
        import cv2
        sample = np.full((48, 240, 3), 255, dtype=np.uint8)
        cv2.putText(sample, 'OCR 12345', (8, 34), cv2.FONT_HERSHEY_SIMPLEX,
                    0.9, (0, 0, 0), 2, cv2.LINE_AA)
        started = time.monotonic()
        text, _ = model.ocr_single_line(sample)
        if not text:
            raise ScriptError('OCR inference warmup did not reach text recognition')
        warmed.add(model_size)
        self._thread_local.warmed_sizes = warmed
        logger.info(f'OCR inference warmup completed: size={model_size}, '
                    f'elapsed={time.monotonic() - started:.2f}s')

    def _run_request(self, func, *args, **kwargs):
        with self._lock:
            self._request_stats["requests_total"] += 1
        future = self._scheduler.submit(func, *args, **kwargs)
        try:
            result = future.result()
        except Exception:
            with self._lock:
                self._request_stats["requests_failed"] += 1
            raise
        with self._lock:
            self._request_stats["requests_succeeded"] += 1
        return result

    @staticmethod
    def _decode_image(image_bytes: bytes) -> np.ndarray:
        image = pickle.loads(image_bytes)
        if not isinstance(image, np.ndarray):
            raise TypeError("OCR payload must be numpy.ndarray")
        return image

    @staticmethod
    def _rotate_vertical(image: np.ndarray) -> np.ndarray:
        height, width = image.shape[0:2]
        if width == 0:
            return image
        if height * 1.0 / width >= 1.5:
            return np.rot90(image)
        return image

    def _get_model(self, model_size: str = "medium") -> "TextSystem":
        model_size = _normalize_model_size(model_size)
        models = getattr(self._thread_local, "models", None)
        if models is None:
            models = {}
            self._thread_local.models = models
        model = models.get(model_size)
        if model is None:
            # PaddleOCR is imported only inside the OCR worker process. Script
            # clients keep using the lightweight RPC proxy without importing
            # the full inference framework into every account process.
            from module.ocr.ppocr import TextSystem

            model = TextSystem(model_size=model_size)
            models[model_size] = model
            worker_name = threading.current_thread().name
            with self._lock:
                self._loaded_workers.add(f"{worker_name}:{model_size}")
            logger.info(f"OCR worker model loaded: {worker_name}, size={model_size}")
        return model

    def _ocr_single_line(
        self,
        image: np.ndarray,
        save_log: bool = False,
        model_size: str = "medium",
    ):
        model = self._get_model(model_size)
        OcrLogger.set_enabled(save_log)
        try:
            result, score = model.ocr_single_line(image)
            return result, float(score)
        finally:
            OcrLogger.set_enabled(False)

    def _detect_and_ocr(
        self,
        image: np.ndarray,
        drop_score: float = 0.5,
        unclip_ratio: Optional[float] = None,
        box_thresh: Optional[float] = None,
        vertical: bool = False,
        save_log: bool = False,
        model_size: str = "medium",
    ) -> List[Dict[str, Any]]:
        model = self._get_model(model_size)
        OcrLogger.set_enabled(save_log)
        try:
            if vertical:
                results = self._detect_and_ocr_vertical(
                    model,
                    image,
                    drop_score=drop_score,
                    unclip_ratio=unclip_ratio,
                    box_thresh=box_thresh,
                )
            else:
                results = model.detect_and_ocr(
                    image,
                    drop_score=drop_score,
                    unclip_ratio=unclip_ratio,
                    box_thresh=box_thresh,
                )
        finally:
            OcrLogger.set_enabled(False)
        return [
            {"box": item.box.tolist(), "ocr_text": item.ocr_text, "score": float(item.score)}
            for item in results
        ]

    def _detect_and_ocr_vertical(
        self,
        model,
        image: np.ndarray,
        drop_score: float = 0.5,
        unclip_ratio: Optional[float] = None,
        box_thresh: Optional[float] = None,
    ) -> list[Any]:
        text_recognizer = model.text_recognizer
        base_recognizer = text_recognizer or model.recognize_batch

        def vertical_text_recognizer(img_crop_list):
            img_crop_list = [self._rotate_vertical(item) for item in img_crop_list]
            return base_recognizer(img_crop_list)

        model.text_recognizer = vertical_text_recognizer
        try:
            return model.detect_and_ocr(
                image,
                drop_score=drop_score,
                unclip_ratio=unclip_ratio,
                box_thresh=box_thresh,
            )
        finally:
            model.text_recognizer = text_recognizer


def _build_server_settings() -> dict[str, Any]:
    from module.server.setting import State

    deploy_config = State.deploy_config
    return {
        "worker_count": int(deploy_config.OcrServerWorkerCount),
    }


def ensure_ocr_server_started() -> bool:
    from module.server.setting import State

    deploy_config = State.deploy_config
    if not deploy_config.StartOcrServer:
        return False

    if deploy_config.OcrServerPort:
        port = int(deploy_config.OcrServerPort)
    else:
        _, port = _split_host_port(str(deploy_config.OcrClientAddress))
    host = "0.0.0.0"

    if _is_port_in_use("127.0.0.1", port):
        logger.info(f"OCR server already running on port {port}")
        return True

    global _OCR_SERVER_PROCESS
    if _OCR_SERVER_PROCESS is not None and _OCR_SERVER_PROCESS.is_alive():
        logger.info("OCR server process already started")
        return True

    _OCR_SERVER_PROCESS = multiprocessing.Process(
        target=run_ocr_server,
        args=(host, port, _build_server_settings()),
        name="ocr_server",
        daemon=True,
    )
    _OCR_SERVER_PROCESS.start()
    logger.info(f"Start OCR server on {host}:{port}")
    deadline = time.monotonic() + _OCR_STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _is_port_in_use("127.0.0.1", port):
            return True
        if not _OCR_SERVER_PROCESS.is_alive():
            logger.error(
                "OCR server exited during model warmup, "
                f"exit_code={_OCR_SERVER_PROCESS.exitcode}"
            )
            return False
        time.sleep(0.1)
    logger.error(
        f"OCR server is not ready on port {port} after "
        f"{_OCR_STARTUP_TIMEOUT_SECONDS:.0f}s"
    )
    return False


def ensure_ocr_server_ready() -> bool:
    from module.server.setting import State

    deploy_config = State.deploy_config
    startup_succeeded = True
    if deploy_config.StartOcrServer:
        startup_succeeded = ensure_ocr_server_started()

    address = deploy_config.OcrClientAddress or "127.0.0.1:22268"
    startup_error: Exception | None = None
    try:
        if not startup_succeeded:
            raise ScriptError(f"OCR server startup failed: {address}")
        get_ocr_client(address=address, refresh=True)
        logger.info(f"OCR server ready: {address}")
        return True
    except Exception as exc:
        startup_error = exc

    # 仅在本进程负责OCR服务、启动确实失败且资源检查不通过时修复。
    issues = _bundled_ocr_model_issues()
    if deploy_config.StartOcrServer and issues:
        logger.error(
            "OCR startup failed and bundled model resources are incomplete: "
            f"{issues}"
        )
        shutdown_ocr_server()
        if _repair_bundled_ocr_models():
            logger.info("Restarting OCR service after model resource repair")
            if ensure_ocr_server_started():
                try:
                    get_ocr_client(address=address, refresh=True)
                    logger.info(f"OCR server ready after model repair: {address}")
                    return True
                except Exception as exc:
                    startup_error = exc
            else:
                startup_error = ScriptError(
                    f"OCR server restart failed after model repair: {address}"
                )

    raise ScriptError(f"OCR server connection failed: {address}") from startup_error


def shutdown_ocr_server(timeout: float = 2.0) -> bool:
    global _OCR_SERVER_PROCESS

    process = _OCR_SERVER_PROCESS
    if process is None:
        return False

    if not process.is_alive():
        _OCR_SERVER_PROCESS = None
        return False

    logger.info("Stopping OCR server process")
    try:
        process.terminate()
        process.join(timeout=timeout)
        if process.is_alive():
            logger.warning("OCR server process did not exit in time, force killing")
            process.kill()
            process.join(timeout=1.0)
        logger.info("OCR server process stopped")
        return True
    except Exception as e:
        logger.exception(e)
        return False
    finally:
        _OCR_SERVER_PROCESS = None
        _OCR_CLIENT_CACHE.clear()


def run_ocr_server(host: str, port: int, settings: dict[str, Any] | None = None) -> None:
    _configure_bundled_paddlex_cache()
    # Import onnxruntime BEFORE zerorpc initializes gevent.
    # gevent's monkey-patching interferes with onnxruntime's C extension
    # DLL initialization on Windows, causing ImportError.
    import onnxruntime as _ort  # noqa: F401
    runtime = OcrRuntime(settings=settings)
    server = zerorpc.Server(runtime)
    try:
        runtime.warmup()
        server.bind(f"tcp://{host}:{port}")
        server.run()
    finally:
        runtime.shutdown()


class ModelProxy:
    def __init__(self, address: str) -> None:
        self.address = _normalize_address(address)
        self.save_log = _OCR_LOGGING_ENABLED
        self.model_size = _OCR_MODEL_SIZE
        try:
            self.client = self._create_client(probe=True)
        except Exception as e:
            raise ScriptError(f"OCR server connection failed: {self.address}") from e

    def _create_client(self, *, probe: bool) -> zerorpc.Client:
        client = zerorpc.Client(
            timeout=_ocr_request_timeout(self.model_size)
        )
        try:
            client.connect(self.address)
            if probe:
                client.ping()
            return client
        except Exception:
            try:
                client.close()
            except Exception:
                pass
            raise






    def ping(self) -> bool:
        return bool(self.client.ping())

    def get_server_info(self) -> dict[str, Any]:
        return self.client.get_server_info()

    def warmup(self) -> bool:
        """要求OCR服务预加载当前脚本配置使用的模型。"""
        return bool(self.client.warmup(self.model_size))

    def ocr_single_line(self, image: np.ndarray):
        payload = pickle.dumps(image, protocol=4)
        return self.client.ocr_single_line(payload, self.save_log, self.model_size)

    def detect_and_ocr(
        self,
        image: np.ndarray,
        drop_score: float = 0.5,
        unclip_ratio: Optional[float] = None,
        box_thresh: Optional[float] = None,
        vertical: bool = False,
    ):
        payload = pickle.dumps(image, protocol=4)
        results = self.client.detect_and_ocr(
            payload, drop_score, unclip_ratio, box_thresh, vertical,
            self.save_log, self.model_size,
        )
        return [
            BoxedResult(np.array(item["box"]), None, item["ocr_text"], item["score"])
            for item in results
        ]


def get_ocr_client(address: str | None = None, refresh: bool = False) -> ModelProxy:
    from module.server.setting import State

    resolved_address = address or State.deploy_config.OcrClientAddress or "127.0.0.1:22268"
    if refresh or resolved_address not in _OCR_CLIENT_CACHE:
        _OCR_CLIENT_CACHE[resolved_address] = ModelProxy(resolved_address)
    return _OCR_CLIENT_CACHE[resolved_address]


def set_ocr_logging_enabled(enabled: bool) -> None:
    """设置当前主体后续 OCR 请求是否保存调试日志。"""
    global _OCR_LOGGING_ENABLED
    _OCR_LOGGING_ENABLED = bool(enabled)
    for client in _OCR_CLIENT_CACHE.values():
        client.save_log = _OCR_LOGGING_ENABLED


def _normalize_model_size(model_size: str) -> str:
    normalized = str(model_size).strip().lower()
    if normalized not in ("medium", "small"):
        raise ValueError(f"Unsupported OCR model size: {model_size}")
    return normalized


def _ocr_request_timeout(model_size: str) -> float:
    # 小模型第一次使用时可能需要下载并初始化，给低配设备留出启动时间。
    if _normalize_model_size(model_size) == "small":
        return _OCR_STARTUP_TIMEOUT_SECONDS
    return _OCR_REQUEST_TIMEOUT_SECONDS


def set_ocr_model_size(model_size: str) -> None:
    """设置当前脚本进程后续 OCR 请求使用的模型规格。"""
    global _OCR_MODEL_SIZE
    _OCR_MODEL_SIZE = _normalize_model_size(model_size)
    for client in _OCR_CLIENT_CACHE.values():
        client.model_size = _OCR_MODEL_SIZE
        client.client._timeout = _ocr_request_timeout(
            _OCR_MODEL_SIZE,
        )




atexit.register(shutdown_ocr_server)
