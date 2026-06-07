__all__ = ["TekParser", "TssParser", "load_waveform"]


def __getattr__(name: str):
    if name == "TekParser":
        from .tek_parser import TekParser

        return TekParser
    if name == "TssParser":
        from .tss_parser import TssParser

        return TssParser
    if name == "load_waveform":
        from .waveform_loader import load_waveform

        return load_waveform
    raise AttributeError(name)
