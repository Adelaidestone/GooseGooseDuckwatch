"""
从保存的HTML页面中分析角色ID映射
"""

import re
import json
import os

def analyze_html_file(filepath):
    """分析HTML文件提取角色信息"""
    print(f"分析文件: {filepath}")
    print("-" * 60)

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    print(f"文件大小: {len(content):,} 字符")

    # 1. 查找所有数字可能是role ID
    role_ids = set(re.findall(r'"role"\s*:\s*(\d+)', content))
    print(f"\n找到的role值: {sorted([int(x) for x in role_ids])}")

    # 2. 已知的角色名称列表
    known_roles = [
        'Goose', 'Duck', 'Dodo', 'Pigeon', 'Vulture', 'Falcon', 'Morphling',
        'Silencer', 'Canadian Goose', 'Vigilante', 'Birdwatcher', 'Detective',
        'Sheriff', 'Gravy', 'Mechanic', 'Technician', 'Mimic', 'Professional',
        'Hitman', 'Assassin', 'Ninja', 'Spy', 'Cannibal', 'Lover', 'Duellist',
        'Medium', 'Adventurer', 'Celebrity', 'Undertaker', 'Esper', 'Bodyguard',
        'Political', 'Astral', 'Street Urchin', 'Avenger', 'Locksmith',
        'Bounty Hunter', 'Identity Thief', 'Pelican', 'Snitch', 'Warlock',
        'Necromancer', 'Invisibility', 'Serial Killer', 'Demolitionist',
        'Tracker', 'Medic', 'Engineer', 'Mayor', 'Lovers', 'Mortician',
        'Partisan', 'Lovers', 'Party Goose', 'Oblivious'
    ]

    # 3. 查找角色名称
    roles_found = []
    for role in known_roles:
        if role.lower() in content.lower():
            roles_found.append(role)

    print(f"\n页面中出现的角色名称: {roles_found}")

    # 4. 尝试找到角色名和数字的关联
    print("\n查找可能的角色ID-名称关联:")
    print("-" * 40)

    # 模式: 在100字符范围内查找数字和角色名
    for role in roles_found:
        pattern = rf'(\d{{1,3}})(?:[^a-zA-Z]{{0,50}}){role}|{role}(?:[^a-zA-Z]{{0,50}})(\d{{1,3}})'
        matches = re.findall(pattern, content, re.IGNORECASE)
        if matches:
            for m in matches[:3]:
                num = m[0] or m[1]
                if num and 1 <= int(num) <= 100:
                    print(f"  可能的映射: {num} -> {role}")

    # 5. 查找JSON格式的映射
    print("\n查找JSON格式数据:")
    print("-" * 40)

    # 查找类似 {"id":33,"name":"Demolitionist"} 的模式
    json_patterns = [
        r'\{"[^"]*id[^"]*"\s*:\s*(\d+)[^}]*"[^"]*name[^"]*"\s*:\s*"([^"]+)"[^}]*\}',
        r'\{"[^"]*name[^"]*"\s*:\s*"([^"]+)"[^}]*"[^"]*id[^"]*"\s*:\s*(\d+)[^}]*\}',
    ]

    found_mappings = {}
    for pattern in json_patterns:
        matches = re.findall(pattern, content)
        for m in matches:
            if len(m) == 2:
                if m[0].isdigit():
                    id_val, name_val = int(m[0]), m[1]
                else:
                    name_val, id_val = m[0], int(m[1])
                if name_val in known_roles or any(r.lower() in name_val.lower() for r in known_roles):
                    found_mappings[id_val] = name_val

    if found_mappings:
        print("找到映射:")
        for k, v in sorted(found_mappings.items()):
            print(f"  {k}: {v}")

    # 6. 打印页面中的实际角色文本
    print("\n页面文本中的角色相关内容:")
    print("-" * 40)

    # 提取页面可见文本
    text_only = re.sub(r'<[^>]+>', ' ', content)
    text_only = re.sub(r'\s+', ' ', text_only)

    for role in roles_found[:5]:
        idx = text_only.lower().find(role.lower())
        if idx >= 0:
            snippet = text_only[max(0, idx-30):idx+len(role)+30]
            print(f"  ...{snippet}...")

    return {
        'role_ids': sorted([int(x) for x in role_ids]),
        'roles_found': roles_found,
        'mappings': found_mappings
    }


def main():
    print("=" * 60)
    print("角色ID映射分析器")
    print("=" * 60)

    folder = r'E:\Code-yssey\GooseGooseDuck游戏记录查询'

    # 分析游戏具体信息页面
    html_files = [
        os.path.join(folder, 'Gaggle Fun 🎮 Next Level Social Gaming游戏具体信息.html'),
    ]

    all_results = []
    for filepath in html_files:
        if os.path.exists(filepath):
            result = analyze_html_file(filepath)
            all_results.append(result)
            print("\n")

    # 合并结果
    if all_results:
        all_ids = set()
        all_roles = set()
        all_mappings = {}

        for r in all_results:
            all_ids.update(r['role_ids'])
            all_roles.update(r['roles_found'])
            all_mappings.update(r['mappings'])

        print("=" * 60)
        print("汇总结果:")
        print("=" * 60)
        print(f"所有Role ID: {sorted(all_ids)}")
        print(f"所有角色名: {sorted(all_roles)}")

        if all_mappings:
            print("\n确认的映射关系:")
            for k, v in sorted(all_mappings.items()):
                print(f"  {k}: {v}")

            with open(os.path.join(folder, 'role_mapping.json'), 'w', encoding='utf-8') as f:
                json.dump(all_mappings, f, ensure_ascii=False, indent=2)
            print("\n映射已保存到: role_mapping.json")


if __name__ == "__main__":
    main()
