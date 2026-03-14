"""플랫폼별 수집기 자동 감지."""
import platform
from .base import BaseCollector


def get_collector() -> BaseCollector:
    """현재 OS에 맞는 Collector 인스턴스를 반환한다."""
    system = platform.system()
    if system == "Darwin":
        from .darwin import DarwinCollector
        return DarwinCollector()
    elif system == "Linux":
        from .linux import LinuxCollector
        return LinuxCollector()
    else:
        raise NotImplementedError(f"지원하지 않는 플랫폼: {system}")
