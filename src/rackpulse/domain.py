from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceSample:
    metric: str
    device: str
    timestamp: int
    value: float
