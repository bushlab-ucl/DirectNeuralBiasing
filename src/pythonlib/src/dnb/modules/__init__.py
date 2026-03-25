from dnb.modules.base import Module, ProcessResult
from dnb.modules.detector import EventDetector
from dnb.modules.power import PowerEstimator
from dnb.modules.wavelet import WaveletConvolution

__all__ = [
    "EventDetector",
    "Module",
    "PowerEstimator",
    "ProcessResult",
    "WaveletConvolution",
]
