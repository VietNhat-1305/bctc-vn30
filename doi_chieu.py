#!/usr/bin/env python3
"""Tự đối chiếu số đã trích với dữ liệu BCTC công bố trên Vietcap IQ, sau mỗi lần chạy phan_tich.py.

- Mỗi mã 1 BCTC (quý mới nhất): đối chiếu cả số năm nay lẫn cột so sánh trong báo cáo (cùng kỳ năm trước, số đầu năm).
- Kết quả: ket_qua/doi_chieu.json (+ .csv); thẻ trên web hiện "Đối chiếu Vietcap: x/y khớp".
- Chỗ lệch > 1% được ghi vào sổ bài học (tri_thuc/bai_hoc.json, mục can_xem_xet). Xét từng mục: lỗi đọc số -> thêm
  quy tắc / lưu ý mã (python tri_thuc.py them-quy-tac ...), lần trích sau AI được dặn trước; khác phiên bản báo cáo -> đóng.

    python doi_chieu.py                  # đối chiếu toàn bộ ket_qua/json
    python doi_chieu.py --tickers VCB,FPT

Đặc điểm dữ liệu Vietcap (đã kiểm khi đối chiếu tay 16/10/2026):
- Lưu chuyển tiền theo quý là số RIÊNG quý -> cộng các quý từ đầu năm để so với số lũy kế trên BCTC.
- Quý 2 / quý 4 tính từ BCTC bán niên soát xét / năm kiểm toán trừ lũy kế quý trước.
- Ngân hàng: trường cfa34 bị gắn nhãn "Lưu chuyển tiền thuần trong kỳ" nhưng là LCTT tài chính; LCTT thuần là cfa35.
- Trường không có số thường để 0 thay vì trống.
"""
from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

import phan_tich as pt
import tri_thuc

API = "https://iq.vietcap.com.vn/api/iq-insight-service/v1/company/{ma}/financial-statement"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
CACHE = pt.OUT / "vietcap"
SECTIONS = ("INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW")
# trường của mình -> (kiểu, {loại hình: [trường Vietcap cộng lại] | None = không so}); "*" = mặc định
MAP = {
    "doanh_thu_thuan": ("q", {"ngan_hang": ["isb38"], "*": ["isa3"]}),
    "loi_nhuan_gop": ("q", {"ngan_hang": ["isb27"], "chung_khoan": None, "*": ["isa5"]}),
    "lnst": ("q", {"*": ["isa20"]}),
    "lnst_cong_ty_me": ("q", {"*": ["isa22"]}),
    "tong_tai_san": ("bs", {"*": ["bsa53"]}),
    "no_phai_tra": ("bs", {"*": ["bsa54"]}),
    "vay_no": ("bs", {"ngan_hang": None, "*": ["bsa56", "bsa71"]}),
    "von_chu_so_huu": ("bs", {"*": ["bsa78"]}),
    "lctt_hdkd": ("cf", {"*": ["cfa18"]}),
    "lctt_hddt": ("cf", {"*": ["cfa26"]}),
    "lctt_hdtc": ("cf", {"*": ["cfa34"]}),
    "lctt_thuan": ("cf", {"*": ["cfa35"]}),
}
TEN = {"doanh_thu_thuan": "Doanh thu thuần", "loi_nhuan_gop": "Lợi nhuận gộp", "lnst": "LNST",
       "lnst_cong_ty_me": "LNST cổ đông mẹ", "tong_tai_san": "Tổng tài sản", "no_phai_tra": "Nợ phải trả",
       "vay_no": "Nợ vay", "von_chu_so_huu": "Vốn chủ sở hữu", "lctt_hdkd": "LCTT kinh doanh (lũy kế)",
       "lctt_hddt": "LCTT đầu tư (lũy kế)", "lctt_hdtc": "LCTT tài chính (lũy kế)", "lctt_thuan": "LCTT thuần (lũy kế)"}


def fetch(ma: str, client: httpx.Client) -> dict[str, dict[tuple[int, int], dict]]:
    """{section: {(năm, quý): dòng}} - cache 12 giờ trong ket_qua/vietcap/."""
    out = {}
    CACHE.mkdir(parents=True, exist_ok=True)
    for sec in SECTIONS:
        f = CACHE / f"{ma}_{sec}.json"
        if f.exists() and time.time() - f.stat().st_mtime < 12 * 3600:
            data = json.loads(f.read_text(encoding="utf-8"))
        else:
            data = None
            for attempt in range(3):
                try:
                    r = client.get(API.format(ma=ma), params={"section": sec}, timeout=30)
                    r.raise_for_status()
                    data = r.json()["data"]
                    break
                except Exception:  # noqa: BLE001
                    time.sleep(2 ** attempt)
            if data is None:
                return {}
            f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        out[sec] = {(int(x["yearReport"]), int(x["lengthReport"])): x for x in data.get("quarters", [])}
    return out


def source_value(vc: dict, kind: str, cols: list[str], key: tuple[int, int]) -> float | None:
    """Số Vietcap (tỷ đồng) cho quý key. LCTT: cộng các quý từ đầu năm (Vietcap ghi riêng quý)."""
    sec = {"q": "INCOME_STATEMENT", "bs": "BALANCE_SHEET", "cf": "CASH_FLOW"}[kind]
    quarters = [(key[0], q) for q in range(1, key[1] + 1)] if kind == "cf" else [key]
    total = 0.0
    for k in quarters:
        row = vc.get(sec, {}).get(k)
        if row is None or all(row.get(c) is None for c in cols):
            return None
        total += sum(row.get(c) or 0.0 for c in cols)
    return total / 1e9


def classify(mine: float | None, src: float | None) -> tuple[str, float | None]:
    if src is None or (src == 0 and mine is not None and abs(mine) > 1):     # Vietcap để 0 khi không có số
        return "Nguồn không có", None
    if mine is None:
        return "Mình không có", None
    diff = mine - src
    pct = diff / abs(src) * 100 if src else None
    if abs(diff) <= 1 or (pct is not None and abs(pct) <= 0.1):
        return "Khớp", pct
    return ("Lệch nhỏ" if pct is not None and abs(pct) <= 1 else "Lệch"), pct


def run(results: dict | None = None, tickers: list[str] | None = None, log: bool = True) -> dict:
    if results is None:
        import dashboard
        results = dashboard.load_results()
    rows, summary, review = [], {}, []
    with httpx.Client(headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}, follow_redirects=True) as client:
        for tk in sorted(results):
            if tickers and tk not in tickers:
                continue
            if not pt.latest(results[tk]):
                continue
            vc = fetch(tk, client)
            if not vc:
                summary[tk] = {"loi": "Không tải được dữ liệu Vietcap"}
                continue
            key, r = pt.latest(results[tk])
            n = pt.normalize(r)
            v, loai, (y, q) = n["v"], n["loai_hinh"], key
            lk = f"{3 * q}T" if q > 1 else "Q1"
            tk_rows = []
            for fld, (kind, mp) in MAP.items():
                cols = mp[loai] if loai in mp else mp["*"]
                if cols is None:
                    continue
                # năm nay + cột so sánh có sẵn trong cùng BCTC (cùng kỳ năm trước / số đầu năm = cuối năm trước)
                sfx = "_dau_nam" if kind == "bs" else "_cung_ky"
                checks = [(v[fld], (y, q), {"q": f"Q{q}/{y}", "bs": f"cuối Q{q}/{y}", "cf": f"{lk}/{y}"}[kind]),
                          (v.get(fld + sfx), (y - 1, 4) if kind == "bs" else (y - 1, q),
                           {"q": f"Q{q}/{y - 1}", "bs": f"31/12/{y - 1}", "cf": f"{lk}/{y - 1}"}[kind])]
                for mine, k2, ky in checks:
                    if mine is None:
                        continue
                    src = source_value(vc, kind, cols, k2)
                    kl, pct = classify(mine, src)
                    row = {"ma": tk, "ky": ky, "chi_tieu": TEN[fld], "so_minh": mine, "so_nguon": src,
                           "chenh_lech_pct": None if pct is None else round(pct, 2), "ket_luan": kl, "bctc": r["ky"]}
                    tk_rows.append(row)
                    if kl == "Lệch":
                        so_sanh = k2 != (y, q)
                        review.append({**row, "nguon": "Vietcap IQ", "goi_y": (
                            "Cột so sánh: BCTC năm nay có thể đã trình bày lại số năm trước (R7, R13) - xem nhãn trên báo cáo"
                            if so_sanh else
                            "Vietcap lấy quý 2/quý 4 từ bản soát xét/kiểm toán (R1): nếu ảnh trang khớp số mình thì đóng mục này"
                            if q in (2, 4) else "Mở ảnh trang BCTC kiểm tra; lỗi đọc -> thêm quy tắc/lưu ý mã")})
            rows += tk_rows
            cmp_rows = [r for r in tk_rows if r["ket_luan"] in ("Khớp", "Lệch nhỏ", "Lệch")]
            summary[tk] = {"khop": sum(r["ket_luan"] == "Khớp" for r in cmp_rows), "tong": len(cmp_rows),
                           "lech": [{"ky": r["ky"], "chi_tieu": r["chi_tieu"], "pct": r["chenh_lech_pct"], "ket_luan": r["ket_luan"]}
                                    for r in cmp_rows if r["ket_luan"] != "Khớp"]}
    out = {"luc": datetime.now().isoformat(timespec="seconds"), "nguon": "Vietcap IQ (iq.vietcap.com.vn)",
           "ma": summary, "rows": rows}
    pt.OUT.mkdir(parents=True, exist_ok=True)
    (pt.OUT / "doi_chieu.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(pt.OUT / "doi_chieu.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Mã", "Kỳ", "Chỉ tiêu", "Của mình (tỷ đ)", "Vietcap (tỷ đ)", "Chênh %", "Kết luận", "BCTC"])
        w.writerows([[r["ma"], r["ky"], r["chi_tieu"], r["so_minh"], r["so_nguon"], r["chenh_lech_pct"], r["ket_luan"], r["bctc"]]
                     for r in rows])
    new = tri_thuc.them_can_xem_xet(review)
    if log:
        n = [r for r in rows if r["ket_luan"] in ("Khớp", "Lệch nhỏ", "Lệch")]
        print(f"Đối chiếu Vietcap: {sum(r['ket_luan'] == 'Khớp' for r in n)}/{len(n)} khớp, "
              f"{sum(r['ket_luan'] == 'Lệch nhỏ' for r in n)} lệch nhỏ, {sum(r['ket_luan'] == 'Lệch' for r in n)} lệch"
              f" -> {pt.OUT / 'doi_chieu.json'}; {new} mục mới cần xem xét trong sổ bài học (python tri_thuc.py)")
    return out


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    tickers = None
    if "--tickers" in argv:
        tickers = [x.strip().upper() for x in argv[argv.index("--tickers") + 1].split(",") if x.strip()]
    run(tickers=tickers)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
