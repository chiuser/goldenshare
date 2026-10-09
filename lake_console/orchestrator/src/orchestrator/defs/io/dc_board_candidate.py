"""DC candidate paths outside the formal lake, with same-device promotion."""

from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4

from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT


def dc_board_staging_root(lake_root: Path) -> Path:
    root = lake_root.resolve()
    if root == Path(DEFAULT_LAKE_ROOT):
        staging = Path(DEFAULT_LAKE_STAGING_ROOT)
        if not staging.is_dir() or staging.resolve() != staging:
            raise ValueError(f"formal DC staging root unavailable: {staging}")
        return staging
    # Isolated helpers/tests may use system temporary roots; arbitrary production roots are forbidden.
    if not any(root.is_relative_to(temp.resolve()) for temp in (Path("/private/tmp"), Path(gettempdir()))):
        raise ValueError("DC writer requires the formal Lake or an isolated system temporary root")
    return root.parent / f"{root.name}_staging"


def assert_dc_board_candidate_can_promote(candidate: Path, target: Path) -> None:
    if candidate.parent.stat().st_dev != target.parent.stat().st_dev:
        raise ValueError("DC candidate and target must be on the same filesystem")


def dc_board_candidate_path(*, lake_root: Path, target: Path) -> Path:
    relative = target.resolve().relative_to(lake_root.resolve())
    if relative.parts[0] not in ("raw", "silver", "gold"):
        raise ValueError("DC candidate target must belong to Raw/Silver/Gold")
    staging = dc_board_staging_root(lake_root)
    candidate = staging / "dc_board" / f"run_id={uuid4().hex}" / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    candidate.parent.mkdir(parents=True, exist_ok=True)
    assert_dc_board_candidate_can_promote(candidate, target)
    return candidate
