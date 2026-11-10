from datetime import date
import pytest
from rackpulse.timewindow import day_window
from rackpulse.config import load_config


def test_day_window():
    window = day_window(date(2026, 11, 9))
    assert len(window.timestamps) == 1440
    assert window.start.isoformat() == '2026-11-08T16:00:00+00:00'
    assert window.end.timestamp() - window.timestamps[-1] == 60


def test_inventory():
    config = load_config('config/racks.example.yaml')
    assert len(config.racks) == 32
    assert config.racks[22].gpu_host_pattern == 'GB200-POD2-E15-.*'
    with pytest.raises(ValueError, match='unconfigured'):
        config.validate_ready()
