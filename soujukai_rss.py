import requests
import hashlib
import re
import time
import xml.etree.ElementTree as ET

from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime, parsedate_to_datetime


SOURCE_URL = "https://soujukai-fukuroku.or.jp/?cat=1"
OUTPUT = Path(__file__).parent / "soujukai.xml"

JST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    )
}

DATE_RE = re.compile(
    r"(20\d{2})\.(\d{2})\.(\d{2})"
)

MAX_RETRIES = 3


# --------------------------------------------------
# URLからGUID生成
# --------------------------------------------------

def make_guid(link):

    return hashlib.sha256(
        ("soujukai|" + link).encode("utf-8")
    ).hexdigest()


# --------------------------------------------------
# HTTP取得
# --------------------------------------------------

def fetch(url, label):

    for attempt in range(1, MAX_RETRIES + 1):

        try:

            print(
                f"{label}取得 "
                f"{attempt}/{MAX_RETRIES}"
            )

            response = requests.get(
                url,
                headers=HEADERS,
                timeout=30
            )

            print(
                "HTTP:",
                response.status_code
            )

            response.raise_for_status()

            return response

        except requests.RequestException as e:

            print(
                "取得失敗:",
                e
            )

            if attempt < MAX_RETRIES:

                print(
                    "10秒待って再試行します。"
                )

                time.sleep(10)

    return None


# --------------------------------------------------
# 既存RSS読み込み
# --------------------------------------------------

old_items = {}

if OUTPUT.exists():

    try:

        tree = ET.parse(OUTPUT)

        for item in tree.getroot().findall(
            "./channel/item"
        ):

            guid = item.findtext(
                "guid",
                ""
            )

            if not guid:
                continue

            old_items[guid] = {
                "title": item.findtext(
                    "title",
                    ""
                ),
                "link": item.findtext(
                    "link",
                    ""
                ),
                "description": item.findtext(
                    "description",
                    ""
                ),
                "pubDate": item.findtext(
                    "pubDate",
                    ""
                ),
                "guid": guid,
            }

    except Exception as e:

        print(
            "既存RSS読み込みエラー:",
            e
        )

        print(
            "安全のため今回は更新しません。"
        )

        raise SystemExit(0)


print(
    "既存RSS件数:",
    len(old_items)
)


# --------------------------------------------------
# 一覧ページ取得
# --------------------------------------------------

print()

response = fetch(
    SOURCE_URL,
    "創樹会 ニュース一覧 "
)


if response is None:

    print()
    print(
        "一覧ページを取得できませんでした。"
    )

    print(
        "既存XMLをそのまま維持します。"
    )

    raise SystemExit(0)


# --------------------------------------------------
# HTML解析
# --------------------------------------------------

soup = BeautifulSoup(
    response.content,
    "html.parser"
)

article_blocks = soup.select(
    "div.bnkt.w3_1.p01.fadein"
)


print()
print(
    "記事候補:",
    len(article_blocks),
    "件"
)


if len(article_blocks) == 0:

    print(
        "ニュース記事を取得できませんでした。"
    )

    print(
        "ページ構造変更の可能性があります。"
    )

    print(
        "既存XMLを維持します。"
    )

    raise SystemExit(0)


# --------------------------------------------------
# 一覧から記事情報を取得
# --------------------------------------------------

list_items = []


for block in article_blocks:

    a = block.find(
        "a",
        href=True
    )

    if a is None:
        continue


    link = urljoin(
        SOURCE_URL,
        a["href"]
    )


    # 個別記事 ?p=数字 のみ対象
    if not re.search(
        r"[?&]p=\d+",
        link
    ):
        continue


    full_text = block.get_text(
        " ",
        strip=True
    )


    match = DATE_RE.search(
        full_text
    )

    if not match:
        continue


    year = int(match.group(1))
    month = int(match.group(2))
    day = int(match.group(3))

    date_text = match.group(0)


    pub_dt = datetime(
        year,
        month,
        day,
        12,
        0,
        0,
        tzinfo=JST
    )


    guid = make_guid(
        link
    )


    # 一覧に表示される概要
    text_parts = [
        re.sub(
            r"\s+",
            " ",
            x
        ).strip()
        for x in a.stripped_strings
    ]

    text_parts = [
        x for x in text_parts
        if x and x != date_text
    ]


    description = ""

    if len(text_parts) >= 2:

        description = " ".join(
            text_parts[1:]
        )


    list_items.append({
        "link": link,
        "guid": guid,
        "pubDate": format_datetime(
            pub_dt
        ),
        "description": description,
    })


# --------------------------------------------------
# 重複除去
# --------------------------------------------------

unique_list_items = []
seen = set()


for item in list_items:

    if item["guid"] in seen:
        continue

    seen.add(
        item["guid"]
    )

    unique_list_items.append(
        item
    )


list_items = unique_list_items


print(
    "有効記事:",
    len(list_items),
    "件"
)


if len(list_items) == 0:

    print()
    print(
        "有効なニュース記事を"
        "1件も取得できませんでした。"
    )

    print(
        "既存XMLを維持します。"
    )

    raise SystemExit(0)


# --------------------------------------------------
# 完全タイトル取得
# --------------------------------------------------

current_items = []


for index, item in enumerate(
    list_items,
    start=1
):

    guid = item["guid"]
    link = item["link"]


    # ----------------------------------------------
    # 既存RSSにある記事
    # 完全タイトルが既に保存されていれば再利用
    # ----------------------------------------------

    if guid in old_items:

        old_title = old_items[guid]["title"]

        # 過去に省略タイトルで保存されている場合は
        # 個別ページを取り直す
        if (
            old_title
            and "…" not in old_title
            and "..." not in old_title
        ):

            print()
            print(
                f"[{index}] 既存記事を再利用:"
            )

            print(
                old_title
            )

            current_items.append({
                "title": old_title,
                "link": link,
                "description": (
                    old_items[guid]["description"]
                    or item["description"]
                ),
                "pubDate": item["pubDate"],
                "guid": guid,
            })

            continue


    # ----------------------------------------------
    # 新規記事は個別ページから完全タイトル取得
    # ----------------------------------------------

    print()
    print(
        f"[{index}] 個別記事を確認:"
    )

    print(link)


    detail_response = fetch(
        link,
        "  個別ページ "
    )


    # 個別ページだけ失敗した場合
    if detail_response is None:

        print(
            "  個別ページ取得失敗。"
        )

        # 既存RSSに同じ記事があるなら
        # 既存情報を維持
        if guid in old_items:

            print(
                "  既存RSSの情報を維持します。"
            )

            current_items.append(
                old_items[guid]
            )

        else:

            print(
                "  新規記事のため今回は"
                "RSS追加を見送ります。"
            )

        continue


    detail_soup = BeautifulSoup(
        detail_response.content,
        "html.parser"
    )


    h2 = detail_soup.find(
        "h2"
    )


    if h2 is None:

        print(
            "  h2が見つかりません。"
        )

        if guid in old_items:

            print(
                "  既存RSSの情報を維持します。"
            )

            current_items.append(
                old_items[guid]
            )

        else:

            print(
                "  新規記事のため今回は"
                "RSS追加を見送ります。"
            )

        continue


    title = h2.get_text(
        " ",
        strip=True
    )


    title = re.sub(
        r"\s+",
        " ",
        title
    ).strip()


    if not title:

        print(
            "  完全タイトルを取得できません。"
        )

        if guid in old_items:

            current_items.append(
                old_items[guid]
            )

        continue


    print(
        "  完全タイトル:",
        title
    )


    current_items.append({
        "title": title,
        "link": link,
        "description": item["description"],
        "pubDate": item["pubDate"],
        "guid": guid,
    })


# --------------------------------------------------
# 安全確認
# --------------------------------------------------

if len(current_items) == 0:

    print()
    print(
        "有効記事を作成できませんでした。"
    )

    print(
        "既存XMLを維持します。"
    )

    raise SystemExit(0)


# --------------------------------------------------
# 現在記事＋過去記事を統合
# --------------------------------------------------

all_items = []
seen_guids = set()


for item in current_items:

    if item["guid"] in seen_guids:
        continue

    all_items.append(
        item
    )

    seen_guids.add(
        item["guid"]
    )


# 一覧から押し出された過去記事も残す
for guid, item in old_items.items():

    if guid in seen_guids:
        continue

    all_items.append(
        item
    )

    seen_guids.add(
        guid
    )


# --------------------------------------------------
# 日付順
# --------------------------------------------------

def get_date(item):

    try:

        return parsedate_to_datetime(
            item["pubDate"]
        )

    except Exception:

        return datetime.min.replace(
            tzinfo=timezone.utc
        )


all_items.sort(
    key=get_date,
    reverse=True
)


# --------------------------------------------------
# RSS生成
# --------------------------------------------------

rss = ET.Element(
    "rss",
    version="2.0"
)

channel = ET.SubElement(
    rss,
    "channel"
)


ET.SubElement(
    channel,
    "title"
).text = (
    "社会福祉法人 創樹会 ニュース"
)


ET.SubElement(
    channel,
    "link"
).text = SOURCE_URL


ET.SubElement(
    channel,
    "description"
).text = (
    "社会福祉法人 創樹会の"
    "ニュース・お知らせ"
)


ET.SubElement(
    channel,
    "language"
).text = "ja"


# --------------------------------------------------
# RSS記事
# --------------------------------------------------

for item in all_items:

    element = ET.SubElement(
        channel,
        "item"
    )


    ET.SubElement(
        element,
        "title"
    ).text = item["title"]


    ET.SubElement(
        element,
        "link"
    ).text = item["link"]


    ET.SubElement(
        element,
        "description"
    ).text = item["description"]


    ET.SubElement(
        element,
        "pubDate"
    ).text = item["pubDate"]


    guid_element = ET.SubElement(
        element,
        "guid"
    )

    guid_element.set(
        "isPermaLink",
        "false"
    )

    guid_element.text = item["guid"]


# --------------------------------------------------
# XML保存
# --------------------------------------------------

tree = ET.ElementTree(
    rss
)

ET.indent(
    tree,
    space="  "
)

tree.write(
    OUTPUT,
    encoding="utf-8",
    xml_declaration=True
)


# --------------------------------------------------
# 結果
# --------------------------------------------------

print()
print("=" * 70)
print("RSS作成成功")
print("=" * 70)

print(
    "今回の一覧記事:",
    len(current_items),
    "件"
)

print(
    "RSS保存件数:",
    len(all_items),
    "件"
)

print(
    "保存先:",
    OUTPUT
)


print()
print("今回取得した記事:")


for i, item in enumerate(
    current_items,
    start=1
):

    print()

    print(
        f"[{i}] "
        f"{item['pubDate']} "
        f"{item['title']}"
    )

    print(
        "    ",
        item["link"]
    )