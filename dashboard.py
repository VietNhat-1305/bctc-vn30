#!/usr/bin/env python3
"""Giao diện web BCTC VN30 (1 file HTML tự chứa dữ liệu, chạy offline hoặc trên GitHub Pages).

4 tab:
  Bảng điểm     - mỗi công ty 1 thẻ: điểm /10 (khi đã chạy Gemini), chỉ số quý này vs quý trước, BCTC mới nhất
  Thư viện BCTC - tra cứu + tải BCTC 2024 trở đi (link thẳng về web công ty, CafeF chỉ khi web không có)
  Nguồn dữ liệu - 30 web IR: kiểm tra đọc được không, kỳ mới nhất, CafeF đăng chậm bao lâu
  Phương pháp   - luồng thu thập + công thức chấm điểm

    python dashboard.py       # dựng lại docs/index.html + ket_qua/dashboard.html từ dữ liệu đã có (không gọi API)
phan_tich.py tự gọi build() sau mỗi lần chạy; dang_web.py dựng + đẩy lên GitHub Pages.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import cham_diem
import phan_tich

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"                      # GitHub Pages phục vụ thư mục này
REPO_URL = "https://github.com/VietNhat-1305/bctc-vn30"
LOAI_VI = {"doanh_nghiep": "Doanh nghiệp", "ngan_hang": "Ngân hàng", "chung_khoan": "Chứng khoán",
           "bao_hiem": "Bảo hiểm"}
# Loại hình mặc định khi chưa có kết quả Gemini (Gemini tự nhận loại hình khi đọc BCTC)
LOAI_MAC_DINH = {**{t: "ngan_hang" for t in "ACB BID CTG HDB LPB MBB SHB SSB STB TCB VCB VIB VPB".split()},
                 **{t: "chung_khoan" for t in ("SSI", "TCX")}}
KIND = {"doanh_thu_thuan": "q", "loi_nhuan_gop": "q", "lnst": "q", "tong_tai_san": "bs", "no_phai_tra": "bs",
        "vay_no": "bs", "von_chu_so_huu": "bs", "lctt_hdkd": "cf", "lctt_thuan": "cf"}


def load_results() -> dict:
    """Đọc kết quả Gemini đã cache: {mã: {(năm, quý): kết quả}}."""
    out: dict = defaultdict(dict)
    for f in (phan_tich.OUT / "json").glob("*.json"):
        r = json.loads(f.read_text(encoding="utf-8"))
        if r.get("data"):
            y, q = r["ky"][3:], r["ky"][1]
            out[r["ticker"]][(int(y), int(q))] = r
    return out


def _file_urls() -> dict[str, str]:
    """Đường dẫn file trong data/ -> link gốc trên web (để thẻ trên web công khai trỏ về file gốc)."""
    mpath = ROOT / "data" / "manifest.json"
    if not mpath.exists():
        return {}
    out = {}
    for rec in json.loads(mpath.read_text(encoding="utf-8")).values():
        url = rec.get("url_used") or rec.get("url")
        if url and (rec["path"] not in out or rec.get("source", "").startswith("official")):
            out[rec["path"]] = url
    return out


def build_cards(results: dict) -> list[dict]:
    companies = {c["ticker"]: c for c in
                 json.loads((ROOT / "companies.json").read_text(encoding="utf-8"))["companies"]}
    urls = _file_urls()
    cards = []
    for tk in sorted(results):
        norm = {k: phan_tich.normalize(r) for k, r in results[tk].items() if r.get("data")}
        if not norm:
            continue
        cur = max(norm)
        prv = phan_tich.prev_q(cur)
        kind = norm[cur]["loai_hinh"]

        def vals(key):
            if key not in norm:
                return None
            d = {f: phan_tich.value(norm, key, f, k) for f, k in KIND.items()}
            d["lnst_cung_ky"] = norm[key]["v"]["lnst_cung_ky"]
            return d
        m = cham_diem.metrics(vals(cur), vals(prv), kind)
        s = cham_diem.score(m, kind)
        warn = norm[cur]["warn"] + ([f"quý trước: {w}" for w in norm[prv]["warn"]] if prv in norm
                                    else [f"thiếu BCTC Q{prv[1]}/{prv[0]}"])
        co = companies.get(tk, {})
        cards.append({
            "ma": tk, "ten": co.get("name", tk), "loai": kind, "loai_vi": LOAI_VI.get(kind, kind),
            "ky": f"Q{cur[1]}/{cur[0]}", "ky_truoc": f"Q{prv[1]}/{prv[0]}",
            "diem": s["diem"], "xep_loai": s["xep_loai"], "thieu": s["thieu"],
            "tieu_chi": [list(t) for t in s["tieu_chi"]],
            "m": {k: (round(v, 6) if isinstance(v, float) else v) for k, v in m.items()},
            "canh_bao": warn, "file": results[tk][cur].get("file"),
            "file_url": urls.get(results[tk][cur].get("file") or ""), "ir": co.get("bctc_url"),
        })
    return cards


def score_rows(cards: list[dict]) -> tuple[list[str], list[list]]:
    """Bảng chấm điểm cho Excel."""
    head = ["Mã", "Tên công ty", "Loại hình", "Quý này", "Quý trước", "Điểm /10", "Xếp loại",
            "DT % QoQ", "LNST % QoQ", "LNST % cùng kỳ", "Nợ vay % QoQ", "Nợ phải trả % QoQ", "Tổng TS % QoQ",
            "LCTT KD trong quý (tỷ)", "Chi tiết điểm", "Cảnh báo"]
    rows = []
    for c in sorted(cards, key=lambda c: (-c["diem"], c["ma"])):
        m = c["m"]
        detail = "; ".join(f"{t[0]}: {t[1]}/{t[2]} ({t[3]})" for t in c["tieu_chi"])
        rows.append([c["ma"], c["ten"], c["loai_vi"], c["ky"], c["ky_truoc"], c["diem"], c["xep_loai"],
                     m["dt_pct"], m["lnst_pct"], m["lnst_yoy"], m["vay_pct"], m["no_pct"], m["ts_pct"], m["cfo"],
                     detail, "; ".join(c["canh_bao"])])
    return head, rows


def library(since: int) -> list[list]:
    """Thư viện BCTC từ data/index.csv (do bctc.py ghi): [mã, năm, kỳ, phạm vi, kiểm toán, tiêu đề, url, nguồn]."""
    path = ROOT / "data" / "index.csv"
    if not path.exists():
        return []
    rows, seen = [], set()
    order = {"Q1": 1, "Q2": 2, "6T": 3, "Q3": 4, "Q4": 5, "NAM": 6}
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        if not r["year"] or int(r["year"]) < since or r["period"] == "NA" or r["url"] in seen:
            continue
        seen.add(r["url"])
        rows.append([r["ticker"], int(r["year"]), r["period"], r["scope"], r["audit"], r["title"][:140], r["url"],
                     "web" if r["source"].startswith("official") else "cafef"])
    rows.sort(key=lambda x: (x[0], -x[1], -order.get(x[2], 0), x[3]))
    return rows


def build(results: dict | None = None, outs: list[Path] | None = None) -> Path:
    results = results if results is not None else load_results()
    companies = json.loads((ROOT / "companies.json").read_text(encoding="utf-8"))["companies"]
    ir_path = phan_tich.OUT / "ir_check.json"
    ir = json.loads(ir_path.read_text(encoding="utf-8")) if ir_path.exists() else {"cong_ty": [], "kiem_tra_luc": None}
    payload = {
        "cards": build_cards(results),
        "companies": [{"ma": c["ticker"], "ten": c.get("name", ""), "website": c.get("website", ""),
                       "bctc_url": c.get("bctc_url", ""), "loai": LOAI_MAC_DINH.get(c["ticker"], "doanh_nghiep")}
                      for c in companies],
        "ir": ir["cong_ty"], "ir_luc": ir["kiem_tra_luc"],
        "lib": library(date.today().year - 2),
        "tao_luc": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "criteria": cham_diem.CRITERIA_DOC,
        "repo": REPO_URL,
    }
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.replace("__DATA__", data)
    outs = outs or [phan_tich.OUT / "dashboard.html", DOCS / "index.html"]
    for out in outs:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
    (DOCS / ".nojekyll").touch()            # GitHub Pages: phục vụ file nguyên trạng, không qua Jekyll
    return outs[0]


TEMPLATE = r"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BCTC VN30</title>
<meta name="description" content="Báo cáo tài chính 30 mã VN30: lấy trực tiếp từ web công ty, so sánh quý này với quý trước, chấm điểm thang 10.">
<style>
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --surface-2: #f3f2ee;
  --ink: #0b0b0b; --ink-2: #52514e; --muted: #6f6d68;
  --line: #e1e0d9; --ring: rgba(11,11,11,0.10);
  --accent: #2a78d6; --accent-soft: #e3eefc;
  --up: #006300; --down: #b42f2f;
  --tier-1: #0ca30c; --tier-2: #2a78d6; --tier-3: #c98500; --tier-4: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --surface-2: #232321;
    --ink: #f0efec; --ink-2: #c3c2b7; --muted: #98968f;
    --line: #2c2c2a; --ring: rgba(255,255,255,0.10);
    --accent: #3987e5; --accent-soft: #17283d;
    --up: #2fbf2f; --down: #f07070;
    --tier-1: #0ca30c; --tier-2: #3987e5; --tier-3: #eda100; --tier-4: #e66767;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --surface-2: #232321;
  --ink: #f0efec; --ink-2: #c3c2b7; --muted: #98968f;
  --line: #2c2c2a; --ring: rgba(255,255,255,0.10);
  --accent: #3987e5; --accent-soft: #17283d;
  --up: #2fbf2f; --down: #f07070;
  --tier-1: #0ca30c; --tier-2: #3987e5; --tier-3: #eda100; --tier-4: #e66767;
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
body { margin: 0; background: var(--page); color: var(--ink);
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.wrap { max-width: 1320px; margin: 0 auto; padding: 18px 16px 48px; }
header { display: flex; gap: 12px; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; }
h1 { font-size: 22px; margin: 0 0 4px; font-weight: 700; }
h2 { font-size: 17px; margin: 22px 0 8px; }
.sub { color: var(--ink-2); margin: 0; }
.btn { font: inherit; color: var(--ink); background: var(--surface); border: 1px solid var(--ring);
  border-radius: 8px; padding: 6px 12px; cursor: pointer; }
.btn:hover { background: var(--surface-2); }
.btn[aria-pressed="true"] { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
nav.tabs { display: flex; gap: 4px; margin: 16px 0 4px; border-bottom: 1px solid var(--line); overflow-x: auto; }
nav.tabs a { padding: 9px 14px; color: var(--ink-2); border-bottom: 2px solid transparent; white-space: nowrap;
  font-weight: 550; text-decoration: none; }
nav.tabs a[aria-current="page"] { color: var(--ink); border-bottom-color: var(--accent); }
.notice { background: var(--accent-soft); border: 1px solid var(--ring); border-radius: 10px; padding: 10px 14px;
  margin: 14px 0; color: var(--ink); }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin: 16px 0; }
.kpi { background: var(--surface); border: 1px solid var(--ring); border-radius: 12px; padding: 12px 14px; }
.kpi .label { color: var(--ink-2); font-size: 13px; }
.kpi .value { font-size: 26px; font-weight: 650; margin-top: 2px; }
.kpi .note { color: var(--muted); font-size: 12px; }
.filters { position: sticky; top: 0; z-index: 5; background: var(--page); padding: 10px 0;
  display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: end; border-bottom: 1px solid var(--line); }
.f { display: flex; flex-direction: column; gap: 3px; font-size: 12px; color: var(--ink-2); }
.f input, .f select { font: inherit; font-size: 14px; color: var(--ink); background: var(--surface);
  border: 1px solid var(--ring); border-radius: 8px; padding: 5px 8px; }
.f input[type=number] { width: 84px; }
.f input[type=search] { width: 190px; }
.f.check { flex-direction: row; align-items: center; gap: 6px; font-size: 14px; color: var(--ink); padding-bottom: 6px; }

.presets { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0 4px; align-items: center; }
.chip { font: inherit; font-size: 13px; color: var(--ink); background: var(--surface); border: 1px solid var(--ring);
  border-radius: 999px; padding: 4px 11px; cursor: pointer; }
.chip:hover { background: var(--surface-2); }
.count { color: var(--ink-2); margin: 10px 0; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(310px, 1fr)); gap: 12px; }
.card { background: var(--surface); border: 1px solid var(--ring); border-radius: 14px; padding: 14px;
  display: flex; flex-direction: column; gap: 10px; }
.card-top { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }
.tk { font-size: 20px; font-weight: 700; letter-spacing: .3px; }
.name { color: var(--ink-2); font-size: 12.5px; line-height: 1.3; }
.tag { display: inline-block; font-size: 11.5px; color: var(--ink-2); background: var(--surface-2);
  border-radius: 6px; padding: 1px 7px; margin-top: 4px; }
.score { text-align: right; min-width: 74px; }
.score .big { font-size: 28px; font-weight: 700; line-height: 1; }
.score .big small { font-size: 14px; color: var(--muted); font-weight: 500; }
.score .none { font-size: 12px; color: var(--muted); max-width: 110px; }
.tier { font-size: 12px; font-weight: 600; margin-top: 3px; white-space: nowrap; }
.meter { height: 6px; background: var(--surface-2); border-radius: 4px; overflow: hidden; }
.meter > i { display: block; height: 100%; border-radius: 4px; }
.rows { display: grid; grid-template-columns: 1fr auto auto; gap: 3px 10px; font-size: 13px; align-items: baseline; }
.rows .k { color: var(--ink-2); }
.rows .v { text-align: right; font-variant-numeric: tabular-nums; }
.rows .d { text-align: right; font-variant-numeric: tabular-nums; min-width: 66px; font-weight: 600; }
.up { color: var(--up); } .down { color: var(--down); } .flat { color: var(--muted); font-weight: 400 !important; }
.latest { font-size: 12.5px; background: var(--surface-2); border-radius: 8px; padding: 8px 10px; display: grid; gap: 2px; }
.latest b { font-weight: 600; }
details { font-size: 12.5px; }
summary { cursor: pointer; color: var(--accent); }
.crit { list-style: none; padding: 0; margin: 6px 0 0; display: grid; gap: 3px; }
.crit li { display: grid; grid-template-columns: 18px 1fr auto; gap: 6px; align-items: baseline; }
.crit .pt { font-variant-numeric: tabular-nums; color: var(--ink-2); }
.crit .dt { grid-column: 2 / 4; color: var(--muted); font-size: 11.5px; margin-top: -2px; }
.warn { font-size: 12px; color: var(--ink-2); border-left: 3px solid var(--tier-3); padding: 2px 8px; }
.foot { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; color: var(--muted); flex-wrap: wrap; }
.tablewrap { overflow-x: auto; border: 1px solid var(--ring); border-radius: 12px; background: var(--surface); }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 7px 9px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
th { color: var(--ink-2); font-weight: 600; background: var(--surface-2); position: sticky; top: 0; white-space: nowrap; }
td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
tr:last-child td { border-bottom: 0; }
.badge { display: inline-block; font-size: 12px; font-weight: 600; border-radius: 6px; padding: 1px 7px; white-space: nowrap; }
.badge.ok { color: var(--up); background: color-mix(in srgb, var(--tier-1) 14%, transparent); }
.badge.bad { color: var(--down); background: color-mix(in srgb, var(--tier-4) 14%, transparent); }
.badge.src { color: var(--ink-2); background: var(--surface-2); font-weight: 500; }
.empty { padding: 40px; text-align: center; color: var(--ink-2); background: var(--surface);
  border: 1px dashed var(--line); border-radius: 12px; }
.methods { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }
.methods td:last-child { text-align: right; white-space: nowrap; }
ol.flow { padding-left: 20px; display: grid; gap: 6px; }
.more { margin: 12px auto; display: block; }
footer { margin-top: 36px; color: var(--muted); font-size: 12.5px; border-top: 1px solid var(--line); padding-top: 12px; }
@media (max-width: 560px) { .f input[type=search] { width: 100%; } .f { flex: 1 1 140px; } h1 { font-size: 19px; } }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>BCTC VN30</h1>
      <p class="sub" id="sub"></p>
    </div>
    <button class="btn" id="themeBtn" title="Đổi giao diện sáng/tối">Sáng/Tối</button>
  </header>
  <nav class="tabs" aria-label="Mục">
    <a href="#bang-diem" data-tab="bang-diem">Bảng điểm</a>
    <a href="#thu-vien" data-tab="thu-vien">Thư viện BCTC</a>
    <a href="#nguon" data-tab="nguon">Nguồn dữ liệu</a>
    <a href="#phuong-phap" data-tab="phuong-phap">Phương pháp</a>
  </nav>

  <!-- ============ BẢNG ĐIỂM ============ -->
  <section id="tab-bang-diem" hidden>
    <div id="noScore" class="notice" hidden>
      Chưa có điểm cho kỳ này: bước phân tích bằng Gemini chưa chạy. Các thẻ dưới đây vẫn hiện BCTC quý mới nhất
      lấy trực tiếp từ web từng công ty; điểm và chỉ số sẽ tự xuất hiện sau khi chạy <code>python phan_tich.py</code>.
    </div>
    <div class="kpis" id="kpis"></div>
    <div class="filters" role="search">
      <label class="f">Tìm mã / tên<input type="search" id="q" placeholder="VNM, ngân hàng..."></label>
      <label class="f">Loại hình
        <select id="loai"><option value="">Tất cả</option><option value="doanh_nghiep">Doanh nghiệp</option>
        <option value="ngan_hang">Ngân hàng</option><option value="chung_khoan">Chứng khoán</option></select></label>
      <label class="f sc">Điểm tối thiểu: <b id="diemOut">0</b><input type="range" id="diem" min="0" max="10" step="1" value="0"></label>
      <label class="f sc">DT tăng ≥ (%)<input type="number" id="dt" step="1" placeholder="VD 20"></label>
      <label class="f sc">LNST tăng ≥ (%)<input type="number" id="lnst" step="1" placeholder="VD 10"></label>
      <label class="f sc">Nợ vay giảm ≥ (%)<input type="number" id="no" step="1" min="0" placeholder="VD 10"></label>
      <label class="f check sc"><input type="checkbox" id="cfo"> Dòng tiền KD dương</label>
      <label class="f">Sắp xếp
        <select id="sort"><option value="diem">Điểm cao → thấp</option><option value="dt">DT tăng mạnh nhất</option>
        <option value="lnst">LNST tăng mạnh nhất</option><option value="no">Nợ vay giảm mạnh nhất</option>
        <option value="ma">Mã A → Z</option></select></label>
      <button class="btn" id="viewBtn" aria-pressed="false">Dạng bảng</button>
      <button class="btn" id="reset">Xoá lọc</button>
    </div>
    <div class="presets sc" aria-label="Lọc nhanh">
      <span class="sub" style="font-size:13px">Lọc nhanh:</span>
      <button class="chip" data-p="10">Đạt 10/10</button>
      <button class="chip" data-p="8">Từ 8 điểm</button>
      <button class="chip" data-p="dt20">Doanh thu tăng &gt; 20%</button>
      <button class="chip" data-p="no10">Nợ vay giảm &gt; 10%</button>
      <button class="chip" data-p="cash">LNST tăng + dòng tiền dương</button>
    </div>
    <p class="count" id="count" aria-live="polite"></p>
    <div id="list"></div>
  </section>

  <!-- ============ THƯ VIỆN ============ -->
  <section id="tab-thu-vien" hidden>
    <p class="sub" style="margin-top:14px">BCTC từ <span id="libFrom"></span> của 30 mã VN30. Link trỏ thẳng về web công ty
      (nguồn đăng sớm nhất); kỳ nào web công ty không còn lưu thì dùng bản trên CafeF.</p>
    <div class="filters">
      <label class="f">Mã<select id="lMa"><option value="">Tất cả</option></select></label>
      <label class="f">Năm<select id="lNam"><option value="">Tất cả</option></select></label>
      <label class="f">Kỳ<select id="lKy"><option value="">Tất cả</option><option>Q1</option><option>Q2</option>
        <option value="6T">Bán niên</option><option>Q3</option><option>Q4</option><option value="NAM">Cả năm</option></select></label>
      <label class="f">Phạm vi<select id="lPv"><option value="">Tất cả</option><option value="HN">Hợp nhất</option>
        <option value="RIENG">Riêng / công ty mẹ</option><option value="CHUNG">Chung</option></select></label>
      <label class="f">Tìm trong tiêu đề<input type="search" id="lQ" placeholder="soát xét, kiểm toán..."></label>
    </div>
    <p class="count" id="lCount"></p>
    <div id="lib"></div>
  </section>

  <!-- ============ NGUỒN ============ -->
  <section id="tab-nguon" hidden>
    <div class="kpis" id="srcKpis"></div>
    <p class="sub">Công cụ đọc trực tiếp trang quan hệ nhà đầu tư của từng công ty (công ty đăng BCTC ở đây trước, CafeF đăng lại sau).
      Mỗi lần kiểm tra: đọc danh sách BCTC, tìm BCTC quý mới nhất, tải thử file. <span id="srcTime"></span></p>
    <div id="src" style="margin-top:12px"></div>
  </section>

  <!-- ============ PHƯƠNG PHÁP ============ -->
  <section id="tab-phuong-phap" hidden>
    <h2>Dữ liệu đi từ đâu</h2>
    <ol class="flow">
      <li><b>Thu thập:</b> đọc trang BCTC trên web của 30 công ty (HTML, API, trang chặn bot thì mở bằng trình duyệt thật).
        CafeF chỉ để dự phòng khi web công ty không có hoặc link hỏng.</li>
      <li><b>Chuyển chữ:</b> khoảng 90% BCTC là PDF scan → OCR tiếng Việt, tự xoay trang scan nằm ngang.</li>
      <li><b>Đọc số liệu:</b> chỉ các trang Bảng cân đối, Kết quả kinh doanh, Lưu chuyển tiền tệ được gửi cho
        Gemini (3.5 Flash-Lite), trả về theo mẫu cố định.</li>
      <li><b>Kiểm tra chéo:</b> Tổng tài sản = Nợ + Vốn chủ sở hữu; lưu chuyển tiền thuần = kinh doanh + đầu tư + tài chính;
        đúng kỳ, đúng đơn vị. Sai lệch hiện thành cảnh báo trên thẻ.</li>
      <li><b>So sánh và chấm điểm:</b> quý này so với quý trước (và cùng kỳ năm trước), lưu chuyển tiền quy về số trong quý.</li>
    </ol>
    <h2>Công thức chấm điểm (thang 10)</h2>
    <p class="sub">Điểm do công thức tính từ số liệu, không do AI tự cho. Mỗi loại hình có bộ tiêu chí riêng vì cấu trúc BCTC khác nhau:
      dòng tiền của ngân hàng và công ty chứng khoán phản ánh luồng tiền gửi/cho vay chứ không đo chất lượng lợi nhuận, nên được thay
      bằng ROE và quy mô. Thiếu số liệu thì tiêu chí đó được 0 điểm và thẻ ghi rõ. Xếp loại: 9–10 Rất tốt · 7–8 Tốt · 4–6 Trung bình · 0–3 Yếu.</p>
    <div class="methods" id="methods" style="margin-top:12px"></div>
    <h2>Lưu ý</h2>
    <p class="sub">Điểm phản ánh sức khỏe của <b>một quý BCTC</b>, không phải khuyến nghị mua bán. Nên xem kèm định giá và xu hướng nhiều quý.
      Số liệu do AI đọc từ BCTC có thể sai; thẻ có cảnh báo thì mở BCTC gốc để đối chiếu.</p>
  </section>

  <footer id="footer"></footer>
</div>

<script type="application/json" id="data">__DATA__</script>
<script>
(() => {
  const D = JSON.parse(document.getElementById('data').textContent);
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch]));
  const nf0 = new Intl.NumberFormat('vi-VN', {maximumFractionDigits: 0});
  const nf1 = new Intl.NumberFormat('vi-VN', {minimumFractionDigits: 1, maximumFractionDigits: 1});
  const nf2 = new Intl.NumberFormat('vi-VN', {maximumFractionDigits: 2});
  const ty = x => x == null ? '–' : (Math.abs(x) >= 1e6 ? nf2.format(x / 1e6) + ' triệu tỷ' : nf0.format(x) + ' tỷ');
  const pct = x => x == null ? '–' : (x > 0 ? '+' : x < 0 ? '−' : '') + nf1.format(Math.abs(x * 100)) + '%';
  const tierVar = d => d >= 9 ? 'var(--tier-1)' : d >= 7 ? 'var(--tier-2)' : d >= 4 ? 'var(--tier-3)' : 'var(--tier-4)';
  const vnDate = s => s ? s.split('-').reverse().join('/') : '';
  const KY = {Q1: 'Quý 1', Q2: 'Quý 2', Q3: 'Quý 3', Q4: 'Quý 4', '6T': 'Bán niên', NAM: 'Cả năm', NA: '?'};
  const PV = {HN: 'Hợp nhất', RIENG: 'Riêng', CHUNG: 'Chung'};
  const LOAI = {doanh_nghiep: 'Doanh nghiệp', ngan_hang: 'Ngân hàng', chung_khoan: 'Chứng khoán', bao_hiem: 'Bảo hiểm'};

  // ---------- gộp dữ liệu: 30 công ty + điểm (nếu có) + kết quả kiểm tra web ----------
  const scoreBy = Object.fromEntries(D.cards.map(c => [c.ma, c]));
  const irBy = Object.fromEntries(D.ir.map(c => [c.ma, c]));
  const items = D.companies.map(co => {
    const c = scoreBy[co.ma], ir = irBy[co.ma];
    return {ma: co.ma, ten: co.ten, loai: c ? c.loai : co.loai, bctc_url: co.bctc_url, c, ir,
            m: c ? c.m : {}, diem: c ? c.diem : null};
  });
  const hasScore = D.cards.length > 0;
  const debt = it => it.m.vay_pct != null ? it.m.vay_pct : it.m.no_pct;

  $('sub').textContent = (hasScore ? `Kỳ ${D.cards[0].ky} so với ${D.cards[0].ky_truoc} · ` : '') +
    `30 mã VN30 · dữ liệu lấy trực tiếp từ web công ty · cập nhật ${D.tao_luc}`;
  $('footer').innerHTML = `Số liệu tỷ đồng. Nguồn: web quan hệ nhà đầu tư của từng công ty. Không phải khuyến nghị đầu tư. ` +
    `Mã nguồn: <a href="${esc(D.repo)}" target="_blank" rel="noopener">${esc(D.repo.replace('https://', ''))}</a>`;

  // ---------- tab ----------
  const TABS = ['bang-diem', 'thu-vien', 'nguon', 'phuong-phap'];
  function showTab() {
    const t = TABS.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'bang-diem';
    TABS.forEach(x => { $('tab-' + x).hidden = x !== t; });
    document.querySelectorAll('nav.tabs a').forEach(a => {
      if (a.dataset.tab === t) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
  }
  addEventListener('hashchange', showTab);

  // ---------- BẢNG ĐIỂM ----------
  function delta(x, upGood = true) {      // mũi tên + dấu + màu (không chỉ dựa vào màu); upGood=null: trung tính
    if (x == null) return '<span class="d flat">–</span>';
    if (Math.abs(x) < 0.0005) return '<span class="d flat">0%</span>';
    if (upGood === null) return `<span class="d flat">${x > 0 ? '▲' : '▼'} ${pct(x)}</span>`;
    return `<span class="d ${(x > 0) === upGood ? 'up' : 'down'}">${x > 0 ? '▲' : '▼'} ${pct(x)}</span>`;
  }
  function kpis() {
    const n = D.cards.length || 1;
    const ok = D.ir.filter(r => r.kiem_tra === 'PASS').length;
    const lags = D.ir.map(r => r.cafef_tre_ngay).filter(x => x != null).sort((a, b) => a - b);
    const tiles = hasScore ? [
      ['Đạt 10/10', D.cards.filter(c => c.diem === 10).length, 'BCTC rất tốt'],
      ['Điểm trung bình', nf1.format(D.cards.reduce((s, c) => s + c.diem, 0) / n), 'trên thang 10'],
      ['Doanh thu tăng', `${D.cards.filter(c => (c.m.dt_pct ?? -1) > 0).length}/${D.cards.length}`, 'so với quý trước'],
      ['LNST tăng', `${D.cards.filter(c => (c.m.lnst_pct ?? -1) > 0).length}/${D.cards.length}`, 'so với quý trước'],
      ['Nợ vay giảm', `${items.filter(it => it.c && (debt(it) ?? 1) < 0).length}/${D.cards.length}`, 'thiếu nợ vay: nợ phải trả'],
      ['Có cảnh báo dữ liệu', D.cards.filter(c => c.canh_bao.length).length, 'nên mở BCTC gốc kiểm tra'],
    ] : [
      ['Công ty theo dõi', items.length, 'rổ VN30 hiện hành'],
      ['Web công ty đọc được', `${ok}/${D.ir.length || 30}`, 'kiểm tra tự động'],
      ['BCTC quý mới nhất', latestPeriod() || '–', 'trên web công ty'],
      ['CafeF đăng chậm', lags.length ? nf1.format(lags[lags.length >> 1]) + ' ngày' : '–', `trung vị, ${lags.length} mã đo được`],
    ];
    $('kpis').innerHTML = tiles.map(([l, v, n2]) =>
      `<div class="kpi"><div class="label">${l}</div><div class="value">${v}</div><div class="note">${n2}</div></div>`).join('');
  }
  function latestPeriod() {
    const ks = D.ir.map(r => r.ir && r.ir.ky).filter(Boolean);
    return ks.sort((a, b) => (a.slice(3) + a[1]).localeCompare(b.slice(3) + b[1])).pop();
  }
  const state = () => ({
    q: $('q').value.trim().toLowerCase(), loai: $('loai').value, diem: +$('diem').value,
    dt: $('dt').value === '' ? null : +$('dt').value / 100, lnst: $('lnst').value === '' ? null : +$('lnst').value / 100,
    no: $('no').value === '' ? null : +$('no').value / 100, cfo: $('cfo').checked, sort: $('sort').value,
  });
  function filtered(s) {
    const r = items.filter(it =>
      (!s.q || it.ma.toLowerCase().includes(s.q) || it.ten.toLowerCase().includes(s.q) || (LOAI[it.loai] || '').toLowerCase().includes(s.q)) &&
      (!s.loai || it.loai === s.loai) && (!hasScore || (it.diem ?? -1) >= s.diem) &&
      (s.dt == null || (it.m.dt_pct != null && it.m.dt_pct >= s.dt)) &&
      (s.lnst == null || (it.m.lnst_pct != null && it.m.lnst_pct >= s.lnst)) &&
      (s.no == null || (debt(it) != null && debt(it) <= -s.no)) &&
      (!s.cfo || (it.m.cfo != null && it.m.cfo > 0)));
    const key = {diem: it => -(it.diem ?? -1) * 1e3 - (it.m.lnst_pct ?? -9), dt: it => -(it.m.dt_pct ?? -9),
                 lnst: it => -(it.m.lnst_pct ?? -9), no: it => (debt(it) ?? 9), ma: () => 0}[s.sort];
    return r.sort((a, b) => key(a) - key(b) || a.ma.localeCompare(b.ma));
  }
  function latestBlock(it) {
    const ir = it.ir;
    if (!ir || !ir.ir) return `<div class="latest"><span>BCTC mới nhất: chưa đọc được từ web công ty${it.bctc_url ? ` · <a href="${esc(it.bctc_url)}" target="_blank" rel="noopener">Mở trang BCTC</a>` : ''}</span></div>`;
    const d = ir.ir;
    return `<div class="latest">
      <span>BCTC mới nhất: <b>${esc(KY[d.ky.slice(0, 2)] || d.ky.slice(0, 2))} ${esc(d.ky.slice(3))}</b> · ${esc(PV[d.pham_vi] || d.pham_vi)}${d.ngay ? ` · công bố ${vnDate(d.ngay)}` : ''}</span>
      <span>${ir.cafef_tre_ngay != null ? `CafeF đăng sau ${nf1.format(ir.cafef_tre_ngay)} ngày · ` : ''}<a href="${esc(d.url)}" target="_blank" rel="noopener">Mở PDF</a> · <a href="${esc(it.bctc_url)}" target="_blank" rel="noopener">Trang BCTC</a></span>
    </div>`;
  }
  function card(it) {
    const c = it.c, m = it.m, bank = it.loai === 'ngan_hang';
    let body = '', head = `<div class="score"><div class="none">Chưa chấm điểm</div></div>`;
    if (c) {
      head = `<div class="score"><div class="big">${c.diem}<small>/10</small></div>
        <div class="tier" style="color:${tierVar(c.diem)}">● ${esc(c.xep_loai)}</div></div>`;
      const rows = [
        [bank ? 'Tổng thu nhập HĐ' : 'Doanh thu', m.dt, delta(m.dt_pct)],
        [bank ? 'Thu nhập lãi thuần' : it.loai === 'chung_khoan' ? 'LN hoạt động' : 'Lợi nhuận gộp', m.lng, delta(m.lng_pct)],
        ['LNST', m.lnst, delta(m.lnst_pct)], ['LNST so cùng kỳ', null, delta(m.lnst_yoy)],
        ['Tổng tài sản', m.ts, delta(m.ts_pct)],
        [m.vay != null ? 'Nợ vay' : 'Nợ phải trả', m.vay != null ? m.vay : m.no, delta(m.vay != null ? m.vay_pct : m.no_pct, bank ? null : false)],
        ['Vốn chủ sở hữu', m.vcsh, delta(m.vcsh_pct)],
      ];
      if (!bank) rows.push(['LCTT kinh doanh', m.cfo, m.cfo == null ? '<span class="d flat">–</span>' :
        `<span class="d ${m.cfo > 0 ? 'up' : 'down'}">${m.cfo > 0 ? 'dương' : 'âm'}</span>`]);
      const crit = c.tieu_chi.map(([t, p, mx, d]) =>
        `<li><span aria-hidden="true">${p === mx ? '✓' : p > 0 ? '◐' : '✗'}</span><span>${esc(t)}</span><span class="pt">${p}/${mx}</span><span class="dt">${esc(d)}</span></li>`).join('');
      body = `<div class="meter" role="img" aria-label="${c.diem} trên 10 điểm"><i style="width:${c.diem * 10}%;background:${tierVar(c.diem)}"></i></div>
        <div class="rows">${rows.map(([k, v, d]) => `<span class="k">${k}</span><span class="v">${v == null ? '' : ty(v)}</span>${d}`).join('')}</div>
        <details><summary>Chi tiết điểm${c.thieu ? ` · thiếu dữ liệu ${c.thieu}đ` : ''}</summary><ul class="crit">${crit}</ul></details>
        ${c.canh_bao.length ? `<div class="warn">⚠ ${c.canh_bao.map(esc).join('<br>⚠ ')}</div>` : ''}`;
    }
    return `<article class="card" aria-label="${esc(it.ma)}">
      <div class="card-top"><div><div class="tk">${esc(it.ma)}</div><div class="name">${esc(it.ten)}</div>
        <span class="tag">${esc(LOAI[it.loai] || it.loai)}${c ? ` · ${esc(c.ky)} vs ${esc(c.ky_truoc)}` : ''}</span></div>${head}</div>
      ${body}${latestBlock(it)}
    </article>`;
  }
  function scoreTable(list) {
    const cols = [['Mã', it => it.ma], ['Loại hình', it => LOAI[it.loai]], ['Điểm', it => it.diem ?? '–'],
      ['DT', it => pct(it.m.dt_pct)], ['LNST', it => pct(it.m.lnst_pct)], ['LNST cùng kỳ', it => pct(it.m.lnst_yoy)],
      ['Nợ vay', it => pct(debt(it))], ['VCSH', it => pct(it.m.vcsh_pct)],
      ['LCTT KD (tỷ)', it => it.m.cfo == null ? '–' : nf0.format(it.m.cfo)],
      ['BCTC mới nhất', it => it.ir && it.ir.ir ? it.ir.ir.ky : '–'], ['Cảnh báo', it => it.c && it.c.canh_bao.length ? '⚠' : '']];
    return `<div class="tablewrap"><table><thead><tr>${cols.map(c => `<th scope="col">${c[0]}</th>`).join('')}</tr></thead>
      <tbody>${list.map(it => `<tr>${cols.map((col, i) => `<td class="${i > 1 ? 'num' : ''}">${esc(col[1](it))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  }
  let asTable = false;
  function renderScores() {
    const s = state();
    $('diemOut').textContent = s.diem;
    const list = filtered(s);
    $('count').textContent = `Đang hiện ${list.length}/${items.length} công ty`;
    $('list').innerHTML = !list.length ? '<div class="empty">Không có công ty nào khớp bộ lọc.</div>'
      : asTable ? scoreTable(list) : `<div class="grid">${list.map(card).join('')}</div>`;
  }
  ['q', 'loai', 'diem', 'dt', 'lnst', 'no', 'cfo', 'sort'].forEach(id => $(id).addEventListener('input', renderScores));
  $('reset').onclick = () => { ['q', 'dt', 'lnst', 'no'].forEach(id => $(id).value = ''); $('loai').value = '';
    $('diem').value = 0; $('cfo').checked = false; $('sort').value = hasScore ? 'diem' : 'ma'; renderScores(); };
  document.querySelectorAll('.chip').forEach(b => b.onclick = () => {
    $('reset').onclick();
    const p = b.dataset.p;
    if (p === '10') $('diem').value = 10;
    if (p === '8') $('diem').value = 8;
    if (p === 'dt20') { $('dt').value = 20; $('sort').value = 'dt'; }
    if (p === 'no10') { $('no').value = 10; $('sort').value = 'no'; }
    if (p === 'cash') { $('lnst').value = 0.01; $('cfo').checked = true; }
    renderScores();
  });
  $('viewBtn').onclick = () => { asTable = !asTable; $('viewBtn').setAttribute('aria-pressed', asTable);
    $('viewBtn').textContent = asTable ? 'Dạng thẻ' : 'Dạng bảng'; renderScores(); };

  // ---------- THƯ VIỆN ----------
  const L = D.lib;      // [mã, năm, kỳ, phạm vi, kiểm toán, tiêu đề, url, nguồn]
  $('libFrom').textContent = L.length ? 'năm ' + Math.min(...L.map(r => r[1])) + ' trở đi' : '';
  [...new Set(L.map(r => r[0]))].sort().forEach(m => $('lMa').insertAdjacentHTML('beforeend', `<option>${esc(m)}</option>`));
  [...new Set(L.map(r => r[1]))].sort((a, b) => b - a).forEach(y => $('lNam').insertAdjacentHTML('beforeend', `<option>${y}</option>`));
  let libLimit = 200;
  function renderLib() {
    const f = {ma: $('lMa').value, nam: $('lNam').value, ky: $('lKy').value, pv: $('lPv').value, q: $('lQ').value.trim().toLowerCase()};
    const rows = L.filter(r => (!f.ma || r[0] === f.ma) && (!f.nam || String(r[1]) === f.nam) && (!f.ky || r[2] === f.ky) &&
      (!f.pv || r[3] === f.pv) && (!f.q || r[5].toLowerCase().includes(f.q)));
    $('lCount').textContent = `${rows.length} BCTC` + (rows.length > libLimit ? ` · đang hiện ${libLimit} dòng đầu` : '');
    if (!rows.length) { $('lib').innerHTML = '<div class="empty">Không có BCTC nào khớp bộ lọc.</div>'; return; }
    $('lib').innerHTML = `<div class="tablewrap"><table><thead><tr><th>Mã</th><th>Kỳ</th><th>Phạm vi</th><th>Tiêu đề</th><th>Nguồn</th><th>Tải</th></tr></thead><tbody>` +
      rows.slice(0, libLimit).map(r => `<tr><td><b>${esc(r[0])}</b></td><td style="white-space:nowrap">${esc(KY[r[2]] || r[2])} ${r[1]}${r[4] === 'KT' ? ' · kiểm toán' : r[4] === 'SX' ? ' · soát xét' : ''}</td>
        <td>${esc(PV[r[3]] || r[3])}</td><td>${esc(r[5])}</td>
        <td><span class="badge src">${r[7] === 'web' ? 'Web công ty' : 'CafeF'}</span></td>
        <td><a href="${esc(r[6])}" target="_blank" rel="noopener">PDF</a></td></tr>`).join('') + `</tbody></table></div>` +
      (rows.length > libLimit ? `<button class="btn more" id="libMore">Hiện thêm</button>` : '');
    const more = $('libMore'); if (more) more.onclick = () => { libLimit += 300; renderLib(); };
  }
  ['lMa', 'lNam', 'lKy', 'lPv', 'lQ'].forEach(id => $(id).addEventListener('input', () => { libLimit = 200; renderLib(); }));

  // ---------- NGUỒN ----------
  function renderSrc() {
    const ok = D.ir.filter(r => r.kiem_tra === 'PASS').length;
    const lags = D.ir.map(r => r.cafef_tre_ngay).filter(x => x != null).sort((a, b) => a - b);
    $('srcKpis').innerHTML = [
      ['Web đọc được', `${ok}/${D.ir.length}`, 'đọc danh sách + tải thử file'],
      ['CafeF chậm (trung vị)', lags.length ? nf1.format(lags[lags.length >> 1]) + ' ngày' : '–', `${lags.length} mã đo được`],
      ['CafeF chậm nhất', lags.length ? nf1.format(lags[lags.length - 1]) + ' ngày' : '–', 'so với web công ty'],
    ].map(([l, v, n]) => `<div class="kpi"><div class="label">${l}</div><div class="value">${v}</div><div class="note">${n}</div></div>`).join('');
    $('srcTime').textContent = D.ir_luc ? `Lần kiểm tra gần nhất: ${D.ir_luc.replace('T', ' ')}.` : '';
    if (!D.ir.length) { $('src').innerHTML = '<div class="empty">Chưa có kết quả kiểm tra (chạy python kiem_tra_ir.py).</div>'; return; }
    $('src').innerHTML = `<div class="tablewrap"><table><thead><tr><th>Mã</th><th>Công ty</th><th>Trang BCTC</th><th>Cách đọc</th>
      <th>Kiểm tra</th><th>BCTC mới nhất</th><th>Công bố</th><th>CafeF chậm</th></tr></thead><tbody>` +
      D.ir.map(r => `<tr><td><b>${esc(r.ma)}</b></td><td>${esc(r.ten)}</td>
        <td><a href="${esc(r.bctc_url)}" target="_blank" rel="noopener">${esc(r.bctc_url.replace(/^https?:\/\/(www\.)?/, '').slice(0, 40))}</a></td>
        <td>${esc(r.cach_doc)}</td>
        <td>${r.kiem_tra === 'PASS' ? '<span class="badge ok">✓ Đạt</span>' : `<span class="badge bad" title="${esc(r.loi)}">✗ Lỗi</span>`}</td>
        <td>${r.ir ? `<a href="${esc(r.ir.url)}" target="_blank" rel="noopener">${esc(r.ir.ky)}</a>` : '–'}</td>
        <td class="num">${r.ir && r.ir.ngay ? vnDate(r.ir.ngay) : '–'}</td>
        <td class="num">${r.cafef_tre_ngay != null ? nf1.format(r.cafef_tre_ngay) + ' ngày' : '–'}</td></tr>`).join('') + '</tbody></table></div>';
  }

  // ---------- PHƯƠNG PHÁP ----------
  const names = {doanh_nghiep: 'Doanh nghiệp, bảo hiểm', ngan_hang: 'Ngân hàng', chung_khoan: 'Công ty chứng khoán'};
  $('methods').innerHTML = Object.entries(D.criteria).map(([k, rows]) =>
    `<div class="tablewrap"><table><thead><tr><th>${names[k]}</th><th>Điểm</th></tr></thead><tbody>${rows.map(([t, p]) =>
      `<tr><td>${esc(t)}</td><td>${esc(p)}</td></tr>`).join('')}<tr><td><b>Tổng tối đa</b></td><td><b>10đ</b></td></tr></tbody></table></div>`).join('');

  // ---------- giao diện sáng/tối ----------
  const root = document.documentElement;
  try { const t = localStorage.getItem('bctc-theme'); if (t) root.dataset.theme = t; } catch (e) {}
  $('themeBtn').onclick = () => {
    const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    root.dataset.theme = dark ? 'light' : 'dark';
    try { localStorage.setItem('bctc-theme', root.dataset.theme); } catch (e) {}
  };

  if (!hasScore) {
    $('noScore').hidden = false;
    document.querySelectorAll('.sc').forEach(el => el.hidden = true);
    $('sort').value = 'ma';
    [...$('sort').options].forEach(o => { if (o.value !== 'ma') o.hidden = true; });
  }
  kpis(); renderScores(); renderLib(); renderSrc(); showTab();
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    out = build()
    print(f"Web: {DOCS / 'index.html'} (GitHub Pages) và {out}")
