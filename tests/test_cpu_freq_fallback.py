from __future__ import annotations

import shutil
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
CIJOE_VENV_SITEPACKAGES = (
    Path(shutil.which("cijoe")).resolve().parent.parent
    / "lib"
    / f"python{sys.version_info.major}.{sys.version_info.minor}"
    / "site-packages"
)
sys.path.insert(0, str(CIJOE_VENV_SITEPACKAGES))
sys.path.insert(0, str(REPO / "scripts"))

from bench_helper import BenchHelper  # noqa: E402
from cpu_freq_helper import CpuFrequencyHelper  # noqa: E402


class FakeState:
    def __init__(self, text: str = ""):
        self._text = text

    def output(self) -> str:
        return self._text


class FakeCijoe:
    def __init__(self):
        self.commands: list[str] = []

    def run(self, command: str):
        self.commands.append(command)
        if command == "lscpu -e":
            return 0, FakeState("CPU NODE SOCKET CORE L1d:L1i:L2:L3 ONLINE\n0 0 0 0 - - - - yes\n")
        if command.startswith("cat /tmp/cpu_freq_logger.out"):
            return 0, FakeState("")
        if command.startswith("pkill -f cpu_freq_logger"):
            return 0, FakeState("")
        return 0, FakeState("")

    def put(self, *_args, **_kwargs):
        return True

    def getconf(self, key, default=None):
        if key == "devices":
            return [{"pci_addr": "0000:02:00.0"}]
        return default


class StubCpuFrequencyManager:
    def __init__(self):
        self.fixed_freq = 0
        self.governor = "performance"
        self.cpu_control_supported = False

    def set_cpu_freq(self, *_args, **_kwargs):
        return 0

    def start_logging(self):
        return 0

    def stop_logging_and_parse(self):
        return 0, []


class TestCpuFrequencyFallback(unittest.TestCase):
    def test_stop_logging_and_parse_handles_empty_output(self):
        cijoe = FakeCijoe()
        helper = CpuFrequencyHelper(cijoe)

        rc, freqs = helper.stop_logging_and_parse()

        self.assertEqual(rc, 0)
        self.assertEqual(freqs, [])
        self.assertFalse(helper.cpu_control_supported)

    def test_stop_logging_and_parse_handles_unsupported_marker(self):
        cijoe = FakeCijoe()

        def run(command: str):
            cijoe.commands.append(command)
            if command.startswith("cat /tmp/cpu_freq_logger.out"):
                return 0, FakeState("UNSUPPORTED\n")
            if command.startswith("pkill -f cpu_freq_logger"):
                return 0, FakeState("")
            if command == "lscpu -e":
                return 0, FakeState("CPU NODE SOCKET CORE L1d:L1i:L2:L3 ONLINE\n0 0 0 0 - - - - yes\n")
            return 0, FakeState("")

        cijoe.run = run
        helper = CpuFrequencyHelper(cijoe)

        rc, freqs = helper.stop_logging_and_parse()

        self.assertEqual(rc, 0)
        self.assertEqual(freqs, [])
        self.assertFalse(helper.cpu_control_supported)

    def test_bench_helper_keeps_cpu_freqs_empty_when_controls_are_unsupported(self):
        cijoe = FakeCijoe()
        cfm = StubCpuFrequencyManager()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            benchmarker = BenchHelper(
                cijoe=cijoe,
                configs_path=root / "configs",
                results_path=root / "results",
                cfm=cfm,
                tool="fio_xnvme",
                backend="spdk",
                fio_size="2GiB",
            )
            benchmarker.results_path.mkdir(parents=True, exist_ok=True)
            benchmarker.configs_path.mkdir(parents=True, exist_ok=True)

            with patch.object(BenchHelper, "_parse_time_output", return_value=(0, 42.0)), patch.object(
                BenchHelper,
                "_parse_bench_results",
                return_value=(0, {"total": {"iops": 1000.0, "mibs": 200.0}}),
            ):
                rc, result = benchmarker.run_benchmark(
                    rw="read",
                    depth=1,
                    size=4096,
                    ndevs=1,
                    ncpus=1,
                    time=1,
                    cpu_freq="performance",
                )

        self.assertEqual(rc, 0)
        self.assertEqual(result["cpu_freqs"], [])
        self.assertEqual(result["cpu_control_supported"], 0)

