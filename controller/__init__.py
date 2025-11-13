"""Controller 패키지"""
from .worker_controller import WorkerController

__all__ = ["WorkerController"]

# 전역 컨트롤러 인스턴스
controller = WorkerController()
