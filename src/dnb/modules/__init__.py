from dnb.modules.audio_stim import AudioStimulator
from dnb.modules.base import Module, ProcessResult
from dnb.modules.detector import EventDetector
from dnb.modules.downsampler import Downsampler
from dnb.modules.power import PowerEstimator
from dnb.modules.slow_wave import SlowWaveDetector
from dnb.modules.wavelet import WaveletConvolution

__all__ = [
    "AudioStimulator",
    "Downsampler",
    "EventDetector",
    "Module",
    "PowerEstimator",
    "ProcessResult",
    "SlowWaveDetector",
    "WaveletConvolution",
]
