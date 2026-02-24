"""
📄 MSDS PDF 파서
MSDS에서 CAS 번호와 제품명을 자동 추출하는 모듈.
추출된 CAS 번호는 KOSHA API로 최신 규제정보를 조회하는 데 사용.

핵심: 사장님이 PDF만 올리면 CAS 번호를 몰라도 자동으로 규제를 확인해 줌
"""

import re
import pdfplumber
from typing import Dict, List, Any


def parse_msds_pdf(pdf_file) -> Dict[str, Any]:
    """
    MSDS PDF에서 제품명, 구성성분(CAS번호·물질명·함유량) 추출
    
    Returns:
        {
            'product_name': str,
            'supplier': str,
            'components': [{'name': str, 'cas': str, 'content': str}],
            'ghs_signal': str,       # 신호어 (위험/경고)
            'h_codes': [str],        # H코드 목록
            'un_no': str,            # UN번호 (14항)
            'section15_text': str,   # 15항 원문 (참고용)
            'full_text': str,
            'page_count': int,
            'success': bool,
            'error': str
        }
    """
    result = {
        'product_name': '', 'supplier': '',
        'components': [],
        'ghs_signal': '', 'h_codes': [], 'un_no': '',
        'section15_text': '',
        'full_text': '', 'page_count': 0,
        'success': False, 'error': ''
    }
    
    try:
        with pdfplumber.open(pdf_file) as pdf:
            result['page_count'] = len(pdf.pages)
            pages_text = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages_text.append(text)
            
            full_text = "\n".join(pages_text)
            result['full_text'] = full_text
            
            if not full_text.strip():
                result['error'] = 'PDF에서 텍스트를 추출할 수 없습니다 (이미지 PDF일 수 있음)'
                return result
            
            # 섹션 분리
            sections = _split_sections(full_text)
            
            # 1항: 제품명
            _extract_product_name(sections.get(1, '') or full_text[:1500], result)
            
            # 2항: GHS 신호어, H코드
            _extract_ghs(sections.get(2, '') or full_text, result)
            
            # 3항: 구성성분 (CAS 번호 추출의 핵심!)
            _extract_components(sections.get(3, ''), full_text, result)
            
            # 14항: UN번호
            _extract_un_no(sections.get(14, '') or full_text, result)
            
            # 15항: 원문 보존 (참고용)
            if sections.get(15):
                result['section15_text'] = sections[15][:3000]
            
            result['success'] = len(result['components']) > 0
            if not result['success']:
                result['error'] = 'CAS 번호를 찾지 못했습니다. MSDS 형식을 확인해 주세요.'
    
    except Exception as e:
        result['error'] = f'PDF 파싱 오류: {str(e)}'
    
    return result


def _split_sections(text: str) -> Dict[int, str]:
    """MSDS 텍스트를 16개 항목으로 분리"""
    sections = {}
    
    # 섹션 헤더 패턴들 (다양한 MSDS 형식 대응)
    header_patterns = [
        # "1. 화학제품과 회사에 관한 정보" 형태
        r'(?:^|\n)\s*(\d{1,2})\s*[.\)]\s*(?:화학제품|유해성|구성성분|응급조치|폭발|누출|취급|노출방지|물리화학|안정성|독성|환경|폐기|운송|법적|그\s*밖)',
        # "제1항" 또는 "1항:" 형태
        r'(?:^|\n)\s*제?\s*(\d{1,2})\s*항\s*[.:\s]',
        # "SECTION 1" 형태 (영문 MSDS)
        r'(?:^|\n)\s*(?:SECTION|Section)\s*(\d{1,2})\s*[.:\-\s]',
        # "1. " 다음에 한글 (최소 매칭)
        r'(?:^|\n)\s*(\d{1,2})\s*\.\s+[가-힣]{2}',
    ]
    
    positions = []
    for pat in header_patterns:
        for m in re.finditer(pat, text):
            sec_num = int(m.group(1))
            if 1 <= sec_num <= 16:
                positions.append((m.start(), sec_num))
    
    positions.sort(key=lambda x: x[0])
    
    # 같은 번호 중복 제거 (첫 번째만)
    seen = set()
    unique = []
    for pos, num in positions:
        if num not in seen:
            seen.add(num)
            unique.append((pos, num))
    
    for i, (pos, num) in enumerate(unique):
        end = unique[i+1][0] if i+1 < len(unique) else len(text)
        sections[num] = text[pos:end]
    
    return sections


def _extract_product_name(text: str, result: Dict):
    """제품명 추출"""
    patterns = [
        r'(?:제품명|제\s*품\s*명|상품명|품명|화학제품명)\s*[:\s]+(.*?)(?:\n|$)',
        r'(?:Product\s*(?:Name|Identifier))\s*[:\s]+(.*?)(?:\n|$)',
        r'(?:제품의\s*명칭)\s*[:\s]+(.*?)(?:\n|$)',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            name = m.group(1).strip().strip('.')
            # 너무 짧거나 이상한 값 필터
            if name and 1 < len(name) < 100 and name not in ['자료없음', '해당없음', '-']:
                result['product_name'] = name
                return
    
    # 공급자/회사명도 시도
    sup_patterns = [
        r'(?:공급자|제조자|회사명|Company|Supplier)\s*[:\s]+(.*?)(?:\n|$)',
    ]
    for pat in sup_patterns:
        m = re.search(pat, text, re.I)
        if m:
            result['supplier'] = m.group(1).strip()
            break


def _extract_ghs(text: str, result: Dict):
    """GHS 신호어, H코드 추출"""
    # 신호어
    sig = re.search(r'(?:신호어|Signal\s*Word)\s*[:\s]*(위험|경고|Danger|Warning)', text, re.I)
    if sig:
        result['ghs_signal'] = sig.group(1)
    
    # H코드
    h_codes = re.findall(r'(H\d{3}[A-Za-z]?)', text)
    result['h_codes'] = list(dict.fromkeys(h_codes))[:20]


def _extract_components(section3_text: str, full_text: str, result: Dict):
    """
    3항에서 구성성분 추출 (CAS 번호가 핵심!)
    
    MSDS 3항 형태 예시:
    | 화학물질명 | CAS 번호 | 함유량(%) |
    | 톨루엔    | 108-88-3 | 50~60    |
    | 크실렌    | 1330-20-7| 20~30    |
    """
    # 3항 텍스트가 있으면 우선 사용, 없으면 전체에서 처음 3000자
    text = section3_text if section3_text else full_text[:4000]
    
    # CAS 번호 패턴: 2~7자리 - 2자리 - 1자리
    cas_pattern = r'\b(\d{2,7}-\d{2}-\d)\b'
    
    components = []
    seen_cas = set()
    
    for m in re.finditer(cas_pattern, text):
        cas = m.group(1)
        if cas in seen_cas:
            continue
        seen_cas.add(cas)
        
        # CAS 번호 주변에서 물질명 추출
        start = max(0, m.start() - 200)
        end_ctx = min(len(text), m.end() + 150)
        before = text[start:m.start()]
        after = text[m.end():end_ctx]
        
        # 물질명: CAS 앞에서 한글명 또는 영문명
        name = _find_chemical_name(before)
        
        # 함유량: CAS 뒤에서 숫자% 패턴
        content = ''
        # "50~60%", "50-60", "50 ~ 60 %", ">= 95%", "≤ 5%" 등
        ct = re.search(r'([<>≤≥]?\s*\d+\.?\d*\s*[~\-]\s*\d+\.?\d*\s*%?|\d+\.?\d*\s*%)', after)
        if ct:
            content = ct.group(1).strip()
        if not content:
            ct2 = re.search(r'([<>≤≥]?\s*\d+\.?\d*\s*[~\-]\s*\d+\.?\d*\s*%?|\d+\.?\d*\s*%)', before[-80:])
            if ct2:
                content = ct2.group(1).strip()
        
        components.append({'name': name, 'cas': cas, 'content': content})
    
    # 3항에서 못 찾으면 전체 텍스트에서 CAS 패턴 검색
    if not components:
        all_cas = re.findall(cas_pattern, full_text)
        unique_cas = list(dict.fromkeys(all_cas))
        for cas in unique_cas[:15]:
            if cas not in seen_cas:
                components.append({'name': '', 'cas': cas, 'content': ''})
    
    result['components'] = components


def _find_chemical_name(before_text: str) -> str:
    """CAS 번호 앞 텍스트에서 화학물질명 추출"""
    # 줄 단위로 분리, 마지막 줄부터 역순 탐색
    lines = before_text.strip().split('\n')
    
    for line in reversed(lines[-3:]):
        line = line.strip()
        if not line:
            continue
        
        # 섹션 헤더 등 제외
        skip_keywords = ['구성성분', '함유량', '명칭', '화학물질명', 'CAS', 'No', '관용명',
                         'SECTION', 'Section', '항목', '비고', '함량']
        if any(kw in line for kw in skip_keywords):
            continue
        
        # 한글 물질명 (2자 이상)
        kor = re.findall(r'([가-힣][가-힣\s\(\)（）\-,·\d]{1,50})', line)
        if kor:
            name = kor[-1].strip().rstrip(',').rstrip('·')
            if len(name) >= 2:
                return name
        
        # 영문 물질명
        eng = re.findall(r'([A-Za-z][A-Za-z\s\-\(\),\.\']{2,60})', line)
        if eng:
            name = eng[-1].strip().rstrip(',')
            if len(name) >= 3:
                return name
    
    return ''


def _extract_un_no(text: str, result: Dict):
    """14항에서 UN번호 추출"""
    patterns = [
        r'UN\s*(\d{4})',
        r'(?:유엔|UN)\s*(?:번호|No\.?)\s*[:\s]*(\d{4})',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            result['un_no'] = m.group(1)
            return
