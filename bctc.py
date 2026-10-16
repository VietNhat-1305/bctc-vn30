#!/usr/bin/env python3
"""Tải báo cáo tài chính (BCTC) của các công ty VN30 trên HOSE.

Luồng: (1) lấy danh mục BCTC mỗi mã (1 request/mã) -> (2) chuẩn hoá + lọc
-> (3) bỏ qua file đã có (manifest) -> (4) tải song song, stream xuống đĩa.
Bước 1 và 4 chạy chồng nhau (pipeline): mã nào có danh mục trước thì tải trước.

Ví dụ:
    python bctc.py                                  # 30 mã, 2 năm gần nhất
    python bctc.py --tickers VNM,FPT --years all     # toàn bộ lịch sử
    python bctc.py --latest 4 --scope HN             # 4 kỳ gần nhất, chỉ hợp nhất
    python bctc.py --list-only                       # chỉ xuất index.csv, không tải
    python bctc.py --source both                     # CafeF + web IR chính thức
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date, datetime
from html import unescape
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

import aiohttp
import yarl

ROOT = Path(__file__).resolve().parent
CURL = shutil.which("curl")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
CAFEF_LIST = "https://cafef.vn/du-lieu/Ajax/CongTy/BaoCaoTaiChinh.aspx?sym={sym}"

FILE_EXT = re.compile(r"\.(pdf|zip|rar|7z|docx?|xlsx?)(?:[?#]|$)", re.I)
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
HREF = re.compile(r"""href\s*=\s*['"]([^'"]+)['"]""", re.I)
ANCHOR = re.compile(r"""<a\b[^>]*?href\s*=\s*['"]([^'"]+)['"][^>]*>(.*?)</a>""", re.S | re.I)
TAG = re.compile(r"<[^>]+>")
YEAR = re.compile(r"(?<!\d)(20[0-4]\d)(?!\d)")
ROMAN = {"i": "1", "ii": "2", "iii": "3", "iv": "4"}
SEMI = re.compile(r"ban ?nien|6 ?thang|semi.?annual|half.?year|(?<![a-z])6t(?![a-z])|\b1h\d\d|\bh1\b|\bhy\d\d")
INTERIM = re.compile(r"giua nien do|interim")          # chỉ là bán niên khi không ghi quý
PERIOD_ORDER = {"Q1": 1, "Q2": 2, "6T": 3, "Q3": 4, "Q4": 5, "NAM": 6, "NA": 0}
TITLE_KEYS = ("title", "name", "ten", "tieude", "filename", "file_name", "displayname", "description")
BCTC_WORDS = ("bao cao tai chinh", "baocaotaichinh", "bctc", "financial statement",
              "financial report", "financial-statement", "consol", "bchn", "bcr ")
NOT_BCTC = ("thuong nien", "annual report", "nghi quyet", "quan tri", "dai hoi", "bien ban",
            "cao bach", "prospectus", "resolution")
NEVER_BCTC = re.compile(r"\bcv\b|cong van|explanation|ben vung|sustainab|presentation|ban tin|thong cao"
                        r"|t[iy] le an toan|an toan tai chinh|safety ratio|tong quan tinh hinh")
MAGIC = (b"%PDF", b"PK\x03\x04", b"Rar!", b"7z\xbc\xaf", b"\xd0\xcf\x11\xe0")


# --------------------------------------------------------------------- model
@dataclass
class Doc:
    ticker: str
    year: int | None
    period: str       # Q1..Q4 | 6T (bán niên) | NAM | NA
    scope: str        # HN (hợp nhất) | RIENG (công ty mẹ/riêng) | CHUNG
    audit: str        # KT (kiểm toán) | SX (soát xét) | ""
    title: str
    url: str
    source: str       # cafef | official

    @property
    def key(self) -> tuple:
        return (self.ticker, self.year, self.period, self.scope, self.audit)

    @property
    def sort_key(self) -> tuple:
        return (self.year or 0, PERIOD_ORDER.get(self.period, 0))

    def ext(self) -> str:
        m = FILE_EXT.search(urlsplit(self.url).path)
        return m.group(1).lower() if m else "pdf"

    def basename(self) -> str:
        parts = [self.ticker, str(self.year or "NA"), self.period, self.scope]
        if self.audit:
            parts.append(self.audit)
        return "_".join(parts)


def unaccent(s: str) -> str:
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


def clean(fragment: str) -> str:
    return re.sub(r"\s+", " ", unescape(TAG.sub(" ", fragment))).strip()


def canon(url: str) -> str:
    """Khoá so trùng URL: gộp '//' trong path, chữ thường; bỏ query cache-buster (?v=..., ?x123)
    nếu path đã là file, giữ query nếu nó định danh file (get_file?uuid=..., Download.ashx?id=...)."""
    p = urlsplit(url.strip())
    path = re.sub("/+", "/", p.path).lower()
    query = "" if FILE_EXT.search(path) else "?" + "&".join(sorted(unescape(p.query).lower().split("&")))
    return f"{p.netloc.lower()}{path}{query}"


def classify(text: str) -> tuple[int | None, str, str, str]:
    """Đoán (năm, kỳ, phạm vi, kiểm toán) từ tiêu đề + tên file."""
    raw = unaccent(text)
    # "kết thúc 31/12/2025" là kỳ báo cáo; các ngày khác (30/1/2026) là ngày đăng -> bỏ.
    end_m = re.search(r"ket thuc (?:ngay )?\d{1,2}[/.-]\d{1,2}[/.-](20[0-4]\d)", raw)
    raw = re.sub(r"(?<!\d)\d{1,2}[/.-]\d{1,2}[/.-]20\d\d(?!\d)", " ", raw)
    qy = re.search(r"(?<![\d/.])([1-4])[./](20[0-4]\d)(?!\d)", raw)          # "HN 1.2026", "quý 2/2026"
    pub = re.search(r"(?<!\d)(20[0-4]\d)(0[1-9]|1[0-2])[0-3]\d(?!\d)", raw)  # "20260730 - BID - ..."
    t = re.sub(r"[_\-.+%]|20(?=[a-z])", " ", raw)
    t = re.sub(r"\b(quy|q|quarter) ?(iv|i{1,3})\b", lambda m: f"{m[1]} {ROMAN[m[2]]}", t)  # quý II -> quý 2
    scope = ("HN" if re.search(r"hop ?nhat|consolidated|conso|\bhn|\bbc(?:tc)?hn", t) else
             "RIENG" if re.search(r"cong ty me|rieng|separate|\bsep\b|parent|\bme\b|\bm\b|\brl\b", t) else
             "CHUNG")
    audit = ("KT" if re.search(r"kiem ?toan|audited|\bkt\b|\b\w*kt\b", t) else
             "SX" if re.search(r"soat ?xet|reviewed|\bsx\b|\b\w*sx\b", t) else "")
    q = re.search(r"(?:quy|quarter) ?0?([1-4])\b|q ?0?([1-4])(?!\d)|\b([1-4]) ?q|q([1-4])(?=20[0-4]\d(?!\d))", t)
    if SEMI.search(t):
        period = "6T"
    elif q or qy:
        period = "Q" + (next(g for g in q.groups() if g) if q else qy.group(1))
    elif INTERIM.search(t):
        period = "6T"
    elif re.search(r"\bnam (?:tai chinh )?20\d\d|annual|full year|year ended|\bfy|\bcn\b|kiem ?toan|audited", t):
        period = "NAM"
    else:
        period = "NA"
    # Năm gắn với kỳ ("quý 4 năm 2025") đáng tin hơn năm bất kỳ trong chuỗi.
    tied = re.search(r"(?:quy|q|nam|nien do|fy|ban nien) ?(?:[1-4] ?)?(?:nam ?)?/? ?(20[0-4]\d)(?!\d)", t)
    years = ([int(end_m.group(1))] if end_m else [int(tied.group(1))] if tied else
             [int(qy.group(2))] if qy else [int(y) for y in YEAR.findall(t)])
    if not years:                                   # năm 2 chữ số: Q2-26, 2Q26, 1H26, 25Q2
        yy = re.search(r"q[1-4] ?(\d{2})(?!\d)|\b[1-4][qh](\d{2})(?!\d)|\b(\d{2})q[1-4]|\b(?:hy|fy|h[12]) ?(\d{2})(?!\d)", t)
        years = [2000 + int(next(g for g in yy.groups() if g))] if yy else []
    if not years and pub:                           # chỉ có ngày đăng: BCTC Q4/năm đăng đầu năm sau
        y, m = int(pub.group(1)), int(pub.group(2))
        years = [y - 1 if m <= 4 and period in ("Q4", "NAM", "NA") else y]
    year = max(years) if years else None
    if period == "NA" and year and re.search(r"bao cao tai chinh|bctc|financial statement", t):
        period = "NAM"                              # BCTC chỉ ghi năm, không ghi kỳ = BCTC năm
    return year, normalize_period(period, audit, year), scope, audit


def normalize_period(period: str, audit: str, year: int | None, cafef: bool = False) -> str:
    """BCTC 'năm' của năm chưa kết thúc chắc chắn là bán niên. CafeF ghi BCTC bán niên soát xét thành
    'quý 2 (đã soát xét)' -> đổi thành 6T; web công ty thì KHÔNG (VNM soát xét cả từng quý, 'Q2 soát xét' là quý 2)."""
    if audit == "SX" and (period == "NA" or (cafef and period == "Q2")):
        return "6T"
    if period == "NAM" and year and year >= date.today().year:
        return "6T"
    return period


# ------------------------------------------------------------------- sources
async def curl_get(url: str, dest: Path | None = None, params: dict | None = None) -> tuple[int, bytes]:
    """GET bằng curl có sẵn của Windows. Một số trang sau Cloudflare chặn TLS của Python (403
    'Just a moment...') nhưng cho curl qua. Trả về (HTTP status, body) hoặc ghi body vào dest."""
    if params:
        url = str(yarl.URL(url).update_query(params))
    args = [CURL, "-sL", "--compressed", "--max-time", "300", "-A", UA,
            "-H", "Accept-Language: vi,en;q=0.8", "-w", "%{http_code}", "-o", str(dest) if dest else "-", url]
    # Chạy trong thread: SelectorEventLoop trên Windows không hỗ trợ asyncio subprocess.
    proc = await asyncio.to_thread(subprocess.run, args, capture_output=True)
    if proc.returncode:
        raise aiohttp.ClientConnectionError(f"curl exit {proc.returncode}")
    return int(proc.stdout[-3:]), proc.stdout[:-3]


async def fetch_text(session: aiohttp.ClientSession, url: str, retries: int,
                     method: str = "GET", use_curl: bool = False, **kw) -> str:
    if use_curl and CURL and method == "GET":
        async def _curl():
            status, body = await curl_get(url, params=kw.get("params"))
            if status in (429, 500, 502, 503, 504):
                raise RetryableError(status)
            if status >= 400:
                raise RuntimeError(f"HTTP {status}")
            return body.decode("utf-8", "replace")
        return await with_retry(_curl, retries)

    async def _do():
        async with session.request(method, url, **kw) as r:
            if r.status in (429, 500, 502, 503, 504):
                raise RetryableError(r.status, r.headers.get("Retry-After"))
            r.raise_for_status()
            return await r.text(errors="replace")
    return await with_retry(_do, retries)


def parse_cafef(sym: str, text: str) -> list[Doc]:
    start = text.find('class="treeview"')
    docs = []
    for row in ROW.findall(text[start:] if start >= 0 else text):
        tds = TD.findall(row)
        if len(tds) < 3:
            continue
        m = HREF.search(tds[2])
        if not m or not FILE_EXT.search(m.group(1)):
            continue
        title, when = clean(tds[0]), clean(tds[1])          # when: "Q2/2026" | "CN/2025"
        url = unescape(m.group(1)).strip()
        t = unaccent(title)
        fname = unaccent(unquote(urlsplit(url).path.rsplit("/", 1)[-1]))
        year_m = YEAR.search(when) or YEAR.search(t)
        year = int(year_m.group(1)) if year_m else None
        code = when.split("/")[0].upper()
        period = ("6T" if SEMI.search(t) or SEMI.search(fname) else
                  code if code in ("Q1", "Q2", "Q3", "Q4") else
                  "NAM" if code == "CN" else classify(title)[1])
        scope = "HN" if "hop nhat" in t else "RIENG" if ("cong ty me" in t or "rieng" in t) else "CHUNG"
        audit = "KT" if "kiem toan" in t else "SX" if "soat xet" in t else ""
        docs.append(Doc(sym, year, normalize_period(period, audit, year, cafef=True), scope, audit, title, url, "cafef"))
    return docs


async def list_cafef(session, sym, retries) -> list[Doc]:
    text = await fetch_text(session, CAFEF_LIST.format(sym=sym), retries)
    return parse_cafef(sym, text)


def not_bctc(t: str) -> bool:
    """Loại báo cáo thường niên, nghị quyết...; vẫn giữ 'BCTC kèm giải trình'."""
    if NEVER_BCTC.search(t) or ("giai trinh" in t and not re.search(r"(kem|va) giai trinh", t)):
        return True
    return any(w in t for w in NOT_BCTC) and not re.search(r"bao ?cao ?tai ?chinh|financial statement", t)


def is_bctc(text: str) -> bool:
    t = re.sub(r"[_\-.+]", " ", unaccent(text))
    return any(w in t for w in BCTC_WORDS) and not not_bctc(t)


def is_title_key(k: str) -> bool:
    k = k.lower().replace("_", "")
    return k in TITLE_KEYS or k.endswith("title") or k.endswith("name")


def walk_json(obj, base: str, parent_title: str = "", href_re: re.Pattern | None = None):
    """Tìm mọi cặp (url file, tiêu đề) trong JSON bất kỳ; tiêu đề kế thừa từ object cha.
    Chuỗi chứa HTML (VCB 'Html', WordPress 'content.rendered', LPB 'content') thì bóc <a href> trong đó;
    href_re cho phép nhận link tải không có đuôi .pdf (LPB: .../file/view/<uuid>)."""
    if isinstance(obj, dict):
        own = ""
        for k, v in obj.items():
            if not is_title_key(k):
                continue
            if isinstance(v, dict):                     # WordPress: "title": {"rendered": "..."}
                v = next((x for x in (v.get("rendered"), v.get("value"), v.get("text")) if isinstance(x, str)), "")
            if isinstance(v, str) and 0 < len(v) < 400:
                own = clean(v)
                break
        # Ghép tiêu đề cha + con: VPB "BCTC Quý 2 năm 2026" > "1. BCTC hợp nhất"
        title = (f"{parent_title} {own}" if own and parent_title and own not in parent_title
                 else own or parent_title)[:300]
        for v in obj.values():
            if isinstance(v, str):
                if (FILE_EXT.search(v.split("?")[0]) or (href_re and href_re.search(v))) and "<" not in v:
                    yield urljoin(base, v.strip().replace(" ", "%20")), title
                elif "href" in v:
                    for m in ANCHOR.finditer(v):
                        if FILE_EXT.search(m.group(1)) or (href_re and href_re.search(m.group(1))):
                            inner = clean(m.group(2))
                            yield (urljoin(base, unescape(m.group(1)).strip().replace(" ", "%20")),
                                   f"{title} {inner}".strip())
            elif isinstance(v, (dict, list)):
                yield from walk_json(v, base, title, href_re)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_json(v, base, parent_title, href_re)


def json_strings(obj) -> str:
    """Mọi chuỗi trong JSON nối lại -> dùng regex tìm link bài viết trong JSON trả HTML (PV GAS)."""
    if isinstance(obj, dict):
        return "\n".join(json_strings(v) for v in obj.values())
    if isinstance(obj, list):
        return "\n".join(json_strings(v) for v in obj)
    return obj if isinstance(obj, str) else ""


def unwrap_json(text: str):
    """JSON trả về trực tiếp, hoặc DOM Chrome bọc JSON trong <pre> (khi đọc API qua trình duyệt)."""
    s = text.lstrip()
    if s[:1] in "[{":
        return json.loads(s)
    m = re.search(r"<pre[^>]*>(.*?)</pre>", text, re.S)
    if m:
        return json.loads(unescape(m.group(1)))
    raise ValueError("không phải JSON")


def fill_year(value, y: int, q: int | None = None):
    """Thay '{year}' / '{q}' trong url/params/body (không dùng str.format vì URL Sitecore có sẵn '{GUID}')."""
    if isinstance(value, str):
        value = value.replace("{year}", str(y))
        return value.replace("{q}", str(q)) if q is not None else value
    if isinstance(value, dict):
        return {k: fill_year(v, y, q) for k, v in value.items()}
    if isinstance(value, list):
        return [fill_year(v, y, q) for v in value]
    return value


# ------------------------------------------------------------------ trình duyệt thật (Cloudflare)
CHROME = next((p for p in (os.environ.get("CHROME_PATH", ""),
                           r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                           r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                           r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                           r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                           shutil.which("chrome") or "", shutil.which("google-chrome") or "")
               if p and Path(p).exists()), None)
BROWSER_UA = UA.replace("Chrome/124.0", "Chrome/141.0.0.0")
_profiles: asyncio.Queue | None = None


async def browser_get(url: str, wait_ms: int = 20000) -> str:
    """Mở trang bằng Chrome/Edge headless thật -> DOM sau khi chạy JS. Vượt được trang chờ
    "Just a moment..." của Cloudflare (VHM, VIC, VPL, SHB) mà HTTP thường bị chặn 403.
    Mỗi lần dùng 1 profile riêng trong pool 3 profile -> chạy song song được, giữ cookie cf_clearance."""
    global _profiles
    if not CHROME:
        raise RuntimeError("không tìm thấy Chrome/Edge (đặt biến CHROME_PATH)")
    if _profiles is None:
        _profiles = asyncio.Queue()
        for i in range(3):
            _profiles.put_nowait(ROOT / ".chrome" / f"p{i}")
    prof = await _profiles.get()
    try:
        args = [CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                f"--user-data-dir={prof}", f"--user-agent={BROWSER_UA}", "--lang=vi-VN",
                f"--virtual-time-budget={wait_ms}", "--dump-dom", url]
        proc = await asyncio.to_thread(subprocess.run, args, capture_output=True, timeout=120)
        dom = proc.stdout.decode("utf-8", "replace")
        if "Just a moment" in dom[:3000] or len(dom) < 500:
            raise RuntimeError("trình duyệt chưa qua được trang chờ chống bot")
        return dom
    finally:
        _profiles.put_nowait(prof)


async def get_page(session, co: dict, url: str, retries: int, method: str = "GET", **kw) -> str:
    """Lấy 1 trang theo cách cấu hình cho công ty: http (mặc định) | curl | browser; 'ua' đổi User-Agent."""
    fetcher = co.get("fetcher", "http")
    if kw.get("params"):
        url = str(yarl.URL(url).update_query(kw.pop("params")))
    if fetcher == "browser" and method == "GET":
        return await with_retry(lambda: browser_get(url), min(retries, 1))
    if co.get("ua"):
        kw["headers"] = {**(kw.get("headers") or {}), "User-Agent": co["ua"]}
    return await fetch_text(session, url, retries, method=method, use_curl=fetcher == "curl", **kw)


async def expand_pages(session, co: dict, retries: int, years: list[int]) -> list[str]:
    """Danh sách trang cần đọc: bctc_pages / bctc_url; year_url với {year} (và {q} nếu trang chia theo quý);
    year_links: tự tìm link trang từng năm trên trang chính (slug năm không đều như Sabeco 2026-2, 2019-5)."""
    if co.get("year_url"):
        tpl = co["year_url"]
        qs = [4, 3, 2, 1] if "{q}" in tpl else [None]
        return [fill_year(tpl, y, q) for y in years for q in qs]
    pages = []
    for p in co.get("bctc_pages") or [co["bctc_url"]]:      # bctc_pages có thể chứa {year}
        pages += [fill_year(p, y) for y in years] if "{year}" in p else [p]
    if co.get("year_links"):
        text = await get_page(session, co, co["bctc_url"], retries)
        found = {}
        for m in re.finditer(co["year_links"], text):
            if int(m.group(2)) in years:
                found.setdefault(int(m.group(2)), urljoin(co["bctc_url"], unescape(m.group(1))))
        pages += [found[y] for y in sorted(found, reverse=True) if found[y] not in pages]
    return pages


def real_file_url(href: str) -> str:
    """Link dạng trình xem /viewer.html?file=https%3A%2F%2F...pdf (Vingroup) -> link file thật."""
    q = urlsplit(href).query
    if q:
        for part in q.split("&"):
            k, _, v = part.partition("=")
            v = unquote(v)
            if k.lower() in ("file", "url", "src") and FILE_EXT.search(v.split("?")[0]):
                return v
    return href


def row_text(html: str, pos: int) -> str:
    """Tiêu đề = chữ trong hàng (<tr>/<li>) chứa link; dùng khi link chỉ là icon tải về."""
    starts = [html.rfind(tag, 0, pos) for tag in ("<tr", "<li")]
    start = max(starts)
    if start < 0 or pos - start > 3000:
        start = max(0, pos - 400)
    end_candidates = [i for i in (html.find("</tr>", pos), html.find("</li>", pos)) if i >= 0]
    end = min(end_candidates + [pos + 400])
    return clean(html[start:end])[:200]


PAGE_TITLE = re.compile(r"<h1[^>]*>(.*?)</h1>|<title[^>]*>(.*?)</title>", re.S | re.I)


async def collect_links(session, co: dict, retries: int, years: list[int],
                        raw_pages: list | None = None) -> list[tuple[str, str]]:
    """Đi vào web IR, trả về [(link file, tiêu đề)]. Chế độ (fetch_mode):
      static_html : đọc trang (có thể chia theo năm/quý), lấy <a href> tới file
      json_api    : gọi API JSON, tự dò mọi link file + tiêu đề trong JSON (kể cả HTML nhúng trong JSON)
      two_step    : trang/API danh sách -> link bài chi tiết (follow_regex) -> file trong từng bài
      custom      : hàm riêng trong ir_adapters.py (API mã hoá, cần token, danh mục động...)
    Lỗi ở 1 trang (VD quý chưa có trang) không làm hỏng cả công ty."""
    mode = co.get("fetch_mode")
    pairs: list[tuple[str, str]] = []
    link_re = re.compile(co["link_regex"], re.I) if co.get("link_regex") else None
    href_re = re.compile(co["href_regex"], re.I) if co.get("href_regex") else None
    seen: set[str] = set()

    def add(href: str, page: str, title: str):
        url = urljoin(page, real_file_url(unescape(href).strip()).replace(" ", "%20"))
        if canon(url) not in seen:
            seen.add(canon(url))
            pairs.append((url, title.strip()))

    def scan(text: str, page: str, prefix: str = ""):
        if raw_pages is not None:
            raw_pages.append((page, text))
        for m in ANCHOR.finditer(text):                  # <a href=...>tiêu đề</a>
            href = unescape(m.group(1))
            if FILE_EXT.search(real_file_url(href).split("#")[0]) or (href_re and href_re.search(href)):
                inner = clean(m.group(2))
                add(href, page, f"{prefix} {inner if len(inner) > 12 else row_text(text, m.start())}")
        if link_re:   # link không nằm trong <a> chuẩn: object JS (BIDV), JSON nhúng (ACB, FPT), HTML thiếu nháy (VJC)
            for m in link_re.finditer(text.replace("\\/", "/")):
                href = m.group(1) if m.groups() else m.group(0)
                add(href, page, f"{prefix} {row_text(text, m.start()) if co.get('title_from_row') else ''}")

    async def safe_get(url: str, **kw) -> str | None:
        try:
            return await get_page(session, co, url, retries, **kw)
        except Exception as e:  # noqa: BLE001
            if len(years) <= 2 or "404" not in str(e):
                print(f"  ! {co['ticker']}: {url[:90]} -> {type(e).__name__}: {str(e)[:80]}")
            return None

    if mode == "custom":
        import ir_adapters
        fn = ir_adapters.ADAPTERS[co["adapter"]]
        return await fn(lambda url, **kw: get_page(session, co, url, retries, **kw), years)

    if mode == "json_api":
        api = co["api"]
        per_year = "{year}" in json.dumps(api, ensure_ascii=False)
        for y in (years if per_year else [0]):
            a = fill_year(api, y) if per_year else api
            kw = {"method": a.get("method", "GET").upper(), "headers": a.get("headers")}
            if isinstance(a.get("params"), dict):
                kw["params"] = dict(a["params"])
            if isinstance(a.get("json"), dict):
                kw["json"] = a["json"]
            text = await safe_get(a["url"], **kw)
            if text is None:
                continue
            base = a.get("base") or a["url"]
            if raw_pages is not None:
                raw_pages.append((base, text))
            for url, title in walk_json(unwrap_json(text), base, href_re=href_re):
                add(url, base, title)
            if link_re:
                scan(text, base)
        return pairs

    pages = await expand_pages(session, co, retries, years)
    if mode == "static_html":
        texts = await asyncio.gather(*(safe_get(p) for p in pages))
        for page, text in zip(pages, texts):
            if text:
                try:                                   # API "xem thêm" trả JSON chứa HTML (Masan)
                    text = json_strings(unwrap_json(text))
                except ValueError:
                    pass
                scan(text, page)
        return pairs

    if mode == "two_step":
        follow = re.compile(co["follow_regex"], re.I)
        details: list[str] = []
        for page in pages:
            text = await safe_get(page)
            if not text:
                continue
            try:
                text = json_strings(unwrap_json(text))        # API danh sách trả JSON có HTML bên trong
            except ValueError:
                pass
            for m in follow.finditer(text.replace("\\/", "/")):
                u = urljoin(page, unescape(m.group(1)))
                if u not in details:
                    details.append(u)
        details = details[: co.get("max_follow", 10)]
        sem = asyncio.Semaphore(4)

        async def one(u):
            async with sem:
                return u, await safe_get(u)
        for u, text in await asyncio.gather(*(one(u) for u in details)):
            if text:
                t = next((clean(a or b) for a, b in PAGE_TITLE.findall(text) if clean(a or b)), "")
                scan(text, u, prefix=t)
        return pairs
    return pairs


async def ai_pick_links(co: dict, raw_pages: list, years: list[int]) -> list[tuple[str, str]]:
    """AI dự phòng: khi luật không nhận ra BCTC nào (web đổi giao diện...), đưa danh sách link trên trang
    cho Gemini chọn link BCTC + kỳ. Cần GEMINI_API_KEY; không có key thì bỏ qua."""
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or _env_key()
    if not key or not raw_pages:
        return []
    from google import genai
    from google.genai import types
    from pydantic import BaseModel

    class Link(BaseModel):
        url: str
        ky: str          # VD Q2/2026, 6T/2026, NAM/2025
        pham_vi: str     # hop_nhat | rieng | chung

    cands, seen = [], set()
    for page, text in raw_pages:
        for m in ANCHOR.finditer(text):
            u = urljoin(page, real_file_url(unescape(m.group(1)).strip()))
            if u not in seen and not u.startswith(("javascript", "mailto", "#")):
                seen.add(u)
                cands.append(f"{u} | {clean(m.group(2))[:80] or row_text(text, m.start())[:80]}")
    if not cands:
        return []
    prompt = (f"Đây là các link trên trang quan hệ nhà đầu tư của {co.get('name', co['ticker'])} ({co['ticker']}). "
              f"Chọn các link TẢI FILE báo cáo tài chính (quý, bán niên, năm) của năm {', '.join(map(str, years))}. "
              "Bỏ qua giải trình, nghị quyết, báo cáo thường niên, tin tức, bản tiếng Anh nếu có bản tiếng Việt.\n\n"
              + "\n".join(cands[:400]))
    client = genai.Client(api_key=key)
    resp = await client.aio.models.generate_content(
        model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"), contents=prompt,
        config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                           response_schema=list[Link]))
    links = resp.parsed or []
    return [(x.url, f"Báo cáo tài chính {x.ky.replace('/', ' năm ')} {x.pham_vi.replace('_', ' ')}") for x in links]


def _env_key() -> str | None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() in ("GEMINI_API_KEY", "GOOGLE_API_KEY") and v.strip():
                return v.strip().strip('"').strip("'")
    return None


async def list_official(session, co: dict, retries, years: set[int], ai: bool = True) -> list[Doc]:
    """Web IR chính thức -> danh sách Doc đã phân loại. Không nhận ra BCTC nào -> nhờ AI chọn link."""
    if co.get("fetch_mode") not in ("static_html", "json_api", "two_step", "custom"):
        return []
    year_list = sorted(years, reverse=True)
    raw_pages: list = []
    pairs = await collect_links(session, co, retries, year_list, raw_pages)
    docs = to_docs(co, pairs)
    if ai and not any(d.year in years for d in docs):
        try:
            picked = await ai_pick_links(co, raw_pages, year_list)
            if picked:
                print(f"  * {co['ticker']}: luật không nhận ra BCTC, AI chọn được {len(picked)} link")
                docs = to_docs({**co, "page_is_bctc": True}, picked, source="official-ai")
        except Exception as e:  # noqa: BLE001
            print(f"  ! {co['ticker']}: AI dự phòng lỗi ({type(e).__name__}: {str(e)[:80]})")
    return docs


def to_docs(co: dict, pairs: list[tuple[str, str]], source: str = "official") -> list[Doc]:
    docs, seen = [], set()
    for url, title in pairs:
        # Tên file = đoạn path cuối có đuôi file (Liferay: .../BCTC HN_Q2.pdf.pdf/<uuid>?download=true)
        segs = unquote(urlsplit(url).path).split("/")
        name = next((s for s in reversed(segs) if re.search(r"\.(pdf|zip|rar|docx?|xlsx?)", s, re.I)), "")
        if "<" in title or "href" in title:           # HTML hỏng -> tiêu đề rác
            title = ""
        label = f"{title} {name}"
        # Trang chỉ đăng BCTC (page_is_bctc) thì không bắt buộc tên file có chữ "BCTC";
        # nhưng file tự nó là giải trình/nghị quyết... thì luôn loại.
        drop = (not co.get("page_is_bctc") and not is_bctc(label)) or not_bctc(
            re.sub(r"[_\-.+]", " ", unaccent(name or title)))
        if canon(url) in seen or drop:
            continue
        seen.add(canon(url))
        # Tên file chính xác hơn tiêu đề (tiêu đề hay chứa ngày đăng: "30/01/2026: BCTC Q4/2025").
        y1, p1, s1, a1 = classify(name) if name else (None, "NA", "CHUNG", "")
        y2, p2, s2, a2 = classify(title)
        year, audit = y1 or y2, a1 or a2
        period = normalize_period(p1 if p1 != "NA" else p2, audit, year)
        docs.append(Doc(co["ticker"], year, period, s1 if s1 != "CHUNG" else s2, audit,
                        (title or name)[:200], url, source))
    return docs


# ------------------------------------------------------------------ network
class RetryableError(Exception):
    def __init__(self, status, retry_after=None):
        super().__init__(f"HTTP {status}")
        self.retry_after = retry_after


async def with_retry(fn, retries: int):
    for attempt in range(retries + 1):
        try:
            return await fn()
        except (RetryableError, aiohttp.ClientConnectionError, aiohttp.ClientPayloadError,
                asyncio.TimeoutError) as e:
            if attempt == retries:
                raise
            ra = getattr(e, "retry_after", None)
            delay = float(ra) if ra and str(ra).isdigit() else 0.5 * 2 ** attempt
            await asyncio.sleep(delay + random.uniform(0, 0.3))


# ------------------------------------------------------------------ download
class Downloader:
    def __init__(self, session, out: Path, manifest: dict, args, curl_hosts: set[str] = frozenset(),
                 host_ua: dict | None = None):
        self.host_ua = host_ua or {}
        self.curl_hosts = curl_hosts if CURL else set()
        self.session, self.out, self.manifest, self.args = session, out, manifest, args
        self.hashes = {v["sha256"]: v["path"] for v in manifest.values() if v.get("sha256")}
        self.claimed = {v["path"] for v in manifest.values()}
        self.stats = {"ok": 0, "skip": 0, "dup": 0, "fail": 0, "bytes": 0}
        self.failed: list[tuple[Doc, str]] = []
        self.host_sems: dict[str, asyncio.Semaphore] = {}
        self.alts: dict[str, list[Doc]] = {}          # canon(url) -> bản dự phòng cùng kỳ

    def dest_for(self, doc: Doc) -> Path:
        rel = Path(doc.ticker) / str(doc.year or "NA") / f"{doc.basename()}.{doc.ext()}"
        if rel.as_posix() in self.claimed:
            rel = rel.with_name(f"{doc.basename()}_{hashlib.sha1(canon(doc.url).encode()).hexdigest()[:6]}.{doc.ext()}")
        self.claimed.add(rel.as_posix())
        return rel

    async def handle(self, doc: Doc):
        k = canon(doc.url)
        rec = self.manifest.get(k)
        if rec and (self.out / rec["path"]).exists():          # đã tải ở lần chạy trước
            self.stats["skip"] += 1
            rec.update({k: v for k, v in asdict(doc).items() if k != "url"})   # nhãn theo luật phân loại mới nhất
            return
        rel = Path(rec["path"]) if rec else self.dest_for(doc)
        # Link hỏng (404...) -> thử lần lượt bản dự phòng cùng kỳ: bản CafeF khác, rồi bản trên web IR
        candidates = [doc.url] + [a.url for a in self.alts.get(k, [])]
        err = None
        for url in candidates:
            host = urlsplit(url).hostname or ""
            sem = self.host_sems.setdefault(host, asyncio.Semaphore(self.args.per_host))
            try:
                async with sem:
                    t0 = time.perf_counter()
                    get = self._get_curl if host in self.curl_hosts else self._get
                    size, digest = await with_retry(lambda: get(url, self.out / rel), self.args.retries)
                break
            except Exception as e:  # noqa: BLE001 - ghi lại mọi lỗi, không dừng cả batch
                err = e
        else:
            self.stats["fail"] += 1
            self.failed.append((doc, f"{type(err).__name__}: {err}"))
            print(f"  x {doc.ticker} {doc.year} {doc.period} {doc.scope}: {err}"
                  + (f" (đã thử {len(candidates) - 1} bản dự phòng)" if len(candidates) > 1 else ""))
            return
        if url != doc.url:
            print(f"  ~ {doc.ticker} {doc.year} {doc.period} {doc.scope}: link gốc hỏng, dùng bản dự phòng {url}")
        if digest in self.hashes and self.hashes[digest] != rel.as_posix():   # trùng nội dung
            (self.out / rel).unlink(missing_ok=True)
            rel_s, self.stats["dup"] = self.hashes[digest], self.stats["dup"] + 1
        else:
            rel_s = rel.as_posix()
            self.hashes[digest] = rel_s
            self.stats["ok"] += 1
            self.stats["bytes"] += size
            print(f"  + {rel_s}  {size / 1e6:.1f}MB  {time.perf_counter() - t0:.1f}s")
        self.manifest[k] = {**asdict(doc), "path": rel_s, "sha256": digest, "size": size,
                            "downloaded_at": datetime.now().isoformat(timespec="seconds"),
                            **({"url_used": url} if url != doc.url else {})}

    async def _get_curl(self, url: str, dest: Path) -> tuple[int, str]:
        """Host chặn TLS của Python (Cloudflare) -> tải bằng curl rồi kiểm tra như thường."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        status, _ = await curl_get(url, dest=part)
        if status in (429, 500, 502, 503, 504):
            raise RetryableError(status)
        if status >= 400:
            part.unlink(missing_ok=True)
            raise RuntimeError(f"HTTP {status}")
        h = hashlib.sha256()
        with open(part, "rb") as f:
            if not f.read(1024).lstrip()[:8].startswith(MAGIC):
                raise ValueError("không phải file BCTC")
            f.seek(0)
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        os.replace(part, dest)
        return dest.stat().st_size, h.hexdigest()

    async def _get(self, url: str, dest: Path) -> tuple[int, str]:
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        pos = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={pos}-"} if pos else {}
        if self.host_ua.get(urlsplit(url).hostname):
            headers["User-Agent"] = self.host_ua[urlsplit(url).hostname]
        async with self.session.get(url, headers=headers) as r:
            if r.status == 416:                       # .part hỏng -> tải lại từ đầu
                part.unlink(missing_ok=True)
                raise RetryableError(416)
            if r.status in (429, 500, 502, 503, 504):
                raise RetryableError(r.status, r.headers.get("Retry-After"))
            r.raise_for_status()
            resume = pos > 0 and r.status == 206
            h = hashlib.sha256()
            if resume:
                with open(part, "rb") as f:
                    for block in iter(lambda: f.read(1 << 20), b""):
                        h.update(block)
            first = not resume
            with open(part, "ab" if resume else "wb") as f:
                async for chunk in r.content.iter_chunked(1 << 18):
                    if first:
                        head = chunk.lstrip()[:8]
                        if not head.startswith(MAGIC):
                            raise ValueError(f"không phải file BCTC (đầu file: {head!r})")
                        first = False
                    f.write(chunk)
                    h.update(chunk)
        os.replace(part, dest)
        return dest.stat().st_size, h.hexdigest()


# ------------------------------------------------------------------ pipeline
def parse_years(spec: str) -> set[int] | None:
    if spec == "all":
        return None
    years: set[int] = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        years.update(range(int(a), int(b or a) + 1))
    return years


def select(docs: list[Doc], args) -> list[Doc]:
    years = parse_years(args.years)
    out = [d for d in docs
           if (years is None or d.year in years)
           and (not args.scope or d.scope in args.scope or d.scope == "CHUNG")   # CHUNG = BCTC duy nhất của cty không có cty con
           and (not args.periods or d.period in args.periods)]
    out.sort(key=lambda d: d.sort_key, reverse=True)
    if args.latest:
        keep = sorted({d.sort_key for d in out}, reverse=True)[: args.latest]
        out = [d for d in out if d.sort_key in keep]
    return out


def merge(cafef: list[Doc], official: list[Doc]) -> list[Doc]:
    """CafeF làm gốc (metadata chuẩn); web IR chỉ bổ sung kỳ CafeF chưa có (thường là bản vừa đăng).
    So theo (mã, năm, kỳ): web IR đặt tên rất không đồng nhất (bản ký số, bản tra cứu, "riengle"...),
    nên kỳ nào CafeF đã có thì tin CafeF; chỉ kỳ CafeF chưa có mới lấy từ web IR."""
    if not cafef:
        return official
    seen_url = {canon(d.url) for d in cafef}
    seen_key = {d.key[:3] for d in cafef}
    extra = []
    for d in official:
        if canon(d.url) in seen_url or not d.year or d.period == "NA" or d.key[:3] in seen_key:
            continue
        extra.append(d)
    return cafef + extra


def _rank_ir(d: Doc) -> tuple:
    """Chọn 1 bản/kỳ trên web IR: tiếng Việt hơn tiếng Anh; 'bản tra cứu' (có sẵn chữ, khỏi OCR) hơn bản scan ký số."""
    t = re.sub(r"[_\-.+%]", " ", unaccent(f"{d.title} {unquote(urlsplit(d.url).path)}"))
    english = bool(re.search(r"\b(en|eng|english|tieng anh)\b|financial statements?|reviewed|consolidated|separate", t)
                   and not re.search(r"bao cao tai chinh|bctc|\bvn\b|\bvie\b|tieng viet", t))
    searchable = bool(re.search(r"tra cuu|searchable", t))
    return (not english, searchable)


def merge_ir_first(official: list[Doc], cafef: list[Doc]) -> list[Doc]:
    """Web công ty làm gốc (đăng sớm hơn CafeF vài giờ - vài ngày); mỗi (mã, năm, kỳ, phạm vi) giữ 1 bản tốt nhất.
    CafeF chỉ bù những kỳ web công ty không có (VD năm cũ web không còn lưu)."""
    best: dict[tuple, Doc] = {}
    for d in official:
        if d.year and d.period != "NA":
            k = d.key[:4]
            if k not in best or _rank_ir(d) > _rank_ir(best[k]):
                best[k] = d
    have = {k[:3] for k in best}
    return list(best.values()) + [d for d in cafef if d.key[:3] not in have]


def load_companies(args) -> list[dict]:
    data = json.loads((ROOT / "companies.json").read_text(encoding="utf-8"))
    by_tk = {c["ticker"]: c for c in data["companies"]}
    if not args.tickers:
        return list(by_tk.values())
    return [by_tk.get(t, {"ticker": t}) for t in args.tickers]   # mã ngoài VN30 vẫn chạy được qua CafeF


async def run(args) -> int:
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    mpath = out / "manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {}
    companies = load_companies(args)

    # +8 slot để request lấy danh mục không phải xếp hàng sau các file đang tải
    conn = aiohttp.TCPConnector(limit=args.concurrency + 8, limit_per_host=max(args.per_host, 8),
                                ttl_dns_cache=600)
    timeout = aiohttp.ClientTimeout(total=None, connect=15, sock_read=60)
    this_year = date.today().year
    official_years = {y for y in (parse_years(args.years) or range(this_year - 9, this_year + 1))
                      if y <= this_year}
    index: list[Doc] = []
    queue: asyncio.Queue = asyncio.Queue()
    t0 = time.perf_counter()

    async with aiohttp.ClientSession(connector=conn, timeout=timeout,
                                     headers={"User-Agent": UA, "Accept-Language": "vi,en;q=0.8"}) as session:
        curl_hosts = {urlsplit(c.get("bctc_url") or "").hostname for c in companies if c.get("fetcher") == "curl"}
        # Host cần User-Agent riêng khi tải file (VIB: Akamai chặn UA trình duyệt)
        host_ua = {urlsplit(c["bctc_url"]).hostname: c["ua"] for c in companies if c.get("ua") and c.get("bctc_url")}
        dl = Downloader(session, out, manifest, args, curl_hosts, host_ua)

        async def produce(co: dict):
            tk = co["ticker"]

            async def get_cafef():
                if args.source == "official":
                    return []
                try:
                    return await list_cafef(session, tk, args.retries)
                except Exception as e:  # noqa: BLE001
                    print(f"  ! {tk}: CafeF lỗi ({e})")
                    return []

            async def get_official():
                if args.source == "cafef" or not co.get("bctc_url"):
                    return []
                try:
                    return await list_official(session, co, args.retries, official_years)
                except Exception as e:  # noqa: BLE001
                    print(f"  ! {tk}: web IR lỗi ({type(e).__name__}: {e}) -> dùng CafeF")
                    return []

            cafef, official = await asyncio.gather(get_cafef(), get_official())    # 2 nguồn đọc song song
            if not cafef and not official:
                print(f"  ! {tk}: không lấy được danh mục")
                return
            docs = merge_ir_first(official, cafef) if args.source in ("ir-first", "official") else merge(cafef, official)
            index.extend(docs)
            chosen = select(docs, args)
            # Bản dự phòng khi link hỏng: cùng (mã, năm, kỳ, phạm vi) - các bản khác trên web IR rồi tới CafeF
            first, second = (official, cafef) if args.source in ("ir-first", "official") else (cafef, official)
            for d in chosen:
                dk = canon(d.url)
                dl.alts[dk] = [x for x in first + second
                               if x.key[:4] == d.key[:4] and canon(x.url) != dk]
            print(f"[{tk}] {len(docs)} BCTC trong danh mục, chọn {len(chosen)}")
            if not args.list_only:
                for d in chosen:
                    queue.put_nowait(d)

        async def work():
            while (doc := await queue.get()) is not None:
                await dl.handle(doc)

        workers = [asyncio.create_task(work()) for _ in range(args.concurrency)]
        try:
            await asyncio.gather(*(produce(c) for c in companies))
        finally:
            for _ in workers:
                queue.put_nowait(None)
            await asyncio.gather(*workers, return_exceptions=True)
            tmp = mpath.with_suffix(".tmp")
            tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, mpath)

    write_index(out / "index.csv", index)
    dt = time.perf_counter() - t0
    s = dl.stats
    print(f"\nXong trong {dt:.1f}s | danh mục: {len(index)} link -> {out / 'index.csv'}")
    if not args.list_only:
        print(f"Tải mới {s['ok']} file ({s['bytes'] / 1e6:.1f}MB, {s['bytes'] / 1e6 / max(dt, 1e-9):.1f}MB/s) | "
              f"bỏ qua (đã có) {s['skip']} | trùng nội dung {s['dup']} | lỗi {s['fail']}")
        if dl.failed:
            write_index(out / "failed.csv", [d for d, _ in dl.failed])
            print(f"Danh sách lỗi: {out / 'failed.csv'} (chạy lại lệnh để thử lại)")
    return 1 if s["fail"] else 0


def write_index(path: Path, docs: list[Doc]):
    docs = sorted(docs, key=lambda d: (d.ticker, d.sort_key), reverse=False)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:      # utf-8-sig: mở thẳng bằng Excel
        w = csv.writer(f)
        w.writerow(["ticker", "year", "period", "scope", "audit", "title", "url", "source"])
        for d in docs:
            w.writerow([d.ticker, d.year, d.period, d.scope, d.audit, d.title, d.url, d.source])


def main(argv=None) -> int:
    this_year = date.today().year
    ap = argparse.ArgumentParser(description="Tải BCTC VN30 (HOSE) nhanh, song song, tải tăng dần.")
    ap.add_argument("--tickers", type=lambda s: [x.strip().upper() for x in s.split(",") if x.strip()],
                    help="VD: VNM,FPT (mặc định: 30 mã trong companies.json)")
    ap.add_argument("--years", default=f"{this_year - 1}-{this_year}",
                    help="VD: 2026 | 2024-2026 | 2023,2025 | all (mặc định: 2 năm gần nhất)")
    ap.add_argument("--latest", type=int, help="Chỉ lấy N kỳ báo cáo gần nhất mỗi mã")
    ap.add_argument("--scope", type=lambda s: s.upper().split(","),
                    help="HN,RIENG (BCTC CHUNG của công ty không có công ty con luôn được giữ)")
    ap.add_argument("--periods", type=lambda s: s.upper().split(","), help="Q1,Q2,Q3,Q4,6T,NAM")
    ap.add_argument("--source", choices=["ir-first", "official", "cafef", "both"], default="ir-first",
                    help="ir-first (mặc định): web công ty là nguồn chính (đăng sớm nhất), CafeF bù kỳ thiếu "
                         "và làm dự phòng; official: chỉ web công ty; cafef: chỉ CafeF; both: CafeF chính + web bù")
    ap.add_argument("--out", default=str(ROOT / "data"), help="Thư mục lưu (mặc định: ./data)")
    ap.add_argument("--concurrency", type=int, default=8, help="Tổng số file tải song song")
    ap.add_argument("--per-host", type=int, default=4,
                    help="Số kết nối tối đa mỗi host (đo thực tế: >4 không nhanh hơn, dễ bị CDN bóp)")
    ap.add_argument("--retries", type=int, default=4)
    ap.add_argument("--list-only", action="store_true", help="Chỉ xuất index.csv, không tải file")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nĐã dừng. Chạy lại để tải tiếp (file dở dang sẽ được resume).")
        return 130


if __name__ == "__main__":
    sys.exit(main())
