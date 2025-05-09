
import requests
import xml.etree.ElementTree as ET
from urllib.parse import quote
import re
import os
import unicodedata
from collections import defaultdict

OC = os.getenv("OC", "chetera")
BASE = "http://www.law.go.kr"

def get_law_list_from_api(query):
    exact_query = f'"{query}"'
    encoded_query = quote(exact_query)
    page = 1
    laws = []
    while True:
        url = f"{BASE}/DRF/lawSearch.do?OC={OC}&target=law&type=XML&display=100&page={page}&search=2&knd=A0002&query={encoded_query}"
        res = requests.get(url, timeout=10)
        res.encoding = 'utf-8'
        if res.status_code != 200:
            break
        root = ET.fromstring(res.content)
        for law in root.findall("law"):
            laws.append({
                "법령명": law.findtext("법령명한글", "").strip(),
                "MST": law.findtext("법령일련번호", "")
            })
        if len(root.findall("law")) < 100:
            break
        page += 1
    return laws

def get_law_text_by_mst(mst):
    url = f"{BASE}/DRF/lawService.do?OC={OC}&target=law&MST={mst}&type=XML"
    try:
        res = requests.get(url, timeout=10)
        res.encoding = 'utf-8'
        return res.content if res.status_code == 200 else None
    except:
        return None

def clean(text):
    return re.sub(r"\s+", "", text or "")

def 조사_을를(word):
    if not word:
        return "을"
    code = ord(word[-1]) - 0xAC00
    jong = code % 28
    return "를" if jong == 0 else "을"

def 조사_으로로(word):
    if not word:
        return "으로"
    code = ord(word[-1]) - 0xAC00
    jong = code % 28
    return "로" if jong == 0 or jong == 8 else "으로"

def highlight(text, keyword):
    escaped = re.escape(keyword)
    return re.sub(f"({escaped})", r"<span style='color:red'>\1</span>", text or "")

def remove_unicode_number_prefix(text):
    return re.sub(r"^[①-⑳]+", "", text)

def normalize_number(text):
    try:
        return str(int(unicodedata.numeric(text)))
    except:
        return text

def make_article_number(조문번호, 조문가지번호):
    if 조문가지번호 and 조문가지번호 != "0":
        return f"제{조문번호}조의{조문가지번호}"
    else:
        return f"제{조문번호}조"

def extract_chunks(text, keyword):
    match = re.search(rf"(\w*{re.escape(keyword)}\w*)", text)
    return match.group(1) if match else None

def format_location(loc):
    조, 항, 호, 목, _ = loc
    parts = [조]
    if 항:
        parts.append(f"제{항}항")
    if 호:
        parts.append(f"제{호}호")
    if 목:
        parts.append(f"{목}목")
    return "".join(parts)

# 아래에 run_search_logic과 run_amendment_logic 삽입

# 개선된 run_search_logic 함수
def run_search_logic(query, unit="법률"):
    result_dict = {}
    keyword_clean = clean(query)

    for law in get_law_list_from_api(query):
        mst = law["MST"]
        xml_data = get_law_text_by_mst(mst)
        if not xml_data:
            continue

        tree = ET.fromstring(xml_data)
        articles = tree.findall(".//조문단위")
        law_results = []

        for article in articles:
            조번호 = article.findtext("조문번호", "").strip()
            조가지번호 = article.findtext("조문가지번호", "").strip()
            조문식별자 = make_article_number(조번호, 조가지번호)
            조문내용 = article.findtext("조문내용", "") or ""
            항들 = article.findall("항")
            출력덩어리 = []
            조출력 = keyword_clean in clean(조문내용)
            첫_항출력됨 = False

            if 조출력:
                출력덩어리.append(highlight(조문내용, query))

            for 항 in 항들:
                항번호 = normalize_number(항.findtext("항번호", "").strip())
                항내용 = 항.findtext("항내용", "") or ""
                항출력 = keyword_clean in clean(항내용)
                항덩어리 = []
                하위검색됨 = False

                for 호 in 항.findall("호"):
                    호내용 = 호.findtext("호내용", "") or ""
                    호출력 = keyword_clean in clean(호내용)
                    if 호출력:
                        하위검색됨 = True
                        항덩어리.append("&nbsp;&nbsp;" + highlight(호내용, query))

                    for 목 in 호.findall("목"):
                        for m in 목.findall("목내용"):
                            if m.text and keyword_clean in clean(m.text):
                                줄들 = [line.strip() for line in m.text.splitlines() if line.strip()]
                                줄들 = [highlight(line, query) for line in 줄들]
                                if 줄들:
                                    하위검색됨 = True
                                    항덩어리.append(
                                        "<div style='margin:0;padding:0'>" +
                                        "<br>".join("&nbsp;&nbsp;&nbsp;&nbsp;" + line for line in 줄들) +
                                        "</div>"
                                    )

                if 항출력 or 하위검색됨:
                    if not 조출력 and not 첫_항출력됨:
                        출력덩어리.append(f"{highlight(조문내용, query)} {highlight(항내용, query)}")
                        첫_항출력됨 = True
                    elif not 첫_항출력됨:
                        출력덩어리.append(highlight(항내용, query))
                        첫_항출력됨 = True
                    else:
                        출력덩어리.append(highlight(항내용, query))
                    출력덩어리.extend(항덩어리)

            if 출력덩어리:
                law_results.append("<br>".join(출력덩어리))

        if law_results:
            result_dict[law["법령명"]] = law_results

    return result_dict




# 아래에 개정문 로직만 수정된 run_amendment_logic 삽입
# ✅ 조사 규칙 적용된 버전(coded by Claude)

def run_amendment_logic(find_word, replace_word):
    amendment_results = []
    for idx, law in enumerate(get_law_list_from_api(find_word)):
        law_name = law["법령명"]
        mst = law["MST"]
        xml_data = get_law_text_by_mst(mst)
        if not xml_data:
            continue
        tree = ET.fromstring(xml_data)
        articles = tree.findall(".//조문단위")
        덩어리별 = defaultdict(list)
        for article in articles:
            조번호 = article.findtext("조문번호", "").strip()
            조가지번호 = article.findtext("조문가지번호", "").strip()
            조문식별자 = make_article_number(조번호, 조가지번호)
            조문내용 = article.findtext("조문내용", "") or ""
            if find_word in 조문내용:
                덩어리 = extract_chunks(조문내용, find_word)
                if 덩어리:
                    덩어리별[덩어리].append((조문식별자, None, None, None, 조문내용.strip()))
            for 항 in article.findall("항"):
                항번호 = normalize_number(항.findtext("항번호", "").strip())
                항내용 = 항.findtext("항내용", "") or ""
                if find_word in 항내용:
                    덩어리 = extract_chunks(항내용, find_word)
                    if 덩어리:
                        덩어리별[덩어리].append((조문식별자, 항번호, None, None, 항내용.strip()))
                for 호 in 항.findall("호"):
                    호번호 = 호.findtext("호번호", "").strip().replace(".", "")
                    호내용 = 호.findtext("호내용", "") or ""
                    if find_word in 호내용:
                        덩어리 = extract_chunks(호내용, find_word)
                        if 덩어리:
                            덩어리별[덩어리].append((조문식별자, 항번호, 호번호, None, 호내용.strip()))
                    for 목 in 호.findall("목"):
                        목번호 = 목.findtext("목번호", "").strip().replace(".", "")
                        for m in 목.findall("목내용"):
                            if m.text and find_word in m.text:
                                덩어리 = extract_chunks(m.text, find_word)
                                if 덩어리:
                                    덩어리별[덩어리].append((조문식별자, 항번호, 호번호, 목번호, m.text.strip()))
        if not 덩어리별:
            continue
        문장들 = []
        for 덩어리, locs in 덩어리별.items():
            각각 = "각각 " if len(locs) > 1 else ""
            loc_str = ", ".join([format_location(l) for l in locs[:-1]]) + (" 및 " if len(locs) > 1 else "") + format_location(locs[-1])
            new_chunk = 덩어리.replace(find_word, replace_word)
            
            # 조사 처리 규칙 적용
            josa_format = get_amendment_format(덩어리, find_word, replace_word)
            문장들.append(f'{loc_str} 중 "{덩어리}"{josa_format.format(각각=각각, new_chunk=new_chunk)}')
        
        prefix = chr(9312 + idx) if idx < 20 else str(idx + 1)
        amendment_results.append(f"{prefix} {law_name} 일부를 다음과 같이 개정한다.<br>" + "<br>".join(문장들))
    return amendment_results if amendment_results else ["⚠️ 개정 대상 조문이 없습니다."]


def has_batchim(word):
    """단어의 마지막 글자가 받침을 가지고 있는지 확인"""
    if not word:
        return False
    char_code = ord(word[-1])
    # 한글 유니코드 범위 확인
    if 0xAC00 <= char_code <= 0xD7A3:
        # 종성 확인 (종성이 없으면 0, 있으면 1~27)
        return (char_code - 0xAC00) % 28 != 0
    return False


def has_batchim_rieul(word):
    """단어의 마지막 글자가 ㄹ 받침인지 확인"""
    if not word:
        return False
    char_code = ord(word[-1])
    # 한글 유니코드 범위 확인
    if 0xAC00 <= char_code <= 0xD7A3:
        # ㄹ 받침은 종성 코드 8
        return (char_code - 0xAC00) % 28 == 8
    return False


def find_josa(text, word):
    """검색어 뒤에 붙은 조사 찾기"""
    # 검색어가 텍스트에 없으면 빈 문자열 반환
    if word not in text:
        return ""
    
    # 검색어 위치 찾기
    pos = text.find(word) + len(word)
    if pos >= len(text):
        return ""
    
    # 조사 후보 - 길이가 긴 것부터 체크
    josas = ["으로", "이나", "으로", "로", "을", "를", "과", "와", "이", "가", "나"]
    
    # 검색어 뒤에 조사가 있는지 확인
    for josa in josas:
        if pos + len(josa) <= len(text) and text[pos:pos+len(josa)] == josa:
            return josa
    
    return ""


def get_amendment_format(text, find_word, replace_word):
    """조사 처리 규칙에 따라 적절한 개정문 문구 포맷 반환"""
    josa = find_josa(text, find_word)
    has_batchim_B = has_batchim(replace_word)
    has_rieul_B = has_batchim_rieul(replace_word)
    has_batchim_A = has_batchim(find_word)
    
    # 1. A을 (검색어에 조사 '을' 이 붙어있는 경우)
    if josa == "을":
        if has_batchim_B:
            if has_rieul_B:
                return "을 {{각각}}\"{new_chunk}\"로 한다."
            else:
                return "을 {{각각}}\"{new_chunk}\"으로 한다."
        else:
            return "을 {{각각}}\"{new_chunk}\"를로 한다."
    
    # 2. A를 (검색어에 조사 '를' 이 붙어있는 경우)
    elif josa == "를":
        if has_batchim_B:
            return "를 {{각각}}\"{new_chunk}\"을로 한다."
        else:
            return "를 {{각각}}\"{new_chunk}\"로 한다."
    
    # 3. A과 
    elif josa == "과":
        if has_batchim_B:
            if has_rieul_B:
                return "과를 {{각각}}\"{new_chunk}\"로 한다."
            else:
                return "과를 {{각각}}\"{new_chunk}\"으로 한다."
        else:
            return "과를 {{각각}}\"{new_chunk}\"와로 한다."
    
    # 4. A와
    elif josa == "와":
        if has_batchim_B:
            return "와를 {{각각}}\"{new_chunk}\"과로 한다."
        else:
            return "와를 {{각각}}\"{new_chunk}\"로 한다."
    
    # 5. A이
    elif josa == "이":
        if has_batchim_B:
            if has_rieul_B:
                return "이를 {{각각}}\"{new_chunk}\"로 한다."
            else:
                return "이를 {{각각}}\"{new_chunk}\"으로 한다."
        else:
            return "이를 {{각각}}\"{new_chunk}\"가로 한다."
    
    # 6. A가
    elif josa == "가":
        if has_batchim_B:
            return "가를 {{각각}}\"{new_chunk}\"이로 한다."
        else:
            return "가를 {{각각}}\"{new_chunk}\"로 한다."
    
    # 7. A이나
    elif josa == "이나":
        if has_batchim_B:
            if has_rieul_B:
                return "이나를 {{각각}}\"{new_chunk}\"로 한다."
            else:
                return "이나를 {{각각}}\"{new_chunk}\"으로 한다."
        else:
            return "이나를 {{각각}}\"{new_chunk}\"나로 한다."
    
    # 8. A나
    elif josa == "나":
        if has_batchim_B:
            return "나를 {{각각}}\"{new_chunk}\"이나로 한다."
        else:
            return "나를 {{각각}}\"{new_chunk}\"로 한다."
    
    # 9. A으로
    elif josa == "으로":
        if has_batchim_B:
            if has_rieul_B:
                return "으로를 {{각각}}\"{new_chunk}\"로로 한다."
            else:
                return "으로를 {{각각}}\"{new_chunk}\"으로로 한다."
        else:
            return "으로를 {{각각}}\"{new_chunk}\"로로 한다."
    
    # 10. A로
    elif josa == "로":
        if has_batchim_A:
            if has_batchim_B:
                if has_rieul_B:
                    return "로를 {{각각}}\"{new_chunk}\"로 한다."
                else:
                    return "로를 {{각각}}\"{new_chunk}\"으로로 한다."
            else:
                return "로를 {{각각}}\"{new_chunk}\"로 한다."
        else:
            if has_batchim_B:
                if has_rieul_B:
                    return "로를 {{각각}}\"{new_chunk}\"로 한다."
                else:
                    return "로를 {{각각}}\"{new_chunk}\"으로로 한다."
            else:
                return "로를 {{각각}}\"{new_chunk}\"로 한다."
    
    # 기본 처리 (조사가 없거나 처리하지 않는 조사인 경우)
    else:
        # 기본 조사는 "을/를" 구분
        if has_batchim_B:
            return "을 {{각각}}\"{new_chunk}\"으로 한다."
        else:
            return "을 {{각각}}\"{new_chunk}\"를 한다."
