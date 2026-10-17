#!/usr/bin/env python3
"""OCR tầng 2 cho trang báo cáo dạng scan: PP-OCRv6 (PaddleOCR, Apache-2.0) chạy bằng RapidOCR + ONNX Runtime trên CPU.

Vì sao có thêm tầng này (đo 18/10/2026 trên trang CĐKT scan của PNJ Q2/2026, 80 con số):
  - Tesseract (pdf2txt.py): 1,6 s/trang, dấu tiếng Việt tốt nhưng đọc sai 7/80 số (1 -> 4: 19.430... thành 49.430...,
    6 -> 8, cắt cụt số dài) -> AI trích phải soi ảnh sửa lại.
  - PP-OCRv6 det small + rec small, lang "vi": 5 s/trang (6 luồng), 80/80 số đúng; chữ hay mất dấu ("Tài sn ngn hn").
    Bản rec medium không đúng thêm số nào mà chậm 16 lần (81 s/trang).
Nên chia việc: Tesseract đọc nhanh cả file để tìm trang báo cáo, PP-OCRv6 chỉ đọc lại các trang báo cáo đã chọn
(4-16 trang) để lấy số. Kết quả lưu cạnh txt của Tesseract: txt/<mã>/<năm>/<file>.ppocr.txt (cùng định dạng).

    python ocr_so.py data/PNJ/2026/PNJ_2026_Q2_HN.pdf 4-7     # OCR thử vài trang, in ra màn hình
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pymupdf

import pdf2txt

DPI = 200
PARAMS = {
    "Global.use_cls": False,            # trang đã xoay đúng chiều ở pdf2txt (dò bằng điểm âm tiết tiếng Việt)
    "Global.max_side_len": 2000,        # A4 200 dpi = 1654 x 2339 px
    "Global.text_score": 0.3,
    "Det.ocr_version": "PP-OCRv6", "Det.model_type": "small",
    "Rec.ocr_version": "PP-OCRv6", "Rec.model_type": "small", "Rec.lang_type": "vi", "Rec.rec_batch_num": 16,
    "EngineConfig.onnxruntime.intra_op_num_threads": 6,
}
_engine = None
_lock = threading.Lock()


def available() -> bool:
    try:
        import rapidocr  # noqa: F401
        import numpy  # noqa: F401
        return True
    except ImportError:
        return False


def engine():
    global _engine
    if _engine is None:
        from rapidocr import EngineType, ModelType, OCRVersion, RapidOCR
        enums = {"PP-OCRv6": OCRVersion.PPOCRV6, "small": ModelType.SMALL, "medium": ModelType.MEDIUM}
        p = {k: enums.get(v, v) if isinstance(v, str) and not k.endswith("lang_type") else v for k, v in PARAMS.items()}
        p["Det.engine_type"] = p["Rec.engine_type"] = EngineType.ONNXRUNTIME
        _engine = RapidOCR(params=p)       # lần đầu tự tải model (~30 MB) về thư mục cài rapidocr
    return _engine


def ocr_page(page, rot: int = 0) -> str:
    """1 trang -> văn bản dựng theo hàng/cột (dùng chung hàm layout của pdf2txt)."""
    import numpy as np
    if rot:
        page.set_rotation((page.rotation + rot) % 360)
    pix = page.get_pixmap(dpi=DPI)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, pix.n)[:, :, :3][:, :, ::-1].copy()
    with _lock:                               # 1 engine dùng đủ 6 luồng CPU -> chạy lần lượt
        r = engine()(img)
    k = 72 / DPI
    words = [(float(b[:, 0].min()) * k, float(b[:, 1].min()) * k, float(b[:, 0].max()) * k, float(b[:, 1].max()) * k, t)
             for b, t in zip(r.boxes if r.boxes is not None else [], r.txts or [])]
    w = page.rect.width
    if rot:
        page.set_rotation((page.rotation - rot) % 360)
    return pdf2txt.layout(words, w)


def path_for(txt_path: Path) -> Path:
    return txt_path.with_suffix(".ppocr.txt")


def pages(pdf: Path, txt_path: Path, wanted: list[int], rots: dict[int, int] | None = None) -> dict[int, tuple[str, str]]:
    """{trang: ("ppocr" | "ppocr@90", văn bản)} cho các trang cần; dùng lại cache nếu PDF không đổi."""
    out = path_for(txt_path)
    have = pdf2txt.read_txt(out)
    if have and out.stat().st_mtime < pdf.stat().st_mtime:
        have = {}
    rots = rots or {}
    todo = [p for p in wanted if p not in have or pdf2txt.rot_of(have[p][0]) != rots.get(p, 0)]
    if todo:
        with pymupdf.open(pdf) as d:
            for p in todo:
                rot = rots.get(p, 0)
                have[p] = (f"ppocr@{rot}" if rot else "ppocr", ocr_page(d[p - 1], rot))
            pdf2txt.write_txt(out, pdf.name, d.page_count, have)
    return {p: have[p] for p in wanted if p in have}


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not argv:
        print(__doc__)
        return 2
    pdf = Path(argv[0])
    with pymupdf.open(pdf) as d:
        wanted = pdf2txt.parse_pages(argv[1] if len(argv) > 1 else None, d.page_count)
        for p in wanted:
            t = time.perf_counter()
            txt = ocr_page(d[p - 1])
            print(f"=== Trang {p} (ppocr, {time.perf_counter() - t:.1f}s) ===\n{txt}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
