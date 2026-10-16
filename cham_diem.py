"""Chấm điểm sức khỏe BCTC quý theo thang 10 (quý này so với quý trước + cùng kỳ năm trước).

Nguyên tắc:
- Mỗi tiêu chí cho điểm rõ ràng, kiểm chứng lại được từ số liệu (không để AI tự cho điểm).
- 3 bộ tiêu chí theo loại hình, bộ nào cũng tối đa 10 điểm:
    doanh nghiệp / bảo hiểm : tăng trưởng + biên lợi nhuận + DÒNG TIỀN + đòn bẩy
    ngân hàng                : LCTT ngân hàng phản ánh luồng tiền gửi/cho vay, không đo chất lượng lãi -> thay bằng ROE, quy mô
    chứng khoán              : tương tự, LCTT phụ thuộc cho vay margin -> thay bằng ROE, quy mô
- Thiếu số liệu -> tiêu chí đó 0 điểm và ghi "thiếu dữ liệu" (không đoán).
- Ngưỡng tăng trưởng "mạnh" khác nhau theo ngành: ngân hàng tăng 15%/quý đã là rất mạnh.
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


def metrics(cur: dict, prev: dict | None, kind: str) -> dict:
    """Chỉ số dùng để chấm và hiển thị. cur/prev: số liệu tỷ đồng của quý này/quý trước
    (LCTT đã quy về 'trong quý')."""
    p = prev or {}
    m = {
        "dt": cur.get("doanh_thu_thuan"), "dt_truoc": p.get("doanh_thu_thuan"),
        "lng": cur.get("loi_nhuan_gop"), "lng_truoc": p.get("loi_nhuan_gop"),
        "lnst": cur.get("lnst"), "lnst_truoc": p.get("lnst"), "lnst_cung_ky": cur.get("lnst_cung_ky"),
        "ts": cur.get("tong_tai_san"), "ts_truoc": p.get("tong_tai_san"),
        "no": cur.get("no_phai_tra"), "no_truoc": p.get("no_phai_tra"),
        "vcsh": cur.get("von_chu_so_huu"), "vcsh_truoc": p.get("von_chu_so_huu"),
        "cfo": cur.get("lctt_hdkd"), "cfo_truoc": p.get("lctt_hdkd"),
    }
    m["dt_pct"] = pct(m["dt"], m["dt_truoc"])
    m["lng_pct"] = pct(m["lng"], m["lng_truoc"])
    m["lnst_pct"] = pct(m["lnst"], m["lnst_truoc"])
    m["lnst_yoy"] = pct(m["lnst"], m["lnst_cung_ky"])
    m["ts_pct"] = pct(m["ts"], m["ts_truoc"])
    m["no_pct"] = pct(m["no"], m["no_truoc"])
    m["vcsh_pct"] = pct(m["vcsh"], m["vcsh_truoc"])
    m["bien_gop"] = ratio(m["lng"], m["dt"])
    m["bien_gop_truoc"] = ratio(m["lng_truoc"], m["dt_truoc"])
    m["vay"], m["vay_truoc"] = cur.get("vay_no"), p.get("vay_no")
    m["vay_pct"] = pct(m["vay"], m["vay_truoc"])
    # Đòn bẩy: Nợ vay/VCSH nếu có số nợ vay cả 2 quý (doanh nghiệp, chứng khoán), không thì Nợ phải trả/VCSH
    if m["vay"] is not None and m["vay_truoc"] is not None:
        m["don_bay_ten"] = "Nợ vay/VCSH"
        m["no_vcsh"], m["no_vcsh_truoc"] = ratio(m["vay"], m["vcsh"]), ratio(m["vay_truoc"], m["vcsh_truoc"])
    else:
        m["don_bay_ten"] = "Nợ phải trả/VCSH"
        m["no_vcsh"], m["no_vcsh_truoc"] = ratio(m["no"], m["vcsh"]), ratio(m["no_truoc"], m["vcsh_truoc"])
    avg_eq = ((m["vcsh"] or 0) + (m["vcsh_truoc"] or m["vcsh"] or 0)) / 2 if m["vcsh"] else None
    m["roe"] = (m["lnst"] * 4 / avg_eq) if m["lnst"] is not None and avg_eq else None   # ROE quý, quy năm
    return m


def _growth(name, a_pct, prev_val, cur_val, strong, max_pts=2):
    """Tăng > 0 -> 1 điểm; tăng >= ngưỡng mạnh -> 2 điểm. Quý trước lỗ, quý này lãi -> 2 điểm."""
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


def score(m: dict, kind: str) -> dict:
    """-> {"diem": tổng /10, "xep_loai": ..., "tieu_chi": [(tên, điểm, tối đa, chi tiết)]}"""
    items = []
    if kind == "ngan_hang":
        items.append(_growth("Tổng thu nhập hoạt động tăng (≥10%: 2đ)", m["dt_pct"], m["dt_truoc"], m["dt"], 0.10))
        items.append(_growth("LNST tăng so với quý trước (≥15%: 2đ)", m["lnst_pct"], m["lnst_truoc"], m["lnst"], 0.15))
        items.append(_check("LNST tăng ≥15% so với cùng kỳ năm trước",
                            None if m["lnst_yoy"] is None else m["lnst_yoy"] >= 0.15, _fmt_pct(m["lnst_yoy"])))
        items.append(_check("Thu nhập lãi thuần tăng", None if m["lng_pct"] is None else m["lng_pct"] > 0,
                            _fmt_pct(m["lng_pct"])))
        items.append(_check("Tổng tài sản tăng (mở rộng quy mô)", None if m["ts_pct"] is None else m["ts_pct"] > 0,
                            _fmt_pct(m["ts_pct"])))
        items.append(_check("ROE quý (quy năm) ≥ 15%", None if m["roe"] is None else m["roe"] >= 0.15,
                            _fmt_pct(m["roe"], sign=False)))
        items.append(_check("Vốn chủ sở hữu tăng", None if m["vcsh_pct"] is None else m["vcsh_pct"] > 0,
                            _fmt_pct(m["vcsh_pct"])))
        items.append(_check(f"Đòn bẩy ({m['don_bay_ten']}) không tăng", _le(m["no_vcsh"], m["no_vcsh_truoc"]),
                            _fmt_x(m["no_vcsh"], m["no_vcsh_truoc"])))
    elif kind == "chung_khoan":
        items.append(_growth("Doanh thu hoạt động tăng (≥20%: 2đ)", m["dt_pct"], m["dt_truoc"], m["dt"], 0.20))
        items.append(_growth("LNST tăng so với quý trước (≥20%: 2đ)", m["lnst_pct"], m["lnst_truoc"], m["lnst"], 0.20))
        items.append(_check("LNST tăng ≥10% so với cùng kỳ năm trước",
                            None if m["lnst_yoy"] is None else m["lnst_yoy"] >= 0.10, _fmt_pct(m["lnst_yoy"])))
        items.append(_check("Biên lợi nhuận hoạt động cải thiện", _gt(m["bien_gop"], m["bien_gop_truoc"]),
                            _fmt_pp(m["bien_gop"], m["bien_gop_truoc"])))
        items.append(_check("ROE quý (quy năm) ≥ 12%", None if m["roe"] is None else m["roe"] >= 0.12,
                            _fmt_pct(m["roe"], sign=False)))
        items.append(_check("Vốn chủ sở hữu tăng", None if m["vcsh_pct"] is None else m["vcsh_pct"] > 0,
                            _fmt_pct(m["vcsh_pct"])))
        items.append(_check(f"Đòn bẩy ({m['don_bay_ten']}) không tăng", _le(m["no_vcsh"], m["no_vcsh_truoc"]),
                            _fmt_x(m["no_vcsh"], m["no_vcsh_truoc"])))
        items.append(_check("Tổng tài sản tăng", None if m["ts_pct"] is None else m["ts_pct"] > 0,
                            _fmt_pct(m["ts_pct"])))
    else:   # doanh nghiệp, bảo hiểm
        items.append(_growth("Doanh thu thuần tăng (≥20%: 2đ)", m["dt_pct"], m["dt_truoc"], m["dt"], 0.20))
        items.append(_growth("LNST tăng so với quý trước (≥20%: 2đ)", m["lnst_pct"], m["lnst_truoc"], m["lnst"], 0.20))
        items.append(_check("LNST tăng ≥10% so với cùng kỳ năm trước",
                            None if m["lnst_yoy"] is None else m["lnst_yoy"] >= 0.10, _fmt_pct(m["lnst_yoy"])))
        items.append(_check("Biên lợi nhuận gộp cải thiện", _gt(m["bien_gop"], m["bien_gop_truoc"]),
                            _fmt_pp(m["bien_gop"], m["bien_gop_truoc"])))
        items.append(_check("Dòng tiền kinh doanh trong quý dương", None if m["cfo"] is None else m["cfo"] > 0,
                            _fmt_ty(m["cfo"])))
        items.append(_check("Lợi nhuận ra tiền: LCTT kinh doanh ≥ LNST",
                            None if None in (m["cfo"], m["lnst"]) else (m["lnst"] > 0 and m["cfo"] >= m["lnst"]),
                            f"{_fmt_ty(m['cfo'])} vs {_fmt_ty(m['lnst'])}"))
        items.append(_check(f"Đòn bẩy ({m['don_bay_ten']}) không tăng", _le(m["no_vcsh"], m["no_vcsh_truoc"]),
                            _fmt_x(m["no_vcsh"], m["no_vcsh_truoc"])))
        items.append(_check("Vốn chủ sở hữu tăng", None if m["vcsh_pct"] is None else m["vcsh_pct"] > 0,
                            _fmt_pct(m["vcsh_pct"])))
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
    "doanh_nghiep": [("Doanh thu thuần tăng so với quý trước", "tăng: 1đ, tăng ≥20%: 2đ"),
                     ("LNST tăng so với quý trước", "tăng: 1đ, tăng ≥20% hoặc lỗ → lãi: 2đ"),
                     ("LNST tăng ≥10% so với cùng kỳ năm trước", "1đ"),
                     ("Biên lợi nhuận gộp cải thiện", "1đ"),
                     ("Dòng tiền kinh doanh trong quý dương", "1đ"),
                     ("Lợi nhuận ra tiền: LCTT kinh doanh ≥ LNST", "1đ"),
                     ("Đòn bẩy Nợ vay/VCSH không tăng (thiếu nợ vay: Nợ phải trả/VCSH)", "1đ"),
                     ("Vốn chủ sở hữu tăng", "1đ")],
    "ngan_hang": [("Tổng thu nhập hoạt động tăng so với quý trước", "tăng: 1đ, tăng ≥10%: 2đ"),
                  ("LNST tăng so với quý trước", "tăng: 1đ, tăng ≥15% hoặc lỗ → lãi: 2đ"),
                  ("LNST tăng ≥15% so với cùng kỳ năm trước", "1đ"),
                  ("Thu nhập lãi thuần tăng", "1đ"),
                  ("Tổng tài sản tăng", "1đ"),
                  ("ROE quý quy năm ≥15%", "1đ"),
                  ("Vốn chủ sở hữu tăng", "1đ"),
                  ("Đòn bẩy Nợ vay/VCSH không tăng (thiếu nợ vay: Nợ phải trả/VCSH)", "1đ")],
    "chung_khoan": [("Doanh thu hoạt động tăng so với quý trước", "tăng: 1đ, tăng ≥20%: 2đ"),
                    ("LNST tăng so với quý trước", "tăng: 1đ, tăng ≥20% hoặc lỗ → lãi: 2đ"),
                    ("LNST tăng ≥10% so với cùng kỳ năm trước", "1đ"),
                    ("Biên lợi nhuận hoạt động cải thiện", "1đ"),
                    ("ROE quý quy năm ≥12%", "1đ"),
                    ("Vốn chủ sở hữu tăng", "1đ"),
                    ("Đòn bẩy Nợ vay/VCSH không tăng (thiếu nợ vay: Nợ phải trả/VCSH)", "1đ"),
                    ("Tổng tài sản tăng", "1đ")],
}
