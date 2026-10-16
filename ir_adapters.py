"""Adapter riêng cho các web IR không đọc được bằng cấu hình chung trong companies.json.

Mỗi adapter: async def(get, years) -> [(link file, tiêu đề)]
  get(url, method="GET", params=..., headers=..., json=...) -> str   (bctc.get_page, đã có retry)
  years: danh sách năm cần, mới nhất trước.
Phần lọc / phân loại kỳ báo cáo do bctc.to_docs làm chung cho mọi nguồn.
Các khoá / đường dẫn API nội bộ dưới đây có thể đổi khi web deploy lại -> chạy kiem_tra_ir.py để phát hiện.
"""
from __future__ import annotations

import base64
import json
import re
from urllib.parse import urljoin

import bctc


async def hdb(get, years):
    """HDBank: API trả JSON bị mã hoá AES-192-ECB (khoá nằm trong _app.js của web) -> giải mã -> menuList
    theo năm, mỗi năm là HTML chứa link PDF trên cdn.hdbank.com.vn."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    text = await get("https://hdbank.com.vn/api/investors/thong-tin-nha-dau-tu/bao-cao-tai-chinh",
                     headers={"local": "vi", "device_type": "0"})
    raw = base64.b64decode(text.strip())
    dec = Cipher(algorithms.AES(b"Z9GRKIgYKH2CUdqfas858Q=="), modes.ECB()).decryptor()
    plain = dec.update(raw) + dec.finalize()
    data = json.loads(plain[:-plain[-1]])                       # bỏ padding PKCS7
    menus = data.get("menuList") or (data.get("data") or {}).get("menuList") or []
    want = {str(y) for y in years}
    menus = [m for m in menus if str(m.get("name")) in want] or menus[:2]
    return list(bctc.walk_json(menus, "https://hdbank.com.vn/"))


async def mbb(get, years):
    """MB: API GetListFinance cần cookie phiên + token XSRF lấy từ trang danh sách (session aiohttp giữ cookie)."""
    page = await get("https://www.mbbank.com.vn/Investor/bao-cao-tai-chinh/0/0/0")
    m = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', page)
    if not m:
        raise RuntimeError("MBB: không thấy token XSRF trên trang")
    out = []
    for y in years:
        for p in (1, 2):
            text = await get(f"https://www.mbbank.com.vn/api/GetListFinance/0/{p}/{y}",
                             headers={"MB-XSRF-Token-FormOnline": m.group(1), "X-Requested-With": "XMLHttpRequest"})
            lst = json.loads(text).get("lst") or []
            out += [(urljoin("https://www.mbbank.com.vn/", x["file_path"]), x.get("title") or "")
                    for x in lst if x.get("file_path")]
            if len(lst) < 10:
                break
    return out


async def mwg(get, years):
    """Thế Giới Di Động: API danh mục động - năm -> mục con 'Báo cáo tài chính...' -> danh sách bài có fileLink."""
    base = "https://api.mwgshop.vn/gw/ir-api/api"

    async def cats(parent):
        j = json.loads(await get(f"{base}/CategoryAPI", params={"langID": "vi-VN", "parentID": parent,
                                                                "pageIndex": 1, "pageSize": 50}))
        return [(str(x.get("categoryName") or x.get("name")), x.get("categoryID") or x.get("id"))
                for x in (j.get("data") if isinstance(j, dict) else j) or []]

    out = []
    year_ids = dict(await cats(7))
    for y in years:
        if str(y) not in year_ids:
            continue
        child = next((cid for name, cid in await cats(year_ids[str(y)]) if "tài chính" in name.lower()), None)
        if child is None:
            continue
        j = json.loads(await get(f"{base}/PostAPI", params={"categoryID": child, "langID": "vi-VN", "pageIndex": 1,
                                                            "pageSize": 50, "condition": -1}))
        posts = j.get("data") if isinstance(j, dict) else j
        out += [(x["fileLink"], x.get("title") or "") for x in posts or [] if x.get("fileLink")]
    return out


async def acb(get, years):
    """ACB: trang năm (SSR) chỉ trả 9 bài đầu; lấy mã danh mục của năm trong __NEXT_DATA__ rồi gọi API
    posts với search[categories.category_id:in]=<mã> & limit=all (tham số tìm trong JS bundle của web)."""
    out = []
    for y in years:
        page = await get(f"https://acb.com.vn/nha-dau-tu/bao-cao-tai-chinh-{y}")
        m = re.search(r'"cat":\[\{"id":(\d+),"title":"[^"]*' + str(y), page)
        if not m:
            continue
        j = json.loads(await get("https://acb.com.vn/api/front/v1/posts",
                                 params={"search[categories.category_id:in]": m.group(1), "limit": "all"},
                                 headers={"Accept": "application/json"}))
        for x in j.get("data") or []:
            path = (x.get("featured_image") or {}).get("path")
            if path:
                out.append((path.replace(" ", "%20"), x.get("title") or ""))
    return out


ADAPTERS = {"hdb": hdb, "mbb": mbb, "mwg": mwg, "acb": acb}
