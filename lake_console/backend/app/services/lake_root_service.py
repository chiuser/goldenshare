from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from lake_console.backend.app.schemas import DiskUsageInfo, LakePathInfo, LakeRiskItem, LakeStatusResponse


LAKE_LAYOUT_VERSION = 1
REQUIRED_DIRECTORIES = (
    "manifest",
    "manifest/security_universe",
    "raw_tushare",
    "derived",
    "research",
    "_tmp",
)


class LakeRootService:
    def __init__(self, lake_root: Path) -> None:
        self.lake_root = lake_root

    def get_status(self) -> LakeStatusResponse:
        exists = self.lake_root.exists()
        readable = os.access(self.lake_root, os.R_OK) if exists else False
        writable = os.access(self.lake_root, os.W_OK) if exists else False
        initialized = self._is_initialized()
        risks: list[LakeRiskItem] = []
        if not exists:
            risks.append(
                LakeRiskItem(
                    severity="error",
                    code="lake_root_missing",
                    message="Lake 根目录不存在。",
                    path=str(self.lake_root),
                    suggested_action="请先创建移动盘 Lake 根目录，或修正 GOLDENSHARE_LAKE_ROOT。",
                )
            )
        elif not writable:
            risks.append(
                LakeRiskItem(
                    severity="error",
                    code="lake_root_not_writable",
                    message="Lake 根目录不可写。",
                    path=str(self.lake_root),
                    suggested_action="请检查移动盘权限或挂载状态。",
                )
            )
        tmp_dir = self.lake_root / "_tmp"
        if tmp_dir.exists() and any(tmp_dir.iterdir()):
            risks.append(
                LakeRiskItem(
                    severity="warning",
                    code="tmp_residue",
                    message="检测到 _tmp 临时目录残留。",
                    path=str(tmp_dir),
                    suggested_action="确认没有任务运行后再清理临时文件。",
                )
            )
        return LakeStatusResponse(
            path=LakePathInfo(
                lake_root=str(self.lake_root),
                exists=exists,
                readable=readable,
                writable=writable,
                initialized=initialized,
                layout_version=self._layout_version() if initialized else None,
            ),
            disk=self._disk_usage() if exists else None,
            risks=risks,
        )

    def initialize(self) -> None:
        self.lake_root.mkdir(parents=True, exist_ok=True)
        for relative in REQUIRED_DIRECTORIES:
            (self.lake_root / relative).mkdir(parents=True, exist_ok=True)
        lake_file = self.lake_root / "manifest" / "lake.json"
        if not lake_file.exists():
            lake_file.write_text(
                json.dumps(
                    {
                        "lake_name": "goldenshare-tushare-lake",
                        "layout_version": LAKE_LAYOUT_VERSION,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

    def require_ready_for_write(self) -> None:
        status = self.get_status()
        if not status.path.exists:
            raise RuntimeError(f"Lake 根目录不存在：{self.lake_root}")
        if not status.path.writable:
            raise RuntimeError(f"Lake 根目录不可写：{self.lake_root}")
        if not status.path.initialized:
            self.initialize()

    def _is_initialized(self) -> bool:
        return (self.lake_root / "manifest" / "lake.json").exists()

    def _layout_version(self) -> int | None:
        lake_file = self.lake_root / "manifest" / "lake.json"
        if not lake_file.exists():
            return None
        try:
            payload = json.loads(lake_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        value = payload.get("layout_version")
        return int(value) if value is not None else None

    def _disk_usage(self) -> DiskUsageInfo:
        usage = os.statvfs(self.lake_root)
        total = usage.f_blocks * usage.f_frsize
        free = usage.f_bavail * usage.f_frsize
        used = total - free
        percent = round((used / total) * 100, 2) if total else 0.0
        return DiskUsageInfo(
            total_bytes=total,
            used_bytes=used,
            free_bytes=free,
            usage_percent=percent,
        )
