#!/usr/bin/env python3
"""Sinh tài liệu chấm điểm từ chính bộ tiêu chí trong code (cham_diem.TIEU_CHI, NGUON) và kết quả chấm kỳ mới nhất.

    python tai_lieu_cham_diem.py    # -> docs/cham-diem.html (bộ tiêu chí 4 loại hình) + docs/bao-cao-cham-diem.html (báo cáo)

dang_web.py gọi lại mỗi lần dựng web -> tài liệu luôn khớp cách chấm thật và số liệu kỳ mới nhất.
"""
from __future__ import annotations

import json
import statistics
from datetime import date
from html import escape as esc
from pathlib import Path

import cham_diem as cd
import dashboard

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
DIEM_CU = ROOT / "ket_qua" / "diem_bo_cu_Q2_2026.json"     # điểm theo bộ cũ (2 bộ dùng chung), chụp trước khi đổi
LOAI = ["doanh_nghiep", "ngan_hang", "chung_khoan", "bao_hiem"]
TEN_NGAN = {"doanh_nghiep": "Doanh nghiệp", "ngan_hang": "Ngân hàng", "chung_khoan": "Chứng khoán", "bao_hiem": "Bảo hiểm"}
VI_DU = {"doanh_nghiep": "HPG", "ngan_hang": "VCB", "chung_khoan": "SSI", "bao_hiem": "MIG"}
# Kiểm độc lập kỳ Q2/2026: agent khác chỉ đọc ảnh trang, so với số đã trích (khoản mục riêng)
KIEM_DOC_LAP = {"khop": 62, "tong": 62, "ma": "VPB, STB, MBB, HCM, PGI"}

PHAP_LY = {
    "doanh_nghiep": dict(
        khung="Tín hiệu kiểu Piotroski F-score", nguon=["bctc_dn", "piotroski"],
        che_do="Thông tư 99/2025/TT-BTC (từ 01/01/2026, thay TT 200/2014)",
        mau="B01-DN Báo cáo tình hình tài chính · B02-DN Kết quả kinh doanh · B03-DN Lưu chuyển tiền tệ",
        dac_thu="Doanh thu bán hàng trừ giá vốn ra lợi nhuận gộp, nên biên gộp đo được sức định giá. Nợ vay tách riêng khỏi "
                "nợ phải trả. Dòng tiền kinh doanh cho biết lợi nhuận có ra tiền thật hay không."),
    "ngan_hang": dict(
        khung="CAMELS (cơ quan giám sát Mỹ) + chỉ tiêu lành mạnh tài chính của IMF", nguon=["bctc_nh", "camels", "imf_fsi"],
        che_do="Quyết định 16/2007/QĐ-NHNN, sửa bởi TT 49/2014, TT 22/2017, TT 27/2021",
        mau="B02a/TCTD Bảng cân đối · B03a/TCTD Kết quả hoạt động · B04a/TCTD Lưu chuyển tiền tệ (giữa niên độ)",
        dac_thu="Không có doanh thu và giá vốn: nguồn thu là thu nhập lãi thuần cộng phí dịch vụ. Nợ phải trả chủ yếu là tiền gửi "
                "của khách hàng, tức nguyên liệu kinh doanh, nên nợ gấp khoảng 10 lần vốn là bình thường. Dòng tiền kinh doanh lên "
                "xuống theo huy động và cho vay, không đo chất lượng lợi nhuận. Rủi ro chính: tín dụng, thanh khoản, vốn."),
    "chung_khoan": dict(
        khung="Hiệu quả, chất lượng thu nhập, đòn bẩy so với trần pháp lý", nguon=["bctc_ck", "ck_no_vn", "margin_vn", "iosco"],
        che_do="Thông tư 210/2014/TT-BTC, sửa bởi TT 334/2016/TT-BTC",
        mau="B01-CTCK Báo cáo tình hình tài chính · B02-CTCK Báo cáo kết quả hoạt động · B03b-CTCK Lưu chuyển tiền tệ",
        dac_thu="Doanh thu và chi phí trình bày theo nghiệp vụ: môi giới, cho vay ký quỹ, tự doanh (FVTPL), tư vấn. Lãi tự doanh "
                "theo giá thị trường nên dễ đảo chiều. Nợ chủ yếu là vay để cho vay ký quỹ, có trần pháp lý 5 lần vốn."),
    "bao_hiem": dict(
        khung="CARAMELS (IMF) + tỷ lệ kết hợp (combined ratio)", nguon=["bctc_bh", "caramels", "combined", "bh_vn"],
        che_do="Thông tư 232/2012/TT-BTC; Luật Kinh doanh bảo hiểm 08/2022/QH15 (sửa bởi Luật 139/2025/QH15), NĐ 46/2023/NĐ-CP",
        mau="B01-DNPNT Bảng cân đối · B02-DNPNT Kết quả kinh doanh (phần I tổng hợp, phần II theo hoạt động) · B03-DNPNT",
        dac_thu="Doanh thu là phí bảo hiểm sau nhượng tái; chi phí chính là bồi thường và trích dự phòng nghiệp vụ. Nợ phải trả phần "
                "lớn là dự phòng nghiệp vụ, tức nghĩa vụ với người được bảo hiểm. Lợi nhuận đến từ 2 nguồn: nghiệp vụ bảo hiểm và "
                "đầu tư khoản phí thu trước."),
}

KHOAN_MUC = {   # (dòng trên BCTC, báo cáo, tiêu chí dùng)
    "doanh_nghiep": [("Doanh thu thuần về bán hàng và cung cấp dịch vụ (quý)", "KQKD", "G1, E1"),
                     ("Lợi nhuận gộp (quý)", "KQKD", "E1"),
                     ("Lợi nhuận sau thuế TNDN (quý và lũy kế)", "KQKD", "G2, P1, CF2"),
                     ("Vay và nợ thuê tài chính ngắn hạn + dài hạn", "Tình hình tài chính", "L1"),
                     ("Nợ phải trả; Vốn chủ sở hữu", "Tình hình tài chính", "L1, C1"),
                     ("Lưu chuyển tiền thuần từ hoạt động kinh doanh (lũy kế)", "LCTT", "CF1, CF2")],
    "ngan_hang": [("Tổng thu nhập hoạt động (quý và lũy kế)", "KQKD", "G1, E3"),
                  ("Thu nhập lãi thuần (lũy kế)", "KQKD", "E4"),
                  ("Chi phí hoạt động (lũy kế)", "KQKD", "E3"),
                  ("Chi phí dự phòng rủi ro tín dụng (lũy kế)", "KQKD", "A1"),
                  ("Lợi nhuận sau thuế (quý và lũy kế)", "KQKD", "E1, E2, G2"),
                  ("Cho vay khách hàng: dư nợ gốc, trước dự phòng", "Cân đối", "A1, A2, L1"),
                  ("Dự phòng rủi ro cho vay khách hàng", "Cân đối", "A2"),
                  ("Tiền gửi của khách hàng", "Cân đối", "L1"),
                  ("Tổng tài sản; Vốn chủ sở hữu", "Cân đối", "C1, C2, E1, E2")],
    "chung_khoan": [("Cộng doanh thu hoạt động (quý và lũy kế)", "KQKD", "G1, E2, Q1"),
                    ("Doanh thu nghiệp vụ môi giới chứng khoán (lũy kế)", "KQKD", "Q1"),
                    ("Lãi từ các khoản cho vay và phải thu (lũy kế)", "KQKD", "Q1"),
                    ("Lãi từ tài sản tài chính FVTPL (lũy kế)", "KQKD", "hiển thị"),
                    ("Lợi nhuận sau thuế (quý và lũy kế)", "KQKD", "E1, E2, G2, Q2"),
                    ("Các khoản cho vay (ký quỹ + ứng trước), trước dự phòng", "Tình hình tài chính", "L2"),
                    ("Nợ phải trả; Vốn chủ sở hữu", "Tình hình tài chính", "L1, L2, C1, E1")],
    "bao_hiem": [("Doanh thu thuần hoạt động kinh doanh bảo hiểm (lũy kế)", "KQKD", "U1"),
                 ("Tổng chi phí hoạt động kinh doanh bảo hiểm (lũy kế)", "KQKD", "U1"),
                 ("Chi phí quản lý doanh nghiệp (lũy kế)", "KQKD", "U1"),
                 ("Doanh thu phí bảo hiểm thuần (lũy kế)", "KQKD", "U2, G1"),
                 ("Bồi thường thuộc phần trách nhiệm giữ lại (lũy kế)", "KQKD", "U2"),
                 ("Lợi nhuận hoạt động tài chính (lũy kế)", "KQKD", "A1, A2"),
                 ("Lợi nhuận sau thuế (quý và lũy kế)", "KQKD", "E1, E2, G2"),
                 ("Đầu tư tài chính ngắn hạn + dài hạn", "Cân đối", "A1"),
                 ("Dự phòng nghiệp vụ", "Cân đối", "R1"),
                 ("Tổng tài sản; Vốn chủ sở hữu", "Cân đối", "C1, C2, E1")],
}

CSS = """
:root {
  --bg: #f4f6f5; --surface: #ffffff; --fg: #17201c; --fg-2: #4c5a54; --line: #d9e0dc;
  --accent: #1d5f78; --accent-soft: #e3eef2; --ok: #23774a; --ok-soft: #e2f1e8; --warn: #9a6512; --warn-soft: #f8edd8;
  --bad: #b03a2e; --bad-soft: #f8e3e0; --def: #566573; --def-soft: #e7ebee;
  --sans: "Be Vietnam Pro", "Segoe UI", system-ui, sans-serif; --mono: "IBM Plex Mono", ui-monospace, Consolas, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #101513; --surface: #171e1b; --fg: #e4ebe7; --fg-2: #9fb0a8; --line: #2b3632; --accent: #6fb6d3; --accent-soft: #1a2c34;
  --ok: #6cc893; --ok-soft: #173024; --warn: #e2b05a; --warn-soft: #33291a; --bad: #f08a7c; --bad-soft: #3a1f1c;
  --def: #a9b6c2; --def-soft: #242c33; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #101513; --surface: #171e1b; --fg: #e4ebe7; --fg-2: #9fb0a8; --line: #2b3632; --accent: #6fb6d3; --accent-soft: #1a2c34;
  --ok: #6cc893; --ok-soft: #173024; --warn: #e2b05a; --warn-soft: #33291a; --bad: #f08a7c; --bad-soft: #3a1f1c;
  --def: #a9b6c2; --def-soft: #242c33; color-scheme: dark }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 15px/1.6 var(--sans); }
.wrap { max-width: 1180px; margin: 0 auto; padding-block: 32px 64px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  display: grid; grid-template-columns: minmax(0, 1fr); gap: 44px; }
.wrap > *, section > * { min-width: 0; }
h1, h2, h3 { text-wrap: balance; margin: 0; line-height: 1.25; }
h1 { font-size: clamp(26px, 4vw, 36px); font-weight: 700; letter-spacing: -0.01em; }
h2 { font-size: 22px; font-weight: 700; } h3 { font-size: 16px; font-weight: 600; }
p { margin: 0; max-width: 80ch; }
.eyebrow { font: 500 12px/1 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--accent); }
.head { display: grid; gap: 12px; } .lede { color: var(--fg-2); font-size: 16px; }
.verdict { background: var(--ok-soft); border: 1px solid color-mix(in srgb, var(--ok) 35%, transparent); border-radius: 10px;
  padding: 14px 18px; display: grid; gap: 6px; max-width: 980px; }
.verdict b { color: var(--ok); }
.callout { background: var(--warn-soft); border: 1px solid color-mix(in srgb, var(--warn) 35%, transparent); border-radius: 10px;
  padding: 12px 16px; max-width: 980px; font-size: 14px; }
section { display: grid; gap: 16px; scroll-margin-top: 16px; }
ul, ol { margin: 0; padding-left: 22px; display: grid; gap: 6px; max-width: 90ch; }
.nav { display: flex; flex-wrap: wrap; gap: 8px; }
.nav a { text-decoration: none; border: 1px solid var(--line); background: var(--surface); border-radius: 999px; padding: 5px 12px;
  font-size: 13.5px; color: var(--fg); } .nav a:hover { border-color: var(--accent); }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }
.tile { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; display: grid; gap: 2px; }
.tile .n { font: 600 24px/1.2 var(--mono); font-variant-numeric: tabular-nums; } .tile .l { font-size: 13px; color: var(--fg-2); }
.tile.ok .n { color: var(--ok); } .tile.warn .n { color: var(--warn); }
.tablewrap { overflow-x: auto; background: var(--surface); border: 1px solid var(--line); border-radius: 10px; }
table { border-collapse: collapse; width: 100%; font-size: 13.5px; }
th, td { padding: 8px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
th { font-size: 12px; font-weight: 600; color: var(--fg-2); background: var(--bg); white-space: nowrap; }
tr:last-child td { border-bottom: 0; }
td.num, th.num { text-align: right; font-family: var(--mono); font-variant-numeric: tabular-nums; white-space: nowrap; }
td.ma { font: 600 13px var(--mono); color: var(--accent); white-space: nowrap; }
td.t { font-weight: 600; min-width: 200px; } td.why { color: var(--fg-2); min-width: 240px; max-width: 420px; }
td.f { min-width: 240px; max-width: 360px; } td.g { color: var(--fg-2); white-space: nowrap; }
.grp td { background: var(--accent-soft); font-weight: 600; font-size: 12.5px; color: var(--accent); }
.chip { display: inline-block; font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 999px; white-space: nowrap; }
.chip.ok { color: var(--ok); background: var(--ok-soft); } .chip.warn { color: var(--warn); background: var(--warn-soft); }
.chip.bad { color: var(--bad); background: var(--bad-soft); } .chip.def { color: var(--def); background: var(--def-soft); }
.meta { display: grid; grid-template-columns: 160px 1fr; gap: 6px 16px; font-size: 14px; background: var(--surface);
  border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; }
.meta dt { color: var(--fg-2); } .meta dd { margin: 0; }
.bar { height: 10px; background: var(--line); border-radius: 3px; overflow: hidden; min-width: 90px; }
.bar span { display: block; height: 100%; border-radius: 3px; }
.ref { font-size: 13.5px; } .ref li { max-width: 110ch; } .ref .y { color: var(--fg-2); }
sup a { text-decoration: none; font-size: 11px; }
.note { font-size: 13px; color: var(--fg-2); }
.foot { font-size: 13px; color: var(--fg-2); display: grid; gap: 6px; border-top: 1px solid var(--line); padding-top: 16px; }
.foot p { max-width: none; } code { font: 13px var(--mono); background: var(--accent-soft); padding: 1px 5px; border-radius: 4px; }
a { color: var(--accent); }
@media (max-width: 640px) { .meta { grid-template-columns: 1fr; } .meta dt { font-weight: 600; } }
"""


def page(title: str, desc: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>{CSS}</style>
</head>
<body>
<main class="wrap">
{body}
</main>
</body>
</html>
"""


# ------------------------------------------------------------------ định dạng
def so(x: float, d: int = 1) -> str:
    """Số kiểu Việt: 7.5 -> '7,5'; bỏ ',0' thừa."""
    s = f"{x:.{d}f}".rstrip("0").rstrip(".") if d else f"{x:.0f}"
    return s.replace(".", ",")


def phan_tram(x: float | None, d: int = 1) -> str:
    return "–" if x is None else so(x * 100, d) + "%"


def nguong(x: float, fmt: str | None) -> str:
    return so(x, 1) + "x" if fmt == "x" else phan_tram(x, 2 if abs(x) < 0.02 else 1)


def thang_diem(tc: dict) -> str:
    """Bậc điểm của 1 tiêu chí dưới dạng chữ: '≥ 8%: 1đ · ≥ 6%: 0,5đ'."""
    k, mx, fmt = tc["kieu"], tc["toi_da"], tc.get("fmt")
    ss = {"ge_truoc": "≥", "le_truoc": "≤", "gt_truoc": ">"}
    if k == "tang":
        bac = [f"{'≥ ' + phan_tram(n) if n > 0 else '> 0%'}: {so(p)}đ" for n, p in tc["bac"]]
        return " · ".join(bac + [f"lỗ → lãi: {so(mx)}đ"])
    if k in ("ge", "le", "lt"):
        op = {"ge": "≥", "le": "≤", "lt": "<"}[k]
        return " · ".join(f"{op + ' ' + nguong(n, fmt) if not (k == 'ge' and n == 0) else '> 0'}: {so(p)}đ"
                          for n, p in tc["bac"])
    if k == "gt0":
        return f"> 0: {so(mx)}đ"
    if k == "tien_lai":
        return f"đạt: {so(mx)}đ"
    return f"{ss[k]} kỳ so sánh: {so(mx)}đ"


# ------------------------------------------------------------------ dữ liệu
def du_lieu() -> dict:
    cards = {c["ma"]: c for c in dashboard.build_cards(dashboard.load_results())}
    nhom = {c["ticker"]: c.get("nhom", "vn30") for c in dashboard.all_companies()}
    cu = json.loads(DIEM_CU.read_text(encoding="utf-8")) if DIEM_CU.exists() else {}
    return {"cards": cards, "nhom": nhom, "cu": cu, "ky": next(iter(cards.values()))["ky"] if cards else ""}


def so_nguon(keys_by_order: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for k in keys_by_order:
        out.setdefault(k, len(out) + 1)
    return out


def thu_tu_nguon() -> dict[str, int]:
    keys = []
    for kind in LOAI:
        keys += PHAP_LY[kind]["nguon"]
        for tc in cd.TIEU_CHI[kind]:
            keys += tc["nguon"]
    keys += ["car_vn", "basel3_lev", "vkd_vn", "bknt_bh", "cir_wb", "npl_vn"]
    return so_nguon([k for k in keys if k in cd.NGUON])


def trich(keys: list[str], so_thu_tu: dict[str, int], trang: str = "") -> str:
    return "".join(f'<sup><a href="{trang}#ng-{k}">[{so_thu_tu[k]}]</a></sup>' for k in keys if k in so_thu_tu)


def ds_nguon(so_thu_tu: dict[str, int]) -> str:
    li = []
    for k, n in sorted(so_thu_tu.items(), key=lambda x: x[1]):
        g = cd.NGUON[k]
        li.append(f'<li id="ng-{k}" value="{n}"><b>{esc(g["tac_gia"])} ({g["nam"]}).</b> {esc(g["ten"])}. {esc(g["noi"])}. '
                  f'<a href="{esc(g["url"])}" target="_blank" rel="noopener">{esc(g["url"].split("/")[2])}</a>'
                  f'<br><span class="y">{esc(g["y"])}</span></li>')
    return f'<ol class="ref">{"".join(li)}</ol>'


# ------------------------------------------------------------------ trang 1: bộ tiêu chí
def bang_tieu_chi(kind: str, d: dict, sn: dict) -> str:
    vd = d["cards"].get(VI_DU[kind])
    rows, nhom_truoc = [], None
    for i, tc in enumerate(cd.TIEU_CHI[kind]):
        if tc["nhom"] != nhom_truoc:
            tong = sum(t["toi_da"] for t in cd.TIEU_CHI[kind] if t["nhom"] == tc["nhom"])
            rows.append(f'<tr class="grp"><td colspan="7">{esc(tc["nhom"])} · {so(tong)} điểm</td></tr>')
            nhom_truoc = tc["nhom"]
        ex = ""
        if vd:
            _, p, mx, ct = vd["tieu_chi"][i]
            chip = "ok" if p == mx else "warn" if p > 0 else "bad" if ct != "thiếu dữ liệu" else "def"
            ex = f'{esc(ct)}<br><span class="chip {chip}">{so(p)}/{so(mx)}đ</span>'
        rows.append(f'<tr><td class="ma">{esc(tc["ma"])}</td><td class="t">{esc(tc["ten"])}{trich(tc["nguon"], sn)}</td>'
                    f'<td class="f">{esc(tc["cong_thuc"])}</td><td>{esc(thang_diem(tc))}</td>'
                    f'<td class="num">{so(tc["toi_da"])}</td><td>{ex}</td><td class="why">{esc(tc["ly_do"])}</td></tr>')
    vd_ten = f'Ví dụ {VI_DU[kind]} {esc(vd["ky"])}' if vd else "Ví dụ"
    vd_tong = f'<b>{so(vd["diem"])}/10</b> · {esc(vd["xep_loai"])}' if vd else ""
    return (f'<div class="tablewrap"><table><thead><tr><th>Mã</th><th>Tiêu chí</th><th>Công thức</th><th>Thang điểm</th>'
            f'<th class="num">Tối đa</th><th>{vd_ten}</th><th>Vì sao</th></tr></thead><tbody>{"".join(rows)}'
            f'<tr><td></td><td class="t">Tổng</td><td></td><td></td><td class="num"><b>10</b></td>'
            f'<td>{vd_tong}</td><td></td></tr></tbody></table></div>')


def trang_tieu_chi(d: dict, sn: dict) -> str:
    tom = []
    for kind in LOAI:
        nh: dict[str, float] = {}
        for tc in cd.TIEU_CHI[kind]:
            nh[tc["nhom"]] = nh.get(tc["nhom"], 0) + tc["toi_da"]
        pl = PHAP_LY[kind]
        tom.append(f'<tr><td class="t"><a href="#{kind}">{esc(cd.LOAI_VI[kind])}</a></td><td>{esc(pl["khung"])}{trich(pl["nguon"], sn)}</td>'
                   f'<td>{esc(pl["che_do"])}</td><td>{" · ".join(f"{esc(k)} {so(v)}đ" for k, v in nh.items())}</td>'
                   f'<td class="num">{len(cd.TIEU_CHI[kind])}</td></tr>')
    secs = []
    for kind in LOAI:
        pl = PHAP_LY[kind]
        km = "".join(f'<tr><td>{esc(a)}</td><td class="g">{esc(b)}</td><td class="g">{esc(c)}</td></tr>' for a, b, c in KHOAN_MUC[kind])
        secs.append(f"""<section id="{kind}">
  <h2>{esc(cd.LOAI_VI[kind])}</h2>
  <dl class="meta">
    <dt>Khung tham chiếu</dt><dd>{esc(pl["khung"])}{trich(pl["nguon"], sn)}</dd>
    <dt>Chế độ BCTC</dt><dd>{esc(pl["che_do"])}</dd>
    <dt>Mẫu biểu</dt><dd>{esc(pl["mau"])}</dd>
    <dt>Đặc thù</dt><dd>{esc(pl["dac_thu"])}</dd>
  </dl>
  <h3>Khoản mục lấy từ BCTC</h3>
  <div class="tablewrap"><table><thead><tr><th>Dòng trên BCTC (nhận diện theo tên)</th><th>Báo cáo</th><th>Dùng cho</th></tr></thead>
  <tbody>{km}</tbody></table></div>
  <h3>Tiêu chí và thang điểm</h3>
  {bang_tieu_chi(kind, d, sn)}
</section>""")
    body = f"""<header class="head">
  <div class="eyebrow">Phương pháp chấm điểm · áp dụng từ kỳ {esc(d["ky"])}</div>
  <h1>Bộ tiêu chí chấm điểm BCTC quý cho 4 loại hình doanh nghiệp</h1>
  <p class="lede">BCTC của ngân hàng, công ty chứng khoán, doanh nghiệp bảo hiểm và doanh nghiệp thường (sản xuất, thương mại,
  dịch vụ) khác nhau về mẫu biểu, tên khoản mục và giới hạn an toàn pháp lý. Vì vậy mỗi loại hình có một bộ tiêu chí riêng.
  Bộ nào cũng tối đa 10 điểm và cho phép nửa điểm. Trang này sinh tự động từ chính đoạn code chấm điểm, nên luôn khớp điểm trên web.</p>
  <nav class="nav"><a href="./">← Bảng điểm</a>{"".join(f'<a href="#{k}">{TEN_NGAN[k]}</a>' for k in LOAI)}
  <a href="bao-cao-cham-diem.html">Báo cáo: vì sao chọn bộ tiêu chí này</a><a href="#nguon">Nguồn tham chiếu</a></nav>
</header>

<section>
  <h2>Nguyên tắc chung</h2>
  <ul>
    <li><b>Chỉ cần 1 BCTC quý.</b> Mỗi báo cáo đã có sẵn kỳ so sánh: KQKD có cùng quý năm trước và cột lũy kế, bảng cân đối có số
      đầu năm, lưu chuyển tiền có lũy kế cùng kỳ.</li>
    <li><b>Điểm do công thức tính, AI không tự cho điểm.</b> AI chỉ chép số từ BCTC, sau đó được kiểm cân đối (tài sản = nợ + vốn,
      lưu chuyển tiền thuần = kinh doanh + đầu tư + tài chính). Mỗi tiêu chí là một phép so sánh mà ai cũng kiểm lại được bằng tay.</li>
    <li><b>Quy năm:</b> chỉ số kiểu ROE, ROA, chi phí tín dụng, lợi suất đầu tư lấy số lũy kế × 4 / số quý, chia cho bình quân đầu
      năm và cuối quý.</li>
    <li><b>Thiếu số liệu thì tiêu chí được 0 điểm</b> và thẻ ghi rõ "thiếu dữ liệu", không đoán. Lỗ chuyển sang lãi được tính là
      tăng trưởng tối đa.</li>
    <li><b>Xếp loại:</b> 9–10 Rất tốt · 7–8,5 Tốt · 4–6,5 Trung bình · 0–3,5 Yếu.</li>
    <li><b>Ngưỡng</b> neo vào giới hạn pháp lý Việt Nam nếu có (tỷ lệ dư nợ/tiền gửi 85%, tổng nợ CTCK ≤ 5 lần vốn, dư nợ ký quỹ
      ≤ 200% vốn...), không có thì theo thông lệ quốc tế và mặt bằng doanh nghiệp niêm yết.</li>
    <li>Điểm phản ánh sức khỏe của <b>một quý BCTC</b>, không phải khuyến nghị mua bán.</li>
  </ul>
</section>

<section>
  <h2>Tóm tắt 4 bộ tiêu chí</h2>
  <div class="tablewrap"><table><thead><tr><th>Loại hình</th><th>Khung tham chiếu</th><th>Chế độ BCTC</th><th>Nhóm và điểm tối đa</th>
  <th class="num">Số tiêu chí</th></tr></thead><tbody>{"".join(tom)}</tbody></table></div>
</section>

{"".join(secs)}

<section id="nguon">
  <h2>Nguồn tham chiếu</h2>
  <p class="note">Văn bản pháp luật đã đối chiếu bản gốc, văn bản hợp nhất hoặc bản dịch nguyên văn ngày 28–29/10/2026.</p>
  {ds_nguon(sn)}
</section>

<footer class="foot"><p>Sinh tự động bởi <code>tai_lieu_cham_diem.py</code> từ <code>cham_diem.TIEU_CHI</code> ngày
{date.today().strftime("%d/%m/%Y")}. <a href="./">Bảng điểm</a> · <a href="bao-cao-cham-diem.html">Báo cáo giải thích</a></p></footer>"""
    return page("Bộ tiêu chí chấm điểm", "Bộ tiêu chí chấm điểm BCTC quý trên thang 10 cho doanh nghiệp, ngân hàng, công ty chứng "
                "khoán và bảo hiểm: khoản mục, công thức, ngưỡng, nguồn.", body)


# ------------------------------------------------------------------ trang 2: báo cáo
def thong_ke(xs: list[float]) -> dict:
    return {"n": len(xs), "tb": statistics.mean(xs) if xs else None, "min": min(xs) if xs else None,
            "max": max(xs) if xs else None, "dl": statistics.pstdev(xs) if len(xs) > 1 else None,
            "mười": sum(1 for x in xs if x >= 10), "rat_tot": sum(1 for x in xs if x >= 9)}


def bar(x: float, mau: str) -> str:
    return f'<div class="bar" aria-hidden="true"><span style="width:{x * 10:.0f}%;background:{mau}"></span></div>'


def mau_diem(x: float) -> str:
    return "var(--ok)" if x >= 7 else "var(--warn)" if x >= 4 else "var(--bad)"


def phan_bo(d: dict) -> str:
    """Ngưỡng so với phân bố thực tế của chính nhóm doanh nghiệp đang theo dõi."""
    rows = []
    for kind in ("ngan_hang", "chung_khoan", "bao_hiem"):
        cs = [c for c in d["cards"].values() if c["loai"] == kind]
        for tc in cd.TIEU_CHI[kind]:
            if tc["kieu"] not in ("ge", "le", "lt") or not tc.get("fmt") in ("pct", "x"):
                continue
            xs = sorted(c["m"][tc["chi_so"]] for c in cs if c["m"].get(tc["chi_so"]) is not None)
            if not xs:
                continue
            f = (lambda z: so(z, 2) + "x") if tc["fmt"] == "x" else (lambda z: phan_tram(z))
            full = sum(1 for c in cs if c["m"].get(tc["chi_so"]) is not None and
                       next(p for t, p, mx, _ in [c["tieu_chi"][[x["ma"] for x in cd.TIEU_CHI[kind]].index(tc["ma"])]]) ==
                       tc["toi_da"])
            rows.append(f'<tr><td class="g">{TEN_NGAN[kind]}</td><td class="ma">{esc(tc["ma"])}</td><td>{esc(tc["ten"])}</td>'
                        f'<td>{esc(thang_diem(tc))}</td><td class="num">{len(xs)}</td><td class="num">{f(xs[0])}</td>'
                        f'<td class="num">{f(statistics.median(xs))}</td><td class="num">{f(xs[-1])}</td>'
                        f'<td class="num">{full}/{len(xs)}</td></tr>')
    return (f'<div class="tablewrap"><table><thead><tr><th>Loại hình</th><th>Mã</th><th>Tiêu chí</th><th>Thang điểm</th>'
            f'<th class="num">Số mã</th><th class="num">Thấp nhất</th><th class="num">Trung vị</th><th class="num">Cao nhất</th>'
            f'<th class="num">Đạt tối đa</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def so_sanh_cu_moi(d: dict) -> tuple[str, str, dict]:
    tiles, rows, tk = [], [], {}
    for kind in ("ngan_hang", "chung_khoan", "doanh_nghiep", "bao_hiem"):
        ma = sorted(m for m, c in d["cards"].items() if c["loai"] == kind)
        moi = [d["cards"][m]["diem"] for m in ma]
        cu = [d["cu"][m]["diem"] for m in ma if m in d["cu"]]
        tk[kind] = (thong_ke(cu), thong_ke(moi), ma)
        if kind == "doanh_nghiep":
            continue
        for m in ma:
            c, o = d["cards"][m], d["cu"].get(m)
            mat = [f'{t[0]} ({so(t[1])}/{so(t[2])})' for t in c["tieu_chi"] if t[1] < t[2]][:3]
            rows.append(f'<tr><td class="ma">{m}</td><td class="g">{TEN_NGAN[kind]}</td>'
                        f'<td class="num">{so(o["diem"]) if o else "–"}</td><td>{bar(o["diem"], "var(--def)") if o else ""}</td>'
                        f'<td class="num"><b>{so(c["diem"])}</b></td><td>{bar(c["diem"], mau_diem(c["diem"]))}</td>'
                        f'<td class="why">{esc("; ".join(mat)) or "đạt tất cả"}</td></tr>')
    bang = (f'<div class="tablewrap"><table><thead><tr><th>Mã</th><th>Loại hình</th><th class="num">Bộ cũ</th><th></th>'
            f'<th class="num">Bộ mới</th><th></th><th>Tiêu chí chưa đạt (tối đa 3)</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
    for kind in ("ngan_hang", "chung_khoan"):
        a, b, ma = tk[kind]
        tiles.append(f'<div class="tile"><span class="n">{a["mười"]} → {b["mười"]}</span>'
                     f'<span class="l">{TEN_NGAN[kind].lower()} đạt 10/10 ({len(ma)} mã), bộ cũ → bộ mới</span></div>')
        if a["dl"] is not None and b["dl"] is not None:
            tiles.append(f'<div class="tile"><span class="n">{so(a["dl"], 2)} → {so(b["dl"], 2)}</span>'
                         f'<span class="l">độ lệch chuẩn điểm {TEN_NGAN[kind].lower()}: điểm phân tán hơn = phân biệt tốt hơn</span></div>')
    return "".join(tiles), bang, tk


def nhom_diem(kind: str) -> str:
    nh: dict[str, float] = {}
    for tc in cd.TIEU_CHI[kind]:
        nh[tc["nhom"]] = nh.get(tc["nhom"], 0) + tc["toi_da"]
    return " · ".join(f"{esc(k)} {so(v)}" for k, v in nh.items())


def trang_bao_cao(d: dict, sn: dict) -> str:
    tiles, bang_cu_moi, tk = so_sanh_cu_moi(d)
    nh_cu, nh_moi, nh_ma = tk["ngan_hang"]
    dn_cu, dn_moi, dn_ma = tk["doanh_nghiep"]
    dn_giu = sum(1 for m in dn_ma if m in d["cu"] and d["cu"][m]["diem"] == d["cards"][m]["diem"])
    thieu = sorted(m for m, c in d["cards"].items() if c["loai"] != "doanh_nghiep" and c["thieu"])
    s = lambda keys: trich(keys, sn)       # noqa: E731
    pt = f"""<header class="head">
  <div class="eyebrow">Báo cáo phương pháp · {date.today().strftime("%d/%m/%Y")}</div>
  <h1>Vì sao chấm điểm riêng cho từng loại hình, và vì sao chọn bộ tiêu chí này</h1>
  <p class="lede">Từ kỳ {esc(d["ky"])}, web BCTC VN30 thay 2 bộ tiêu chí dùng chung bằng 4 bộ riêng: doanh nghiệp, ngân hàng,
  công ty chứng khoán, bảo hiểm. Báo cáo này giải thích lý do, căn cứ chọn từng tiêu chí và ngưỡng, kết quả trên dữ liệu thật,
  và những giới hạn còn lại.</p>
  <div class="verdict"><div><b>Kết luận.</b> Mỗi bộ tiêu chí dựng trên khung đánh giá mà cơ quan giám sát và giới nghiên cứu dùng
  cho đúng loại hình đó: tín hiệu Piotroski cho doanh nghiệp{s(["piotroski"])}, CAMELS và chỉ tiêu FSI của IMF cho ngân hàng{s(["camels", "imf_fsi"])},
  giới hạn an toàn của công ty chứng khoán{s(["ck_no_vn", "margin_vn"])}, CARAMELS và tỷ lệ kết hợp cho bảo hiểm{s(["caramels", "combined"])}.
  Ngưỡng neo vào quy định Việt Nam còn hiệu lực năm 2026. Mọi tiêu chí chỉ dùng số có trên BCTC quý, nên tính tự động được và ai cũng
  kiểm lại được. Với 14 ngân hàng, bộ cũ cho {nh_cu["mười"]} mã điểm 10/10; bộ mới cho {nh_moi["mười"]} mã, tách được ngân hàng
  mạnh và yếu theo vốn, chất lượng tài sản, hiệu quả và thanh khoản thay vì chỉ theo tăng trưởng.</div></div>
  <nav class="nav"><a href="./">← Bảng điểm</a><a href="cham-diem.html">Bộ tiêu chí chi tiết</a><a href="#van-de">1. Vấn đề</a>
  <a href="#thiet-ke">2. Thiết kế</a><a href="#vi-sao">3. Vì sao chọn</a><a href="#ket-qua">4. Kết quả</a><a href="#nguong">5. Ngưỡng</a>
  <a href="#gioi-han">6. Giới hạn</a><a href="#nguon">Nguồn</a></nav>
</header>

<section><div class="tiles">{tiles}
  <div class="tile ok"><span class="n">{dn_giu}/{len([m for m in dn_ma if m in d["cu"]])}</span><span class="l">doanh nghiệp giữ nguyên điểm (bộ doanh nghiệp không đổi)</span></div>
  <div class="tile"><span class="n">{len(cd.NGUON)}</span><span class="l">nguồn tham chiếu đã kiểm chứng</span></div>
  <div class="tile ok"><span class="n">{KIEM_DOC_LAP["khop"]}/{KIEM_DOC_LAP["tong"]}</span><span class="l">trường khoản mục riêng khớp ảnh
  trang khi kiểm độc lập ({KIEM_DOC_LAP["ma"]})</span></div>
</div></section>

<section id="van-de">
  <h2>1. Vì sao không dùng chung một bộ tiêu chí</h2>
  <p>Cùng một tên khoản mục nhưng mỗi loại hình hiểu khác nhau. Nếu chấm chung, ngân hàng bị chấm "dòng tiền kinh doanh", trong khi
  chỉ số này chỉ phản ánh tiền gửi vào ra. Doanh nghiệp bảo hiểm thì bị chấm "đòn bẩy", trong khi nợ của họ chủ yếu là dự phòng
  bồi thường cho khách hàng.</p>
  <div class="tablewrap"><table><thead><tr><th></th><th>Doanh nghiệp</th><th>Ngân hàng</th><th>Công ty chứng khoán</th><th>Bảo hiểm phi nhân thọ</th></tr></thead><tbody>
  <tr><td class="t">"Doanh thu"</td><td>Doanh thu thuần bán hàng, dịch vụ</td><td>Không có; thay bằng tổng thu nhập hoạt động (lãi thuần + phí + khác)</td>
    <td>Cộng doanh thu hoạt động: môi giới, cho vay ký quỹ, lãi tự doanh, tư vấn</td><td>Phí bảo hiểm thuần sau nhượng tái + hoa hồng nhượng tái</td></tr>
  <tr><td class="t">"Giá vốn", lợi nhuận gộp</td><td>Giá vốn hàng bán; biên gộp đo sức định giá</td><td>Không có; chi phí lãi → thu nhập lãi thuần</td>
    <td>Cộng chi phí hoạt động, gồm cả lỗ tự doanh và dự phòng</td><td>Bồi thường, hoa hồng, trích dự phòng nghiệp vụ</td></tr>
  <tr><td class="t">Nợ phải trả</td><td>Nợ vay, phải trả người bán; tăng là rủi ro</td><td>Chủ yếu tiền gửi khách hàng (nguyên liệu kinh doanh); nợ/vốn ≈ 10 lần là bình thường</td>
    <td>Vay để cho vay ký quỹ; trần 5 lần vốn{s(["ck_no_vn"])}</td><td>Chủ yếu dự phòng nghiệp vụ (nghĩa vụ với người được bảo hiểm)</td></tr>
  <tr><td class="t">Dòng tiền kinh doanh</td><td>Đo lợi nhuận có ra tiền không</td><td>Lên xuống theo huy động và cho vay; không đo chất lượng lợi nhuận</td>
    <td>Gồm mua bán tài sản tài chính và giải ngân ký quỹ</td><td>Thu phí trước, chi bồi thường sau</td></tr>
  <tr><td class="t">Rủi ro chính</td><td>Cầu, biên lợi nhuận, nợ vay</td><td>Tín dụng (nợ xấu), thanh khoản, vốn</td>
    <td>Thị trường (tự doanh), cho vay ký quỹ</td><td>Nghiệp vụ (bồi thường), đầu tư, dự phòng</td></tr>
  <tr><td class="t">Giới hạn an toàn</td><td>Không có trần chung</td><td>CAR ≥ 8%{s(["car_vn"])}; dư nợ/tiền gửi ≤ 85%{s(["ldr_vn"])}</td>
    <td>Vốn khả dụng ≥ 180%{s(["vkd_vn"])}; nợ ≤ 5 lần vốn; ký quỹ ≤ 200% vốn{s(["margin_vn"])}</td>
    <td>Biên khả năng thanh toán ≥ max(25% phí giữ lại; 12,5% phí gốc + nhận tái){s(["bknt_bh"])}</td></tr>
  </tbody></table></div>
  <p><b>Hậu quả ở bộ cũ.</b> Bộ cũ chấm ngân hàng bằng 8 tiêu chí, trong đó 5/10 điểm là tăng trưởng (thu nhập, LNST, lũy kế, lãi thuần,
  tổng tài sản). Ngân hàng nào tăng trưởng đều thì gần như chắc chắn đạt 9–10, dù vốn mỏng hay dự phòng giảm. Kỳ {esc(d["ky"])},
  {nh_cu["mười"]}/14 ngân hàng đạt 10/10 và {nh_cu["rat_tot"]}/14 đạt từ 9 điểm. Bảo hiểm thì bị chấm bằng bộ doanh nghiệp, tức
  có "giá vốn", "nợ vay" và dòng tiền, là những chỉ số không mang nghĩa đó với bảo hiểm.</p>
</section>

<section id="thiet-ke">
  <h2>2. Thiết kế bộ mới</h2>
  <p>Mỗi loại hình ánh xạ sang khung đánh giá chuẩn của ngành, chỉ giữ những chữ cái của khung đo được bằng số trên BCTC quý.
  Chi tiết công thức, ngưỡng và ví dụ từng tiêu chí ở trang <a href="cham-diem.html">Bộ tiêu chí</a>.</p>
  <div class="tablewrap"><table><thead><tr><th>Loại hình</th><th>Khung gốc</th><th>Nhóm giữ lại (điểm)</th><th>Phần của khung không đo được từ BCTC quý</th></tr></thead><tbody>
  <tr><td class="t">Doanh nghiệp</td><td>Piotroski F-score{s(["piotroski"])}</td>
    <td>{nhom_diem("doanh_nghiep")}</td><td>Phát hành cổ phiếu mới, vòng quay tài sản (cần BCTC năm)</td></tr>
  <tr><td class="t">Ngân hàng</td><td>CAMELS{s(["camels"])}, IMF FSI{s(["imf_fsi"])}</td>
    <td>{nhom_diem("ngan_hang")}</td>
    <td>M Quản trị (định tính); S Nhạy cảm thị trường; CAR, nợ xấu (chỉ ở thuyết minh / báo cáo riêng)</td></tr>
  <tr><td class="t">Chứng khoán</td><td>Giới hạn an toàn CTCK{s(["ck_no_vn", "margin_vn", "vkd_vn"])}, IOSCO{s(["iosco"])}</td>
    <td>{nhom_diem("chung_khoan")}</td><td>Tỷ lệ vốn khả dụng (công bố riêng, không nằm trong BCTC)</td></tr>
  <tr><td class="t">Bảo hiểm</td><td>CARAMELS{s(["caramels"])}, combined ratio{s(["combined"])}</td>
    <td>{nhom_diem("bao_hiem")}</td><td>Biên khả năng thanh toán thực tế (BCTC năm), M Quản trị</td></tr>
  </tbody></table></div>
</section>

<section id="vi-sao">
  <h2>3. Vì sao đây là lựa chọn tốt nhất trong điều kiện hiện có</h2>
  <p>"Tối ưu" ở đây hiểu là tốt nhất khi đồng thời thỏa 6 yêu cầu của web: chấm tự động sau mỗi kỳ BCTC, chỉ dùng BCTC quý
  công khai, kiểm lại được bằng tay, đúng bản chất từng ngành, có căn cứ, và phân biệt được doanh nghiệp tốt với doanh nghiệp yếu.
  Không có bộ điểm nào tối ưu tuyệt đối; dưới đây là 6 lý do bộ này đáp ứng tốt nhất các yêu cầu trên, kèm các phương án khác
  đã cân nhắc.</p>
  <ol>
    <li><b>Đúng bản chất ngành.</b> Mỗi bộ dựng trên khung mà chính cơ quan giám sát dùng để chấm loại hình đó: CAMELS được
      Fed, FDIC dùng xếp hạng ngân hàng từ 1979; IMF dùng FSI và CARAMELS khi đánh giá khu vực tài chính các nước. Không tự đặt khung mới.</li>
    <li><b>Ngưỡng có căn cứ.</b> Ngưỡng bám giới hạn pháp lý Việt Nam còn hiệu lực năm 2026: dư nợ/tiền gửi 85%{s(["ldr_vn"])},
      tổng nợ CTCK 5 lần vốn{s(["ck_no_vn"])}, dư nợ ký quỹ 200% vốn{s(["margin_vn"])}, mục tiêu nợ xấu dưới 3%{s(["npl_vn"])}.
      Tiêu chí mà luật không đặt trần thì theo thông lệ quốc tế (combined ratio dưới 100%{s(["combined"])}, đòn bẩy Basel 3%{s(["basel3_lev"])}),
      rồi đối chiếu với phân bố thực tế ở mục 5.</li>
    <li><b>Chỉ dùng số trên BCTC quý.</b> Mọi chỉ số tính được từ 3 báo cáo chính, không cần dữ liệu giá cổ phiếu hay báo cáo riêng.
      Nhờ đó điểm có ngay khi công ty công bố BCTC, trước cả các trang tổng hợp.</li>
    <li><b>Cân bằng các mặt.</b> Ở 3 bộ ngân hàng, chứng khoán, bảo hiểm, không nhóm nào chiếm quá 35% điểm. Tăng trưởng ở ngân
      hàng giảm từ 5/10 xuống 2/10, phần còn lại chia cho vốn, chất lượng tài sản, hiệu quả, thanh khoản. Mỗi ý chỉ tính một lần,
      tránh chấm trùng.</li>
    <li><b>Phân biệt tốt hơn.</b> Điểm ngân hàng trải rộng hơn (mục 4); thang nửa điểm cho phép phân biệt mức "đạt" và "gần đạt"
      thay vì chỉ có/không.</li>
    <li><b>Minh bạch, tái lập được.</b> Tiêu chí lưu dưới dạng dữ liệu trong code. Cùng một bảng dữ liệu đó vừa dùng để chấm điểm,
      vừa dùng để sinh trang tài liệu, nên hai bên không lệch nhau. Mỗi thẻ trên web ghi rõ điểm từng tiêu chí kèm giá trị thực tế.</li>
  </ol>
  <h3>Các phương án đã cân nhắc và lý do không chọn</h3>
  <div class="tablewrap"><table><thead><tr><th>Phương án</th><th>Ưu điểm</th><th>Lý do không chọn</th></tr></thead><tbody>
  <tr><td class="t">Giữ 1–2 bộ dùng chung</td><td>Đơn giản, so sánh chéo ngành được</td><td>Sai bản chất (mục 1); ngân hàng tăng trưởng nào cũng gần 10 điểm</td></tr>
  <tr><td class="t">Altman Z-score</td><td>Nổi tiếng, dự báo phá sản</td><td>Thiết kế cho doanh nghiệp sản xuất, cần giá trị vốn hóa thị trường; không áp dụng cho ngân hàng, bảo hiểm</td></tr>
  <tr><td class="t">CAMELS / CARAMELS đầy đủ</td><td>Chuẩn giám sát</td><td>Cần CAR, nợ xấu, LCR, biên khả năng thanh toán và đánh giá quản trị; không có trong BCTC quý. Bộ mới giữ phần đo được.</td></tr>
  <tr><td class="t">Xếp hạng tín nhiệm (Moody's, S&amp;P, FiinRatings)</td><td>Toàn diện</td><td>Cần dữ liệu định tính và thông tin không công khai; không cập nhật theo quý cho mọi mã</td></tr>
  <tr><td class="t">Mô hình học máy</td><td>Có thể chính xác hơn</td><td>Cần dữ liệu vỡ nợ, sự kiện xấu có gắn nhãn; VN30 quá ít mẫu; khó giải thích vì sao một mã bị trừ điểm</td></tr>
  <tr><td class="t">Xếp hạng theo phân vị ngành</td><td>Tự hiệu chỉnh theo mặt bằng</td><td>Điểm của một mã phụ thuộc mã khác; mã bảo hiểm và chứng khoán quá ít để tính phân vị. Dùng để kiểm tra ngưỡng ở mục 5.</td></tr>
  </tbody></table></div>
</section>

<section id="ket-qua">
  <h2>4. Kết quả trên dữ liệu {esc(d["ky"])}: bộ cũ so với bộ mới</h2>
  <p>Ngân hàng: điểm trung bình {so(nh_cu["tb"], 1)} → {so(nh_moi["tb"], 1)}; thấp nhất {so(nh_cu["min"])} → {so(nh_moi["min"])};
  cao nhất {so(nh_cu["max"])} → {so(nh_moi["max"])}. Doanh nghiệp thường: bộ tiêu chí giữ nguyên, {dn_giu} mã giữ nguyên điểm.
  Bảo hiểm (MIG, PGI) là 2 mã mẫu, ngoài VN30 (rổ VN30 không có công ty bảo hiểm).</p>
  {bang_cu_moi}
  {f'<p class="callout">Còn thiếu dữ liệu ở: {esc(", ".join(thieu))}. Tiêu chí thiếu số được 0 điểm và ghi rõ trên thẻ.</p>' if thieu else ''}
  <p class="note">Số liệu khoản mục riêng do AI đọc từ ảnh trang BCTC. Mỗi số được kiểm bằng phép cộng ngay trên báo cáo (cho vay − dự
  phòng = dư nợ thuần; các khoản nợ cộng ra tổng nợ phải trả; chuỗi lợi nhuận ra đúng lợi nhuận trước thuế). Sau đó một agent khác
  kiểm độc lập {KIEM_DOC_LAP["tong"]} trường của {KIEM_DOC_LAP["ma"]} chỉ bằng ảnh: {KIEM_DOC_LAP["khop"]}/{KIEM_DOC_LAP["tong"]} khớp.</p>
</section>

<section id="nguong">
  <h2>5. Ngưỡng so với phân bố thực tế</h2>
  <p>Ngưỡng tốt phải để một phần doanh nghiệp đạt, một phần không. Nếu mã nào cũng đạt hoặc không mã nào đạt thì tiêu chí đó không
  phân biệt được gì. Bảng dưới đặt ngưỡng cạnh giá trị thực tế kỳ {esc(d["ky"])} của chính nhóm mã đang theo dõi.</p>
  {phan_bo(d)}
  <p class="note">Mẫu nhỏ (14 ngân hàng, 3 công ty chứng khoán, 2 công ty bảo hiểm) nên đây là kiểm tra hợp lý, chưa phải hiệu chỉnh
  thống kê. Ngưỡng sẽ được rà lại khi có thêm kỳ và thêm mã.</p>
</section>

<section id="gioi-han">
  <h2>6. Giới hạn và hướng cải tiến</h2>
  <ul>
    <li><b>Chưa có CAR và tỷ lệ nợ xấu.</b> Hai chỉ tiêu quan trọng nhất của ngân hàng chỉ có trong thuyết minh hoặc báo cáo riêng
      theo Basel. Bộ mới dùng chỉ số thay thế: VCSH/tổng tài sản cho vốn; chi phí tín dụng và tỷ lệ dự phòng/dư nợ cho chất lượng tài sản.
      Hướng tiếp theo: trích thêm tỷ lệ nợ xấu từ thuyết minh.</li>
    <li><b>LDR tính từ BCTC là xấp xỉ.</b> Công thức pháp lý điều chỉnh cả tử và mẫu số. Từ 01/12/2026, TT 50/2026 đổi cách tính và
      nâng trần lên 95%{s(["ldr_vn"])}; bộ tiêu chí sẽ cập nhật từ kỳ quý 4/2026.</li>
    <li><b>Chưa có tỷ lệ vốn khả dụng</b> của công ty chứng khoán và <b>biên khả năng thanh toán</b> của bảo hiểm: được công bố riêng.
      Dùng nợ/vốn, ký quỹ/vốn và VCSH/tổng tài sản thay thế.</li>
    <li><b>Quy năm từ số lũy kế</b> có thể lệch với ngành có tính mùa vụ (bảo hiểm, chứng khoán). Tiêu chí so cùng kỳ giảm được phần này.</li>
    <li><b>Mẫu nhỏ</b> ở chứng khoán (3 mã) và bảo hiểm (2 mã): ngưỡng theo quy định và thông lệ, chưa hiệu chỉnh thống kê được.</li>
    <li><b>Chưa kiểm định với kết quả sau này</b> (ví dụ giá cổ phiếu, xếp hạng tín nhiệm). Khi có từ 4 quý dữ liệu sẽ kiểm tra
      mã điểm cao có kết quả kinh doanh các quý sau tốt hơn hay không.</li>
    <li>Điểm là sức khỏe của một quý BCTC, không phải định giá hay khuyến nghị đầu tư.</li>
  </ul>
</section>

<section id="nguon">
  <h2>Nguồn tham chiếu</h2>
  <p class="note">Văn bản pháp luật đã đối chiếu bản gốc, văn bản hợp nhất hoặc bản dịch nguyên văn ngày 28–29/10/2026. Mỗi nguồn ghi
  rõ nội dung được dùng.</p>
  {ds_nguon(sn)}
</section>

<footer class="foot"><p>Sinh tự động bởi <code>tai_lieu_cham_diem.py</code> từ bộ tiêu chí trong code và kết quả chấm kỳ {esc(d["ky"])}.
Điểm bộ cũ: <code>ket_qua/diem_bo_cu_Q2_2026.json</code>. <a href="./">Bảng điểm</a> · <a href="cham-diem.html">Bộ tiêu chí</a></p></footer>"""
    return page("Báo cáo chấm điểm", "Vì sao chấm điểm BCTC riêng cho ngân hàng, chứng khoán, bảo hiểm và doanh nghiệp; căn cứ "
                "chọn tiêu chí, kết quả bộ cũ và bộ mới, nguồn tham chiếu.", pt)


def main() -> int:
    d = du_lieu()
    sn = thu_tu_nguon()
    DOCS.mkdir(exist_ok=True)
    (DOCS / "cham-diem.html").write_text(trang_tieu_chi(d, sn), encoding="utf-8")
    (DOCS / "bao-cao-cham-diem.html").write_text(trang_bao_cao(d, sn), encoding="utf-8")
    print("Đã sinh docs/cham-diem.html, docs/bao-cao-cham-diem.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
