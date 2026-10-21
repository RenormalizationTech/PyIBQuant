"""Build/inspect local artifacts and run an isolated installed-wheel smoke check.

Uses the existing environment's setuptools/pip; no new build dependencies or
network downloads. Generated artifacts default to ignored dist/. Never publishes.
"""

import argparse
import hashlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile
from pathlib import Path


def run(*command, cwd=None):
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path('dist'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    output = args.output_dir.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='pyibquant-build-') as temporary:
        work = Path(temporary)
        source = work / 'source'
        source.mkdir()
        for name in ('pyproject.toml', 'MANIFEST.in', 'LICENSE', 'README.md', 'CHANGELOG.md',
                     'HANDOFF.md', 'PROJECT_PLAN.md', 'TODO.md'):
            shutil.copy2(root / name, source / name)
        for directory in ('src', 'examples', 'tests', 'docs'):
            shutil.copytree(root / directory, source / directory,
                            ignore=shutil.ignore_patterns('__pycache__', '*.egg-info'))
        stage = work / 'artifacts'
        stage.mkdir()
        run(sys.executable, '-c', 'from setuptools.build_meta import build_sdist; '
            f'build_sdist({str(stage)!r})', cwd=source)
        archive = next(stage.glob('*.tar.gz'))
        unpacked = work / 'unpacked'
        unpacked.mkdir()
        with tarfile.open(archive) as package:
            names = package.getnames()
            for required in ('examples/research_studies.py', 'docs/API.md', 'CHANGELOG.md',
                             'tests/wheel_smoke.py', 'tests/live_workflow_check.py',
                             'examples/paper_aapl.json', 'examples/paper_preflight.py',
                             'examples/paper_cancel_check.py', 'examples/paper_option_strategy.py'):
                assert any(name.endswith('/' + required) for name in names), required
            assert not any('/charts/' in name or '/.venv/' in name or '/.git/' in name
                           for name in names)
            # This is the archive just built from the curated source copy above.
            if hasattr(tarfile, 'data_filter'):
                package.extractall(unpacked, filter='data')
            else:
                package.extractall(unpacked)
        archive_root = next(path for path in unpacked.iterdir() if path.is_dir())
        run(sys.executable, '-m', 'pip', 'wheel', '--no-index', '--no-deps',
            '--no-build-isolation', str(archive_root), '-w', str(stage))
        wheel = next(stage.glob('*.whl'))
        with zipfile.ZipFile(wheel) as package:
            names = package.namelist()
            for required in ('pyibquant/simulation.py', 'pyibquant/studies.py',
                             'pyibquant/collection.py', 'pyibquant/py.typed',
                             'pyibquant/visualization/chart.js',
                             'pyibquant/trading/cancel_check.py',
                             'pyibquant/trading/funding.py',
                             'pyibquant/trading/option_runner.py'):
                assert required in names, required
            metadata = package.read(next(name for name in names if name.endswith('/METADATA')))
            requirements = [line for line in metadata.decode().splitlines()
                            if line.startswith('Requires-Dist:')]
            assert all('extra ==' in line for line in requirements), requirements
        environment = work / 'venv'
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / 'bin/python'
        run(str(python), '-m', 'pip', 'install', '--no-index', '--no-deps', str(wheel))
        run(str(python), '-I', str(archive_root / 'tests/wheel_smoke.py'))
        run(str(python), '-I', '-m', 'pyibquant', '--help')
        # Cache inspection intentionally requires the optional Parquet extra.
        cache_check = subprocess.run(
            [str(python), '-I', '-m', 'pyibquant', 'cache', 'inspect',
             '--cache-dir', str(work / 'empty-cache')], capture_output=True, text=True,
        )
        assert cache_check.returncode == 1, cache_check
        assert 'pyibquant[cache]' in cache_check.stderr, cache_check.stderr
        # Copy only successfully validated artifacts to the persistent destination.
        for artifact in (archive, wheel):
            shutil.copy2(artifact, output / artifact.name)
        lines = [f'{hashlib.sha256(artifact.read_bytes()).hexdigest()}  {artifact.name}'
                 for artifact in (archive, wheel)]
        checksums = '\n'.join(lines) + '\n'
        checksum_path = output / f'{archive.name.removesuffix(".tar.gz")}.SHA256SUMS'
        checksum_path.write_text(checksums, encoding='utf-8')
        print(f'PASS: source archive, wheel, isolated SDK-free smoke/CLI; {checksum_path}')


if __name__ == '__main__':
    main()
