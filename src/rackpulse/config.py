from dataclasses import dataclass, field
import re
import yaml


@dataclass
class RackConfig:
    rack_id: str
    gpu_host_pattern: str | None = None
    psu_vendor: str | None = None
    expected_gpu: int = 72
    expected_psu: int = 48


@dataclass
class AppConfig:
    racks: list[RackConfig]
    rules: dict = field(default_factory=lambda: {'low': 10, 'high': 80, 'load_minutes': 60, 'missing_minutes': 10})

    def validate_ready(self):
        if any(not r.gpu_host_pattern or not r.psu_vendor for r in self.racks):
            raise ValueError('unconfigured rack mapping or PSU vendor')

    def rack_for_host(self, host):
        matches = [r for r in self.racks if r.gpu_host_pattern and re.fullmatch(r.gpu_host_pattern, host)]
        if len(matches) > 1:
            raise ValueError('overlapping rack host patterns')
        return matches[0] if matches else None


def load_config(path: str) -> AppConfig:
    with open(path, encoding='utf-8') as handle:
        data = yaml.safe_load(handle)
    racks = [RackConfig(**r) for r in data['racks']]
    if not racks or len({r.rack_id for r in racks}) != len(racks):
        raise ValueError('rack IDs must be nonempty and unique')
    for rack in racks:
        if rack.psu_vendor not in (None, 'liteon', 'delta'):
            raise ValueError('invalid PSU vendor')
        if rack.expected_gpu <= 0 or rack.expected_psu <= 0:
            raise ValueError('expected device counts must be positive')
        if rack.gpu_host_pattern:
            re.compile(rack.gpu_host_pattern)
    return AppConfig(racks, {**AppConfig([]).rules, **data.get('rules', {})})
