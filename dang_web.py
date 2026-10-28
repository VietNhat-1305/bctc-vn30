#!/usr/bin/env python3
"""Dựng lại web (docs/index.html) từ dữ liệu mới nhất rồi đẩy lên GitHub -> GitHub Pages tự cập nhật sau ~1 phút.

    python dang_web.py              # dựng web + commit + push
    python dang_web.py --kiem-tra   # chạy kiem_tra_ir.py trước (cập nhật tab Nguồn dữ liệu, BCTC mới nhất)

Mỗi quý: python phan_tich.py  (tải BCTC + Gemini + chấm điểm)  ->  python dang_web.py
Sửa từ điển: python tu_dien.py  ->  python dang_web.py
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = "https://vietnhat-1305.github.io/bctc-vn30/"


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise SystemExit(f"git {' '.join(args)} lỗi:\n{r.stderr.strip()}")
    return r.stdout.strip()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--kiem-tra" in sys.argv:
        import kiem_tra_ir
        kiem_tra_ir.main([])
    import dashboard
    import tai_lieu_cham_diem
    dashboard.build()
    tai_lieu_cham_diem.main()           # trang bộ tiêu chí + báo cáo chấm điểm, sinh từ cham_diem.TIEU_CHI
    paths = ["docs", "ket_qua/diem_bo_cu_Q2_2026.json", "ket_qua/ir_check.json", "website_30cty.xlsx", "LINKS.md", "tu_dien", "tu_dien_500.xlsx", "ket_qua/json", "ket_qua/doi_chieu.json", "tri_thuc", "ket_qua/lich_su_quet.json"]
    paths = [x for x in paths if (ROOT / x).exists()]
    git("add", *paths)
    if not git("status", "--porcelain", "--", *paths):
        print("Web không có gì mới.")
        return 0
    git("commit", "-m", f"Cập nhật web BCTC VN30 {datetime.now():%d/%m/%Y %H:%M}")
    git("push")
    print(f"Đã đẩy lên GitHub. Web cập nhật sau khoảng 1 phút: {SITE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
