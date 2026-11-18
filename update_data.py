import json
import os
import re
from datetime import datetime, timezone, timedelta
import requests

DATA_FILE = "data.json"
DDRAGON_VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
CDRAGON_ARENA_KO_URL = "https://raw.communitydragon.org/latest/cdragon/arena/ko_kr.json"

STATS_API_URL = os.getenv("ARAM_STATS_API_URL", "").strip()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AramAugmentUpdater/2.0)"
}

ROLE_KO_MAP = {
    "Marksman": "원딜",
    "Mage": "메이지",
    "Tank": "탱커",
    "Fighter": "브루저",
    "Assassin": "암살자",
    "Support": "서포터"
}

TAG_KEYWORDS = {
    "쿨감": ["스킬 가속", "재사용 대기시간", "초기화"],
    "치명타": ["치명타"],
    "공속": ["공격 속도"],
    "온힛": ["적중 시", "기본 공격 시"],
    "주문력": ["주문력", "마법 피해"],
    "물리": ["공격력", "물리 피해", "방어구 관통"],
    "체력": ["체력", "보호막", "방어력", "마법 저항력"],
    "기동력": ["이동 속도", "돌진", "점멸"],
    "유틸": ["회복", "둔화", "아군"]
}

ROLE_TAG_PREFS = {
    "Marksman": ["공속", "온힛", "치명타", "기동력"],
    "Mage": ["주문력", "쿨감", "치명타"],
    "Tank": ["체력", "쿨감", "유틸"],
    "Fighter": ["체력", "물리", "온힛", "기동력"],
    "Assassin": ["물리", "치명타", "기동력", "쿨감"],
    "Support": ["유틸", "쿨감", "체력"]
}

ARCHETYPE_BUILD_PRESETS = {
    "marksman": {
        "spells": ["점멸", "유체화 또는 회복"],
        "skillOrder": "Q > W > E",
        "start_mana": ["절정의 화살", "장화"],
        "start_nomana": ["절정의 화살", "장화"],
        "core": ["크라켄 학살자", "무한의 대검", "도미닉 경의 인사"],
        "fallback_tags": ["CriticalStrike", "AttackSpeed", "Damage"]
    },
    "mage_burst": {
        "spells": ["점멸", "총명 또는 유체화"],
        "skillOrder": "Q > W > E",
        "start_mana": ["사라진 양피지"],
        "start_nomana": ["수호자의 보주", "증폭의 고서"],
        "core": ["루덴의 동반자", "그림자불꽃", "라바돈의 죽음모자"],
        "fallback_tags": ["SpellDamage", "Mana", "MagicPenetration"]
    },
    "ap_bruiser": {
        "spells": ["점멸", "표식(눈덩이)"],
        "skillOrder": "Q > E > W",
        "start_mana": ["수호자의 보주", "여신의 눈물"],
        "start_nomana": ["수호자의 보주", "증폭의 고서"],
        "core": ["리안드리의 고통", "균열 생성기", "존야의 모래시계"],
        "fallback_tags": ["SpellDamage", "Health"]
    },
    "ad_assassin": {
        "spells": ["점멸", "표식(눈덩이)"],
        "skillOrder": "Q > E > W",
        "start_mana": ["톱날 단검", "장화"],
        "start_nomana": ["톱날 단검", "장화"],
        "core": ["요우무의 유령검", "기회", "세릴다의 원한"],
        "fallback_tags": ["ArmorPenetration", "Damage"]
    },
    "ad_fighter": {
        "spells": ["점멸", "표식(눈덩이)"],
        "skillOrder": "Q > E > W",
        "start_mana": ["수호자의 뿔피리", "장화"],
        "start_nomana": ["수호자의 뿔피리", "장화"],
        "core": ["갈라진 하늘", "스테락의 도전", "죽음의 무도"],
        "fallback_tags": ["Health", "Damage"]
    },
    "tank": {
        "spells": ["점멸", "표식(눈덩이)"],
        "skillOrder": "W > E > Q",
        "start_mana": ["수호자의 뿔피리", "여신의 눈물"],
        "start_nomana": ["수호자의 뿔피리", "루비 수정"],
        "core": ["태양불꽃 방패", "가시 갑옷", "끝없는 절망"],
        "fallback_tags": ["Health", "Armor", "SpellBlock"]
    },
    "enchanter": {
        "spells": ["점멸", "총명 또는 탈진"],
        "skillOrder": "E > W > Q",
        "start_mana": ["밴들유리 거울", "요정의 부적"],
        "start_nomana": ["수호자의 보주", "장화"],
        "core": ["월석 재생기", "흐르는 물의 지팡이", "구원"],
        "fallback_tags": ["ManaRegen", "SpellDamage"]
    }
}


def load_existing_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"champions": {}, "augments": {}}


def clean_description(raw_desc: str) -> str:
    if not raw_desc:
        return ""
    text = re.sub(r"<br\s*/?>", " ", raw_desc, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"@[^@]+@", "일정 수치", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def detect_tags(desc: str) -> list[str]:
    matched = [tag for tag, keywords in TAG_KEYWORDS.items() if any(kw in desc for kw in keywords)]
    return matched[:2] if matched else ["유틸"]


def map_augment_rarity(rarity_val) -> str:
    val = str(rarity_val).lower()
    if "prismatic" in val or val == "2":
        return "prismatic"
    if "gold" in val or val == "1":
        return "gold"
    return "silver"


def fetch_latest_patch() -> str:
    res = requests.get(DDRAGON_VERSIONS_URL, headers=HEADERS, timeout=15)
    res.raise_for_status()
    return res.json()[0]


def fetch_cdragon_augments() -> dict:
    res = requests.get(CDRAGON_ARENA_KO_URL, headers=HEADERS, timeout=20)
    res.raise_for_status()
    payload = res.json()

    raw_list = payload.get("augments", []) if isinstance(payload, dict) else payload
    parsed = {}

    for item in raw_list:
        api_name = item.get("apiName") or str(item.get("id", ""))
        name = (item.get("name") or "").strip()
        if not api_name or not name:
            continue

        key = re.sub(r"[^a-z0-9_]", "_", api_name.lower()).strip("_")
        desc = clean_description(item.get("desc", ""))
        tier = map_augment_rarity(item.get("rarity", 0))
        tags = detect_tags(desc)

        parsed[key] = {
            "name": name,
            "tier": tier,
            "tags": tags,
            "desc": desc
        }
    return parsed


def fetch_ddragon_champions(patch: str) -> dict:
    url = f"https://ddragon.leagueoflegends.com/cdn/{patch}/data/ko_KR/champion.json"
    res = requests.get(url, headers=HEADERS, timeout=15)
    res.raise_for_status()
    return res.json().get("data", {})


def fetch_ddragon_aram_items(patch: str) -> dict:
    url = f"https://ddragon.leagueoflegends.com/cdn/{patch}/data/ko_KR/item.json"
    res = requests.get(url, headers=HEADERS, timeout=15)
    res.raise_for_status()
    raw_items = res.json().get("data", {})

    valid_by_name = {}
    legendary_pool = []

    for item_id, item in raw_items.items():
        if not item.get("maps", {}).get("12", False):
            continue
        if not item.get("gold", {}).get("purchasable", False):
            continue
        if item.get("requiredAlly"):
            continue

        name = item.get("name", "").strip()
        total_gold = item.get("gold", {}).get("total", 0)
        tags = item.get("tags", [])
        is_completed = len(item.get("into", [])) == 0 and total_gold >= 2200

        entry = {
            "id": item_id,
            "name": name,
            "gold": total_gold,
            "tags": tags,
            "is_completed": is_completed
        }
        valid_by_name[name] = entry
        if is_completed and "Boots" not in tags:
            legendary_pool.append(entry)

    legendary_pool.sort(key=lambda x: x["gold"], reverse=True)
    return {"by_name": valid_by_name, "legendary_pool": legendary_pool}


def determine_champion_archetype(c_info: dict) -> str:
    tags = c_info.get("tags", ["Fighter"])
    primary = tags[0]
    info = c_info.get("info", {})
    attack_score = info.get("attack", 5)
    magic_score = info.get("magic", 5)

    if primary == "Marksman":
        return "marksman"
    if primary == "Tank":
        return "tank"
    if primary == "Support":
        if "Tank" in tags:
            return "tank"
        if "Mage" in tags and magic_score >= 7:
            return "mage_burst"
        return "enchanter"
    if primary == "Mage":
        if "Fighter" in tags or "Assassin" in tags:
            return "ap_bruiser"
        return "mage_burst"
    if primary == "Assassin":
        return "ap_bruiser" if magic_score > attack_score else "ad_assassin"
    if primary == "Fighter":
        return "ap_bruiser" if magic_score > attack_score else "ad_fighter"

    return "ad_fighter"


def resolve_items_from_ddragon(c_info: dict, aram_items: dict) -> dict:
    archetype = determine_champion_archetype(c_info)
    preset = ARCHETYPE_BUILD_PRESETS[archetype]
    uses_mana = c_info.get("partype", "") == "마나"

    by_name = aram_items["by_name"]
    legendary_pool = aram_items["legendary_pool"]

    raw_starts = preset["start_mana"] if uses_mana else preset["start_nomana"]
    valid_starts = [name for name in raw_starts if name in by_name]
    if not valid_starts:
        valid_starts = ["장화"] if "장화" in by_name else []

    valid_cores = [name for name in preset["core"] if name in by_name]
    if len(valid_cores) < 3:
        needed_tags = set(preset["fallback_tags"])
        for candidate in legendary_pool:
            if candidate["name"] in valid_cores:
                continue
            if needed_tags & set(candidate["tags"]):
                valid_cores.append(candidate["name"])
            if len(valid_cores) >= 3:
                break

    ko_roles = [ROLE_KO_MAP.get(t, t) for t in c_info.get("tags", [])[:2]]
    role_label = " / ".join(ko_roles) if ko_roles else "만능"

    return {
        "role": role_label,
        "spells": preset["spells"],
        "skillOrder": preset["skillOrder"],
        "startItems": valid_starts,
        "coreItems": valid_cores[:3]
    }


def fetch_external_tier_stats() -> dict:
    if not STATS_API_URL:
        return {}
    try:
        res = requests.get(STATS_API_URL, headers=HEADERS, timeout=15)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"[경고] 외부 통계 API 조회 생략: {e}")
        return {}


def build_auto_recommendations(champ_tags: list[str], all_augments: dict, existing_recs: dict) -> dict:
    recs = dict(existing_recs)
    preferred_tags = []
    for role in champ_tags:
        preferred_tags.extend(ROLE_TAG_PREFS.get(role, []))

    for aug_id, aug in all_augments.items():
        if aug_id in recs:
            continue
        overlap = len(set(aug["tags"]) & set(preferred_tags))
        if overlap == 0:
            continue

        if aug["tier"] == "prismatic" and overlap >= 2:
            tier = "OP"
        elif overlap >= 2 or aug["tier"] == "prismatic":
            tier = "S"
        else:
            tier = "A"

        tag_str = "·".join(aug["tags"])
        recs[aug_id] = {
            "tier": tier,
            "reason": f"[{tag_str}] 시너지가 챔피언 역할군과 잘 맞아 교전 효율이 크게 상승합니다."
        }
    return recs


def main():
    existing = load_existing_data()
    patch = fetch_latest_patch()
    print(f"현재 최신 패치 버전: {patch}")

    latest_augments = fetch_cdragon_augments()
    merged_augments = dict(existing.get("augments", {}))

    new_aug_count = 0
    for aug_id, aug_info in latest_augments.items():
        if aug_id not in merged_augments:
            merged_augments[aug_id] = aug_info
            new_aug_count += 1
        else:
            merged_augments[aug_id]["desc"] = aug_info["desc"]
            merged_augments[aug_id]["tier"] = aug_info["tier"]

    ddragon_champs = fetch_ddragon_champions(patch)
    aram_items = fetch_ddragon_aram_items(patch)
    external_stats = fetch_external_tier_stats()
    merged_champions = dict(existing.get("champions", {}))

    new_champ_count = 0
    for raw_id, c_info in ddragon_champs.items():
        champ_key = raw_id.lower()
        champ_name = c_info["name"]
        primary_roles = c_info.get("tags", ["Fighter"])

        if champ_key not in merged_champions:
            auto_build = resolve_items_from_ddragon(c_info, aram_items)
            merged_champions[champ_key] = {
                "name": champ_name,
                "role": auto_build["role"],
                "spells": auto_build["spells"],
                "skillOrder": auto_build["skillOrder"],
                "startItems": auto_build["startItems"],
                "coreItems": auto_build["coreItems"],
                "recommendAugments": {}
            }
            new_champ_count += 1
        else:
            current_cores = merged_champions[champ_key].get("coreItems", [])
            if any(item not in aram_items["by_name"] for item in current_cores):
                refreshed = resolve_items_from_ddragon(c_info, aram_items)
                merged_champions[champ_key]["coreItems"] = refreshed["coreItems"]

        ext_champ_recs = external_stats.get(champ_key, {}).get("recommendAugments")
        if ext_champ_recs:
            merged_champions[champ_key]["recommendAugments"].update(ext_champ_recs)
        else:
            merged_champions[champ_key]["recommendAugments"] = build_auto_recommendations(
                primary_roles,
                merged_augments,
                merged_champions[champ_key].get("recommendAugments", {})
            )

    kst = timezone(timedelta(hours=9))
    output = {
        "_meta": {
            "patch": patch,
            "updatedAt": datetime.now(kst).strftime("%Y-%m-%d %H:%M:%S KST"),
            "championCount": len(merged_champions),
            "augmentCount": len(merged_augments),
            "aramItemCount": len(aram_items["by_name"])
        },
        "champions": merged_champions,
        "augments": merged_augments
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(
        f"업데이트 완료: 챔피언 {len(merged_champions)}종 (신규 {new_champ_count}종), "
        f"증강 {len(merged_augments)}종 (신규 {new_aug_count}종), "
        f"칼바람 유효 아이템 {len(aram_items['by_name'])}종 검증 완료"
    )


if __name__ == "__main__":
    main()
