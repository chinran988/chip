"""Reports API — list and download daily chip reports."""
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.core.config import settings

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


def _report_path(d: date) -> Path:
    return settings.reports_dir / f"{d.strftime('%Y%m%d')}_chip_report.xlsx"


@router.get("")
def list_reports(limit: int = Query(30, le=365)):
    """List available daily reports (newest first)."""
    rdir = settings.reports_dir
    files = sorted(rdir.glob("*_chip_report.xlsx"), reverse=True)[:limit]
    result = []
    for f in files:
        dt_str = f.stem[:8]
        try:
            dt = date(int(dt_str[:4]), int(dt_str[4:6]), int(dt_str[6:8]))
            result.append({
                "date": str(dt),
                "filename": f.name,
                "size_kb": round(f.stat().st_size / 1024, 1),
                "url": f"/api/v1/reports/{dt}",
            })
        except ValueError:
            pass
    return {"count": len(result), "reports": result}


@router.get("/{report_date}")
def download_report(report_date: date):
    """Download Excel report for a given date."""
    fpath = _report_path(report_date)
    if not fpath.exists():
        raise HTTPException(
            404,
            f"Report for {report_date} not found. "
            f"Use POST /api/admin/generate/report to generate it."
        )
    return FileResponse(
        path=str(fpath),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=fpath.name,
    )


@router.get("/{report_date}/summary")
def report_summary(report_date: date):
    """Return JSON metadata about an existing report."""
    fpath = _report_path(report_date)
    if not fpath.exists():
        raise HTTPException(404, f"Report for {report_date} not found.")
    return {
        "date": str(report_date),
        "filename": fpath.name,
        "size_kb": round(fpath.stat().st_size / 1024, 1),
        "sheets": ["總覽", "三大法人", "外資連買", "融資融券", "期貨走勢"],
        "download_url": f"/api/v1/reports/{report_date}",
    }
