from __future__ import annotations

import sys
import shutil
from argparse import ArgumentParser, Namespace
from pathlib import Path
import unittest


REPO = Path(__file__).resolve().parents[1]
CIJOE_VENV_SITEPACKAGES = (
    Path(shutil.which("cijoe")).resolve().parent.parent
    / "lib"
    / f"python{sys.version_info.major}.{sys.version_info.minor}"
    / "site-packages"
)
sys.path.insert(0, str(CIJOE_VENV_SITEPACKAGES))
sys.path.insert(0, str(REPO / "scripts"))

import fio_xnvme_prefill  # noqa: E402
import fio_xnvme_trim  # noqa: E402


class FakeState:
    def __init__(self, text: str = ""):
        self._text = text

    def output(self) -> str:
        return self._text


class FakeCijoe:
    def __init__(self, outputs: list[tuple[int, str]]):
        self.outputs = outputs
        self.commands: list[str] = []

    def run(self, command: str):
        self.commands.append(command)
        if self.outputs:
            err, output = self.outputs.pop(0)
        else:
            err, output = 0, ""
        return err, FakeState(output)


class TestFioCompareRefactor(unittest.TestCase):
    def test_compare_workflows_use_dedicated_trim_and_prefill_actions(self):
        for path in (
            REPO / "tasks" / "bench_fio_compare.yaml",
            REPO / "tasks" / "bench_fio_compare_smoke.yaml",
        ):
            workflow = path.read_text()
            self.assertIn("uses: fio_xnvme_trim", workflow)
            self.assertIn("uses: fio_xnvme_prefill", workflow)
            self.assertNotIn("prefill_only:", workflow)
            self.assertNotIn("xnvme dsm", workflow)

    def test_fio_xnvme_trim_runs_full_namespace_dsm(self):
        cijoe = FakeCijoe(
            outputs=[
                (
                    0,
                    "\n".join(
                        [
                            "xnvme info",
                            "  nsid: 0x1",
                            "  nsect: 0x400",
                        ]
                    ),
                ),
                (0, ""),
            ]
        )

        rc = fio_xnvme_trim.main(
            Namespace(backend="spdk", device="0000:02:00.0"),
            cijoe,
        )

        self.assertEqual(rc, 0)
        self.assertEqual(len(cijoe.commands), 2)
        self.assertEqual(
            cijoe.commands[0],
            "xnvme info --be spdk 0000:02:00.0",
        )
        self.assertEqual(
            cijoe.commands[1],
            "xnvme dsm 0000:02:00.0 --be spdk --dev-nsid 0x1 --nsid 0x1 --ad --slba 0x0 --llb 1023",
        )

    def test_fio_xnvme_trim_fails_when_namespace_metadata_is_missing(self):
        cijoe = FakeCijoe(outputs=[(0, "xnvme info\n  nsid: 0x1\n")])

        rc = fio_xnvme_trim.main(
            Namespace(backend="spdk", device="0000:02:00.0"),
            cijoe,
        )

        self.assertEqual(rc, 1)
        self.assertEqual(len(cijoe.commands), 1)

    def test_fio_xnvme_prefill_runs_fixed_compare_prefill_command(self):
        cijoe = FakeCijoe(outputs=[(0, "")])

        rc = fio_xnvme_prefill.main(
            Namespace(
                backend="upcie",
                device="0000:02:00.0",
                fio_size="2GiB",
            ),
            cijoe,
        )

        self.assertEqual(rc, 0)
        self.assertEqual(
            cijoe.commands,
            [
                "fio --name=prefill --thread=1 --direct=1 --group_reporting=1 "
                "--ioengine=xnvme --xnvme_be=upcie --xnvme_dev_nsid=1 --rw=write "
                "--bs=131072 --iodepth=32 --io_size=2GiB "
                "--filename='0000\\:02\\:00.0' --output-format=json"
            ],
        )

    def test_fio_xnvme_prefill_accepts_fio_size_argument_name_from_workflow(self):
        parser = ArgumentParser()
        fio_xnvme_prefill.add_args(parser)

        args = parser.parse_args(
            [
                "--backend",
                "spdk",
                "--device",
                "0000:02:00.0",
                "--fio_size",
                "1GiB",
            ]
        )

        self.assertEqual(args.backend, "spdk")
        self.assertEqual(args.device, "0000:02:00.0")
        self.assertEqual(args.fio_size, "1GiB")
