#!/usr/bin/env python3
"""Từ điển 500 thuật ngữ kinh tế - tài chính - kế toán - ngân hàng - chứng khoán.

Nguồn định nghĩa:
  1. Định nghĩa biên soạn (tu_dien/nguon/*.json): ngắn gọn, gắn bối cảnh BCTC Việt Nam, có công thức với chỉ số.
  2. Wikipedia tiếng Việt: đoạn mở đầu bài viết (API chính thức, theo trang chuyển hướng, bỏ trang định hướng),
     ghi nguồn + giấy phép CC BY-SA 4.0 như yêu cầu của Wikipedia.

    python tu_dien.py            # gộp nguồn + tra Wikipedia (có cache) -> tu_dien/tu_dien.json + tu_dien_500.xlsx
    python tu_dien.py --lam-moi  # tra lại Wikipedia, bỏ cache
"""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
DIR = ROOT / "tu_dien"
API = "https://vi.wikipedia.org/w/api.php"
# Wikimedia yêu cầu User-Agent mô tả rõ công cụ + liên hệ
UA = "BCTC-VN30-glossary/1.0 (https://github.com/VietNhat-1305/bctc-vn30; educational use)"   # header phải là ASCII
NHOM_THU_TU = ["Kinh tế vĩ mô & chính sách", "Kế toán & Báo cáo tài chính", "Phân tích tài chính & Định giá",
               "Ngân hàng & Tín dụng", "Chứng khoán & Đầu tư"]
STOP = {"va", "cua", "cac", "trong", "theo", "tren", "duoc", "mot", "nhung", "voi", "cho", "tu", "la", "co", "khong"}
# Đã soát tay: Wikipedia trả về bài sai khái niệm (chữ cái Beta/G, giao thức FTP, Viện PMI...) hoặc quá chung chung
WIKI_BO_QUA = {"Hệ số beta", "Tốc độ tăng trưởng dài hạn", "Định giá điều chuyển vốn nội bộ", "Chỉ số nhà quản trị mua hàng",
               "Cho vay tiêu dùng", "Công ty tài chính", "Hệ thống KRX"}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower().replace("đ", "d"))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", "".join(c for c in s if unicodedata.category(c) != "Mn"))).strip()


def load_sources() -> list[dict]:
    """Gộp các file nhóm, bỏ trùng theo tên chuẩn hoá (giữ bản xuất hiện trước)."""
    items, seen = [], set()
    for f in sorted((DIR / "nguon").glob("*.json")):
        for it in json.loads(f.read_text(encoding="utf-8")):
            k = norm(it["thuat_ngu"])
            if not k or k in seen:
                continue
            seen.add(k)
            items.append({"thuat_ngu": it["thuat_ngu"].strip(), "viet_tat": (it.get("viet_tat") or "").strip() or None,
                          "tieng_anh": (it.get("tieng_anh") or "").strip(), "nhom": it.get("nhom", "").strip(),
                          "dinh_nghia": it["dinh_nghia"].strip(), "lien_quan": it.get("lien_quan") or []})
    return items


def first_sentences(text: str, limit: int = 600) -> str:
    """Đoạn mở đầu Wikipedia, cắt ở ranh giới câu, tối đa ~limit ký tự."""
    text = re.sub(r"\s+", " ", re.sub(r"\(\s*[;,]?\s*\)", "", text)).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    m = list(re.finditer(r"[.!?](?=\s+[A-ZĐÀ-Ỹ0-9])", cut))
    return cut[: m[-1].end()] if m else cut.rsplit(" ", 1)[0] + "…"


def wiki_lookup(titles: list[str], client: httpx.Client) -> dict[str, dict]:
    """{tiêu đề hỏi: {title, url, extract}} cho các bài tồn tại, không phải trang định hướng. 20 tiêu đề/lần."""
    out = {}
    for i in range(0, len(titles), 20):
        chunk = titles[i:i + 20]
        params = {"action": "query", "format": "json", "formatversion": "2", "redirects": "1",
                  "prop": "extracts|pageprops|info", "inprop": "url", "exintro": "1", "explaintext": "1",
                  "exlimit": "20", "ppprop": "disambiguation", "titles": "|".join(chunk)}
        for attempt in range(4):
            try:
                r = client.get(API, params=params, timeout=30)
                r.raise_for_status()
                data = r.json()["query"]
                break
            except Exception:  # noqa: BLE001
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        # hỏi -> (chuẩn hoá chữ hoa đầu) -> (chuyển hướng) -> tiêu đề bài thật
        mapping = {t: t for t in chunk}
        for n in data.get("normalized", []):
            for k, v in mapping.items():
                if v == n["from"]:
                    mapping[k] = n["to"]
        for rd in data.get("redirects", []):
            for k, v in mapping.items():
                if v == rd["from"]:
                    mapping[k] = rd["to"]
        pages = {p["title"]: p for p in data.get("pages", [])}
        for asked, real in mapping.items():
            p = pages.get(real)
            if not p or p.get("missing") or "disambiguation" in (p.get("pageprops") or {}):
                continue
            ext = (p.get("extract") or "").strip()
            if len(ext) >= 60:
                out[asked] = {"title": p["title"], "url": p["fullurl"], "extract": first_sentences(ext)}
        time.sleep(0.3)
    return out


def relevant(item: dict, wiki: dict) -> bool:
    """Bài tìm qua TỪ VIẾT TẮT (VD 'NIM', 'CAR') phải nói đúng khái niệm: có từ khoá của tên/tiếng Anh."""
    words = {w for w in norm(item["thuat_ngu"] + " " + item["tieng_anh"]).split() if len(w) > 2 and w not in STOP}
    text = norm(wiki["title"] + " " + wiki["extract"])
    return sum(w in text for w in words) >= max(1, len(words) // 3)


def enrich(items: list[dict], refresh: bool = False) -> None:
    cache_path = DIR / "wiki_cache.json"
    cache = {} if refresh or not cache_path.exists() else json.loads(cache_path.read_text(encoding="utf-8"))
    asks = []
    for it in items:
        for t in filter(None, [it["thuat_ngu"], it["viet_tat"]]):
            if t not in cache:
                asks.append(t)
    asks = list(dict.fromkeys(asks))
    if asks:
        print(f"Tra Wikipedia tiếng Việt: {len(asks)} tiêu đề ({(len(asks) + 19) // 20} lần gọi API)...")
        with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True) as client:
            found = wiki_lookup(asks, client)
        for t in asks:
            cache[t] = found.get(t)                      # None = không có bài phù hợp (cũng cache lại)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    for it in items:
        w = cache.get(it["thuat_ngu"])
        if not w and it["viet_tat"]:
            w = cache.get(it["viet_tat"])
            if w and not relevant(it, w):
                w = None
        it["wiki"] = None if it["thuat_ngu"] in WIKI_BO_QUA else w


def link_related(items: list[dict]) -> None:
    """Chỉ giữ thuật ngữ liên quan có trong từ điển (để bấm được), khớp không phân biệt dấu/hoa thường/viết tắt."""
    idx = {}
    for it in items:
        idx[norm(it["thuat_ngu"])] = it["thuat_ngu"]
        if it["viet_tat"]:
            idx.setdefault(norm(it["viet_tat"]), it["thuat_ngu"])
    for it in items:
        rel = []
        for r in it["lien_quan"]:
            t = idx.get(norm(r))
            if t and t != it["thuat_ngu"] and t not in rel:
                rel.append(t)
        it["lien_quan"] = rel[:6]


def write_excel(items: list[dict], path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Từ điển"
    head = ["STT", "Thuật ngữ", "Viết tắt", "Tiếng Anh", "Nhóm", "Định nghĩa (biên soạn)",
            "Theo Wikipedia tiếng Việt", "Bài Wikipedia", "Thuật ngữ liên quan"]
    ws.append(head)
    for i, it in enumerate(items, 1):
        w = it.get("wiki") or {}
        ws.append([i, it["thuat_ngu"], it["viet_tat"] or "", it["tieng_anh"], it["nhom"], it["dinh_nghia"],
                   w.get("extract", ""), w.get("url", ""), ", ".join(it["lien_quan"])])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E78")
        c.alignment = Alignment(vertical="center", wrap_text=True)
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(vertical="top", wrap_text=c.column in (6, 7, 9))
        if row[7].value:
            row[7].hyperlink = row[7].value
            row[7].font = Font(color="0563C1", underline="single")
    for col, w in zip("ABCDEFGHI", (5, 30, 10, 28, 24, 70, 70, 34, 40)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions
    ws2 = wb.create_sheet("Nguồn & giấy phép")
    for line in ["Định nghĩa (biên soạn): viết cho dự án BCTC VN30 (https://github.com/VietNhat-1305/bctc-vn30).",
                 "Cột 'Theo Wikipedia tiếng Việt': đoạn mở đầu bài viết tương ứng trên vi.wikipedia.org,",
                 "giấy phép Creative Commons Ghi công - Chia sẻ tương tự 4.0 (CC BY-SA 4.0):",
                 "https://creativecommons.org/licenses/by-sa/4.0/deed.vi - xem tác giả trong lịch sử từng bài (cột 'Bài Wikipedia')."]:
        ws2.append([line])
    ws2.column_dimensions["A"].width = 120
    wb.save(path)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    items = load_sources()
    items.sort(key=lambda it: (NHOM_THU_TU.index(it["nhom"]) if it["nhom"] in NHOM_THU_TU else 9, norm(it["thuat_ngu"])))
    enrich(items, refresh="--lam-moi" in sys.argv)
    link_related(items)
    (DIR / "tu_dien.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    write_excel(items, ROOT / "tu_dien_500.xlsx")
    n_wiki = sum(1 for it in items if it.get("wiki"))
    by = {}
    for it in items:
        by[it["nhom"]] = by.get(it["nhom"], 0) + 1
    print(f"{len(items)} thuật ngữ | có bài Wikipedia: {n_wiki} | theo nhóm: {by}")
    print(f"-> {DIR / 'tu_dien.json'}  +  {ROOT / 'tu_dien_500.xlsx'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
