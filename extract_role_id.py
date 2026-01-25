"""
从保存的HTML文件中提取角色ID与名称映射
"""
import re
import json

html_file = r'E:\Code-yssey\GooseGooseDuck游戏记录查询\Gaggle Fun 🎮 Next Level Social Gaming游戏具体信息.html'

print("读取HTML文件...")
with open(html_file, 'r', encoding='utf-8') as f:
    content = f.read()

print(f"文件大小: {len(content):,} 字符\n")

# 1. 查找所有 "role": 数字 模式
print("=" * 50)
print("查找后端JSON中的role字段:")
print("=" * 50)
role_pattern = r'"role"\s*:\s*(\d+)'
role_ids = re.findall(role_pattern, content)
unique_role_ids = sorted(set(int(x) for x in role_ids))
print(f"找到的role ID值: {unique_role_ids}")

# 2. 已知游戏角色列表
known_roles = [
    'Adventurer', 'Demolitionist', 'Sheriff', 'Vigilante', 'Detective',
    'Vulture', 'Pelican', 'Dodo', 'Morphling', 'Assassin', 'Cannibal',
    'Silencer', 'Warlock', 'Pigeon', 'Falcon', 'Birdwatcher', 'Tracker',
    'Medium', 'Celebrity', 'Lover', 'Spy', 'Hitman', 'Bodyguard',
    'Technician', 'Mechanic', 'Bounty Hunter', 'Identity Thief',
    'Canadian Goose', 'Mimic', 'Professional', 'Ninja', 'Duellist',
    'Undertaker', 'Esper', 'Political', 'Astral', 'Street Urchin',
    'Avenger', 'Locksmith', 'Snitch', 'Necromancer', 'Serial Killer',
    'Medic', 'Engineer', 'Mayor', 'Mortician', 'Goose', 'Duck'
]

# 3. 查找页面中出现的角色名
print("\n" + "=" * 50)
print("页面中出现的游戏角色:")
print("=" * 50)
found_roles = []
for role in known_roles:
    if re.search(rf'\b{role}\b', content, re.IGNORECASE):
        found_roles.append(role)
        print(f"  ✓ {role}")

# 4. 查找角色名附近的数字（可能的映射关系）
print("\n" + "=" * 50)
print("尝试关联role ID与角色名:")
print("=" * 50)

# 查找JSON对象中同时包含role数字和角色名的模式
# 模式1: {"role": 33, ..., "xxx": "Demolitionist"}
mapping = {}

for role in found_roles:
    # 在role附近100字符内查找数字
    pattern = rf'"role"\s*:\s*(\d+).{{0,200}}?{role}|{role}.{{0,200}}?"role"\s*:\s*(\d+)'
    matches = re.findall(pattern, content, re.IGNORECASE | re.DOTALL)
    for m in matches:
        role_id = m[0] or m[1]
        if role_id:
            role_id = int(role_id)
            if role_id not in mapping:
                mapping[role_id] = role
                print(f"  {role_id} -> {role}")

# 5. 查找更多模式
print("\n" + "=" * 50)
print("查找其他可能的映射模式:")
print("=" * 50)

# 查找类似 "roleName": "xxx" 的模式
role_name_pattern = r'"roleName"\s*:\s*"([^"]+)"'
role_names = re.findall(role_name_pattern, content)
if role_names:
    print(f"找到 roleName 字段: {set(role_names)}")

# 查找 "name": "角色名" 附近的 "id": 数字
for role in found_roles:
    pattern = rf'"id"\s*:\s*(\d+)[^}}]{{0,100}}"{role}"|"{role}"[^}}]{{0,100}}"id"\s*:\s*(\d+)'
    matches = re.findall(pattern, content, re.IGNORECASE)
    for m in matches:
        role_id = m[0] or m[1]
        if role_id and int(role_id) < 100:  # 角色ID应该是较小的数字
            role_id = int(role_id)
            if role_id not in mapping:
                mapping[role_id] = role
                print(f"  {role_id} -> {role}")

# 6. 输出最终映射
print("\n" + "=" * 50)
print("最终角色ID映射表:")
print("=" * 50)
if mapping:
    for k, v in sorted(mapping.items()):
        print(f"  {k}: \"{v}\"")

    # 保存映射
    with open('game_role_mapping.json', 'w', encoding='utf-8') as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    print(f"\n映射已保存到: game_role_mapping.json")
else:
    print("未能自动建立映射，需要手动分析JSON数据")
    print("\n请在浏览器Network中找到对应的JSON响应并保存")
