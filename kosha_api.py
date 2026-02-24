#!/usr/bin/env python3
"""
KOSHA MSDS API 연동 스크립트
안전보건공단 화학물질정보시스템 Open API를 통해 MSDS 정보를 조회한다.
"""

import requests
import xml.etree.ElementTree as ET
import argparse
import json
import time
from typing import Optional, Dict, List, Any

# ============================================================
# API 설정
# ============================================================
API_KEY = "5002b52ede58ae3359d098a19d4e11ce7f88ffddc737233c2ebce75c033ff44a"
BASE_URL = "https://msds.kosha.or.kr/openapi/service/msdschem"
TIMEOUT = 30
DELAY = 0.3  # API 호출 간격 (초)


def set_api_key(key: str):
    """API 키 설정"""
    global API_KEY
    API_KEY = key


# ============================================================
# 기본 API 호출 함수
# ============================================================
def _call_api(endpoint: str, params: Dict[str, Any]) -> Optional[ET.Element]:
    """API 호출 후 XML 파싱하여 반환"""
    url = f"{BASE_URL}/{endpoint}"
    params["serviceKey"] = API_KEY
    
    try:
        response = requests.get(url, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        return ET.fromstring(response.content)
    except requests.RequestException as e:
        print(f"[ERROR] API 호출 실패: {e}")
        return None
    except ET.ParseError as e:
        print(f"[ERROR] XML 파싱 실패: {e}")
        return None


def _get_text(element: Optional[ET.Element], tag: str) -> str:
    """XML 요소에서 텍스트 추출"""
    if element is None:
        return ""
    child = element.find(tag)
    return child.text if child is not None and child.text else ""


# ============================================================
# 화학물질 검색
# ============================================================
def search_by_cas(cas_no: str) -> Dict[str, Any]:
    """
    CAS 번호로 화학물질 검색
    
    Args:
        cas_no: CAS 번호 (예: "67-64-1")
    
    Returns:
        {'success': True, 'chemId': '...', 'chemNameKor': '...', ...} 또는
        {'success': False, 'error': '...'}
    """
    root = _call_api("chemlist", {
        "searchWrd": cas_no,
        "searchCnd": 1,  # CAS No 검색
        "numOfRows": 10,
        "pageNo": 1
    })
    
    if root is None:
        return {"success": False, "error": "API 호출 실패"}
    
    items = root.findall(".//item")
    if not items:
        return {"success": False, "error": "물질 미등록"}
    
    item = items[0]
    return {
        "success": True,
        "chemId": _get_text(item, "chemId"),
        "chemNameKor": _get_text(item, "chemNameKor"),
        "casNo": _get_text(item, "casNo"),
        "keNo": _get_text(item, "keNo"),
        "unNo": _get_text(item, "unNo"),
        "enNo": _get_text(item, "enNo"),
        "lastDate": _get_text(item, "lastDate")
    }


def search_by_name(name: str) -> Dict[str, Any]:
    """
    국문명으로 화학물질 검색
    
    Args:
        name: 물질명 (예: "아세톤")
    
    Returns:
        검색 결과 딕셔너리
    """
    root = _call_api("chemlist", {
        "searchWrd": name,
        "searchCnd": 0,  # 국문명 검색
        "numOfRows": 10,
        "pageNo": 1
    })
    
    if root is None:
        return {"success": False, "error": "API 호출 실패"}
    
    items = root.findall(".//item")
    if not items:
        return {"success": False, "error": "물질 미등록"}
    
    results = []
    for item in items:
        results.append({
            "chemId": _get_text(item, "chemId"),
            "chemNameKor": _get_text(item, "chemNameKor"),
            "casNo": _get_text(item, "casNo")
        })
    
    return {"success": True, "results": results}


# ============================================================
# 상세 정보 조회
# ============================================================
def get_exposure_limits(chem_id: str) -> Dict[str, str]:
    """
    노출기준 조회 (8번 항목: 노출방지 및 개인보호구)
    
    Args:
        chem_id: 화학물질 ID (6자리)
    
    Returns:
        {'twa': '...', 'stel': '...', 'acgih_twa': '...', 'acgih_stel': '...'}
    """
    root = _call_api("chemdetail08", {"chemId": chem_id})
    
    result = {"twa": "-", "stel": "-", "acgih_twa": "-", "acgih_stel": "-"}
    
    if root is None:
        return result
    
    items = root.findall(".//item")
    for item in items:
        name_kor = _get_text(item, "msdsItemNameKor")
        detail = _get_text(item, "itemDetail")
        
        if not detail or detail in ["자료없음", ""]:
            continue
        
        # 국내규정 TWA/STEL 파싱
        if "국내규정" in name_kor:
            if "TWA" in detail.upper():
                import re
                twa_match = re.search(r'TWA[:\s]*([^\s,;]+(?:\s*[a-zA-Z/³]+)?)', detail, re.I)
                if twa_match:
                    result["twa"] = twa_match.group(1).strip()
            if "STEL" in detail.upper():
                import re
                stel_match = re.search(r'STEL[:\s]*([^\s,;]+(?:\s*[a-zA-Z/³]+)?)', detail, re.I)
                if stel_match:
                    result["stel"] = stel_match.group(1).strip()
            # TWA/STEL 구분 없이 값만 있는 경우
            if result["twa"] == "-" and ("ppm" in detail or "mg/m" in detail):
                result["twa"] = detail.split(",")[0].strip()
        
        # ACGIH 규정
        if "ACGIH" in name_kor:
            if "TWA" in detail.upper():
                import re
                twa_match = re.search(r'TWA[:\s]*([^\s,;]+(?:\s*[a-zA-Z/³]+)?)', detail, re.I)
                if twa_match:
                    result["acgih_twa"] = twa_match.group(1).strip()
            if "STEL" in detail.upper():
                import re
                stel_match = re.search(r'STEL[:\s]*([^\s,;]+(?:\s*[a-zA-Z/³]+)?)', detail, re.I)
                if stel_match:
                    result["acgih_stel"] = stel_match.group(1).strip()
    
    return result


def get_legal_regulations(chem_id: str) -> Dict[str, str]:
    """
    법적 규제현황 조회 (15번 항목)
    
    Args:
        chem_id: 화학물질 ID (6자리)
    
    Returns:
        {
            'measurement': 'O/X',      # 작업환경측정 대상
            'healthCheck': 'O/X',      # 특수건강진단 대상
            'managedHazard': 'O/X',    # 관리대상유해물질
            'specialManaged': 'O/X',   # 특별관리물질
            'rawText': '...'           # 원본 텍스트
        }
    """
    root = _call_api("chemdetail15", {"chemId": chem_id})
    
    result = {
        "measurement": "X",
        "healthCheck": "X",
        "managedHazard": "X",
        "specialManaged": "X",
        "rawText": ""
    }
    
    if root is None:
        return result
    
    items = root.findall(".//item")
    raw_texts = []
    
    for item in items:
        name_kor = _get_text(item, "msdsItemNameKor")
        detail = _get_text(item, "itemDetail")
        
        if not detail or detail in ["해당없음", "자료없음", ""]:
            continue
        
        if "산업안전보건법" in name_kor:
            raw_texts.append(detail)
            
            # 규제 항목 파싱
            if any(k in detail for k in ["작업환경측정", "측정대상"]):
                result["measurement"] = "O"
            if any(k in detail for k in ["특수건강진단", "건강진단"]):
                result["healthCheck"] = "O"
            if any(k in detail for k in ["관리대상", "유해물질"]):
                result["managedHazard"] = "O"
            if any(k in detail for k in ["특별관리", "발암성", "CMR"]):
                result["specialManaged"] = "O"
            
            # 일반 규제 표시가 있으면 기본 항목 O
            if detail and result["measurement"] == "X":
                result["measurement"] = "O"
                result["healthCheck"] = "O"
    
    result["rawText"] = " | ".join(raw_texts)
    return result


def get_hazard_classification(chem_id: str) -> Dict[str, Any]:
    """
    유해성·위험성 분류 조회 (2번 항목)
    
    Args:
        chem_id: 화학물질 ID
    
    Returns:
        {'classification': '...', 'signal': '...', 'pictograms': [...]}
    """
    root = _call_api("chemdetail02", {"chemId": chem_id})
    
    result = {
        "classification": "",
        "signal": "",
        "pictograms": [],
        "hazardStatements": [],
        "precautionStatements": []
    }
    
    if root is None:
        return result
    
    items = root.findall(".//item")
    for item in items:
        name_kor = _get_text(item, "msdsItemNameKor")
        detail = _get_text(item, "itemDetail")
        
        if not detail or detail in ["자료없음", ""]:
            continue
        
        if "유해성" in name_kor and "위험성" in name_kor and "분류" in name_kor:
            result["classification"] = detail
        elif "신호어" in name_kor:
            result["signal"] = detail
        elif "그림문자" in name_kor:
            result["pictograms"].append(detail)
        elif "유해" in name_kor and "위험문구" in name_kor:
            result["hazardStatements"].append(detail)
        elif "예방조치문구" in name_kor:
            result["precautionStatements"].append(detail)
    
    return result


def get_physical_properties(chem_id: str) -> Dict[str, str]:
    """
    물리화학적 특성 조회 (9번 항목)
    
    Args:
        chem_id: 화학물질 ID
    
    Returns:
        {'appearance': '...', 'odor': '...', 'pH': '...', ...}
    """
    root = _call_api("chemdetail09", {"chemId": chem_id})
    
    result = {}
    
    if root is None:
        return result
    
    # 항목명 → 키 매핑
    key_map = {
        "외관": "appearance",
        "냄새": "odor",
        "pH": "pH",
        "녹는점": "meltingPoint",
        "끓는점": "boilingPoint",
        "인화점": "flashPoint",
        "증기압": "vaporPressure",
        "비중": "specificGravity",
        "용해도": "solubility",
        "분자량": "molecularWeight"
    }
    
    items = root.findall(".//item")
    for item in items:
        name_kor = _get_text(item, "msdsItemNameKor")
        detail = _get_text(item, "itemDetail")
        
        if not detail or detail in ["자료없음", ""]:
            continue
        
        for kor_name, eng_key in key_map.items():
            if kor_name in name_kor:
                result[eng_key] = detail
                break
    
    return result


# ============================================================
# 통합 조회 함수
# ============================================================
def get_chemical_info(cas_no: str) -> Dict[str, Any]:
    """
    CAS 번호로 화학물질 정보 통합 조회
    
    Args:
        cas_no: CAS 번호
    
    Returns:
        통합된 화학물질 정보 딕셔너리
    """
    # 1. 물질 검색
    search_result = search_by_cas(cas_no)
    
    if not search_result.get("success"):
        return {
            "success": False,
            "casNo": cas_no,
            "name": "미등록",
            "error": search_result.get("error", "검색 실패")
        }
    
    chem_id = search_result["chemId"]
    
    # 2. 노출기준 조회
    time.sleep(DELAY)
    exposure = get_exposure_limits(chem_id)
    
    # 3. 법적규제 조회
    time.sleep(DELAY)
    regulations = get_legal_regulations(chem_id)
    
    return {
        "success": True,
        "casNo": cas_no,
        "chemId": chem_id,
        "name": search_result.get("chemNameKor", cas_no),
        "keNo": search_result.get("keNo", ""),
        "unNo": search_result.get("unNo", ""),
        "twa": exposure.get("twa", "-"),
        "stel": exposure.get("stel", "-"),
        "acgih_twa": exposure.get("acgih_twa", "-"),
        "acgih_stel": exposure.get("acgih_stel", "-"),
        "measurement": regulations.get("measurement", "X"),
        "healthCheck": regulations.get("healthCheck", "X"),
        "managedHazard": regulations.get("managedHazard", "X"),
        "specialManaged": regulations.get("specialManaged", "X")
    }


def get_chemical_info_full(cas_no: str) -> Dict[str, Any]:
    """
    CAS 번호로 화학물질 전체 정보 조회 (유해성, 물리적 특성 포함)
    """
    basic = get_chemical_info(cas_no)
    
    if not basic.get("success"):
        return basic
    
    chem_id = basic["chemId"]
    
    # 추가 정보 조회
    time.sleep(DELAY)
    hazard = get_hazard_classification(chem_id)
    
    time.sleep(DELAY)
    physical = get_physical_properties(chem_id)
    
    return {
        **basic,
        "hazardClassification": hazard.get("classification", ""),
        "signal": hazard.get("signal", ""),
        "pictograms": hazard.get("pictograms", []),
        "physicalProperties": physical
    }


def batch_query(cas_list: List[str], full_info: bool = False) -> List[Dict[str, Any]]:
    """
    여러 CAS 번호 일괄 조회
    
    Args:
        cas_list: CAS 번호 리스트
        full_info: True면 전체 정보 조회
    
    Returns:
        조회 결과 리스트
    """
    results = []
    total = len(cas_list)
    
    for i, cas in enumerate(cas_list):
        print(f"[{i+1}/{total}] {cas} 조회 중...")
        
        if full_info:
            info = get_chemical_info_full(cas)
        else:
            info = get_chemical_info(cas)
        
        results.append(info)
        
        if i < total - 1:
            time.sleep(DELAY)
    
    return results


# ============================================================
# CLI
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="KOSHA MSDS API 조회")
    parser.add_argument("--api-key", help="KOSHA API 키")
    parser.add_argument("--cas", help="조회할 CAS 번호")
    parser.add_argument("--cas-list", help="조회할 CAS 번호 목록 (쉼표 구분)")
    parser.add_argument("--name", help="조회할 물질명")
    parser.add_argument("--full", action="store_true", help="전체 정보 조회")
    parser.add_argument("--output", "-o", help="결과 저장 파일 (JSON)")
    
    args = parser.parse_args()
    
    if args.api_key:
        set_api_key(args.api_key)
    
    results = []
    
    if args.cas:
        if args.full:
            results = [get_chemical_info_full(args.cas)]
        else:
            results = [get_chemical_info(args.cas)]
    
    elif args.cas_list:
        cas_list = [c.strip() for c in args.cas_list.split(",")]
        results = batch_query(cas_list, full_info=args.full)
    
    elif args.name:
        results = [search_by_name(args.name)]
    
    else:
        parser.print_help()
        return
    
    # 출력
    output = json.dumps(results, ensure_ascii=False, indent=2)
    print(output)
    
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"\n결과 저장: {args.output}")


if __name__ == "__main__":
    main()
