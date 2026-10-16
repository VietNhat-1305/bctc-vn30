"""Chấm điểm sức khỏe BCTC quý theo thang 10, chỉ cần 1 BCTC: so sánh với các cột có sẵn trong chính báo cáo.

- Kết quả kinh doanh: quý này so với CÙNG QUÝ NĂM TRƯỚC (VD Q2/2026 vs Q2/2025) và lũy kế từ đầu năm so với cùng kỳ.
- Bảng cân đối: cuối quý so với ĐẦU NĂM (BCTC quý không có số cuối quý năm trước).
- Lưu chuyển tiền: lũy kế từ đầu năm (so với cùng kỳ năm trước).

Nguyên tắc:
- Mỗi tiêu chí cho điểm rõ ràng, kiểm chứng lại được từ số liệu (không để AI tự cho điểm).
- 3 bộ tiêu chí theo loại hình, bộ nào cũng tối đa 10 điểm:
    doanh nghiệp / bảo hiểm : tăng trưởng + biên lợi nhuận + DÒNG TIỀN + đòn bẩy
    ngân hàng                : LCTT ngân hàng phản ánh luồng tiền gửi/cho vay, không đo chất lượng lãi -> thay bằng ROE, quy mô
    chứng khoán              : tương tự, LCTT phụ thuộc cho vay margin -> thay bằng ROE, quy mô
- Thiếu số liệu -> tiêu chí đó 0 điểm và ghi "thiếu dữ liệu" (không đoán).
- Ngưỡng tăng trưởng "mạnh" khác nhau theo ngành: ngân hàng tăng 15%/năm đã là mạnh.
"""
from __future__ import annotations

TIERS = [(9, "Rất tốt"), (7, "Tốt"), (4, "Trung bình"), (0, "Yếu")]


def pct(a, b):
    """% thay đổi a so với b; mẫu âm dùng |b| để dấu luôn đúng chiều (lỗ ít đi = tăng)."""
    if a is None or b is None or b == 0:
        return None
    return (a - b) / abs(b)


def ratio(a, b):
    return a / b if a is not None and b not in (None, 0) else None


def metrics(cur: dict, cmp: dict | None, kind: str, quy: int = 4) -> dict:
    """Chỉ số dùng để chấm và hiển thị (tỷ đồng). cur: số năm nay; cmp: kỳ so sánh trong cùng BCTC
    (KQKD cùng quý năm trước, CĐKT đầu năm, LCTT/lũy kế cùng kỳ năm trước). quy: quý báo cáo (để quy năm ROE)."""
    p = cmp or {}
    m = {
        "dt": cur.get("doanh_thu_thuan"), "dt_truoc": p.get("doanh_thu_thuan"),
        "lng": cur.get("loi_nhuan_gop"), "lng_truoc": p.get("loi_nhuan_gop"),
        "lnst": cur.get("lnst"), "lnst_truoc": p.get("lnst"),
        "lnst_lk": cur.get("lnst_lk"), "lnst_lk_truoc": p.get("lnst_lk"),
        "ts": cur.get("tong_tai_san"), "ts_truoc": p.get("tong_tai_san"),
        "no": cur.get("no_phai_tra"), "no_truoc": p.get("no_phai_tra"),
        "vcsh": cur.get("von_chu_so_huu"), "vcsh_truoc": p.get("von_chu_so_huu"),
        "cfo": cur.get("lctt_hdkd"), "cfo_truoc": p.get("lctt_hdkd"),
    }
    m["dt_pct"] = pct(m["dt"], m["dt_truoc"])
    m["lng_pct"] = pct(m["lng"], m["lng_truoc"])
    m["lnst_pct"] = pct(m["lnst"], m["lnst_truoc"])
    m["lnst_lk_pct"] = pct(m["lnst_lk"], m["lnst_lk_truoc"])
    m["ts_pct"] = pct(m["ts"], m["ts_truoc"])
    m["no_pct"] = pct(m["no"], m["no_truoc"])
    m["vcsh_pct"] = pct(m["vcsh"], m["vcsh_truoc"])
    m["cfo_pct"] = pct(m["cfo"], m["cfo_truoc"])
    m["bien_gop"] = ratio(m["lng"], m["dt"])
    m["bien_gop_truoc"] = ratio(m["lng_truoc"], m["dt_truoc"])
    m["vay"], m["vay_truoc"] = cur.get("vay_no"), p.get("vay_no")
    m["vay_pct"] = pct(m["vay"], m["vay_truoc"])
    # Đòn bẩy: Nợ vay/VCSH nếu có số nợ vay cả cuối quý và đầu năm (doanh nghiệp, chứng khoán), không thì Nợ phải trả/VCSH
    if m["vay"] is not None and m["vay_truoc"] is not None:
        m["don_bay_ten"] = "Nợ vay/VCSH"
        m["no_vcsh"], m["no_vcsh_truoc"] = ratio(m["vay"], m["vcsh"]), ratio(m["vay_truoc"], m["vcsh_truoc"])
    else:
        m["don_bay_ten"] = "Nợ phải trả/VCSH"
        m["no_vcsh"], m["no_vcsh_truoc"] = ratio(m["no"], m["vcsh"]), ratio(m["no_truoc"], m["vcsh_truoc"])
    # ROE quy năm = LNST lũy kế × (4 / số quý) / VCSH bình quân (đầu năm, cuối quý)
    avg_eq = ((m["vcsh"] or 0) + (m["vcsh_truoc"] or m["vcsh"] or 0)) / 2 if m["vcsh"] else None
    lk = m["lnst_lk"] if m["lnst_lk"] is not None else m["lnst"]
    n_q = quy if m["lnst_lk"] is not None else 1
    m["roe"] = (lk * 4 / n_q / avg_eq) if lk is not None and avg_eq else None
    return m


def _growth(name, a_pct, prev_val, cur_val, strong, max_pts=2):
    """Tăng > 0 -> 1 điểm; tăng >= ngưỡng mạnh -> 2 điểm. Năm trước lỗ, năm nay lãi -> 2 điểm."""
    if prev_val is not None and cur_val is not None and prev_val <= 0 < cur_val:
        return (name, max_pts, max_pts, "chuyển từ lỗ sang lãi")
    if a_pct is None:
        return (name, 0, max_pts, "thiếu dữ liệu")
    pts = 2 if a_pct >= strong else 1 if a_pct > 0 else 0
    return (name, min(pts, max_pts), max_pts, f"{a_pct:+.1%}")


def _check(name, ok, detail, pts=1):
    if ok is None:
        return (name, 0, pts, "thiếu dữ liệu")
    return (name, pts if ok else 0, pts, detail)


def _up(x):
    return None if x is None else x > 0


def score(m: dict, kind: str) -> dict:
    """-> {"diem": tổng /10, "xep_loai": ..., "tieu_chi": [(tên, điểm, tối đa, chi tiết)]}"""
    items = []
    lk_check = _check("LNST lũy kế từ đầu năm tăng so với cùng kỳ", _up(m["lnst_lk_pct"]), _fmt_pct(m["lnst_lk_pct"]))
    if kind == "ngan_hang":
        items.append(_growth("Tổng thu nhập hoạt động tăng so với cùng kỳ (≥15%: 2đ)", m["dt_pct"], m["dt_truoc"], m["dt"], 0.15))
        items.append(_growth("LNST quý tăng so với cùng kỳ (≥15%: 2đ)", m["lnst_pct"], m["lnst_truoc"], m["lnst"], 0.15))
        items.append(lk_check)
        items.append(_check("Thu nhập lãi thuần tăng so với cùng kỳ", _up(m["lng_pct"]), _fmt_pct(m["lng_pct"])))
        items.append(_check("Tổng tài sản tăng so với đầu năm", _up(m["ts_pct"]), _fmt_pct(m["ts_pct"])))
        items.append(_check("ROE (quy năm) ≥ 15%", None if m["roe"] is None else m["roe"] >= 0.15,
                            _fmt_pct(m["roe"], sign=False)))
        items.append(_check("Vốn chủ sở hữu tăng so với đầu năm", _up(m["vcsh_pct"]), _fmt_pct(m["vcsh_pct"])))
        items.append(_check(f"Đòn bẩy ({m['don_bay_ten']}) không tăng so với đầu năm", _le(m["no_vcsh"], m["no_vcsh_truoc"]),
                            _fmt_x(m["no_vcsh"], m["no_vcsh_truoc"])))
    elif kind == "chung_khoan":
        items.append(_growth("Doanh thu hoạt động tăng so với cùng kỳ (≥20%: 2đ)", m["dt_pct"], m["dt_truoc"], m["dt"], 0.20))
        items.append(_growth("LNST quý tăng so với cùng kỳ (≥20%: 2đ)", m["lnst_pct"], m["lnst_truoc"], m["lnst"], 0.20))
        items.append(lk_check)
        items.append(_check("Biên lợi nhuận hoạt động cải thiện so với cùng kỳ", _gt(m["bien_gop"], m["bien_gop_truoc"]),
                            _fmt_pp(m["bien_gop"], m["bien_gop_truoc"])))
        items.append(_check("ROE (quy năm) ≥ 12%", None if m["roe"] is None else m["roe"] >= 0.12,
                            _fmt_pct(m["roe"], sign=False)))
        items.append(_check("Vốn chủ sở hữu tăng so với đầu năm", _up(m["vcsh_pct"]), _fmt_pct(m["vcsh_pct"])))
        items.append(_check(f"Đòn bẩy ({m['don_bay_ten']}) không tăng so với đầu năm", _le(m["no_vcsh"], m["no_vcsh_truoc"]),
                            _fmt_x(m["no_vcsh"], m["no_vcsh_truoc"])))
        items.append(_check("Tổng tài sản tăng so với đầu năm", _up(m["ts_pct"]), _fmt_pct(m["ts_pct"])))
    else:   # doanh nghiệp, bảo hiểm
        items.append(_growth("Doanh thu thuần tăng so với cùng kỳ (≥20%: 2đ)", m["dt_pct"], m["dt_truoc"], m["dt"], 0.20))
        items.append(_growth("LNST quý tăng so với cùng kỳ (≥20%: 2đ)", m["lnst_pct"], m["lnst_truoc"], m["lnst"], 0.20))
        items.append(lk_check)
        items.append(_check("Biên lợi nhuận gộp cải thiện so với cùng kỳ", _gt(m["bien_gop"], m["bien_gop_truoc"]),
                            _fmt_pp(m["bien_gop"], m["bien_gop_truoc"])))
        items.append(_check("Dòng tiền kinh doanh lũy kế dương", _up(m["cfo"]), _fmt_ty(m["cfo"])))
        lk = m["lnst_lk"] if m["lnst_lk"] is not None else m["lnst"]
        items.append(_check("Lợi nhuận ra tiền: LCTT kinh doanh lũy kế ≥ LNST lũy kế",
                            None if None in (m["cfo"], lk) else (lk > 0 and m["cfo"] >= lk),
                            f"{_fmt_ty(m['cfo'])} vs {_fmt_ty(lk)}"))
        items.append(_check(f"Đòn bẩy ({m['don_bay_ten']}) không tăng so với đầu năm", _le(m["no_vcsh"], m["no_vcsh_truoc"]),
                            _fmt_x(m["no_vcsh"], m["no_vcsh_truoc"])))
        items.append(_check("Vốn chủ sở hữu tăng so với đầu năm", _up(m["vcsh_pct"]), _fmt_pct(m["vcsh_pct"])))
    total = sum(i[1] for i in items)
    missing = sum(i[2] for i in items if i[3] == "thiếu dữ liệu")
    return {"diem": total, "xep_loai": next(n for t, n in TIERS if total >= t),
            "thieu": missing, "tieu_chi": items}


def _gt(a, b):
    return None if a is None or b is None else a > b


def _le(a, b):
    return None if a is None or b is None else a <= b


def _fmt_pct(x, sign=True):
    return "-" if x is None else (f"{x:+.1%}" if sign else f"{x:.1%}")


def _fmt_pp(a, b):
    return "-" if a is None or b is None else f"{a:.1%} so với {b:.1%}"


def _fmt_x(a, b):
    return "-" if a is None or b is None else f"{a:.2f}x so với {b:.2f}x"


def _fmt_ty(x):
    return "-" if x is None else f"{x:,.0f} tỷ"


CRITERIA_DOC = {   # hiển thị ở dashboard + README
    "doanh_nghiep": [("Doanh thu thuần quý tăng so với cùng quý năm trước", "tăng: 1đ, tăng ≥20%: 2đ"),
                     ("LNST quý tăng so với cùng quý năm trước", "tăng: 1đ, tăng ≥20% hoặc lỗ → lãi: 2đ"),
                     ("LNST lũy kế từ đầu năm tăng so với cùng kỳ", "1đ"),
                     ("Biên lợi nhuận gộp cải thiện so với cùng kỳ", "1đ"),
                     ("Dòng tiền kinh doanh lũy kế dương", "1đ"),
                     ("Lợi nhuận ra tiền: LCTT kinh doanh lũy kế ≥ LNST lũy kế", "1đ"),
                     ("Đòn bẩy Nợ vay/VCSH không tăng so với đầu năm (thiếu nợ vay: Nợ phải trả/VCSH)", "1đ"),
                     ("Vốn chủ sở hữu tăng so với đầu năm", "1đ")],
    "ngan_hang": [("Tổng thu nhập hoạt động quý tăng so với cùng quý năm trước", "tăng: 1đ, tăng ≥15%: 2đ"),
                  ("LNST quý tăng so với cùng quý năm trước", "tăng: 1đ, tăng ≥15% hoặc lỗ → lãi: 2đ"),
                  ("LNST lũy kế từ đầu năm tăng so với cùng kỳ", "1đ"),
                  ("Thu nhập lãi thuần tăng so với cùng kỳ", "1đ"),
                  ("Tổng tài sản tăng so với đầu năm", "1đ"),
                  ("ROE quy năm ≥15%", "1đ"),
                  ("Vốn chủ sở hữu tăng so với đầu năm", "1đ"),
                  ("Đòn bẩy Nợ phải trả/VCSH không tăng so với đầu năm", "1đ")],
    "chung_khoan": [("Doanh thu hoạt động quý tăng so với cùng quý năm trước", "tăng: 1đ, tăng ≥20%: 2đ"),
                    ("LNST quý tăng so với cùng quý năm trước", "tăng: 1đ, tăng ≥20% hoặc lỗ → lãi: 2đ"),
                    ("LNST lũy kế từ đầu năm tăng so với cùng kỳ", "1đ"),
                    ("Biên lợi nhuận hoạt động cải thiện so với cùng kỳ", "1đ"),
                    ("ROE quy năm ≥12%", "1đ"),
                    ("Vốn chủ sở hữu tăng so với đầu năm", "1đ"),
                    ("Đòn bẩy Nợ vay/VCSH không tăng so với đầu năm (thiếu nợ vay: Nợ phải trả/VCSH)", "1đ"),
                    ("Tổng tài sản tăng so với đầu năm", "1đ")],
}
