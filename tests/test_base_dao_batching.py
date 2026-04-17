from src.foundation.dao.base_dao import BaseDAO


def test_compute_batch_size_respects_config_when_wide_enough_limit() -> None:
    result = BaseDAO._compute_batch_size(configured_batch_size=1000, row_param_count=10)
    assert result == 1000


def test_compute_batch_size_shrinks_for_wide_rows() -> None:
    # 65535-32=65503; 65503//227 = 288
    result = BaseDAO._compute_batch_size(configured_batch_size=1000, row_param_count=227)
    assert result == 288


def test_compute_batch_size_never_exceeds_configured() -> None:
    result = BaseDAO._compute_batch_size(configured_batch_size=200, row_param_count=227)
    assert result == 200


def test_compute_batch_size_never_below_one() -> None:
    result = BaseDAO._compute_batch_size(configured_batch_size=0, row_param_count=999999)
    assert result == 1
