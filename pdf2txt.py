#!/usr/bin/env python3
"""Bước 3: chuyển PDF (thường hoặc scan) sang TXT.

Mỗi trang:
  - có lớp chữ tốt  -> lấy chữ trực tiếp (vài ms/trang)
  - scan / font lỗi -> OCR bằng Tesseract tích hợp sẵn trong PyMuPDF (chỉ cần tessdata/vie.traineddata,
                       không phải cài Tesseract), ~1-3 s/trang, chạy song song theo số nhân CPU thật.
Chữ được dựng lại theo toạ độ (dòng + cột) nên bảng số giữ nguyên hàng/cột.

Ví dụ:
    python pdf2txt.py                         # toàn bộ PDF trong data/ -> txt/
    python pdf2txt.py data/VNM                # một thư mục / một file
    python pdf2txt.py --pages 1-20            # chỉ 20 trang đầu (đủ cho 3 báo cáo chính)
    python pdf2txt.py --ocr always            # OCR cả trang có lớp chữ
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
import unicodedata
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent
VERSION = 1
# Ký tự đặc trưng khi PDF dùng font TCVN3/VNI hoặc mất bảng mã -> lớp chữ vô dụng, phải OCR
BAD_CHARS = set("¸µ¶·¹¨©ª«¬®¯°±²³´½¾¿�")
PAGE_MARK = re.compile(r"^=== Trang (\d+) \((text|(?:pp)?ocr(?:@\d+)?|none)\) ===$", re.M)   # ocr@90: đã xoay 90°; ppocr: ocr_so.py


# ------------------------------------------------------------------ một trang
SIGNED = re.compile(r"digitally signed|signed by|ký bởi|ký số bởi", re.I)
# Âm tiết tiếng Việt (đã bỏ dấu): phụ âm đầu + nguyên âm + phụ âm cuối
VN_SYLLABLE = re.compile(r"^(ngh|ng|nh|ch|gh|gi|kh|ph|qu|th|tr|[bcdghklmnprstvx])?[aeiouy]{1,3}(ch|ng|nh|[cmnpt])?$")


def _plain(w: str) -> str:
    w = unicodedata.normalize("NFD", w.lower().replace("đ", "d"))
    return "".join(c for c in w if unicodedata.category(c) != "Mn")


def text_ok(text: str) -> bool:
    """Lớp chữ dùng được? Trang scan có ký số vẫn mang ~40 từ của chữ ký -> bỏ khối đó trước khi đếm."""
    words = text.split()
    m = SIGNED.search(text)
    if m:                                    # bỏ ~60 từ của khối chữ ký số (DN:, CN=, OID, Reason, Date...)
        start = len(text[:m.start()].split())
        words = words[:start] + words[start + 60:]
    s = " ".join(words)
    if len(words) < 50 or len(s) < 200:      # trang scan chỉ còn vài chữ của con dấu/chữ ký
        return False
    bad = sum(c in BAD_CHARS for c in s) + 5 * s.count("(cid:")
    if bad / len(s) >= 0.01:
        return False
    # Font không map được chữ có dấu -> rơi ký tự: "h p nh t", "Chu k s n xu ng" -> nhiều "từ" 1 chữ cái
    alpha = [w for w in words if w.isalpha()]
    if alpha and sum(len(w) == 1 for w in alpha) / len(alpha) >= 0.2:
        return False
    # Font mã hoá lạ / OCR kém có sẵn: "rHLrc/NG MAr cd", "TiEn g&itai Ngen heng" -> nhiều "từ" không phải âm tiết.
    # Đo: trang tốt 0,87-1,0; trang hỏng (HDB) 0,60-0,66 -> ngưỡng 0,8
    syl = [_plain(w) for w in alpha if len(w) >= 2]
    return len(syl) < 30 or sum(bool(VN_SYLLABLE.match(w)) for w in syl) / len(syl) >= 0.8


def layout(words: list, page_width: float) -> str:
    """Ghép từ thành dòng theo toạ độ y, căn cột theo toạ độ x (giống pdftotext -layout)."""
    if not words:
        return ""
    hs = sorted(w[3] - w[1] for w in words)
    h = max(hs[len(hs) // 2], 4.0)        # chiều cao chữ trung vị
    cw = h * 0.5                          # bề rộng 1 ký tự ước lượng
    words = sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines, cur, y0 = [], [], None
    for w in words:
        yc = (w[1] + w[3]) / 2
        if cur and abs(yc - y0) > h * 0.6:
            lines.append(cur)
            cur = []
        if not cur:
            y0 = yc
        cur.append(w)
    lines.append(cur)
    out = []
    for ln in lines:
        s = ""
        for w in sorted(ln, key=lambda w: w[0]):
            col = int(w[0] / cw)
            s += (" " * max(1, col - len(s)) if s else " " * min(col, 40)) + w[4]
        out.append(s.rstrip())
    return "\n".join(out)


def _init_worker():
    # Tesseract in vài cảnh báo vô hại ("Parameter not found") ra stderr -> tắt cho gọn
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 2)


def vn_score(text: str) -> float:
    """Độ 'giống tiếng Việt' của chữ OCR = số âm tiết hợp lệ × (tỷ lệ âm tiết hợp lệ)².
    OCR trang scan nằm ngang vẫn lọt nhiều mẩu ngắn tình cờ hợp lệ ("ae", "go", "sẽ") nhưng tỷ lệ chỉ ~0,3
    so với ~0,75 của chữ thật -> bình phương tỷ lệ để tách rõ (đo: rác ~1-2 điểm, tiêu đề thật 10-30)."""
    toks = [w for w in text.split() if len(w) >= 2]
    if not toks:
        return 0.0
    valid = sum(1 for w in toks if w.isalpha() and VN_SYLLABLE.match(_plain(w)))
    return valid * (valid / len(toks)) ** 2


def rot_of(method: str) -> int:
    """'ocr@90' -> 90: góc phải xoay thêm vì trang được scan nằm ngang/ngược."""
    return int(method.split("@")[1]) if "@" in method else 0


def _best_rotation(page, ocr_text, min_score: int, prefer: int = 0) -> tuple[int, str]:
    """OCR ra rác (ít âm tiết tiếng Việt) -> thử xoay 90/270/180 độ, giữ góc cho nhiều âm tiết nhất.
    prefer: góc đã đúng ở trang trước (cùng file thường scan cùng một kiểu) -> thử trước."""
    base = page.rotation
    order = [prefer] + [r for r in (0, 90, 270, 180) if r != prefer]
    best = (-1.0, 0, "")
    for r in order:
        page.set_rotation((base + r) % 360)
        text = ocr_text(page)
        sc = vn_score(text)
        if sc > best[0]:
            best = (sc, r, text)
        if r == 0:
            sc0, text0 = sc, text
        if sc >= min_score:          # chắc chắn là chữ thật -> khỏi thử tiếp
            break
    # Chỉ xoay khi góc mới tốt hơn RÕ RỆT (tránh xoay nhầm trang ít chữ như biểu đồ, trang trắng)
    if best[1] != 0 and "sc0" in locals() and best[0] < max(1.5, 2 * sc0):
        best = (sc0, 0, text0)
    page.set_rotation((base + best[1]) % 360)
    return best[1], best[2]


def convert_pages(pdf: str, pages: list[int], ocr: str, dpi: int, tessdata: str, lang: str,
                  rots: dict | None = None):
    """Chạy trong process con. Trả về {số trang (1-based): (cách lấy, văn bản)}.
    rots: góc xoay thêm đã biết cho từng trang (từ scan_titles); không có thì tự dò nếu OCR ra rác."""
    doc = pymupdf.open(pdf)
    res = {}
    prefer = 0
    for pno in pages:
        page = doc[pno - 1]
        words = [] if ocr == "always" else page.get_text("words")
        method = "text"
        if ocr == "always" or (ocr == "auto" and not text_ok(" ".join(w[4] for w in words))):
            try:
                def ocr_words(pg):
                    tp = pg.get_textpage_ocr(language=lang, dpi=dpi, full=True, tessdata=tessdata)
                    return pg.get_text("words", textpage=tp)
                known = (rots or {}).get(pno)
                if known is not None:
                    page.set_rotation((page.rotation + known) % 360)
                    words, extra = ocr_words(page), known
                else:
                    words, extra = ocr_words(page), 0
                    # Nhiều chữ mà toàn rác -> trang scan nằm ngang (trang ít chữ như bìa, chữ ký thì bỏ qua cho nhanh)
                    if len(words) >= 40 and vn_score(" ".join(w[4] for w in words)) < 10:
                        cache = {}

                        def text_at(pg):
                            cache[pg.rotation] = ocr_words(pg)
                            return " ".join(w[4] for w in cache[pg.rotation])
                        page_rot0 = page.rotation
                        extra, _ = _best_rotation(page, text_at, 30, prefer)
                        words = cache[(page_rot0 + extra) % 360]
                        prefer = extra
                method = f"ocr@{extra}" if extra else "ocr"
            except Exception:  # noqa: BLE001 - trang hỏng thì giữ lớp chữ (nếu có)
                method = "text" if words else "none"
        if page.rotation:                # trang lưu xoay (VD 270°): đưa toạ độ về hướng hiển thị
            m = page.rotation_matrix
            words = [(*(pymupdf.Rect(w[:4]) * m), *w[4:]) for w in words]
        res[pno] = (method, layout(words, page.rect.width))
    return pdf, res


def scan_titles(pdf: str, pages: list[int], tessdata: str, lang: str = "vie+eng",
                frac: float = 0.3, dpi: int = 110) -> dict[int, tuple[str, str]]:
    """Đọc vùng tiêu đề (30% đầu trang) để tìm trang báo cáo: OCR ~0,25 s/trang thay vì ~1-3 s cả trang.
    Luôn OCR vùng này kể cả trang có lớp chữ: lớp chữ BCTC hay hỏng (chỉ có chữ ký số, font mất dấu,
    OCR kém của chính công ty) mà rẻ hơn không đáng kể. Trả về {trang: (lớp chữ dùng được? text|ocr, chữ vùng đầu)}."""
    doc = pymupdf.open(pdf)
    out = {}
    prefer = 0

    def top_text(pg):
        r = pg.rect
        top = pymupdf.Rect(r.x0, r.y0, r.x1, r.y0 + r.height * frac)
        pix = pg.get_pixmap(dpi=dpi, clip=top)   # phải là RGB: ảnh xám -> Tesseract tích hợp trả về rỗng
        return pymupdf.open("pdf", pix.pdfocr_tobytes(language=lang, tessdata=tessdata))[0].get_text()

    for pno in pages:
        page = doc[pno - 1]
        method = "text" if text_ok(page.get_text()) else "ocr"
        try:
            text, extra = top_text(page), 0
            if method == "ocr" and len(text.split()) >= 12 and vn_score(text) < 3:   # nhiều chữ rác -> scan nằm ngang
                extra, text = _best_rotation(page, top_text, 6, prefer)
                prefer = extra
            out[pno] = (f"{method}@{extra}" if extra else method, text)
        except Exception:  # noqa: BLE001
            out[pno] = (method, "")
    return out


def default_workers() -> int:
    # Đo trên máy 6 nhân/12 luồng: OCR nhanh nhất ở 4-6 tiến trình, 12 tiến trình còn chậm hơn
    # (Tesseract tranh bộ nhớ/cache) -> mặc định = số nhân thật.
    return max(1, (os.cpu_count() or 2) // 2)


# ------------------------------------------------------------------ file txt
def read_txt(path: Path) -> dict[int, tuple[str, str]]:
    """Đọc lại txt đã tạo -> {trang: (cách lấy, văn bản)}."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    marks = list(PAGE_MARK.finditer(text))
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out[int(m[1])] = (m[2], text[m.end():end].strip("\n"))
    return out


def write_txt(path: Path, pdf_rel: str, n_pages: int, pages: dict[int, tuple[str, str]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    n_ocr = sum(1 for m, _ in pages.values() if "ocr" in m)
    parts = [f"# {pdf_rel} | {n_pages} trang | đã chuyển {len(pages)} trang, OCR {n_ocr} trang"]
    for pno in sorted(pages):
        method, txt = pages[pno]
        parts.append(f"=== Trang {pno} ({method}) ===\n{txt}")
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def parse_pages(spec: str | None, n: int) -> list[int]:
    if not spec:
        return list(range(1, n + 1))
    pages: set[int] = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        pages.update(range(int(a), (int(b) if b else int(a)) + 1))
    return sorted(p for p in pages if 1 <= p <= n)


def txt_path_for(pdf: Path, out_dir: Path, base: Path) -> Path:
    try:
        rel = pdf.resolve().relative_to(base.resolve())
    except ValueError:
        rel = Path(pdf.name)
    return out_dir / rel.with_suffix(".txt")


# ------------------------------------------------------------------ API dùng chung
def convert(pdfs: list[Path], out_dir: Path, base: Path, pages_spec: str | None = None,
            ocr: str = "auto", dpi: int = 200, tessdata: Path | None = None, lang: str = "vie+eng",
            workers: int | None = None, chunk: int = 4, force: bool = False, verbose: bool = True,
            ) -> dict[Path, dict[int, tuple[str, str]]]:
    """Chuyển nhiều PDF song song; chỉ xử lý trang chưa có trong txt (tăng dần). Trả về nội dung theo file."""
    tessdata = str(tessdata or ROOT / "tessdata")
    if ocr != "never" and not (Path(tessdata) / "vie.traineddata").exists():
        sys.exit(f"Thiếu {tessdata}/vie.traineddata - tải tại https://github.com/tesseract-ocr/tessdata_fast")
    results: dict[Path, dict[int, tuple[str, str]]] = {}
    pending: dict[str, dict] = {}
    tasks = []
    for pdf in pdfs:
        out = txt_path_for(pdf, out_dir, base)
        with pymupdf.open(pdf) as d:
            n = d.page_count
        want = parse_pages(pages_spec, n)
        have = {} if force else read_txt(out)
        if have and out.stat().st_mtime < pdf.stat().st_mtime:      # PDF mới hơn txt -> làm lại
            have = {}
        todo = [p for p in want if p not in have]
        results[pdf] = have
        if not todo:
            continue
        pending[str(pdf)] = {"pdf": pdf, "out": out, "n": n, "left": 0, "rel": out.relative_to(out_dir).as_posix()}
        for i in range(0, len(todo), chunk):
            tasks.append((str(pdf), todo[i:i + chunk]))
            pending[str(pdf)]["left"] += 1

    if not tasks:
        return results
    t0 = time.perf_counter()
    n_pages = sum(len(p) for _, p in tasks)
    workers = workers or default_workers()
    if verbose:
        print(f"Chuyển {n_pages} trang của {len(pending)} file bằng {workers} tiến trình...")
    done_pages = 0
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as ex:
        futs = [ex.submit(convert_pages, pdf, pages, ocr, dpi, tessdata, lang) for pdf, pages in tasks]
        for fut in as_completed(futs):
            pdf_s, res = fut.result()
            job = pending[pdf_s]
            results[job["pdf"]].update(res)
            done_pages += len(res)
            job["left"] -= 1
            if job["left"] == 0:                 # file xong -> ghi ngay, không chờ cả lô
                write_txt(job["out"], job["rel"].replace(".txt", ".pdf"), job["n"], results[job["pdf"]])
                if verbose:
                    n_ocr = sum(1 for m, _ in res.values() if m.startswith("ocr"))
                    el = time.perf_counter() - t0
                    print(f"  + {job['rel']}  ({done_pages}/{n_pages} trang, {el:.0f}s, "
                          f"{done_pages / max(el, 1e-9):.1f} trang/s){' [OCR]' if n_ocr else ''}")
    if verbose:
        el = time.perf_counter() - t0
        print(f"Xong {n_pages} trang trong {el:.1f}s ({n_pages / max(el, 1e-9):.1f} trang/s)")
    return results


def collect(paths: list[str]) -> list[Path]:
    out = []
    for p in map(Path, paths):
        if p.is_dir():
            out += sorted(p.rglob("*.pdf"))
        elif p.suffix.lower() == ".pdf" and p.exists():
            out.append(p)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Chuyển PDF thường/scan sang TXT (OCR tiếng Việt, song song).")
    ap.add_argument("paths", nargs="*", default=[str(ROOT / "data")], help="File/thư mục PDF (mặc định: data/)")
    ap.add_argument("--out", default=str(ROOT / "txt"), help="Thư mục txt (mặc định: txt/, giữ cấu trúc thư mục)")
    ap.add_argument("--pages", help="VD: 1-20 hoặc 1-5,8 (mặc định: mọi trang)")
    ap.add_argument("--ocr", choices=["auto", "always", "never"], default="auto",
                    help="auto: chỉ OCR trang không có/hỏng lớp chữ (mặc định)")
    ap.add_argument("--dpi", type=int, default=200, help="Độ phân giải OCR (mặc định 200; 300 chậm hơn ~20%%)")
    ap.add_argument("--lang", default="vie+eng")
    ap.add_argument("--tessdata", help="Thư mục chứa *.traineddata (mặc định: ./tessdata)")
    ap.add_argument("--workers", type=int, help="Số tiến trình (mặc định: số nhân CPU thật)")
    ap.add_argument("--force", action="store_true", help="Làm lại kể cả trang đã có")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    pdfs = collect(args.paths)
    if not pdfs:
        print("Không tìm thấy PDF nào.")
        return 1
    # PDF trong data/ -> txt/ giữ nguyên cấu trúc <mã>/<năm>/; PDF ở nơi khác -> theo thư mục chung
    base = ROOT / "data"
    if not all(str(p.resolve()).startswith(str(base.resolve())) for p in pdfs):
        base = Path(os.path.commonpath([str(p.resolve().parent) for p in pdfs]))
    convert(pdfs, Path(args.out), base, args.pages, args.ocr, args.dpi,
            Path(args.tessdata) if args.tessdata else None, args.lang, args.workers, force=args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
